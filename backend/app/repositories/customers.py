"""Customer repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.customer import Customer
from app.repositories.base import apply_business_scope
from app.repositories.pagination import apply_sort, clamp_page


SORTABLE_CUSTOMERS = {
    "created_at": Customer.created_at,
    "updated_at": Customer.updated_at,
    "customer_since": Customer.customer_since,
}


def create(
    db: Session,
    *,
    business_id: uuid.UUID,
    contact_id: uuid.UUID,
    status: str = "active",
    customer_since: datetime | None = None,
    notes: str = "",
) -> Customer:
    customer = Customer(
        business_id=business_id,
        contact_id=contact_id,
        status=status,
        customer_since=customer_since,
        notes=notes,
    )
    db.add(customer)
    db.flush()
    return customer


def get_scoped(
    db: Session,
    *,
    customer_id: object,
    business_id: uuid.UUID,
    with_contact: bool = False,
) -> Customer | None:
    from app.repositories.base import get_scoped as _get

    customer = _get(db, Customer, customer_id, business_id)
    if customer is not None and with_contact:
        db.refresh(customer, attribute_names=["contact"])
    return customer


def get_by_contact(
    db: Session, *, business_id: uuid.UUID, contact_id: uuid.UUID
) -> Customer | None:
    stmt = select(Customer).where(
        Customer.business_id == business_id,
        Customer.contact_id == contact_id,
    )
    return db.execute(stmt).scalars().first()


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Customer], int]:
    stmt = apply_business_scope(select(Customer), Customer, business_id)
    if status:
        stmt = stmt.where(Customer.status == status)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_CUSTOMERS,
        default=Customer.created_at,
    )
    stmt = stmt.options(selectinload(Customer.contact))
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total
