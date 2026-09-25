"""Business service: creation/update with validation (no SQL outside repos)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.business import BUSINESS_STATUSES, BUSINESS_TYPES, Business
from app.repositories import businesses as business_repo

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if not normalized or len(normalized) > 64 or not _SLUG_RE.match(normalized):
        raise ValueError("Slug must be lowercase alphanumeric with optional hyphens.")
    return normalized


def create_business(
    db: Session,
    *,
    slug: str,
    name: str,
    business_type: str = "other",
    status: str = "active",
    **extra: object,
) -> Business:
    normalized_slug = validate_slug(slug)
    if business_type not in BUSINESS_TYPES:
        raise ValueError(f"business_type must be one of {sorted(BUSINESS_TYPES)}.")
    if status not in BUSINESS_STATUSES:
        raise ValueError(f"status must be one of {sorted(BUSINESS_STATUSES)}.")
    if not name or not name.strip():
        raise ValueError("Business name is required.")
    existing = business_repo.get_by_slug(db, normalized_slug)
    if existing is not None:
        raise ValueError(f"Business slug '{normalized_slug}' already exists.")
    business = business_repo.create(
        db,
        slug=normalized_slug,
        name=name.strip(),
        business_type=business_type,
        status=status,
        is_active=(status == "active"),
        **extra,
    )
    db.commit()
    db.refresh(business)
    return business


# Fields clients may update via PATCH /business (identity subset).
BUSINESS_UPDATABLE_FIELDS = {
    "name",
    "phone",
    "whatsapp",
    "email",
    "website_url",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "postal_code",
    "country",
    "timezone",
    "currency",
    "locale",
}


def update_business(db: Session, *, business: Business, fields: dict) -> Business:
    safe = {k: v for k, v in fields.items() if k in BUSINESS_UPDATABLE_FIELDS}
    if "website_url" in safe and safe["website_url"]:
        _validate_url(str(safe["website_url"]))
    if "timezone" in safe and safe["timezone"]:
        _validate_timezone(str(safe["timezone"]))
    updated = business_repo.update(db, business, **safe)
    db.commit()
    db.refresh(updated)
    return updated


def _validate_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("website_url must be a valid http(s) URL.")


def _validate_timezone(value: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid timezone: {value}") from exc
