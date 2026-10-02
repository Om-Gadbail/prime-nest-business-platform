"""First-boot demo bootstrap (Render free-tier, no Shell).

Provisions the three canonical demo identities on an EMPTY database only:
  owner@prime-nest-dashboard.com (OWNER, prime + nest)
  staff@primefitness.in          (STAFF, prime only)
  staff@nestlibrary.in           (STAFF, nest only)

Safety (all enforced, all tested):
- Runs only when DEMO_PROVISION_ENABLED=true (explicit kill-switch; hardened
  production sets false) AND the users table is empty (zero rows).
- Non-empty databases are never touched (self-disabling after first success;
  later restarts skip; no public endpoint can trigger this).
- Existing users are never password-reset (passwords set only on creation).
- Only the three canonical emails are ever created; arbitrary users untouched.
- Passwords come from settings (OWNER_SEED_PASSWORD / STAFF_SEED_PASSWORD
  env when set, else documented demo defaults); plaintext never logged.
- RBAC + businesses are ensured first via the safe base seed (no users).
- Tenant isolation preserved: staff get exactly one membership each; owner
  gets both; roles are STAFF (staff) / OWNER (owner) on creation.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.user import User

OWNER_EMAIL = "owner@prime-nest-dashboard.com"
PRIME_STAFF_EMAIL = "staff@primefitness.in"
NEST_STAFF_EMAIL = "staff@nestlibrary.in"


def is_bootstrap_needed(db: Session, *, enabled: bool) -> bool:
    """True only when bootstrap is allowed AND the database has zero users."""
    if not enabled:
        return False
    try:
        total = db.execute(select(func.count(User.id))).scalar_one()
    except Exception:
        return False
    return int(total or 0) == 0


def bootstrap_demo_access(db: Session, settings) -> dict:
    """Create the three canonical demo users on an empty DB (idempotent).

    Returns {"created": [...], "skipped": bool, "reason": str}.
    Never raises for expected skip conditions; raises only on DB errors
    (caller decides to log + continue boot).
    """
    from app.core import security
    from app.repositories import memberships as mr
    from app.repositories import users as ur
    from app.services import seed as seed_service

    if not bool(getattr(settings, "demo_provision_enabled", False)):
        return {"created": [], "skipped": True, "reason": "disabled"}
    try:
        total = db.execute(select(func.count(User.id))).scalar_one()
    except Exception as exc:
        raise exc
    if int(total or 0) != 0:
        return {"created": [], "skipped": True, "reason": "non_empty"}

    owner_password = str(
        getattr(settings, "owner_seed_password", "") or ""
    )
    staff_password = str(
        getattr(settings, "staff_seed_password", "") or ""
    )
    if len(owner_password) < 10 or len(staff_password) > 128 or len(staff_password) < 10 or len(owner_password) > 128:
        raise ValueError("Demo seed passwords must be 10-128 characters.")

    # Base platform first (RBAC + businesses + templates, no users).
    seed_service.seed_development(
        db, include_owner=False, include_staff=False
    )
    businesses = {b.slug: b for b in db.execute(select(Business)).scalars().all()}
    if "prime" not in businesses or "nest" not in businesses:
        raise RuntimeError("prime/nest businesses missing after base seed")
    owner_role = mr.get_role_by_name(db, name="OWNER")
    staff_role = mr.get_role_by_name(db, name="STAFF")
    if owner_role is None or staff_role is None:
        raise RuntimeError("RBAC roles missing after base seed")

    created: list[str] = []
    # Owner (both businesses). Users table was empty, so these are creations.
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
        created.append(OWNER_EMAIL)
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
    # Staff (single business each, never OWNER, no password resets).
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
            created.append(email)
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
    db.commit()
    return {"created": created, "skipped": False, "reason": "provisioned"}
