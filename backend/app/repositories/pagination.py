"""Pagination + sorting helpers (bounded, allowlisted, SQL-injection safe)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def clamp_page(limit: int | None, offset: int | None) -> tuple[int, int]:
    """Enforce sane server-side bounds (never trust client page sizes)."""
    try:
        lim = int(limit) if limit is not None else DEFAULT_PAGE_SIZE
    except (TypeError, ValueError):
        lim = DEFAULT_PAGE_SIZE
    try:
        off = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        off = 0
    lim = max(1, min(lim, MAX_PAGE_SIZE))
    off = max(0, off)
    return lim, off


def apply_sort(
    stmt: Select,
    *,
    sort: str | None,
    direction: str | None,
    allowed: dict[str, Any],
    default: Any,
) -> Select:
    """Order by an allowlisted column only (never raw client strings)."""
    column = allowed.get((sort or "").strip().lower(), default)
    desc = (direction or "desc").strip().lower() == "desc"
    return stmt.order_by(column.desc() if desc else column.asc())


def parse_uuid(value: object) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
