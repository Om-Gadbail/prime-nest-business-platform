"""Hyperdrive adapter for Cloudflare Python Workers (Phase 2 cutover).

Docker behavior is UNCHANGED: when no Hyperdrive binding env is present this
module is inert and the existing ``DATABASE_URL`` / per-key URL path is used.

Worker behavior: Hyperdrive exposes one binding per database
(PLATFORM/PRIME/NEST). Each binding provides ``host/port/user/password/
database`` parts (never a full URL with credentials in code). This module
builds a per-request sync SQLAlchemy URL with ``NullPool`` (no pooled TCP
sockets inside isolates) for the Worker edge.

Driver: synchronous only (async SQLAlchemy is unsupported on Python Workers
— no greenlet). ``pg8000`` (pure Python) is preferred; ``psycopg`` sync is
the fallback. Both are listed as Hyperdrive-supported for Python Workers.

Env contract (set from the Hyperdrive binding in ``cloudflare_entry.py`` or
by the Worker runtime — never committed):
  HYPERDRIVE_PLATFORM_HOST/PORT/USER/PASSWORD/DATABASE
  HYPERDRIVE_PRIME_HOST/PORT/USER/PASSWORD/DATABASE
  HYPERDRIVE_NEST_HOST/PORT/USER/PASSWORD/DATABASE
Co-located mode: only PLATFORM parts set → all keys share it (same as the
existing ``DATABASE_URL`` fallback posture). No request input ever selects
a database — routing still goes through ``db_routing.resolve_database_key``.
"""

from __future__ import annotations

import os

_KEY_PREFIX: dict[str, str] = {
    "platform_db": "HYPERDRIVE_PLATFORM",
    "prime_db": "HYPERDRIVE_PRIME",
    "nest_db": "HYPERDRIVE_NEST",
}

# Single shared binding (co-located mode): one Hyperdrive config serves all
# three logical keys. Set from the `HYPERDRIVE` Worker binding (see
# cloudflare_entry._apply_hyperdrive_env). Per-key bindings above win when
# present (physical-split mode) — no code changes needed to split later.
_SHARED_PREFIX = "HYPERDRIVE"


def _binding_parts(prefix: str) -> dict[str, str]:
    return {
        part: os.environ.get(f"{prefix}_{part}", "").strip()
        for part in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE")
    }


def _prefix_for_key(database_key: str) -> str | None:
    from app.core.db_routing import normalize_database_key

    key = normalize_database_key(database_key)
    if is_hyperdrive_key_configured(key):
        return _KEY_PREFIX[key]
    if _binding_parts(_SHARED_PREFIX)["HOST"] and _binding_parts(_SHARED_PREFIX)["DATABASE"]:
        return _SHARED_PREFIX
    return None


def is_hyperdrive_key_configured(database_key: str) -> bool:
    prefix = _KEY_PREFIX.get((database_key or "").strip(), "")
    if not prefix:
        return False
    return bool(
        os.environ.get(f"{prefix}_HOST", "").strip()
        and os.environ.get(f"{prefix}_DATABASE", "").strip()
    )


def is_hyperdrive_mode() -> bool:
    shared = _binding_parts(_SHARED_PREFIX)
    if shared["HOST"] and shared["DATABASE"]:
        return True
    return any(is_hyperdrive_key_configured(k) for k in _KEY_PREFIX)


def is_edge() -> bool:
    """True inside the Cloudflare Worker (any DB path): short-lived NullPool
    connections, no pooled TCP sockets in isolates. Docker/local never sets
    WORKER_EDGE, so the QueuePool path there is untouched."""
    return os.environ.get("WORKER_EDGE", "") == "1" or is_hyperdrive_mode()


def hyperdrive_sqlalchemy_url(
    database_key: str, *, driver: str = "pg8000"
) -> str:
    """Build a sync SQLAlchemy URL from a Hyperdrive binding (no secrets logged).

    Raises ``KeyError``/``ValueError`` when the binding is missing — callers
    must fail closed (503), never fall back to another tenant's database.
    """
    from app.core.db_routing import normalize_database_key

    key = normalize_database_key(database_key)
    prefix = _prefix_for_key(key)
    if prefix is None:
        raise ValueError(f"Hyperdrive binding missing for {key}.")
    host = os.environ.get(f"{prefix}_HOST", "").strip()
    port = os.environ.get(f"{prefix}_PORT", "5432").strip() or "5432"
    user = os.environ.get(f"{prefix}_USER", "").strip()
    password = os.environ.get(f"{prefix}_PASSWORD", "")
    database = os.environ.get(f"{prefix}_DATABASE", "").strip()
    if not host or not database or not user:
        # Co-located fallback: share the platform binding (mirrors
        # the existing shared-DATABASE_URL posture).
        if key != "platform_db" and is_hyperdrive_key_configured("platform_db"):
            return hyperdrive_sqlalchemy_url("platform_db", driver=driver)
        raise ValueError(f"Hyperdrive binding missing for {key}.")
    scheme = "postgresql+pg8000" if driver == "pg8000" else "postgresql+psycopg"
    # NOTE: password may contain URL-unsafe chars; quote it.
    from urllib.parse import quote_plus

    return (
        f"{scheme}://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )


def _hyperdrive_hosts() -> set[str]:
    """Lowercased hosts supplied by Hyperdrive bindings (never logged)."""
    hosts: set[str] = set()
    for prefix in (*_KEY_PREFIX.values(), _SHARED_PREFIX):
        host = os.environ.get(f"{prefix}_HOST", "").strip().lower()
        if host:
            hosts.add(host)
    return hosts


def build_edge_engine(database_url: str):
    """Sync engine for the Worker edge: NullPool, short-lived connections."""
    import ssl
    from urllib.parse import urlsplit, urlunsplit

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    # The edge ships pg8000 (not psycopg/psycopg2): normalize bare
    # `postgresql://` URLs (e.g. a DATABASE_URL secret) to the pg8000
    # dialect so engine creation never raises ModuleNotFoundError.
    # Docker callers never reach here (WORKER_EDGE is unset there).
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+pg8000://" + database_url[len("postgresql://"):]
    if database_url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    # Strip libpq query params (sslmode/channel_binding): the pg8000
    # dialect does not consume them (unknown kwargs raise TypeError inside
    # pg8000.connect, which only accepts `timeout`, not `connect_timeout`).
    # TLS is enforced via the explicit ssl_context below instead.
    parts = urlsplit(database_url)
    database_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    # Hyperdrive bindings: the Worker <-> Hyperdrive hop is Cloudflare-internal
    # plaintext (Hyperdrive owns upstream TLS validation to Neon). Forcing an
    # ssl_context here would make the proxy refuse SSL, so Hyperdrive-provided
    # hosts use a plain short-lived connection. Direct-TCP fallback URLs keep
    # the explicit TLS context below.
    try:
        target_host = (parts.hostname or "").lower()
    except Exception:  # noqa: BLE001 - unparseable host falls through to TLS path
        target_host = ""
    if target_host and target_host in _hyperdrive_hosts():
        return create_engine(
            database_url,
            poolclass=NullPool,
            connect_args={"timeout": 5},
        )
    # Fallback-path TLS (Hyperdrive normally owns upstream TLS validation):
    # traffic is TLS-encrypted + SCRAM-authenticated; endpoint identity is
    # NOT verified here. Harden by re-attaching Hyperdrive (see wrangler).
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"timeout": 5, "ssl_context": ctx},
    )
