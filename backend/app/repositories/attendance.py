"""Attendance repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.operations import Attendance
from app.repositories.base import apply_business_scope, get_scoped
from app.repositories.pagination import apply_sort, clamp_page

SORTABLE_ATTENDANCE = {
    "attendance_date": Attendance.attendance_date,
    "checked_in_at": Attendance.checked_in_at,
    "created_at": Attendance.created_at,
}


def create(db: Session, *, business_id: uuid.UUID, fields: dict) -> Attendance:
    row = Attendance(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def get(
    db: Session, *, attendance_id: object, business_id: uuid.UUID
) -> Attendance | None:
    return get_scoped(db, Attendance, attendance_id, business_id)


def get_for_day(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id: uuid.UUID,
    attendance_date: date,
) -> Attendance | None:
    stmt = select(Attendance).where(
        Attendance.business_id == business_id,
        Attendance.member_id == member_id,
        Attendance.attendance_date == attendance_date,
    )
    return db.execute(stmt).scalars().first()


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id: uuid.UUID | None = None,
    day: date | None = None,
    day_from: date | None = None,
    day_to: date | None = None,
    open_only: bool = False,
    source: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Attendance], int]:
    stmt = apply_business_scope(select(Attendance), Attendance, business_id)
    if member_id is not None:
        stmt = stmt.where(Attendance.member_id == member_id)
    if day is not None:
        stmt = stmt.where(Attendance.attendance_date == day)
    if day_from is not None:
        stmt = stmt.where(Attendance.attendance_date >= day_from)
    if day_to is not None:
        stmt = stmt.where(Attendance.attendance_date <= day_to)
    if open_only:
        stmt = stmt.where(Attendance.checked_out_at.is_(None))
    if source:
        stmt = stmt.where(Attendance.source == source)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_ATTENDANCE,
        default=Attendance.checked_in_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total
