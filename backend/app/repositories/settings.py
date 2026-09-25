"""Business settings repository: SQL only (business_id is authoritative)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.business_settings import BusinessSettings


def get_by_business(db: Session, business_id: uuid.UUID) -> BusinessSettings | None:
    return db.get(BusinessSettings, business_id)


def ensure_for_business(db: Session, business_id: uuid.UUID) -> BusinessSettings:
    existing = get_by_business(db, business_id)
    if existing is not None:
        return existing
    row = BusinessSettings(
        business_id=business_id,
        branding={},
        contact={},
        address={},
        hours={},
        localization={},
        operational={},
    )
    db.add(row)
    db.flush()
    return row


def update_sections(
    db: Session, settings: BusinessSettings, sections: dict[str, dict]
) -> BusinessSettings:
    for section, value in sections.items():
        if hasattr(settings, section) and isinstance(value, dict):
            setattr(settings, section, value)
    db.flush()
    return settings
