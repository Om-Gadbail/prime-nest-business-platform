"""Booking repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.repositories.base import apply_business_scope
from app.repositories.pagination import apply_sort, clamp_page


SORTABLE_BOOKINGS = {
    "created_at": Booking.created_at,
    "updated_at": Booking.updated_at,
    "requested_start_at": Booking.requested_start_at,
    "status": Booking.status,
    "title": Booking.title,
}


def create(db: Session, *, business_id: uuid.UUID, fields: dict) -> Booking:
    booking = Booking(business_id=business_id, **fields)
    db.add(booking)
    db.flush()
    return booking


def get_scoped(
    db: Session, *, booking_id: object, business_id: uuid.UUID
) -> Booking | None:
    from app.repositories.base import get_scoped as _get

    return _get(db, Booking, booking_id, business_id)


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    booking_type: str | None = None,
    assigned_user_id: uuid.UUID | None = None,
    start_from: datetime | None = None,
    start_to: datetime | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Booking], int]:
    stmt = apply_business_scope(select(Booking), Booking, business_id)
    if status:
        stmt = stmt.where(Booking.status == status)
    if booking_type:
        stmt = stmt.where(Booking.booking_type == booking_type)
    if assigned_user_id is not None:
        stmt = stmt.where(Booking.assigned_user_id == assigned_user_id)
    if start_from is not None:
        stmt = stmt.where(Booking.requested_start_at >= start_from)
    if start_to is not None:
        stmt = stmt.where(Booking.requested_start_at <= start_to)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_BOOKINGS,
        default=Booking.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def set_fields(booking: Booking, fields: dict) -> Booking:
    for key, value in fields.items():
        if hasattr(booking, key):
            setattr(booking, key, value)
    return booking
