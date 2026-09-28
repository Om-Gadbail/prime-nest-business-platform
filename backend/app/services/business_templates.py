"""Reusable business templates + provisioning path (Blocks 5-7).

Future clients are onboarded as DATA, not code forks:

    provision_business(db, slug=..., name=..., template="fitness"|"self_study_center")
      -> business + settings (capabilities) + membership plans (+ seat areas)

Plan pricing and seat layouts are template DATA (editable afterwards by
owner/admin). No Prime/Nest literals leak into generic services — the
templates below are the only place business-specific catalogue values
exist, and they are explicitly seed/configuration data.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.business import Business
from app.repositories import businesses as business_repo
from app.repositories import op_memberships as op_membership_repo
from app.repositories import seats as seats_repo
from app.repositories import settings as settings_repo

CURRENCY_DEFAULT = "INR"

# Nest catalogue (Block 7 step 34). Values mirror the product spec exactly:
# no free trial, no invented offers. `best_value` marks the 12-month tiers.
NEST_PLANS: tuple[dict, ...] = (
    # Regular
    {
        "code": "nest-regular-1m",
        "name": "Regular · 1 Month",
        "category": "regular",
        "duration_months": 1,
        "price": Decimal("800"),
        "best_value": False,
    },
    {
        "code": "nest-regular-3m",
        "name": "Regular · 3 Months",
        "category": "regular",
        "duration_months": 3,
        "price": Decimal("2400"),
        "best_value": False,
    },
    {
        "code": "nest-regular-6m",
        "name": "Regular · 6 Months",
        "category": "regular",
        "duration_months": 6,
        "price": Decimal("4800"),
        "best_value": False,
    },
    {
        "code": "nest-regular-8m",
        "name": "Regular · 8 Months",
        "category": "regular",
        "duration_months": 8,
        "price": Decimal("6400"),
        "best_value": False,
    },
    {
        "code": "nest-regular-12m",
        "name": "Regular · 12 Months",
        "category": "regular",
        "duration_months": 12,
        "price": Decimal("9600"),
        "best_value": True,
    },
    # Confirmed
    {
        "code": "nest-confirmed-1m",
        "name": "Confirmed · 1 Month",
        "category": "confirmed",
        "duration_months": 1,
        "price": Decimal("1000"),
        "best_value": False,
    },
    {
        "code": "nest-confirmed-3m",
        "name": "Confirmed · 3 Months",
        "category": "confirmed",
        "duration_months": 3,
        "price": Decimal("3000"),
        "best_value": False,
    },
    {
        "code": "nest-confirmed-6m",
        "name": "Confirmed · 6 Months",
        "category": "confirmed",
        "duration_months": 6,
        "price": Decimal("6000"),
        "best_value": False,
    },
    {
        "code": "nest-confirmed-8m",
        "name": "Confirmed · 8 Months",
        "category": "confirmed",
        "duration_months": 8,
        "price": Decimal("8000"),
        "best_value": False,
    },
    {
        "code": "nest-confirmed-12m",
        "name": "Confirmed · 12 Months",
        "category": "confirmed",
        "duration_months": 12,
        "price": Decimal("12000"),
        "best_value": True,
    },
    # Opening Offer — Regular
    {
        "code": "nest-offer-regular-1m",
        "name": "Opening Offer Regular · 1 Month",
        "category": "opening_regular",
        "duration_months": 1,
        "price": Decimal("699"),
        "best_value": False,
    },
    {
        "code": "nest-offer-regular-3m",
        "name": "Opening Offer Regular · 3 Months",
        "category": "opening_regular",
        "duration_months": 3,
        "price": Decimal("1999"),
        "best_value": False,
    },
    {
        "code": "nest-offer-regular-6m",
        "name": "Opening Offer Regular · 6 Months",
        "category": "opening_regular",
        "duration_months": 6,
        "price": Decimal("3999"),
        "best_value": False,
    },
    {
        "code": "nest-offer-regular-8m",
        "name": "Opening Offer Regular · 8 Months",
        "category": "opening_regular",
        "duration_months": 8,
        "price": Decimal("4999"),
        "best_value": False,
    },
    {
        "code": "nest-offer-regular-12m",
        "name": "Opening Offer Regular · 12 Months",
        "category": "opening_regular",
        "duration_months": 12,
        "price": Decimal("7999"),
        "best_value": True,
    },
    # Opening Offer — Confirmed
    {
        "code": "nest-offer-confirmed-1m",
        "name": "Opening Offer Confirmed · 1 Month",
        "category": "opening_confirmed",
        "duration_months": 1,
        "price": Decimal("899"),
        "best_value": False,
    },
    {
        "code": "nest-offer-confirmed-3m",
        "name": "Opening Offer Confirmed · 3 Months",
        "category": "opening_confirmed",
        "duration_months": 3,
        "price": Decimal("2599"),
        "best_value": False,
    },
    {
        "code": "nest-offer-confirmed-6m",
        "name": "Opening Offer Confirmed · 6 Months",
        "category": "opening_confirmed",
        "duration_months": 6,
        "price": Decimal("4999"),
        "best_value": False,
    },
    {
        "code": "nest-offer-confirmed-8m",
        "name": "Opening Offer Confirmed · 8 Months",
        "category": "opening_confirmed",
        "duration_months": 8,
        "price": Decimal("5999"),
        "best_value": False,
    },
    {
        "code": "nest-offer-confirmed-12m",
        "name": "Opening Offer Confirmed · 12 Months",
        "category": "opening_confirmed",
        "duration_months": 12,
        "price": Decimal("9999"),
        "best_value": True,
    },
)

# Generic fitness starter catalogue (editable seed for Prime + future gyms).
FITNESS_PLANS: tuple[dict, ...] = (
    {
        "code": "fitness-monthly",
        "name": "Monthly",
        "category": "regular",
        "duration_months": 1,
        "price": Decimal("1500"),
        "best_value": False,
    },
    {
        "code": "fitness-quarterly",
        "name": "Quarterly",
        "category": "regular",
        "duration_months": 3,
        "price": Decimal("4000"),
        "best_value": False,
    },
    {
        "code": "fitness-half-yearly",
        "name": "Half Yearly",
        "category": "regular",
        "duration_months": 6,
        "price": Decimal("7500"),
        "best_value": False,
    },
    {
        "code": "fitness-annual",
        "name": "Annual",
        "category": "regular",
        "duration_months": 12,
        "price": Decimal("12000"),
        "best_value": True,
    },
)

TEMPLATES: dict[str, dict] = {
    "fitness": {
        "business_type": "fitness",
        "plans": FITNESS_PLANS,
        "seat_areas": (),
        "capabilities": {
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
        },
    },
    "self_study_center": {
        "business_type": "library",
        "plans": NEST_PLANS,
        "seat_areas": (
            {
                "code": "ground-regular",
                "name": "Ground Floor · Regular",
                "floor": "Ground",
            },
            {
                "code": "first-confirmed",
                "name": "First Floor · Confirmed",
                "floor": "First",
            },
        ),
        "capabilities": {
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
        },
    },
}


def ensure_plans(
    db: Session,
    *,
    business_id: uuid.UUID,
    plans: tuple[dict, ...],
    currency: str = CURRENCY_DEFAULT,
) -> int:
    """Idempotent plan seeding (matched by code; never duplicates)."""
    created = 0
    for spec in plans:
        existing = op_membership_repo.get_plan_by_code(
            db, business_id=business_id, code=str(spec["code"])
        )
        if existing is not None:
            continue
        op_membership_repo.create_plan(
            db,
            business_id=business_id,
            fields={
                "code": str(spec["code"]),
                "name": str(spec["name"]),
                "category": str(spec.get("category", "custom")),
                "duration_months": int(spec.get("duration_months", 1)),
                "price": Decimal(str(spec.get("price", "0"))),
                "currency": currency,
                "is_best_value": bool(spec.get("best_value", False)),
                "is_active": True,
                "features": {"free_registration": True},
                "version": 1,
            },
        )
        created += 1
    db.flush()
    return created


def ensure_seat_areas(
    db: Session, *, business_id: uuid.UUID, areas: tuple[dict, ...]
) -> int:
    created = 0
    for spec in areas:
        rows, _ = seats_repo.list_areas(
            db, business_id=business_id, limit=100, offset=0
        )
        if any(a.code == spec["code"] for a in rows):
            continue
        seats_repo.create_area(
            db,
            business_id=business_id,
            fields={
                "code": str(spec["code"]),
                "name": str(spec.get("name", spec["code"])),
                "floor": str(spec.get("floor", "")),
                "description": str(spec.get("description", "")),
            },
        )
        created += 1
    db.flush()
    return created


def ensure_capabilities(
    db: Session, *, business_id: uuid.UUID, capabilities: dict
) -> None:
    row = settings_repo.ensure_for_business(db, business_id)
    operational = dict(getattr(row, "operational", None) or {})
    existing = dict(operational.get("capabilities") or {})
    merged = {**capabilities, **existing}  # explicit staff edits always win
    operational["capabilities"] = merged
    settings_repo.update_sections(db, row, {"operational": operational})
    db.flush()


def provision_business(
    db: Session,
    *,
    slug: str,
    name: str,
    template: str,
    timezone: str = "Asia/Kolkata",
    currency: str = CURRENCY_DEFAULT,
) -> Business:
    """Documented provisioning path for future clients (idempotent).

    Creates (or reuses) the business, applies template capabilities, and
    seeds the template plan catalogue + seat areas. Safe to run twice.
    """
    if template not in TEMPLATES:
        raise ValueError(
            f"Unknown business template: {template!r}. Allowed: {sorted(TEMPLATES)}."
        )
    spec = TEMPLATES[template]
    business = business_repo.get_by_slug(db, slug)
    if business is None:
        business = Business(
            slug=slug,
            name=name,
            business_type=str(spec["business_type"]),
            status="active",
            is_active=True,
            timezone=timezone,
            currency=currency,
            locale="en-IN",
        )
        db.add(business)
        db.flush()
    settings_repo.ensure_for_business(db, business.id)
    ensure_capabilities(db, business_id=business.id, capabilities=spec["capabilities"])
    ensure_plans(db, business_id=business.id, plans=spec["plans"], currency=currency)
    ensure_seat_areas(db, business_id=business.id, areas=spec["seat_areas"])
    db.flush()
    return business
