"""SQLAlchemy engine / session wiring.

Synchronous (psycopg) engine is sufficient for this modular-monolith
foundation. Switch to async later only if a module proves it needs it.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _build_engine(database_url: str) -> Engine:
    kwargs: dict = {
        "pool_pre_ping": True,
        # Bound every new TCP connection so /ready degrades instead of
        # hanging when the database is unreachable (psycopg has no default).
        "connect_args": {"connect_timeout": 3},
    }
    # SQLite (used only by some local tests) needs a different pool setting.
    if database_url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    return create_engine(database_url, **kwargs)


def get_engine() -> Engine:
    """Lazily build (and cache) the global engine from settings."""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        # Raises a clear ValidationError at startup if DATABASE_URL is bad.
        _engine = _build_engine(settings.database_url)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session per request."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def ping_database(timeout_seconds: int = 3) -> bool:
    """Return True when `SELECT 1` succeeds, False otherwise (never raises)."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - readiness must degrade, not crash
        logger.warning("database ping failed: %s", type(exc).__name__)
        return False


def reset_engine_cache() -> None:
    """Test helper: drop cached engine so new settings take effect."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
