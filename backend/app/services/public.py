"""Public (anonymous) business resolution + feature gates.

Anonymous clients never supply business UUIDs — they address a business by
its public slug, which is resolved and verified server-side:

slug -> exists + active -> feature flag enabled -> proceed.

Unknown slug and inactive business both yield NotFoundError (no oracle).
A disabled feature yields ForbiddenError (the public config endpoint
already advertises the flags, so nothing leaks).
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.business import Business
from app.repositories import businesses as business_repo
from app.repositories import settings as settings_repo
from app.services.errors import ForbiddenError, NotFoundError

_SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def normalize_slug(raw: object) -> str:
    slug = str(raw or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise NotFoundError("Business not found.")
    return slug


def resolve_public_business(db: Session, *, slug: object) -> Business:
    clean = normalize_slug(slug)
    business = business_repo.get_by_slug(db, clean)
    if business is None or not business.is_active or business.status != "active":
        raise NotFoundError("Business not found.")
    return business


def operational_flag(db: Session, *, business: Business, flag: str) -> bool:
    """Read an operational feature flag (missing flag => enabled).

    Missing flags default to enabled so Block 1-era settings rows (empty
    ``operational`` section) keep working; the seed writes explicit True.
    Only an explicit ``False`` disables a feature.
    """
    row = settings_repo.get_by_business(db, business.id)
    if row is None:
        return True
    operational = row.operational or {}
    value = operational.get(flag, True)
    return value is True


def require_feature(
    db: Session, *, business: Business, flag: str, feature: str
) -> None:
    if not operational_flag(db, business=business, flag=flag):
        raise ForbiddenError(f"{feature} is currently disabled for this business.")


def public_config(db: Session, *, slug: object) -> dict:
    business = resolve_public_business(db, slug=slug)
    return {
        "slug": business.slug,
        "name": business.name,
        "business_type": business.business_type,
        "timezone": business.timezone or "UTC",
        "lead_capture_enabled": operational_flag(
            db, business=business, flag="lead_capture_enabled"
        ),
        "booking_enabled": operational_flag(
            db, business=business, flag="booking_enabled"
        ),
    }
