"""Provision canonical OWNER-DEMO identities on the live demo backend (Render Shell).

DEMO ONLY — NOT hardened production. Creates the three documented demo
logins with demo passwords so the owner can click through end-to-end:

  owner@prime-nest-dashboard.com  (OWNER of Prime + Nest)
  staff@primefitness.in           (STAFF, prime only)
  staff@nestlibrary.in            (STAFF, nest only)

Run in the Render Shell for service `prime-nest-business-platform`:

  CONFIRM_DEMO_SEED=true python provision_demo_access.py

Requires CONFIRM_DEMO_SEED=true (explicit human confirmation). Passwords
come from OWNER_SEED_PASSWORD / STAFF_SEED_PASSWORD env when set, else the
documented demo defaults. Plaintext passwords are NEVER printed or logged.
Idempotent: re-running heals memberships, never duplicates.

Security: demo passwords MUST NEVER be used on a hardened production
instance with real customer PII/money. This script is for the free-tier
owner-demo instance only.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select

from app.core import security
from app.core.database import get_session_factory, reset_engine_cache
from app.models.business import Business
from app.repositories import memberships as mr
from app.repositories import users as ur
from app.services import seed as seed_service

OWNER_EMAIL = "owner@prime-nest-dashboard.com"
OWNER_DEMO_PASSWORD = "OwnerDemo123!"
PRIME_STAFF_EMAIL = "staff@primefitness.in"
NEST_STAFF_EMAIL = "staff@nestlibrary.in"
STAFF_DEMO_PASSWORD = "StaffDemo123!"


def main() -> None:
    if os.environ.get("CONFIRM_DEMO_SEED", "").lower() not in ("true", "1", "yes"):
        print("REFUSED: set CONFIRM_DEMO_SEED=true to provision demo access.")
        print("Demo passwords are never seeded without explicit confirmation.")
        sys.exit(2)
    print("WARNING: provisioning DEMO credentials (demo instance only).")
    reset_engine_cache()
    owner_password = (
        os.environ.get("OWNER_SEED_PASSWORD") or OWNER_DEMO_PASSWORD
    )
    staff_password = (
        os.environ.get("STAFF_SEED_PASSWORD") or STAFF_DEMO_PASSWORD
    )
    if len(owner_password) < 10 or len(staff_password) < 10:
        print("REFUSED: demo passwords must be 10+ characters.")
        sys.exit(2)
    factory = get_session_factory()
    db = factory()
    try:
        # Base platform (safe, idempotent, no users).
        seed_service.seed_development(
            db, include_owner=False, include_staff=False
        )
        businesses = {
            b.slug: b for b in db.execute(select(Business)).scalars().all()
        }
        assert "prime" in businesses and "nest" in businesses, "prime/nest missing"
        owner_role = mr.get_role_by_name(db, name="OWNER")
        staff_role = mr.get_role_by_name(db, name="STAFF")
        assert owner_role is not None and staff_role is not None, "RBAC missing"

        # Owner (both businesses, OWNER role).
        owner = ur.get_by_email(db, email=OWNER_EMAIL)
        if owner is None:
            owner = ur.create(
                db,
                email=OWNER_EMAIL,
                password_hash=security.hash_password(owner_password),
                full_name="Platform Owner",
                is_active=True,
                is_verified=True,
            )
            db.flush()
            print(f"created owner {OWNER_EMAIL}")
        else:
            print(f"owner exists {OWNER_EMAIL}")
        for slug in ("prime", "nest"):
            m = mr.get_membership(
                db, user_id=owner.id, business_id=businesses[slug].id
            )
            if m is None:
                mr.create_membership(
                    db,
                    user_id=owner.id,
                    business_id=businesses[slug].id,
                    role_id=owner_role.id,
                    status="active",
                    is_default=(slug == "prime"),
                )
                print(f"owner -> {slug} OWNER")
            elif m.status != "active" or m.role_id != owner_role.id:
                m.status = "active"
                m.role_id = owner_role.id
                print(f"owner healed -> {slug} OWNER")

        # Staff (single-business STAFF, never OWNER).
        for email, slug, label in (
            (PRIME_STAFF_EMAIL, "prime", "Prime Staff"),
            (NEST_STAFF_EMAIL, "nest", "Nest Staff"),
        ):
            user = ur.get_by_email(db, email=email)
            if user is None:
                user = ur.create(
                    db,
                    email=email,
                    password_hash=security.hash_password(staff_password),
                    full_name=label,
                    is_active=True,
                    is_verified=True,
                )
                db.flush()
                print(f"created staff {email}")
            else:
                print(f"staff exists {email}")
            m = mr.get_membership(
                db, user_id=user.id, business_id=businesses[slug].id
            )
            if m is None:
                mr.create_membership(
                    db,
                    user_id=user.id,
                    business_id=businesses[slug].id,
                    role_id=staff_role.id,
                    status="active",
                    is_default=True,
                )
                print(f"staff -> {slug} STAFF")
            elif m.status != "active":
                m.status = "active"
                print(f"staff healed -> {slug} STAFF")
            # Ensure no cross-business membership for staff.
            other = "nest" if slug == "prime" else "prime"
            cross = mr.get_membership(
                db, user_id=user.id, business_id=businesses[other].id
            )
            if cross is not None:
                print(f"WARNING: {email} has unexpected {other} membership (left intact)")

        db.commit()
        print("DONE: demo access provisioned (passwords never printed).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
