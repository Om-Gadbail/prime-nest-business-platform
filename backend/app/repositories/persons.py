"""Identity-link repository: persons + per-business links."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.person import IdentityLink, Person


def get_person_by_signals(
    db: Session,
    *,
    normalized_phone: str | None,
    normalized_email: str | None,
) -> Person | None:
    """Strict lookup: exact normalized match on phone OR email (same business-agnostic)."""
    if normalized_phone:
        row = (
            db.execute(
                select(Person).where(Person.normalized_phone == normalized_phone)
            )
            .scalars()
            .first()
        )
        if row is not None:
            return row
    if normalized_email:
        row = (
            db.execute(
                select(Person).where(Person.normalized_email == normalized_email)
            )
            .scalars()
            .first()
        )
        if row is not None:
            return row
    return None


def create_person(
    db: Session,
    *,
    normalized_phone: str | None,
    normalized_email: str | None,
) -> Person:
    """Insert one person row (flush only). Unique violations raise
    IntegrityError; the SERVICE retries once and reuses the winner
    (same pattern as lead conversion)."""
    person = Person(
        normalized_phone=normalized_phone, normalized_email=normalized_email
    )
    db.add(person)
    db.flush()
    return person


def get_link(
    db: Session, *, business_id: uuid.UUID, contact_id: uuid.UUID
) -> IdentityLink | None:
    stmt = select(IdentityLink).where(
        IdentityLink.business_id == business_id,
        IdentityLink.contact_id == contact_id,
    )
    return db.execute(stmt).scalars().first()


def create_link(
    db: Session,
    *,
    business_id: uuid.UUID,
    person_id: uuid.UUID,
    contact_id: uuid.UUID,
    link_type: str = "auto",
    confidence: str = "",
    created_by_user_id: uuid.UUID | None = None,
    note: str = "",
) -> IdentityLink:
    """Insert one link (flush only). Duplicate (business, contact) raises
    IntegrityError; the SERVICE retries once and reuses the winner."""
    link = IdentityLink(
        business_id=business_id,
        person_id=person_id,
        contact_id=contact_id,
        link_type=link_type,
        confidence=confidence,
        created_by_user_id=created_by_user_id,
        note=(note or "")[:500],
    )
    db.add(link)
    db.flush()
    return link


def list_links_for_person(
    db: Session, *, person_id: uuid.UUID, business_id: uuid.UUID | None = None
) -> list[IdentityLink]:
    stmt = select(IdentityLink).where(IdentityLink.person_id == person_id)
    if business_id is not None:
        stmt = stmt.where(IdentityLink.business_id == business_id)
    return list(db.execute(stmt).scalars().all())


def list_business_links(
    db: Session,
    *,
    business_id: uuid.UUID,
    person_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[IdentityLink], int]:
    from sqlalchemy import func

    from app.repositories.pagination import clamp_page

    limit, offset = clamp_page(limit, offset)
    stmt = select(IdentityLink).where(IdentityLink.business_id == business_id)
    if person_id is not None:
        stmt = stmt.where(IdentityLink.person_id == person_id)
    total = int(
        db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    )
    items = list(
        db.execute(
            stmt.order_by(IdentityLink.created_at.desc()).offset(offset).limit(limit)
        )
        .scalars()
        .all()
    )
    return items, total


def get_person(db: Session, *, person_id: object) -> Person | None:
    try:
        wanted = (
            person_id if isinstance(person_id, uuid.UUID) else uuid.UUID(str(person_id))
        )
    except (ValueError, AttributeError, TypeError):
        return None
    return db.get(Person, wanted)
