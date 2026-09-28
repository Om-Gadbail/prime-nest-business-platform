"""Business capabilities: configurable module enablement (Blocks 5-7).

Replaces `if business.name == "Prime"` branching with data. Capabilities
live in ``business_settings.operational.capabilities`` (validated JSON)
with template defaults below for businesses created before capabilities
existed. Resolution order:

1. Explicit per-business ``capabilities`` flags in settings.
2. Template default for the business's ``business_type``.
3. Conservative ``False`` for unknown capabilities.

Prime (fitness) vs Nest (library) differ ONLY by these flags + seed data.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.repositories import settings as settings_repo
from app.services.settings import KNOWN_CAPABILITIES

# Template defaults keyed by Business.business_type. `other` stays minimal:
# future businesses opt in explicitly via PATCH /business/settings.
# Blocks 8-12 modules default ON for fitness/library templates (owner can
# disable per business); `other` stays conservative.
_TEMPLATE_EXTRA_8_12 = {
    "automation": True,
    "whatsapp": True,
    "ai_assistant": True,
    "ai_public_chat": True,
    "growth": True,
    "reviews": True,
    "referrals": True,
}
TEMPLATE_DEFAULTS: dict[str, dict[str, bool]] = {
    "fitness": {
        "crm": True,
        "leads": True,
        "bookings": True,
        "memberships": True,
        "members": True,
        "payments": True,
        "attendance": True,
        "renewals": True,
        "plans": True,
        "seat_management": False,
        "fitness_tracking": True,
        "approvals": True,
        "analytics": True,
        "owner_dashboard": True,
        **_TEMPLATE_EXTRA_8_12,
    },
    "library": {
        "crm": True,
        "leads": True,
        "bookings": True,
        "memberships": True,
        "members": True,
        "payments": True,
        "attendance": True,
        "renewals": True,
        "plans": True,
        "seat_management": True,
        "fitness_tracking": False,
        "approvals": True,
        "analytics": True,
        "owner_dashboard": True,
        **_TEMPLATE_EXTRA_8_12,
    },
    "other": {
        "crm": True,
        "leads": True,
        "bookings": True,
        "memberships": False,
        "members": False,
        "payments": False,
        "attendance": False,
        "renewals": False,
        "plans": False,
        "seat_management": False,
        "fitness_tracking": False,
        "approvals": True,
        "analytics": True,
        "owner_dashboard": True,
    },
}


def get_capabilities(
    db: Session, *, business_id: uuid.UUID, business_type: str = "other"
) -> dict[str, bool]:
    """Merged capability map (explicit settings over template defaults)."""
    defaults = dict(TEMPLATE_DEFAULTS.get(business_type, TEMPLATE_DEFAULTS["other"]))
    row = settings_repo.get_by_business(db, business_id)
    operational = dict(getattr(row, "operational", None) or {}) if row else {}
    explicit = operational.get("capabilities") or {}
    for key in KNOWN_CAPABILITIES:
        if key in explicit and isinstance(explicit[key], bool):
            defaults[key] = explicit[key]
    return defaults


def is_enabled(
    db: Session, *, business_id: uuid.UUID, business_type: str, capability: str
) -> bool:
    if capability not in KNOWN_CAPABILITIES:
        raise ValueError(f"Unknown capability: {capability!r}.")
    return bool(
        get_capabilities(db, business_id=business_id, business_type=business_type).get(
            capability, False
        )
    )


def require_capability(
    db: Session, *, business_id: uuid.UUID, business_type: str, capability: str
) -> None:
    """Fail closed (404-style) when a module is disabled for the business."""
    from app.services.errors import NotFoundError

    if not is_enabled(
        db,
        business_id=business_id,
        business_type=business_type,
        capability=capability,
    ):
        raise NotFoundError(f"Module '{capability}' is not enabled for this business.")
