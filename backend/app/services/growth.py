"""Growth system (Block 11): sources, attribution, referrals, cross-sell.

source -> lead -> contact -> booking -> conversion -> customer -> revenue.
Sources are data rows (GrowthSource), never hardcoded enums. Cross-business
links use BusinessRelationship rows (e.g. Prime <-> Nest configured, not
`if business == ...` branches).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models.ops_vocab import GROWTH_SOURCES_DEFAULT
from app.repositories import blocks812 as repo
from app.services.errors import NotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_money(value: object) -> Decimal:
    """Coerce user/automation revenue input to NUMERIC(12,2)-safe Decimal.

    Rejects NaN/Infinity, negatives, and unparseable strings. Quantizes to
    2dp. Raises ValueError on invalid input (mapped to 422 by _helpers).
    """
    try:
        d = Decimal(str(value).strip() if isinstance(value, str) else str(value))
    except (InvalidOperation, ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Revenue must be a valid decimal amount.") from exc
    if not d.is_finite():
        raise ValueError("Revenue must be a finite amount.")
    if d < 0:
        raise ValueError("Revenue cannot be negative.")
    if d > Decimal("9999999999.99"):
        raise ValueError("Revenue exceeds the maximum supported amount.")
    return d.quantize(Decimal("0.01"))


def _coerce_id(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise NotFoundError("Record not found.") from exc


def ensure_default_sources(db: Session, *, business_id: uuid.UUID) -> int:
    count = 0
    for code in GROWTH_SOURCES_DEFAULT:
        repo.upsert_source(
            db, business_id=business_id, code=code, name=code.replace("-", " ").title()
        )
        count += 1
    db.flush()
    return count


def record_attribution(
    db: Session,
    *,
    business_id: uuid.UUID,
    subject_type: str,
    subject_id=None,
    source_code: str = "other",
    campaign: str = "",
    landing_page: str = "",
    referrer: str = "",
    utm: dict | None = None,
) -> object:
    sources = {s.code for s in repo.list_sources(db, business_id=business_id)}
    if sources and source_code not in sources:
        # Unknown sources fall back to "other" (configurable list stays clean).
        source_code = "other"
    row = repo.create_attribution(
        db,
        business_id=business_id,
        fields={
            "subject_type": subject_type,
            "subject_id": subject_id,
            "source_code": source_code,
            "campaign": campaign[:200],
            "landing_page": landing_page[:500],
            "referrer": referrer[:500],
            "utm": dict(utm or {}),
        },
    )
    db.flush()
    return row


def mark_converted(
    db: Session,
    *,
    business_id: uuid.UUID,
    subject_type: str,
    subject_id,
    revenue: object = "0",
) -> int:
    from sqlalchemy import select as _select
    from app.models.growth import Attribution

    try:
        sid = (
            subject_id
            if isinstance(subject_id, uuid.UUID)
            else uuid.UUID(str(subject_id))
        )
    except (ValueError, AttributeError, TypeError):
        return 0
    amount = _coerce_money(revenue)
    rows = list(
        db.execute(
            _select(Attribution).where(
                Attribution.business_id == business_id,
                Attribution.subject_type == subject_type,
                Attribution.subject_id == sid,
            )
        )
        .scalars()
        .all()
    )
    for r in rows:
        r.converted = True
        r.revenue = amount
    db.flush()
    return len(rows)


def create_referral(db: Session, *, business_id: uuid.UUID, fields: dict) -> object:
    row = repo.create_referral(
        db,
        business_id=business_id,
        fields={
            "referrer_name": str(fields.get("referrer_name", ""))[:200],
            "referrer_phone": fields.get("referrer_phone"),
            "referrer_member_id": fields.get("referrer_member_id"),
            "referred_name": str(fields.get("referred_name", ""))[:200],
            "referred_phone": fields.get("referred_phone"),
            "source": str(fields.get("source", "other"))[:64],
            "status": "pending",
            "consent": bool(fields.get("consent", False)),
            "notes": str(fields.get("notes", ""))[:2000],
        },
    )
    # A referred lead row is created alongside (conversion tracked on it).
    if fields.get("create_lead"):
        from app.services import leads as leads_service

        lead = leads_service.create_lead(
            db,
            business_id=business_id,
            data={
                "display_name": row.referred_name,
                "phone": row.referred_phone,
                "source": "referral",
                "service_interest": "Referred enquiry",
            },
        )
        row.referred_lead_id = lead.id
    db.flush()
    return row


def convert_referral(db: Session, *, business_id: uuid.UUID, referral_id) -> object:
    from sqlalchemy import select as _select
    from app.models.growth import Referral
    from app.repositories.base import apply_business_scope

    rid = _coerce_id(referral_id)
    stmt = apply_business_scope(_select(Referral), Referral, business_id).where(
        Referral.id == rid
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise NotFoundError("Referral not found.")
    row.status = "converted"
    row.converted_at = _utcnow()
    if row.referred_lead_id:
        mark_converted(
            db,
            business_id=business_id,
            subject_type="lead",
            subject_id=row.referred_lead_id,
        )
    db.flush()
    return row


def evaluate_cross_sell(
    db: Session,
    *,
    business_id: uuid.UUID,
    target_business_id,
    member_id=None,
    customer_id=None,
    lead_id=None,
    reason: str = "",
    offer: str = "",
) -> object:
    row = repo.create_xsell(
        db,
        business_id=business_id,
        fields={
            "target_business_id": target_business_id,
            "member_id": member_id,
            "customer_id": customer_id,
            "lead_id": lead_id,
            "eligibility_reason": reason[:1000],
            "offer": offer[:1000],
            "status": "eligible",
            "consent": False,
        },
    )
    db.flush()
    return row


def set_xsell_consent(
    db: Session, *, business_id: uuid.UUID, opportunity_id, consent: bool
) -> object:
    from sqlalchemy import select as _select
    from app.models.growth import CrossSellOpportunity
    from app.repositories.base import apply_business_scope

    oid = _coerce_id(opportunity_id)
    stmt = apply_business_scope(
        _select(CrossSellOpportunity), CrossSellOpportunity, business_id
    ).where(CrossSellOpportunity.id == oid)
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise NotFoundError("Opportunity not found.")
    row.consent = bool(consent)
    row.status = "consented" if consent else "declined"
    db.flush()
    return row


def convert_xsell(db: Session, *, business_id: uuid.UUID, opportunity_id) -> object:
    from sqlalchemy import select as _select
    from app.models.growth import CrossSellOpportunity
    from app.repositories.base import apply_business_scope

    oid = _coerce_id(opportunity_id)
    stmt = apply_business_scope(
        _select(CrossSellOpportunity), CrossSellOpportunity, business_id
    ).where(CrossSellOpportunity.id == oid)
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise NotFoundError("Opportunity not found.")
    if not row.consent:
        raise ValueError("Consent is required before conversion.")
    row.status = "converted"
    row.converted_at = _utcnow()
    db.flush()
    return row
