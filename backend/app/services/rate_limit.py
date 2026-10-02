"""Rate-limit abstraction (Block 2 abuse protection).

Design: endpoint/service code depends ONLY on the ``RateLimiter`` interface
(``check`` / ``reset``) plus the ``enforce_*`` helpers below. The default
backend is an in-process fixed-window limiter — correct for development and
single-worker deployments.

PRODUCTION REQUIREMENT: with multiple workers or replicas the in-process
backend is NOT shared state. Deploy a Redis-backed ``RateLimiter``
implementation (same interface, e.g. fixed window via INCR+EXPIRE keyed by
the same bucket strings) and inject it with ``set_limiter()``. No
endpoint/service code changes are needed for the swap.
"""

from __future__ import annotations

import abc
import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.services.errors import RateLimitedError


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter(abc.ABC):
    """Interface — Redis implementations must honor this contract."""

    @abc.abstractmethod
    def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Fixed-window check+increment. Denied when count exceeds ``limit``."""

    @abc.abstractmethod
    def reset(self) -> None:
        """Clear all state (tests / ops)."""


class InMemoryRateLimiter(RateLimiter):
    """Thread-safe single-process fixed window (NOT distributed).

    Memory is bounded: buckets hold at most ``limit`` timestamps each and
    idle buckets are evicted on access.
    """

    def __init__(self, *, max_buckets: int = 10000) -> None:
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_buckets = max_buckets

    def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        window_start = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_buckets:
                    # Fail open on saturation (availability over strictness in
                    # dev); production Redis backend does not have this bound.
                    return RateLimitResult(allowed=True)
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and bucket[0] <= window_start:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(bucket[0] + window_seconds - now) + 1
                return RateLimitResult(
                    allowed=False, retry_after_seconds=max(1, retry_after)
                )
            bucket.append(now)
            if not bucket:
                self._buckets.pop(key, None)
            return RateLimitResult(allowed=True)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_limiter: RateLimiter = InMemoryRateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter


def set_limiter(limiter: RateLimiter) -> None:
    """Inject a production backend (e.g. Redis). Used by tests to isolate state."""
    global _limiter
    _limiter = limiter


class RedisRateLimiter(RateLimiter):
    """Distributed fixed-window limiter (multi-worker safe).

    Backend: Redis ``INCR`` + ``EXPIRE`` per bucket key. Fails OPEN on Redis
    errors (availability over strictness) with a warning log — the API stays
    up and the in-process limiter remains as a per-process second layer only
    when explicitly stacked by the deployer. Key format matches the in-memory
    limiter so behavior is identical when Redis is healthy.
    """

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        import logging as _logging

        try:
            pipe = self._redis.pipeline()
            pipe.incr(f"ratelimit:{key}")
            pipe.ttl(f"ratelimit:{key}")
            count, ttl = pipe.execute()
            if ttl is None or ttl < 0:
                self._redis.expire(f"ratelimit:{key}", window_seconds)
                ttl = window_seconds
            if int(count or 0) > limit:
                return RateLimitResult(
                    allowed=False, retry_after_seconds=max(1, int(ttl or 1))
                )
            return RateLimitResult(allowed=True)
        except Exception as exc:  # noqa: BLE001 - degraded mode, never 500 on limiter
            _logging.getLogger(__name__).warning(
                "redis limiter degraded: %s", type(exc).__name__
            )
            return RateLimitResult(allowed=True)

    def reset(self) -> None:
        try:
            keys = list(self._redis.scan_iter("ratelimit:*"))
            if keys:
                self._redis.delete(*keys)
        except Exception:  # noqa: BLE001 - best effort only
            pass


class RestRedisRateLimiter(RateLimiter):
    """Distributed fixed-window limiter over Upstash REST (Worker-safe).

    Same INCR+EXPIRE semantics and key format as ``RedisRateLimiter``;
    fails OPEN on transport errors (availability over strictness).
    """

    def __init__(self, client) -> None:
        self._client = client

    def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        import logging as _logging

        try:
            rkey = f"ratelimit:{key}"
            count = int(self._client.incr(rkey) or 0)
            ttl = int(self._client.ttl(rkey))
            if ttl < 0:
                self._client.expire(rkey, window_seconds)
                ttl = window_seconds
            if count > limit:
                return RateLimitResult(
                    allowed=False, retry_after_seconds=max(1, int(ttl or 1))
                )
            return RateLimitResult(allowed=True)
        except Exception as exc:  # noqa: BLE001 - degraded mode, never 500 on limiter
            _logging.getLogger(__name__).warning(
                "redis-rest limiter degraded: %s", type(exc).__name__
            )
            return RateLimitResult(allowed=True)

    def reset(self) -> None:
        # REST has no SCAN parity guarantee; reset is best-effort no-op at
        # the edge (tests use the in-memory limiter). Never raises.
        return None


def configure_redis_limiter(settings: Settings) -> str:
    """Swap in the Redis limiter when REDIS_URL is set. Returns backend name.

    Returns "redis" when connected (PING ok), else "memory" (fallback, logged).
    Never raises — the app always boots.
    """
    import logging as _logging

    log = _logging.getLogger(__name__)
    # Phase 2: Worker-compatible REST transport wins when configured
    # (Upstash REST via httpx — no raw TCP in Workers isolates).
    try:
        from app.services import redis_rest as _rest

        rest_client = _rest.rest_client_from_settings(settings)
        if rest_client is not None:
            try:
                rest_client.ping()
                set_limiter(RestRedisRateLimiter(rest_client))
                log.info("rate limiter backend=redis-rest")
                return "redis-rest"
            except Exception as exc:  # noqa: BLE001 - fall through to TCP/memory
                log.warning(
                    "redis-rest unavailable (%s); trying redis-py/memory",
                    type(exc).__name__,
                )
    except ImportError:
        pass
    url = (getattr(settings, "redis_url", "") or "").strip()
    if not url:
        return "memory"
    try:
        import redis as _redis

        client = _redis.Redis.from_url(
            url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
        )
        client.ping()
        set_limiter(RedisRateLimiter(client))
        log.info("rate limiter backend=redis url_host=%s", url.split("@")[-1][:48])
        return "redis"
    except Exception as exc:  # noqa: BLE001 - fallback keeps single-process correctness
        log.warning(
            "redis unavailable (%s); using in-memory limiter", type(exc).__name__
        )
        return "memory"


def client_ip(request: Request) -> str:
    try:
        if request.client:
            return str(request.client.host)
    except (AttributeError, TypeError, ValueError):
        pass
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64] or "unknown"
    return "unknown"


def enforce(
    settings: Settings,
    *,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Raise RateLimitedError when the bucket is exhausted (no-op if disabled)."""
    if not settings.rate_limit_enabled:
        return
    result = get_limiter().check(key=key, limit=limit, window_seconds=window_seconds)
    if not result.allowed:
        raise RateLimitedError(
            "Rate limit exceeded. Please try again later.",
            retry_after=result.retry_after_seconds,
        )


