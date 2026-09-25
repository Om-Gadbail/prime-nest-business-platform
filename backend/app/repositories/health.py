"""Repository layer: direct database access only (no business logic)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger(__name__)


def ping(db: Session) -> bool:
    """Execute SELECT 1 on the given session. Returns False instead of raising."""
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("repository ping failed: %s", type(exc).__name__)
        return False
