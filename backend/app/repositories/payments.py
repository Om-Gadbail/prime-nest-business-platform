"""Payment repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.operations import Payment
from app.repositories.base import apply_business_scope, get_scoped
from app.repositories.pagination import apply_sort, clamp_page

SORTABLE_PAYMENTS = {
    "created_at": Payment.created_at,
    "updated_at": Payment.created_at,
    "amount": Payment.amount,
    "status": Payment.status,
    "due_at": Payment.due_at,
}


def create(db: Session, *, business_id: uuid.UUID, fields: dict) -> Payment:
    payment = Payment(business_id=business_id, **fields)
    db.add(payment)
    db.flush()
    return payment


def get(db: Session, *, payment_id: object, business_id: uuid.UUID) -> Payment | None:
    return get_scoped(db, Payment, payment_id, business_id)


def get_by_idem(
    db: Session, *, business_id: uuid.UUID, idempotency_key: str
) -> Payment | None:
    if not idempotency_key:
        return None
    stmt = select(Payment).where(
        Payment.business_id == business_id,
        Payment.idempotency_key == idempotency_key,
    )
    return db.execute(stmt).scalars().first()


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id: uuid.UUID | None = None,
    membership_id: uuid.UUID | None = None,
    status: str | None = None,
    method: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Payment], int]:
    stmt = apply_business_scope(select(Payment), Payment, business_id)
    if member_id is not None:
        stmt = stmt.where(Payment.member_id == member_id)
    if membership_id is not None:
        stmt = stmt.where(Payment.membership_id == membership_id)
    if status:
        stmt = stmt.where(Payment.status == status)
    if method:
        stmt = stmt.where(Payment.method == method)
    if created_from is not None:
        stmt = stmt.where(Payment.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Payment.created_at <= created_to)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_PAYMENTS,
        default=Payment.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total
