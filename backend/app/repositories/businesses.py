"""Business repository: SQL only."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business import Business


def get_by_id(db: Session, business_id: uuid.UUID) -> Business | None:
    return db.get(Business, business_id)


def get_by_slug(db: Session, slug: str) -> Business | None:
    stmt = select(Business).where(Business.slug == slug.strip().lower())
    return db.execute(stmt).scalars().first()


def list_all(db: Session) -> list[Business]:
    return list(db.execute(select(Business).order_by(Business.slug)).scalars().all())


def create(db: Session, **fields: object) -> Business:
    business = Business(**fields)  # type: ignore[arg-type]
    db.add(business)
    db.flush()
    return business


def update(db: Session, business: Business, **fields: object) -> Business:
    for key, value in fields.items():
        if hasattr(business, key) and value is not None:
            setattr(business, key, value)
    db.flush()
    return business
