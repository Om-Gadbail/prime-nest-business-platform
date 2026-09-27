"""Development/test seed: idempotent, non-destructive, no real secrets.

Creates:
- all permissions + system roles + role-permission matrix
- businesses `prime` (fitness) and `nest` (library)
- one empty business_settings row per business
- Blocks 5-7: per-business capabilities + membership plan catalogues
  (Nest pricing lives in the DB, never in UI code) + Nest seat areas

Never deletes data. Safe to run multiple times. Never creates real users or
credentials — tests create their own users via fixtures.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.rbac import ALL_PERMISSIONS, ROLE_PERMISSIONS, SYSTEM_ROLES
from app.core import db_routing as routing
from app.repositories import businesses as business_repo
from app.repositories import memberships as membership_repo
from app.repositories import settings as settings_repo

PRIME_SEED = {
    "slug": "prime",
    "name": "Prime Fitness",
    "business_type": "fitness",
    "status": "active",
    "is_active": True,
    "timezone": "Asia/Kolkata",
    "currency": "INR",
    "locale": "en-IN",
    # Prompt 2 business registry: stable platform identifiers + trusted
    # operational-database mapping (server authority, never client input).
    "external_id": "prime-fitness-001",
    "database_key": "prime_db",
    "config_ref": "template:fitness",
}

NEST_SEED = {
    "slug": "nest",
    "name": "Nest Library",
    "business_type": "library",
    "status": "active",
    "is_active": True,
    "timezone": "Asia/Kolkata",
    "currency": "INR",
    "locale": "en-IN",
    "external_id": "nest-library-001",
    "database_key": "nest_db",
    "config_ref": "template:self_study_center",
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
        # Backfill registry fields on pre-Prompt-2 rows (idempotent,
        # non-destructive: only fills empty/missing values, never renames).
        updated = False
        for field in ("external_id", "database_key", "config_ref"):
            if not getattr(existing, field, None) and seed.get(field):
                setattr(existing, field, seed[field])
                updated = True
        if updated:
            db.flush()
        # Validate the trusted mapping eagerly so a broken registry is
        # loud at seed time instead of failing requests later.
        routing.resolve_database_key(existing)
        return existing
    business = Business(**seed)
    db.add(business)
    db.flush()
    return business


def ensure_businesses(db: Session) -> list[Business]:
    from app.services import business_templates as templates

    prime = ensure_business(db, PRIME_SEED)
    nest = ensure_business(db, NEST_SEED)
    # NOTE (Block 2): public-intake flags (lead_capture_enabled,
    # booking_enabled) are intentionally left unset here. Missing flags
    # read as enabled (see public.operational_flag), so pre-Block-2
    # settings rows keep working and owners disable explicitly per
    # business via PATCH /api/v1/business/settings.
    settings_repo.ensure_for_business(db, prime.id)
    settings_repo.ensure_for_business(db, nest.id)
    # Blocks 5-7: plan catalogues + seat areas from the reusable business
    # templates (idempotent). Capabilities are NOT persisted here: they
    # resolve from template defaults by business_type (see capabilities
    # service) until an owner explicitly overrides them via
    # PATCH /api/v1/business/settings — so seeded settings rows stay
    # empty and explicit staff edits always win.
    prime_spec = templates.TEMPLATES["fitness"]
    templates.ensure_plans(
        db, business_id=prime.id, plans=prime_spec["plans"], currency="INR"
    )
    nest_spec = templates.TEMPLATES["self_study_center"]
    templates.ensure_plans(
        db, business_id=nest.id, plans=nest_spec["plans"], currency="INR"
    )
    templates.ensure_seat_areas(
        db, business_id=nest.id, areas=nest_spec["seat_areas"]
    )
    db.flush()
    return [prime, nest]


def seed_development(db: Session, *, include_owner: bool = True) -> dict[str, object]:
    """Idempotent seed entrypoint. Commits once at the end."""
    rbac = ensure_rbac(db)
    businesses = ensure_businesses(db)
    ensure_blocks812(db, businesses)
    owner = None
    if include_owner:
        owner = ensure_platform_owner(db, businesses=businesses)
    db.commit()
    return {"businesses": businesses, "owner": owner, **rbac}


OWNER_SEED_EMAIL = "owner@prime-nest-dashboard.com"
OWNER_SEED_PASSWORD_DEMO = "OwnerDemo123!"


def ensure_platform_owner(
    db: Session,
    *,
    businesses: list[Business] | None = None,
    email: str | None = None,
    password: str | None = None,
) -> object:
    """Ensure the ONE canonical platform owner identity (idempotent).

    The identity lives in the PLATFORM identity layer exactly once and gains
    explicit memberships to the seeded businesses (Prime + Nest). Running
    twice never duplicates users, credentials, or memberships.

    Credentials: ``password`` wins; else ``OWNER_SEED_PASSWORD`` env; else
    the documented demo default (refused in production — set the env var).
    Only the Argon2id hash is persisted; plaintext never touches the DB.
    The owner is intentionally NOT hardcoded into authorization logic:
    access flows through normal memberships + the existing RBAC matrix.
    """
    import os as _os

    from app.core import security as _security
    from app.repositories import users as _users

    from app.core.config import get_settings as _get_settings

    settings = _get_settings()
    owner_email = (email or settings.owner_seed_email or OWNER_SEED_EMAIL).strip().lower()
    raw_password = password or _os.environ.get("OWNER_SEED_PASSWORD") or settings.owner_seed_password
    if settings.is_production and raw_password == OWNER_SEED_PASSWORD_DEMO:
        raise ValueError(
            "Refusing to seed the demo owner password in production. "
            "Set OWNER_SEED_PASSWORD to a strong value."
        )
    if len(raw_password) < 10 or len(raw_password) > 128:
        raise ValueError("Owner seed password must be 10-128 characters.")

    user = _users.get_by_email(db, owner_email)
    if user is None:
        user = _users.create(
            db,
            email=owner_email,
            password_hash=_security.hash_password(raw_password),
            full_name="Platform Owner",
            is_active=True,
            is_verified=True,
        )
        db.flush()
    # Explicit memberships to every seeded business (OWNER role). Existing
    # memberships are reused; revoked/suspended rows are re-activated so a
    # re-run heals instead of duplicating.
    targets = list(businesses) if businesses is not None else ensure_businesses(db)
    owner_role = membership_repo.get_role_by_name(db, name="OWNER")
    assert owner_role is not None, "RBAC seed must run before owner seed"
    for business in targets:
        membership = membership_repo.get_membership(
            db, user_id=user.id, business_id=business.id
        )
        if membership is None:
            membership_repo.create_membership(
                db,
                user_id=user.id,
                business_id=business.id,
                role_id=owner_role.id,
                status="active",
                is_default=(business.slug == "prime"),
            )
        else:
            if membership.role_id != owner_role.id:
                membership.role_id = owner_role.id
            if membership.status != "active":
                membership.status = "active"
        db.flush()
    return user


def ensure_blocks812(db: Session, businesses: list[Business]) -> dict:
    """Blocks 8-12 seed: default automation + templates + sources + Prime<->Nest link."""
    from app.repositories import blocks812 as brepo
    from app.services import automation as auto_service
    from app.services import communications as comms
    from app.services import growth as growth_service

    for business in businesses:
        auto_service.ensure_default_rules(db, business_id=business.id)
        comms.ensure_default_templates(db, business_id=business.id)
        growth_service.ensure_default_sources(db, business_id=business.id)
    # Prime <-> Nest cross-sell relationship (data, not code branches).
    by_slug = {b.slug: b for b in businesses}
    if "prime" in by_slug and "nest" in by_slug:
        brepo.upsert_relationship(
            db, from_business_id=by_slug["prime"].id, to_business_id=by_slug["nest"].id,
            rel_type="cross_sell", config={"note": "Prime Fitness <-> Nest Library growth link"})
        brepo.upsert_relationship(
            db, from_business_id=by_slug["nest"].id, to_business_id=by_slug["prime"].id,
            rel_type="cross_sell", config={"note": "Nest Library <-> Prime Fitness growth link"})
    db.flush()
    return {"seeded": len(businesses)}


def main() -> None:  # pragma: no cover - manual dev entrypoint
    from app.core.config import get_settings
    from app.core.database import get_session_factory

    factory = get_session_factory()
    db = factory()
    try:
        result = seed_development(
            db, include_owner=get_settings().seed_platform_owner
        )
        businesses = result["businesses"]
        assert isinstance(businesses, list)
        print(f"Seeded {len(businesses)} businesses + RBAC matrix.")
    finally:
        db.close()


def seed_demo_data(db: Session) -> dict:
    """Deterministic DEMO records for Blocks 8-12 walkthroughs (NOT production data).

    Clearly labeled (source/idempotency prefix ``demo-``), idempotent, and
    safe to re-run. Creates per business (prime + nest): leads (+attribution),
    members, active memberships (one expiring soon for renewal demos), paid
    payments, attendance, bookings, referrals, and a sample conversation.
    Run explicitly: ``python -m app.services.seed_demo`` or
    ``SEED_DEMO=true python -m app.services.seed``. Never runs in tests.
    """
    from datetime import date, timedelta

    from sqlalchemy import select as _select
    from app.models.booking import Booking as _Booking
    from app.models.growth import Referral as _Referral
    from app.models.lead import Lead as _Lead
    from app.models.operations import Member as _Member
    from app.services import attendance as attendance_service
    from app.services import bookings as bookings_service
    from app.services import communications as comms
    from app.services import growth as growth_service
    from app.services import leads as leads_service
    from app.services import members as members_service
    from app.services import memberships as memberships_service
    from app.services import payments as payments_service

    businesses = ensure_businesses(db)
    ensure_blocks812(db, businesses)
    created: dict[str, int] = {"leads": 0, "members": 0, "memberships": 0,
                               "payments": 0, "bookings": 0, "referrals": 0}
    for business in businesses:
        slug = business.slug
        # -- leads (deterministic phones; service dedupes contacts) --
        for i, (name, interest, source, attr) in enumerate([
            ("Demo Walker", "General enquiry", "walk_in", "walk-in"),
            ("Demo Searcher", "Membership Inquiry", "google", "google"),
            ("Demo Scroller", "Trial visit", "instagram", "instagram"),
        ]):
            display = f"{name} ({slug})"
            exists = db.execute(_select(_Lead).where(
                _Lead.business_id == business.id,
                _Lead.display_name == display)).scalars().first()
            if exists is None:
                phone = f"+9100000{100 + i if slug == 'prime' else 200 + i}"
                lead = leads_service.create_lead(db, business_id=business.id, data={
                    "display_name": display, "phone": phone,
                    "service_interest": interest, "source": source,
                    "source_detail": "demo-seed", "consent_marketing": True,
                })
                growth_service.record_attribution(
                    db, business_id=business.id, subject_type="lead",
                    subject_id=lead.id, source_code=attr, campaign="demo-seed")
                created["leads"] += 1
        # -- members + memberships (one expiring soon) --
        for i in range(2):
            display = f"Demo Member {i + 1} ({slug})"
            member = db.execute(_select(_Member).where(
                _Member.business_id == business.id,
                _Member.display_name == display)).scalars().first()
            if member is None:
                member = members_service.create_member(db, business_id=business.id, data={
                    "display_name": display,
                    "phone": f"+9100000{310 + i if slug == 'prime' else 410 + i}",
                    "source": "other",
                    "notes": "demo-seed",
                })
                created["members"] += 1
            end = date.today() + timedelta(days=5 if i == 0 else 90)
            membership, is_new = memberships_service.create_membership(
                db, business_id=business.id, data={
                    "member_id": str(member.id),
                    "status": "active",
                    "start_date": (date.today() - timedelta(days=30)).isoformat(),
                    "end_date": end.isoformat(),
                    "price": "2000.00", "currency": "INR",
                    "idempotency_key": f"demo-{slug}-ms-{i}",
                })
            if is_new:
                created["memberships"] += 1
                payment, pay_new = payments_service.create_payment(
                    db, business_id=business.id, data={
                        "member_id": str(member.id),
                        "membership_id": str(membership.id),
                        "amount": "2000.00", "currency": "INR",
                        "method": "upi",
                        "idempotency_key": f"demo-{slug}-pay-{i}",
                    })
                if pay_new:
                    # pending -> paid through the real state machine (paid_at set).
                    payments_service.set_status(db, business_id=business.id,
                                                payment_id=payment.id, to_status="paid")
                    created["payments"] += 1
                try:
                    attendance_service.check_in(db, business_id=business.id,
                                                member_id=member.id, data={"source": "manual"})
                except ValueError:
                    pass
        # -- booking request (stays REQUESTED until staff confirm) --
        if db.execute(_select(_Booking).where(
                _Booking.business_id == business.id,
                _Booking.title == "Demo visit (seed)")).scalars().first() is None:
            bookings_service.create_booking(db, business_id=business.id, data={
                "display_name": f"Demo Booker ({slug})", "phone": "+910000099999",
                "booking_type": "visit", "title": "Demo visit (seed)",
                "source": "website", "notes": "demo-seed",
            })
            created["bookings"] += 1
        # -- referral + sample conversation --
        if db.execute(_select(_Referral).where(
                _Referral.business_id == business.id,
                _Referral.referred_name == f"Demo Friend ({slug})")).scalars().first() is None:
            growth_service.create_referral(db, business_id=business.id, fields={
                "referrer_name": f"Demo Member 1 ({slug})",
                "referred_name": f"Demo Friend ({slug})",
                "referred_phone": "+910000088888", "source": "demo-seed",
                "consent": True, "create_lead": True, "notes": "demo seed referral",
            })
            created["referrals"] += 1
        comms.record_inbound(db, business_id=business.id, channel="whatsapp",
                             external_id="+910000077777", sender="+910000077777",
                             body="Hi! What are your timings? (demo)",
                             provider_message_id=f"demo-{slug}-in-1",
                             raw={"demo": True})
    db.commit()
    return created


if __name__ == "__main__":  # pragma: no cover
    main()
