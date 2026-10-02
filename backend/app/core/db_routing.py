"""Trusted database routing for the multi-business foundation (Prompt 2).

ONE codebase, ONE FastAPI app, ONE auth/RBAC system — but separate
operational databases per business:

    platform_db  -> identity, RBAC, business registry, audit, owner access
    prime_db     -> Prime Fitness operational rows
    nest_db      -> Nest Library operational rows

Routing rule (absolute):

    authenticated user
        -> authorized business membership (server-verified, per request)
        -> BusinessContext (frozen, server-derived)
        -> Business.database_key (trusted platform registry value)
        -> database session for that key

The request NEVER chooses a database. There is no ``database_url`` /
``database_name`` / ``X-Database`` request inputHonor — grep the codebase:
no such input exists, and this module accepts only server-side objects
(Business rows, BusinessContext values, Settings).

Failure rule: unknown / empty / unconfigured database_key FAILS CLOSED.
There is no default tenant — a missing mapping raises instead of falling
back to Prime, Nest, or any other database.

Physical topology: each key lazily owns ONE independent engine (own pool).
When PLATFORM/PRIME/NEST_DATABASE_URL are unset (default), every key maps
to the shared DATABASE_URL — "co-located mode": logically routed, one
physical database, row-level isolation (the pre-split posture). Setting
distinct URLs cuts over to physically separate databases with no code
changes. See docs/database-migration-report.md.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from app.models.business import Business

logger = get_logger(__name__)

# Closed allowlist of database keys. Anything else fails closed.
DATABASE_KEYS: frozenset[str] = frozenset({"platform_db", "prime_db", "nest_db"})

# The platform control plane always lives on this key.
PLATFORM_DATABASE_KEY = "platform_db"

# Seed-time canonical mapping (trusted server constant, not request input).
SEED_DATABASE_KEYS: dict[str, str] = {
    "prime": "prime_db",
    "nest": "nest_db",
}

# Canonical stable business identifiers (Prompt 2 business registry).
SEED_EXTERNAL_IDS: dict[str, str] = {
    "prime": "prime-fitness-001",
    "nest": "nest-library-001",
}


class DatabaseRoutingError(Exception):
    """Trusted mapping missing/invalid — fail closed, never fall back."""


def normalize_database_key(raw: object) -> str:
    """Return the key iff it is on the allowlist, else raise (no default)."""
    key = str(raw or "").strip()
    if key not in DATABASE_KEYS:
        raise DatabaseRoutingError(
            f"Unknown database mapping: {raw!r}. "
            "Refusing to select a fallback database."
        )
    return key


def resolve_database_key(business: "Business") -> str:
    """Trusted registry -> database key for one business row.

    Reads ONLY the server-side ``business.database_key`` written by
    seed/migrations/platform ops. Empty or off-allowlist values raise.
    """
    return normalize_database_key(getattr(business, "database_key", ""))


def database_url_for_key(settings: Settings, database_key: str) -> str:
    """Settings URL for a trusted key (per-key URL or shared fallback)."""
    key = normalize_database_key(database_key)
    # Worker edge: Hyperdrive binding wins when configured (env branch).
    # Docker/local: falls through to the existing URL routing unchanged.
    try:
        from app.core.hyperdrive import hyperdrive_sqlalchemy_url, is_hyperdrive_mode

        if is_hyperdrive_mode():
            # Shared `HYPERDRIVE` binding (co-located) or per-key bindings
            # (split) resolve inside; ValueError = misconfigured key.
            return hyperdrive_sqlalchemy_url(key)
    except (ImportError, ValueError):
        pass
    return settings.database_url_for_key(key)


def tenant_redis_key(business_id: object, *parts: object) -> str:
    """Tenant-aware Redis/cache key: ``business:{id}:...``.

    Business-specific cached data MUST use this (or an equivalent
    business-scoped prefix). A shared bare key for tenant data is a
    cross-business leak — review any new Redis usage against this helper.
    """
    cleaned = [str(p).strip().replace(" ", "_") for p in parts if str(p).strip()]
    suffix = ":".join(cleaned) if cleaned else "default"
    return f"business:{business_id}:{suffix}"


# --- Per-key engine / session registry (independent pools) -------------------

_lock = threading.Lock()
_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}


def _build_engine(database_url: str) -> Engine:
    # Worker edge (Hyperdrive or direct-TCP fallback): NullPool per-request
    # connections. Docker QueuePool behavior below is unchanged.
    try:
        from app.core.hyperdrive import build_edge_engine, is_edge

        if is_edge():
            return build_edge_engine(database_url)
    except ImportError:
        pass
    kwargs: dict = {
        "pool_pre_ping": True,
        "connect_args": {"connect_timeout": 3},
    }
    if database_url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    return create_engine(database_url, **kwargs)


def get_engine_for_key(database_key: str, settings: Settings | None = None) -> Engine:
    """Lazily build (and cache) the independent engine for one trusted key."""
    key = normalize_database_key(database_key)
    with _lock:
        engine = _engines.get(key)
        if engine is None:
            cfg = settings or get_settings()
            engine = _build_engine(database_url_for_key(cfg, key))
            _engines[key] = engine
            _session_factories[key] = sessionmaker(
                bind=engine, autoflush=False, expire_on_commit=False
            )
        return engine


def get_session_factory_for_key(
    database_key: str, settings: Settings | None = None
) -> sessionmaker[Session]:
    get_engine_for_key(database_key, settings)
    with _lock:
        factory = _session_factories.get(normalize_database_key(database_key))
        assert factory is not None
        return factory


def session_for_key(
    database_key: str, settings: Settings | None = None
) -> Generator[Session, None, None]:
    """Request-scoped session for one trusted key (closed by the caller)."""
    factory = get_session_factory_for_key(database_key, settings)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def get_platform_session(
    settings: Settings | None = None,
) -> Generator[Session, None, None]:
    """Request-scoped session for the platform control plane."""
    yield from session_for_key(PLATFORM_DATABASE_KEY, settings)


def ping_key(database_key: str, settings: Settings | None = None) -> bool:
    """SELECT 1 against one key's engine. False on any failure (never raises)."""
    try:
        engine = get_engine_for_key(database_key, settings)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - readiness degrades, never crashes
        logger.warning(
            "database ping failed key=%s err=%s", database_key, type(exc).__name__
        )
        return False


