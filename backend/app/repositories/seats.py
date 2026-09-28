"""Seat area / seat / allocation repositories: SQL only, scoped.

Allocation writes MUST go through ``app.services.seats`` (transactional
checks + constraint handling). These helpers are plain queries.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.operations import Seat, SeatAllocation, SeatArea
from app.repositories.base import apply_business_scope, get_scoped
from app.repositories.pagination import apply_sort, clamp_page

SORTABLE_SEATS = {
    "created_at": Seat.created_at,
    "seat_number": Seat.seat_number,
    "status": Seat.status,
}

SORTABLE_ALLOCATIONS = {
    "created_at": SeatAllocation.created_at,
    "allocated_at": SeatAllocation.allocated_at,
    "status": SeatAllocation.status,
}


# -- areas ----------------------------------------------------------------


def create_area(db: Session, *, business_id: uuid.UUID, fields: dict) -> SeatArea:
    area = SeatArea(business_id=business_id, **fields)
    db.add(area)
    db.flush()
    return area


def get_area(
    db: Session, *, area_id: object, business_id: uuid.UUID
) -> SeatArea | None:
    return get_scoped(db, SeatArea, area_id, business_id)


def list_areas(
    db: Session,
    *,
    business_id: uuid.UUID,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[SeatArea], int]:
    stmt = apply_business_scope(select(SeatArea), SeatArea, business_id)
    stmt = stmt.order_by(SeatArea.floor.asc(), SeatArea.name.asc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


# -- seats -----------------------------------------------------------------


def create_seat(db: Session, *, business_id: uuid.UUID, fields: dict) -> Seat:
    seat = Seat(business_id=business_id, **fields)
    db.add(seat)
    db.flush()
    return seat


def get_seat(db: Session, *, seat_id: object, business_id: uuid.UUID) -> Seat | None:
    return get_scoped(db, Seat, seat_id, business_id)


def list_seats(
    db: Session,
    *,
    business_id: uuid.UUID,
    area_id: uuid.UUID | None = None,
    status: str | None = None,
    seat_type: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Seat], int]:
    stmt = apply_business_scope(select(Seat), Seat, business_id)
    if area_id is not None:
        stmt = stmt.where(Seat.area_id == area_id)
    if status:
        stmt = stmt.where(Seat.status == status)
    if seat_type:
        stmt = stmt.where(Seat.seat_type == seat_type)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Seat.seat_number.ilike(like))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_SEATS,
        default=Seat.seat_number,
    )
    if sort is None:
        stmt = stmt.order_by(Seat.seat_number.asc())
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


# -- allocations -------------------------------------------------------------


def active_for_seat(
    db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID
) -> SeatAllocation | None:
    stmt = select(SeatAllocation).where(
        SeatAllocation.business_id == business_id,
        SeatAllocation.seat_id == seat_id,
        SeatAllocation.status == "active",
    )
    return db.execute(stmt).scalars().first()


def active_for_member(
    db: Session, *, business_id: uuid.UUID, member_id: uuid.UUID
) -> SeatAllocation | None:
    stmt = select(SeatAllocation).where(
        SeatAllocation.business_id == business_id,
        SeatAllocation.member_id == member_id,
        SeatAllocation.status == "active",
    )
    return db.execute(stmt).scalars().first()


def get_allocation(
    db: Session, *, allocation_id: object, business_id: uuid.UUID
) -> SeatAllocation | None:
    return get_scoped(db, SeatAllocation, allocation_id, business_id)


def list_allocations(
    db: Session,
    *,
    business_id: uuid.UUID,
    seat_id: uuid.UUID | None = None,
    member_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[SeatAllocation], int]:
    stmt = apply_business_scope(select(SeatAllocation), SeatAllocation, business_id)
    if seat_id is not None:
        stmt = stmt.where(SeatAllocation.seat_id == seat_id)
    if member_id is not None:
        stmt = stmt.where(SeatAllocation.member_id == member_id)
    if status:
        stmt = stmt.where(SeatAllocation.status == status)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_ALLOCATIONS,
        default=SeatAllocation.allocated_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def availability_summary(db: Session, *, business_id: uuid.UUID) -> dict[str, int]:
    """Authoritative seat availability from DB state (never frontend input)."""
    rows = db.execute(
        select(Seat.status, func.count())
        .where(Seat.business_id == business_id)
        .group_by(Seat.status)
    ).all()
    by_status = {str(s): int(n) for s, n in rows}
    allocated = int(
        db.execute(
            select(func.count())
            .select_from(SeatAllocation)
            .where(
                SeatAllocation.business_id == business_id,
                SeatAllocation.status == "active",
            )
        ).scalar()
        or 0
    )
    total = sum(by_status.values())
    available = by_status.get("available", 0)
    return {
        "total": total,
        "available": available,
        "allocated_active": allocated,
        "by_status": by_status,
    }


def search_available(
    db: Session,
    *,
    business_id: uuid.UUID,
    seat_type: str | None = None,
    area_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Seat]:
    """Seats free for allocation: status AVAILABLE and no ACTIVE allocation."""
    active_seat_ids = (
        select(SeatAllocation.seat_id)
        .where(
            SeatAllocation.business_id == business_id,
            SeatAllocation.status == "active",
        )
        .scalar_subquery()
    )
    stmt = select(Seat).where(
        Seat.business_id == business_id,
        Seat.status == "available",
        ~Seat.id.in_(active_seat_ids),
    )
    if seat_type:
        stmt = stmt.where(Seat.seat_type == seat_type)
    if area_id is not None:
        stmt = stmt.where(Seat.area_id == area_id)
    stmt = stmt.order_by(Seat.seat_number.asc()).limit(max(1, min(limit, 100)))
    return list(db.execute(stmt).scalars().all())
