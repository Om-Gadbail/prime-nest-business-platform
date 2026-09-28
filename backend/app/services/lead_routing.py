"""Lead routing between Prime / Nest (Block 3, step 13).

"Routing" means the platform correctly determines WHICH business owns a
lead, WHERE it originated, and WHO should handle it — NOT that Prime
staff can see Nest's private leads (they cannot; isolation is absolute).

Deterministic explicit rules first (no AI for basic routing):

1. ``slug`` — slug-addressed public intake (``/public/{slug}/leads``):
   the verified slug IS the owner. Prime website -> Prime, Nest -> Nest.
2. ``intent`` — shared entry points that carry an intent/service
   selection route by keyword map (fitness/trial/gym -> prime,
   library/seat/study -> nest). Ambiguous intent + explicit default
   business -> default with reason recorded; unresolvable -> error.
3. ``staff`` — explicit cross-business transfer by OWNER/ADMIN only,
   creating a linked copy in the target business + audit events in BOTH
   businesses. The source row is never silently moved or deleted.

Every routed lead stores ``routed_by`` / ``routing_reason`` /
``routed_at`` so routing is auditable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ops_vocab import LEAD_ROUTED_BY
from app.repositories import businesses as business_repo
from app.services.errors import ConflictError, ForbiddenError, NotFoundError

# Intent keywords -> business slug. Explicit allowlists (no fuzzy/AI).
PRIME_INTENT_KEYWORDS = frozenset(
    {
        "gym",
        "fitness",
        "workout",
        "trial",
        "personal training",
        "physiotherapy",
        "membership",
        "weight",
        "cardio",
        "yoga",
        "zumba",
        "prime",
    }
)

NEST_INTENT_KEYWORDS = frozenset(
    {
        "library",
        "seat",
        "study",
        "reading",
        "book",
        "exam",
        "upsc",
        "coaching",
        "quiet",
        "nest",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_routed_by(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in LEAD_ROUTED_BY:
        raise ValueError(
            f"Unknown routed_by: {value!r}. Allowed: {sorted(LEAD_ROUTED_BY)}."
        )
    return text


def resolve_by_slug(db: Session, *, slug: str) -> tuple[uuid.UUID, str]:
    """Rule 1: verified slug owns the lead. Returns (business_id, reason)."""
    from app.services import public as public_service

    business = public_service.resolve_public_business(db, slug=slug)
    return business.id, f"Public intake via verified business slug '{business.slug}'."


def resolve_by_intent(
    db: Session,
    *,
    intent: str,
    default_slug: str | None = None,
) -> tuple[uuid.UUID, str]:
    """Rule 2: shared entry point with an intent/service selection.

    Scores explicit keyword hits for each business. Exactly one winner
    routes; ties/zero-hits fall back to ``default_slug`` (recorded) or
    raise when no default is configured.
    """
    text = str(intent or "").strip().lower()
    if not text:
        raise ValueError("Intent is required for intent-based routing.")
    prime_hits = sum(1 for kw in PRIME_INTENT_KEYWORDS if kw in text)
    nest_hits = sum(1 for kw in NEST_INTENT_KEYWORDS if kw in text)
    winner: str | None = None
    if prime_hits > 0 and nest_hits == 0:
        winner = "prime"
    elif nest_hits > 0 and prime_hits == 0:
        winner = "nest"
    if winner is None and default_slug:
        business = business_repo.get_by_slug(db, default_slug.strip().lower())
        if business is None or not business.is_active or business.status != "active":
            raise NotFoundError("Business not found.")
        return business.id, (
            f"Ambiguous intent (prime={prime_hits}, nest={nest_hits}); "
            f"routed to configured default '{business.slug}' for human review."
        )
    if winner is None:
        raise ConflictError(
            "Could not determine the owning business from the provided intent. "
            "Please choose Prime Fitness or Nest Library explicitly."
        )
    business = business_repo.get_by_slug(db, winner)
    if business is None or not business.is_active or business.status != "active":
        raise NotFoundError("Business not found.")
    reason = (
        f"Intent matched {winner} ({prime_hits} prime / {nest_hits} nest keyword hits)."
    )
    return business.id, reason


def routing_metadata(*, routed_by: str, reason: str) -> dict:
    """Build the auditable routing columns for lead creation."""
    return {
        "routed_by": validate_routed_by(routed_by),
        "routing_reason": str(reason or "").strip()[:500],
        "routed_at": _utcnow(),
    }


def transfer_lead(
    db: Session,
    *,
    source_business_id: uuid.UUID,
    lead_id: object,
    target_slug: str,
    reason: str,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> tuple[object, object]:
    """Rule 3: explicit cross-business transfer (OWNER/ADMIN only).

    Creates a LINKED COPY in the target business (routing metadata
    records the source business + actor + reason) and appends an audit
    note on the source lead. The source row is preserved — never moved
    or deleted silently. Normal STAFF can never invoke this (the router
    enforces ``leads.transfer`` + OWNER/ADMIN role first).
    """
    from app.repositories import leads as leads_repo

    if actor_role not in ("OWNER", "ADMIN"):
        raise ForbiddenError("Cross-business transfer requires OWNER or ADMIN.")
    clean_reason = str(reason or "").strip()
    if len(clean_reason) < 10:
        raise ValueError("A transfer reason of at least 10 characters is required.")
    lead = leads_repo.get_scoped(db, lead_id=lead_id, business_id=source_business_id)
    if lead is None:
        raise NotFoundError("Lead not found.")
    target = business_repo.get_by_slug(db, str(target_slug or "").strip().lower())
    if target is None or not target.is_active or target.status != "active":
        raise NotFoundError("Business not found.")
    if target.id == source_business_id:
        raise ConflictError("Source and target businesses are the same.")

    from app.services import leads as leads_service

    source_slug = _slug_of(db, business_id=source_business_id)
    copy_data = {
        "display_name": lead.display_name,
        "phone": lead.phone,
        "email": lead.email,
        "source": lead.source,
        "source_detail": (lead.source_detail or "")
        + f" [transferred from {source_slug}]",
        "service_interest": lead.service_interest,
        "message": lead.message,
        "consent_marketing": bool(lead.consent_marketing),
        "landing_page": lead.landing_page,
        "referrer": lead.referrer,
        "utm_source": lead.utm_source,
        "utm_medium": lead.utm_medium,
        "utm_campaign": lead.utm_campaign,
        "utm_term": lead.utm_term,
        "utm_content": lead.utm_content,
    }
    new_lead = leads_service.create_lead(
        db,
        business_id=target.id,
        data=copy_data,
        actor_user_id=actor_user_id,
    )
    # Stamp auditable routing lineage on the copy.
    new_lead.routed_by = "staff"  # type: ignore[attr-defined]
    new_lead.routing_reason = (  # type: ignore[attr-defined]
        f"Transferred from {source_slug} by staff. Reason: {clean_reason}"[:500]
    )
    new_lead.routed_at = _utcnow()  # type: ignore[attr-defined]
    # Leave a visible trail on the source lead.
    leads_repo.add_activity(
        db,
        business_id=source_business_id,
        lead_id=lead.id,
        activity_type="note",
        note=f"Transferred to {target.slug}. Reason: {clean_reason}"[:2000],
        actor_user_id=actor_user_id,
    )
    db.flush()
    return lead, new_lead


def _slug_of(db: Session, *, business_id: uuid.UUID) -> str:
    from sqlalchemy import select

    from app.models.business import Business

    row = db.execute(select(Business.slug).where(Business.id == business_id)).scalar()
    return str(row or "unknown")
