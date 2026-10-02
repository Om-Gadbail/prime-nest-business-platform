"""Service layer: readiness/health business logic (no SQL here)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories import health as health_repo


def get_health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
    }


def get_api_version() -> dict:
    settings = get_settings()
    return {
        "api_version": "v1",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
    }


def check_readiness(db: Session) -> dict:
    """Check downstream dependencies (database required; redis informational).

    Liveness (/health) never touches the DB. Readiness reports the primary
    (platform) database plus per-key status for platform_db / prime_db /
    nest_db WITHOUT leaking URLs or credentials — values are one of
    ``up`` / ``down`` / ``shared`` (co-located on the primary URL) /
    ``disabled``. In split mode each distinct database is pinged; in
    co-located mode the keys share the primary verdict (no extra I/O).
    """
    settings = get_settings()
    db_up = health_repo.ping(db)
    redis_status = _redis_status(settings)
    databases = _database_status(db_up=db_up)
    if db_up:
        return {
            "ready": True,
            "status": "ready",
            "database": "up",
            "databases": databases,
            "redis": redis_status,
            "app": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
        }
    return {
        "ready": False,
        "status": "not_ready",
        "database": "down",
        "databases": databases,
        "redis": redis_status,
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
    }


def _database_status(*, db_up: bool) -> dict:
    """Per-key readiness detail. Never raises, never leaks connection info."""
    from app.core import db_routing as routing

    try:
        settings = get_settings()
        detail: dict[str, str] = {}
        for key in sorted(routing.DATABASE_KEYS):
            try:
                if settings.database_url_for_key(key) == settings.database_url:
                    detail[key] = "up" if db_up else "down"
                else:
                    detail[key] = "up" if routing.ping_key(key, settings) else "down"
            except Exception:  # noqa: BLE001 - one key never breaks the report
                detail[key] = "down"
        return detail
    except Exception:  # noqa: BLE001 - readiness degrades, never crashes
        return {
            key: ("up" if db_up else "down")
            for key in ("platform_db", "prime_db", "nest_db")
        }


def _redis_status(settings) -> str:
    """Best-effort Redis probe: up / down / disabled. Never raises."""
    # Phase 2: REST transport (Worker-safe) probed first when configured.
    try:
        from app.services import redis_rest as _rest

        if _rest.is_rest_configured(settings):
            try:
                client = _rest.rest_client_from_settings(settings)
                assert client is not None
                client.ping()
                return "up"
            except Exception:  # noqa: BLE001 - readiness degrades, never crashes
                return "down"
    except ImportError:
        pass
    url = (getattr(settings, "redis_url", "") or "").strip()
    if not url:
        return "disabled"
    try:
        import redis as _redis

        client = _redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return "up"
    except Exception:  # noqa: BLE001 - readiness degrades, never crashes
        return "down"
