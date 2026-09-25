"""Repository base helpers: explicit tenant scoping.

Primary isolation mechanism = explicit authenticated business context +
repository/service scoping. These helpers make it hard to forget the filter.
"""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.base import BusinessScopedMixin

T = TypeVar("T")


def parse_business_id(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def apply_business_scope(stmt: Select, model: type, business_id: uuid.UUID) -> Select:
    """Apply tenant filter. Raises if model is not business-scoped (fail closed)."""
    if not issubclass(model, BusinessScopedMixin) and not hasattr(model, "business_id"):
        raise TypeError(f"Model {model.__name__} is not business-scoped; refusing unscoped query.")
    return stmt.where(model.business_id == business_id)  # type: ignore[attr-defined]


def get_scoped(db: Session, model: type[T], object_id: object, business_id: uuid.UUID) -> T | None:
    """Single-record fetch constrained to the business. Returns None if foreign."""
    if hasattr(model, "id"):
        stmt = select(model).where(model.id == object_id)  # type: ignore[attr-defined]
        stmt = apply_business_scope(stmt, model, business_id)
        return db.execute(stmt).scalars().first()
    # Models whose PK *is* business_id (e.g. BusinessSettings): the object
    # belongs to the business only when the PK equals the scoped business.
    if hasattr(model, "business_id"):
        try:
            import uuid as _uuid

            wanted = object_id if isinstance(object_id, _uuid.UUID) else _uuid.UUID(str(object_id))
        except (ValueError, TypeError, AttributeError):
            return None
        if wanted != business_id:
            return None
        return db.get(model, wanted)
    raise TypeError(f"Model {model.__name__} has no scoping key; refusing unscoped query.")


def list_scoped(
    db: Session, model: type[T], business_id: uuid.UUID, *, limit: int = 100, offset: int = 0
) -> list[T]:
    stmt = apply_business_scope(select(model), model, business_id)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


def count_scoped(db: Session, model: type[T], business_id: uuid.UUID) -> int:
    from sqlalchemy import func

    stmt = apply_business_scope(select(func.count()).select_from(model), model, business_id)
    result = db.execute(stmt).scalar()
    return int(result or 0)
