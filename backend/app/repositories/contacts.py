"""Contact repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.repositories.base import apply_business_scope
from app.repositories.pagination import apply_sort, clamp_page


SORTABLE_CONTACTS = {
    "created_at": Contact.created_at,
    "updated_at": Contact.updated_at,
    "first_name": Contact.first_name,
    "last_name": Contact.last_name,
}


def create(
    db: Session,
    *,
    business_id: uuid.UUID,
    first_name: str = "",
    last_name: str = "",
    phone: str | None = None,
    normalized_phone: str | None = None,
    email: str | None = None,
    normalized_email: str | None = None,
    preferred_contact_channel: str = "other",
    source: str = "other",
    notes: str = "",
    status: str = "active",
) -> Contact:
    contact = Contact(
        business_id=business_id,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        normalized_phone=normalized_phone,
        email=email,
        normalized_email=normalized_email,
        preferred_contact_channel=preferred_contact_channel,
        source=source,
        notes=notes,
        status=status,
    )
    db.add(contact)
    db.flush()
    return contact


def get_scoped(
    db: Session, *, contact_id: object, business_id: uuid.UUID
) -> Contact | None:
    from app.repositories.base import get_scoped as _get

    return _get(db, Contact, contact_id, business_id)


def find_by_normalized(
    db: Session,
    *,
    business_id: uuid.UUID,
    normalized_phone: str | None = None,
    normalized_email: str | None = None,
) -> Contact | None:
    """Best-effort match for intake dedup (never leaks across businesses)."""
    conditions = []
    if normalized_phone:
        conditions.append(Contact.normalized_phone == normalized_phone)
    if normalized_email:
        conditions.append(Contact.normalized_email == normalized_email)
    if not conditions:
        return None
    stmt = select(Contact).where(Contact.business_id == business_id)
    stmt = stmt.where(or_(*conditions)).order_by(Contact.created_at.asc()).limit(1)
    return db.execute(stmt).scalars().first()


def _filtered_stmt(
    db: Session,
    *,
    business_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
) -> object:
    stmt = apply_business_scope(select(Contact), Contact, business_id)
    if status:
        stmt = stmt.where(Contact.status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Contact.first_name.ilike(like),
                Contact.last_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
                Contact.normalized_phone.ilike(like),
                Contact.normalized_email.ilike(like),
            )
        )
    return stmt


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Contact], int]:
    stmt = _filtered_stmt(db, business_id=business_id, search=search, status=status)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_CONTACTS,
        default=Contact.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def set_fields(contact: Contact, fields: dict) -> Contact:
    for key, value in fields.items():
        if hasattr(contact, key):
            setattr(contact, key, value)
    return contact


def touch_updated(contact: Contact, *, now: datetime) -> None:
    contact.updated_at = now
