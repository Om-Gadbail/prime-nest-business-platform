"""Worker-compatible Redis transport (Upstash REST via httpx).

Raw ``redis-py`` TCP cannot run inside Cloudflare Workers isolates. This
module speaks the Upstash Redis REST API over HTTPS (already edge-compatible
via ``httpx``) with the SAME fixed-window semantics as ``RedisRateLimiter``:

  INCR ratelimit:{key} -> count; EXPIRE on first hit (TTL missing).
  SET scheduler:tick:{tick} NX EX -> lease election.
  PING / DEL for health + reset.

Interface-compatible with ``app.services.rate_limit.RateLimiter`` so no
endpoint/service code changes. Docker keeps using ``redis-py`` unchanged —
this transport is only selected when ``REDIS_REST_URL`` + ``REDIS_REST_TOKEN``
are set (Worker secrets, never frontend vars). All failures FAIL OPEN with a
warning (same degraded posture as the TCP limiter), except the scheduler
lease which is fail-open by design (jobs are idempotent).

Upstash REST reference: POST {url}/pipeline or GET {url}/incr/{key} with
``Authorization: Bearer <token>``. This client uses the simple command
endpoints (INCR/EXPIRE/TTL/SET/GET/DEL/PING) to avoid pipeline dialect drift.
"""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 5.0


class RestRedisClient:
    """Minimal Upstash REST client (https only, no raw sockets)."""

    def __init__(self, base_url: str, token: str) -> None:
        self._base = base_url.rstrip("/")
        self._token = token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _cmd(self, *parts: str):
        import httpx
        from urllib.parse import quote

        path = "/".join(quote(str(p), safe="") for p in parts)
        resp = httpx.get(
            f"{self._base}/{path}",
            headers=self._headers(),
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result")

    def ping(self) -> bool:
        return str(self._cmd("PING") or "").upper() == "PONG"

    def incr(self, key: str) -> int:
        return int(self._cmd("INCR", key) or 0)

    def ttl(self, key: str) -> int:
        try:
            return int(self._cmd("TTL", key))
        except (TypeError, ValueError):
            return -1

    def expire(self, key: str, seconds: int) -> None:
        self._cmd("EXPIRE", key, str(int(seconds)))

    def set_nx_ex(self, key: str, value: str, seconds: int) -> bool:
        # SET key value EX seconds NX -> "OK" when acquired, nil otherwise.
        result = self._cmd("SET", key, value, "EX", str(int(seconds)), "NX")
        return result == "OK"

    def delete(self, *keys: str) -> None:
        for key in keys:
            try:
                self._cmd("DEL", key)
            except Exception:  # noqa: BLE001 - best effort
                pass


def rest_client_from_settings(settings) -> RestRedisClient | None:
    url = (getattr(settings, "redis_rest_url", "") or "").strip()
    token = (getattr(settings, "redis_rest_token", "") or "").strip()
    if not url or not token:
        return None
    return RestRedisClient(url, token)


def is_rest_configured(settings) -> bool:
    return rest_client_from_settings(settings) is not None