def enforce_public(
    settings: Settings, *, request: Request, endpoint: str, business_slug: str
) -> None:
    """Anonymous intake bucket: per IP + business + endpoint."""
    enforce(
        settings,
        key=f"public:{endpoint}:{business_slug}:{client_ip(request)}",
        limit=settings.rate_limit_public_requests,
        window_seconds=settings.rate_limit_public_window_seconds,
    )


def enforce_auth(settings: Settings, *, request: Request, endpoint: str) -> None:
    """Auth-endpoint bucket (login/refresh abuse extension point)."""
    enforce(
        settings,
        key=f"auth:{endpoint}:{client_ip(request)}",
        limit=settings.rate_limit_auth_requests,
        window_seconds=settings.rate_limit_auth_window_seconds,
    )


def enforce_login_account(
    settings: Settings, *, request: Request, account_key: str
) -> None:
    """Per-account login throttle (stacked on the per-IP bucket).

    ``account_key`` must be a non-reversible digest (e.g. sha256 of the
    normalized email), never the raw email — bucket keys may appear in
    Redis key listings / logs.
    """
    enforce(
        settings,
        key=f"auth:login:account:{account_key}:{client_ip(request)}",
        limit=int(getattr(settings, "rate_limit_login_account_requests", 10)),
        window_seconds=int(
            getattr(settings, "rate_limit_login_account_window_seconds", 300)
        ),
    )


def enforce_owner(settings: Settings, *, request: Request, endpoint: str) -> None:
    """Owner aggregate bucket: per IP + endpoint (expensive multi-biz reads)."""
    enforce(
        settings,
        key=f"owner:{endpoint}:{client_ip(request)}",
        limit=int(getattr(settings, "rate_limit_owner_requests", 60)),
        window_seconds=int(getattr(settings, "rate_limit_owner_window_seconds", 60)),
    )


def enforce_webhook(settings: Settings, *, request: Request, endpoint: str) -> None:
    """Webhook bucket: per IP + endpoint (vendor retries + replay abuse)."""
    enforce(
        settings,
        key=f"webhook:{endpoint}:{client_ip(request)}",
        limit=int(getattr(settings, "rate_limit_webhook_requests", 120)),
        window_seconds=int(
            getattr(settings, "rate_limit_webhook_window_seconds", 60)
        ),
    )


def enforce_automation(
    settings: Settings, *, request: Request, endpoint: str, business_id: object = None
) -> None:
    """Privileged automation-op bucket: per business (tenant-aware) + IP."""
    biz = str(business_id or "nobiz")
    enforce(
        settings,
        key=f"automation:{endpoint}:{biz}:{client_ip(request)}",
        limit=int(getattr(settings, "rate_limit_automation_requests", 60)),
        window_seconds=int(
            getattr(settings, "rate_limit_automation_window_seconds", 60)
        ),
    )
