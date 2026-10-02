"""Demo bootstrap (Render free-tier, no Shell).

Ensures the three canonical demo identities whenever DEMO_PROVISION_ENABLED=true:
  owner@prime-nest-dashboard.com (OWNER, prime + nest)
  staff@primefitness.in          (STAFF, prime only)
  staff@nestlibrary.in           (STAFF, nest only)

Safety:
- Flag-gated (hardened production sets DEMO_PROVISION_ENABLED=false).
- Startup-only; no public endpoint can trigger it.
- Only the three canonical emails are ever created/updated; all other users untouched.
- Idempotent (get_by_email checks; re-runs heal to same state, never duplicate).
- Passwords come from settings (OWNER_SEED_PASSWORD / STAFF_SEED_PASSWORD env
  when set, else documented demo defaults); plaintext never logged.
- RBAC + businesses ensured first via safe base seed. Tenant isolation preserved.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business import Business

OWNER_EMAIL = "owner@prime-nest-dashboard.com"
PRIME_STAFF_EMAIL = "staff@primefitness.in"
NEST_STAFF_EMAIL = "staff@nestlibrary.in"

STATE: dict = {"status": "pending", "created": 0, "healed": 0, "reason": "pending"}


def is_bootstrap_needed(db: Session, *, enabled: bool) -> bool:
    """Legacy helper: True when enabled (kept for tests/back-compat)."""
    return bool(enabled)


def bootstrap_demo_access(db: Session, settings) -> dict:
    """Ensure canonical demo users exist with settings passwords (idempotent)."""
    from app.core import security
    from app.repositories import memberships as mr
    from app.repositories import users as ur
    from app.services import seed as seed_service

    if not bool(getattr(settings, "demo_provision_enabled", False)):
        STATE.update({"status": "skipped", "reason": "disabled"})
        return {"created": [], "healed": [], "skipped": True, "reason": "disabled"}

    owner_password = str(getattr(settings, "owner_seed_password", "") or "")
    staff_password = str(getattr(settings, "staff_seed_password", "") or "")
    if len(owner_password) < 10 or len(owner_password) > 128 or len(staff_password) < 10 or len(staff_password) > 128:
        # Config error (e.g. operator cleared demo passwords): fail fast, no retry.
        STATE.update({"status": "skipped", "reason": "bad_password_config"})
        return {"created": [], "healed": [], "skipped": True, "reason": "bad_password_config"}

    seed_service.seed_development(db, include_owner=False, include_staff=False)
    businesses = {b.slug: b for b in db.execute(select(Business)).scalars().all()}
    if "prime" not in businesses or "nest" not in businesses:
        STATE.update({"status": "error", "reason": "no_businesses"})
        raise RuntimeError("prime/nest businesses missing after base seed")
    owner_role = mr.get_role_by_name(db, name="OWNER")
    staff_role = mr.get_role_by_name(db, name="STAFF")
    if owner_role is None or staff_role is None:
        STATE.update({"status": "error", "reason": "no_roles"})
        raise RuntimeError("RBAC roles missing after base seed")

    created: list[str] = []
    healed: list[str] = []

    def ensure_user(email: str, password: str, full_name: str) -> object:
        user = ur.get_by_email(db, email=email)
        if user is None:
            user = ur.create(
                db, email=email, password_hash=security.hash_password(password),
                full_name=full_name, is_active=True, is_verified=True,
            )
            db.flush()
            created.append(email)
        else:
            # Heal to settings password + active/verified (demo instances only;
            # flag false disables entirely). Never touches other users.
            new_hash = security.hash_password(password)
            changed = False
            if not security.verify_password(password, user.password_hash):
                user.password_hash = new_hash
                changed = True
            if not user.is_active or not user.is_verified:
                user.is_active = True
                user.is_verified = True
                changed = True
            if changed:
                db.flush()
                healed.append(email)
        return user

    def ensure_membership(user: object, slug: str, role: object, default: bool) -> None:
        m = mr.get_membership(db, user_id=user.id, business_id=businesses[slug].id)
        if m is None:
            mr.create_membership(
                db, user_id=user.id, business_id=businesses[slug].id,
                role_id=role.id, status="active", is_default=default,
            )
        else:
            touched = False
            if m.status != "active":
                m.status = "active"
                touched = True
            if m.role_id != role.id:
                m.role_id = role.id
                touched = True
            if touched:
                db.flush()

    owner = ensure_user(OWNER_EMAIL, owner_password, "Platform Owner")
    ensure_membership(owner, "prime", owner_role, True)
    ensure_membership(owner, "nest", owner_role, False)
    prime_staff = ensure_user(PRIME_STAFF_EMAIL, staff_password, "Prime Staff")
    ensure_membership(prime_staff, "prime", staff_role, True)
    nest_staff = ensure_user(NEST_STAFF_EMAIL, staff_password, "Nest Staff")
    ensure_membership(nest_staff, "nest", staff_role, True)

    db.commit()
    STATE.update({"status": "ok", "created": len(created), "healed": len(healed), "reason": "ensured"})
    return {"created": created, "healed": healed, "skipped": False, "reason": "ensured"}
