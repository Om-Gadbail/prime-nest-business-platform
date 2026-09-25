"""Development/test seed: idempotent, non-destructive, no real secrets.

Creates:
- all permissions + system roles + role-permission matrix
- businesses `prime` (fitness) and `nest` (library)
- one empty business_settings row per business

Never deletes data. Safe to run multiple times. Never creates real users or
credentials — tests create their own users via fixtures.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.rbac import ALL_PERMISSIONS, ROLE_PERMISSIONS, SYSTEM_ROLES
from app.repositories import businesses as business_repo
from app.repositories import memberships as membership_repo
from app.repositories import settings as settings_repo

PRIME_SEED = {
    "slug": "prime",
    "name": "Prime Fitness",
    "business_type": "fitness",
    "status": "active",
    "is_active": True,
    "timezone": "UTC",
    "currency": None,
    "locale": None,
}

NEST_SEED = {
    "slug": "nest",
    "name": "Nest Library",
    "business_type": "library",
    "status": "active",
    "is_active": True,
    "timezone": "UTC",
    "currency": None,
    "locale": None,
}

_ROLE_DESCRIPTIONS = {
    "OWNER": "Full control of the business.",
    "ADMIN": "Operational administration (no platform-level grants).",
    "MANAGER": "Day-to-day operational management.",
    "STAFF": "Frontline operational access.",
    "VIEWER": "Read-only access.",
}


def ensure_rbac(db: Session) -> dict[str, object]:
    roles = {}
    for role_name in SYSTEM_ROLES:
        role = membership_repo.ensure_role(
            db,
            name=role_name,
            display_name=role_name.title(),
            description=_ROLE_DESCRIPTIONS.get(role_name, ""),
            business_id=None,
            is_system=True,
        )
        roles[role_name] = role
    permissions = {}
    for key in ALL_PERMISSIONS:
        permissions[key] = membership_repo.ensure_permission(db, key=key)
    for role_name, keys in ROLE_PERMISSIONS.items():
        role = roles[role_name]
        for key in keys:
            perm = permissions[key]
            membership_repo.grant_permission(db, role_id=role.id, permission_id=perm.id)
    db.flush()
    return {"roles": roles, "permissions": permissions}


def ensure_business(db: Session, seed: dict) -> Business:
    existing = business_repo.get_by_slug(db, str(seed["slug"]))
    if existing is not None:
        return existing
    business = Business(**seed)
    db.add(business)
    db.flush()
    return business


def ensure_businesses(db: Session) -> list[Business]:
    prime = ensure_business(db, PRIME_SEED)
    nest = ensure_business(db, NEST_SEED)
    settings_repo.ensure_for_business(db, prime.id)
    settings_repo.ensure_for_business(db, nest.id)
    db.flush()
    return [prime, nest]


def seed_development(db: Session) -> dict[str, object]:
    """Idempotent seed entrypoint. Commits once at the end."""
    rbac = ensure_rbac(db)
    businesses = ensure_businesses(db)
    db.commit()
    return {"businesses": businesses, **rbac}


def main() -> None:  # pragma: no cover - manual dev entrypoint
    from app.core.database import get_session_factory

    factory = get_session_factory()
    db = factory()
    try:
        result = seed_development(db)
        businesses = result["businesses"]
        assert isinstance(businesses, list)
        print(f"Seeded {len(businesses)} businesses + RBAC matrix.")
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    main()