def ping_all(settings: Settings | None = None) -> dict[str, bool]:
    """Per-key liveness for readiness reporting (never raises, never leaks)."""
    cfg = settings or get_settings()
    result: dict[str, bool] = {}
    for key in sorted(DATABASE_KEYS):
        try:
            if cfg.database_url_for_key(key) == cfg.database_url:
                # Co-located with the primary URL: fate is shared; avoid
                # opening redundant connections per key.
                result[key] = "shared"
            else:
                result[key] = ping_key(key, cfg)
        except Exception:  # noqa: BLE001 - one key never breaks the report
            result[key] = False
    return result


def reset_routing_cache() -> None:
    """Test helper: dispose per-key engines so new settings take effect."""
    global _engines, _session_factories
    with _lock:
        for engine in _engines.values():
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001 - best effort
                pass
        _engines = {}
        _session_factories = {}


# --- Worker / scheduler job-scope validation ---------------------------------


def validate_business_job_scope(db: Session, *, business_id: object) -> "Business":
    """Validate a queued job's business scope against the trusted registry.

    A job payload's ``business_id`` is routing information, NOT authorization.
    The worker must call this BEFORE executing tenant-sensitive work: it
    verifies the business exists, is active, and carries a valid database
    mapping, then returns the row. Any failure raises (fail closed) — the
    caller must skip the job, never run it against a fallback database.
    """
    import uuid as _uuid

    from app.repositories import businesses as business_repo

    try:
        bid = _uuid.UUID(str(business_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise DatabaseRoutingError(
            f"Invalid job business scope: {business_id!r}."
        ) from exc
    business = business_repo.get_by_id(db, bid)
    if business is None or not business.is_active or business.status != "active":
        raise DatabaseRoutingError(f"Job business scope is not active: {bid}.")
    # Raises when the mapping is missing/invalid — fail closed, no fallback.
    resolve_database_key(business)
    return business
