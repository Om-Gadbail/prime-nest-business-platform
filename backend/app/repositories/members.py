"""Member repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.operations import Member
from app.repositories.base import apply_business_scope, get_scoped
from app.repositories.pagination import apply_sort, clamp_page

SORTABLE_MEMBERS = {
    "created_at": Member.created_at,
    "updated_at": Member.updated_at,
    "display_name": Member.display_name,
    "status": Member.status,
}


def create(db: Session, *, business_id: uuid.UUID, fields: dict) -> Member:
    member = Member(business_id=business_id, **fields)
    db.add(member)
    db.flush()
    return member


def get(db: Session, *, member_id: object, business_id: uuid.UUID) -> Member | None:
    return get_scoped(db, Member, member_id, business_id)


def get_by_customer(
    db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID
) -> Member | None:
    stmt = select(Member).where(
        Member.business_id == business_id, Member.customer_id == customer_id
    )
    return db.execute(stmt).scalars().first()


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    source: str | None = None,
    search: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Member], int]:
    stmt = apply_business_scope(select(Member), Member, business_id)
    if status:
        stmt = stmt.where(Member.status == status)
    if source:
        stmt = stmt.where(Member.source == source)
    if created_from is not None:
        stmt = stmt.where(Member.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Member.created_at <= created_to)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Member.display_name.ilike(like),
                Member.phone.ilike(like),
                Member.email.ilike(like),
                Member.normalized_phone.ilike(like),
                Member.normalized_email.ilike(like),
            )
        )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_MEMBERS,
        default=Member.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total
