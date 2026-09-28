"""Business Growth + Retention Operating System (Prompt 7).

Event-driven communication and automation engine built ON the existing
foundation — never a rebuild:

    BUSINESS EVENT
          ↓
    EVENT / AUTOMATION ENGINE (app.services.automation — reused)
          ↓
    ELIGIBILITY CHECK (this module — deterministic, backend-owned)
          ↓
    AUTOMATION RULE (per-business rows — reused)
          ↓
    ACTION
          ↓
    GEMINI IF INTELLIGENCE IS USEFUL (this module — intelligence layer only)
          ↓
    WHATSAPP / TASK / NOTIFICATION (communications + business-scoped
    provider — reused)
          ↓
    DELIVERY / EXECUTION STATUS (automation_executions — reused)
          ↓
    OWNER INTELLIGENCE (automation-health + daily brief — reused)

Non-negotiables enforced here:
- Business logic stays deterministic: every workflow entrypoint checks
  real database state FIRST (membership active? already renewed? opted
  out? reminder already sent?). Gemini never decides eligibility.
- Gemini is an intelligence layer, NOT the source of truth: it receives
  structured verified context, drafts wording only, and can never mutate
  the database, select credentials, or invent prices/hours/plans/status.
- WhatsApp sends are business-scoped: all sends flow through
  communications.send_message with the server-verified business_id, which
  resolves that business's OWN credentials (Prime↔Nest isolation holds).
- No Prime/Nest branches: terminology, plans, timing, and templates
  resolve per business from configuration (Business row + settings +
  templates + capabilities). The engine code is business-neutral.
- Idempotency: workflows dispatch through automation.dispatch_event /
  enqueue_for_event, so the (business_id, idempotency_key) execution
  constraint makes duplicate events safe.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings

# Events this engine can process. Every entry must be backed by actual
# existing data/state (see module docstring) — no invented domain state.
SUPPORTED_EVENTS = frozenset(
    {
        "lead.created",
        "lead.contacted",
        "trial.booked",
        "trial.reminder_due",
        "trial.attended",
        "trial.no_show",
        "visit.booked",
        "visit.reminder_due",
        "visit.attended",
        "visit.no_show",
        "membership.created",
        "membership.expiring",
        "membership.expired",
        "membership.renewed",
        "payment.created",
        "payment.success",
        "payment.paid",
        "payment.failed",
        "payment.refunded",
        "member.inactive",
        "customer.inactive",
        "seat.continuity_due",
        "review.received",
        "review.reply_required",
    }
)

# Renewal reminder stages (days before expiry). The scheduler only fires
# stages its infrastructure can support safely; each stage is idempotent
# (duplicate scans collapse on the execution idempotency key).
RENEWAL_STAGES = (30, 14, 7, 3, 1, 0)

# Inactivity window default (days without attendance before retention).
INACTIVITY_DAYS_DEFAULT = 14

# Trial/visit reminder horizon (hours before the booked slot).
REMINDER_HORIZON_HOURS = 24


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _audit(db: Session, *, business_id, action: str, meta: dict | None = None) -> None:
    try:
        from app.services import audit as audit_service

        audit_service.log_event(
            db,
            business_id=business_id,
            action=action,
            entity_type="automation",
            meta=dict(meta or {}),
        )
    except Exception:  # noqa: BLE001 - audit never breaks growth flows
        pass


# ---------------------------------------------------------------------------
# Business configuration context (no hardcoded business data)
# ---------------------------------------------------------------------------


def business_config_context(db: Session, *, business_id: uuid.UUID) -> dict[str, Any]:
    """Structured verified facts about ONE business for templates + Gemini.

    Sources (all server-side): Business row (name/phone/address/hours-ish
    fields), active plan catalogue rows, capabilities. Never invents
    opening hours or plan details — missing values stay empty and the
    template/Gemini layer must cope without inventing them.
    """
    from app.repositories import businesses as business_repo
    from app.repositories import op_memberships as plans_repo
    from app.repositories import settings as settings_repo

    business = business_repo.get_by_id(db, business_id)
    if business is None:
        return {"business": "your business"}
    address_parts = [
        str(getattr(business, "address_line_1", "") or ""),
        str(getattr(business, "city", "") or ""),
        str(getattr(business, "state", "") or ""),
    ]
    plans: list[dict[str, str]] = []
    try:
        rows, _ = plans_repo.list_plans(
            db, business_id=business_id, is_active=True, limit=20, offset=0
        )
        for plan in rows:
            plans.append(
                {
                    "code": str(getattr(plan, "code", "")),
                    "name": str(getattr(plan, "name", "")),
                    "price": str(getattr(plan, "price", "")),
                    "currency": str(getattr(plan, "currency", "") or "INR"),
                }
            )
    except Exception:  # noqa: BLE001 - catalogue is nice-to-have context
        plans = []
    operational: dict = {}
    try:
        row = settings_repo.get_by_business(db, business_id)
        operational = dict(getattr(row, "operational", None) or {})
    except Exception:  # noqa: BLE001
        operational = {}
    return {
        "business": str(getattr(business, "name", "") or "your business"),
        "business_slug": str(getattr(business, "slug", "") or ""),
        "external_id": str(getattr(business, "external_id", "") or ""),
        "phone": str(getattr(business, "phone", "") or ""),
        "whatsapp": str(getattr(business, "whatsapp", "") or ""),
        "email": str(getattr(business, "email", "") or ""),
        "address": ", ".join(p for p in address_parts if p.strip()),
        "city": str(getattr(business, "city", "") or ""),
        "timezone": str(getattr(business, "timezone", "") or "UTC"),
        "currency": str(getattr(business, "currency", "") or "INR"),
        "plans": plans,
        "business_type": str(getattr(business, "business_type", "") or "other"),
        "operational": {
            k: v
            for k, v in operational.items()
            if k not in ("capabilities",) and isinstance(v, (str, int, float, bool))
        },
    }


# ---------------------------------------------------------------------------
# Eligibility (deterministic, backend-owned — Gemini never decides these)
# ---------------------------------------------------------------------------


def eligible_for_whatsapp(db: Session, *, business_id: uuid.UUID, phone: str) -> bool:
    """True unless the recipient opted out of WhatsApp (mandatory gate)."""
    from app.services import communications as comms

    address = (phone or "").strip()
    if not address:
        return False
    return bool(
        comms.is_eligible(
            db, business_id=business_id, channel="whatsapp", address=address
        )
    )


def membership_still_active(
    db: Session, *, business_id: uuid.UUID, membership_id
) -> bool:
    """True only when the membership row is still ACTIVE (renewal guard)."""
    from app.repositories import op_memberships as membership_repo

    row = membership_repo.get_membership(
        db, membership_id=membership_id, business_id=business_id
    )
    return row is not None and str(getattr(row, "status", "")) == "active"


def already_renewed(db: Session, *, business_id: uuid.UUID, membership_id) -> bool:
    """True when a confirmed renewal (or successor row) already exists."""
    from app.models.operations import Membership, Renewal

    try:
        mid = (
            membership_id
            if isinstance(membership_id, uuid.UUID)
            else uuid.UUID(str(membership_id))
        )
    except (ValueError, AttributeError, TypeError):
        return False
    successor = (
        db.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.business_id == business_id, Membership.renewed_from_id == mid
            )
        ).scalar()
        or 0
    )
    if int(successor) > 0:
        return True
    confirmed = (
        db.execute(
            select(func.count())
            .select_from(Renewal)
            .where(
                Renewal.business_id == business_id,
                Renewal.membership_id == mid,
                Renewal.status == "confirmed",
            )
        ).scalar()
        or 0
    )
    return int(confirmed) > 0


def reminder_already_sent(
    db: Session,
    *,
    business_id: uuid.UUID,
    phone: str,
    template_code: str,
    since_hours: int = 72,
) -> bool:
    """True when the same template reached the same recipient recently."""
    from app.models.communication import Message

    cutoff = _utcnow() - timedelta(hours=max(1, since_hours))
    count = (
        db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.business_id == business_id,
                Message.direction == "outbound",
                Message.recipient == (phone or "").strip(),
                Message.template_code == template_code,
                Message.created_at >= cutoff,
            )
        ).scalar()
        or 0
    )
    return int(count) > 0


# ---------------------------------------------------------------------------
# Gemini personalization (intelligence layer with guardrails + fallback)
# ---------------------------------------------------------------------------

# Maximum characters for an AI-drafted customer message.
AI_MESSAGE_MAX_CHARS = 1000


def _gemini_available(settings: Settings) -> bool:
    from app.services import integration_configs as iconf

    cfg = iconf.resolve_gemini_config(settings)
    return bool(cfg.live)


def personalize_message(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    kind: str,
    fallback_body: str,
    context: dict | None = None,
) -> tuple[str, bool]:
    """Draft a customer message with Gemini when useful; else fallback.

    Returns (body, ai_used). ``ai_used`` is True ONLY when a real Gemini
    API call succeeded and its output passed validation — never claimed
    otherwise. Guardrails: structured verified context only (sanitized),
    output validated (non-empty, bounded, no invented secrets/links), and
    any failure resolves to the deterministic fallback so the system keeps
    operating.
    """
    fallback = str(fallback_body or "")[:AI_MESSAGE_MAX_CHARS]
    if not _gemini_available(settings):
        return fallback, False
    try:
        from app.services import integration_configs as iconf
        from app.services.ai_gateway import get_gemini_service

        facts = business_config_context(db, business_id=business_id)
        safe_context = iconf.sanitize_context_for_gemini(
            {
                "kind": str(kind)[:64],
                "customer_name": str(
                    (context or {}).get("display_name", "")
                    or (context or {}).get("name", "")
                )[:80],
                "event_type": str((context or {}).get("event_type", ""))[:64],
                "slot": str(
                    (context or {}).get("slot", "")
                    or (context or {}).get("requested_start_at", "")
                )[:80],
                "expiry": str(
                    (context or {}).get("end_date", "")
                    or (context or {}).get("expiry", "")
                )[:32],
                "amount": str((context or {}).get("amount", ""))[:32],
                "business": facts.get("business", ""),
                "business_type": facts.get("business_type", ""),
            }
        )
        service = get_gemini_service(settings)
        _audit(
            db,
            business_id=business_id,
            action="ai.generation_requested",
            meta={"kind": str(kind)[:64]},
        )
        result = service.chat(
            system=(
                "You draft a short WhatsApp message for a business to send to its customer. "
                "Rules: use ONLY the verified facts provided; never invent prices, opening hours, "
                "addresses, plan names, availability, payment status, or links/URLs. "
                "Keep it under 4 lines, friendly, with a clear next step. "
                "Do not include internal notes, placeholders like {{...}}, or secrets. "
                f"Reference draft (same meaning, may rephrase): {fallback[:500]}"
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Draft a {kind} message for: {safe_context}",
                }
            ],
            business=facts.get("external_id")
            or facts.get("business_slug")
            or "unknown",
            context=safe_context,
        )
        draft = _validate_ai_draft(getattr(result, "text", ""), fallback=fallback)
        if draft is None:
            _audit(
                db,
                business_id=business_id,
                action="ai.generation_failed",
                meta={"kind": str(kind)[:64], "reason": "validation"},
            )
            return fallback, False
        _audit(
            db,
            business_id=business_id,
            action="ai.generation_succeeded",
            meta={"kind": str(kind)[:64]},
        )
        return draft, True
    except Exception:  # noqa: BLE001 - Gemini failure -> honest fallback
        try:
            _audit(
                db,
                business_id=business_id,
                action="ai.generation_failed",
                meta={"kind": str(kind)[:64]},
            )
        except Exception:  # noqa: BLE001
            pass
        return fallback, False


def _validate_ai_draft(text: str, *, fallback: str) -> str | None:
    """Validate a Gemini draft. Returns the cleaned draft or None."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if len(cleaned) < 10:
        return None
    # Never pass through placeholders, secrets-looking content, or
    # invented links (the fallback carries no links unless configured).
    lowered = cleaned.lower()
    for marker in (
        "{{",
        "}}",
        "api_key",
        "password",
        "secret",
        "as an ai",
        "as an ai ",
    ):
        if marker in lowered:
            return None
    if "http" in lowered and "http" not in str(fallback).lower():
        return None
    return cleaned[:AI_MESSAGE_MAX_CHARS]


# ---------------------------------------------------------------------------
# Workflow entrypoints (deterministic eligibility -> automation dispatch)
# ---------------------------------------------------------------------------


def _event_for_entity(
    db: Session,
    *,
    business_id: uuid.UUID,
    event_type: str,
    entity_id,
    payload_match: dict | None = None,
):
    """Find the latest domain event for one logical occurrence (or None).

    ``payload_match`` scopes dedupe to a payload subset (e.g. renewal
    ``offset_days``): the 14-day and 7-day reminders for one membership are
    distinct occurrences and must not collapse into each other.
    """
    from app.models.operations import DomainEvent

    try:
        eid = (
            entity_id
            if isinstance(entity_id, uuid.UUID)
            else (uuid.UUID(str(entity_id)) if entity_id else None)
        )
    except (ValueError, AttributeError, TypeError):
        eid = None
    stmt = (
        select(DomainEvent)
        .where(
            DomainEvent.business_id == business_id,
            DomainEvent.event_type == event_type,
        )
        .order_by(DomainEvent.created_at.desc())
        .limit(25)
    )
    if eid is not None:
        stmt = stmt.where(DomainEvent.entity_id == eid)
    for row in db.execute(stmt).scalars().all():
        if not payload_match:
            return row
        payload = dict(getattr(row, "payload", None) or {})
        if all(payload.get(k) == v for k, v in payload_match.items()):
            return row
    return None


def _dispatch(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    event_type: str,
    entity_type: str | None = None,
    entity_id=None,
    payload: dict | None = None,
    actor_user_id=None,
    fast: bool = False,
    dedupe_payload: dict | None = None,
) -> list:
    """Emit + route one growth event through the automation engine.

    Exactly-once per logical occurrence: when the service layer already
    emitted the domain event for this entity (the normal path), it is
    reused; otherwise it is emitted now. Automation executions stay
    idempotent via (business_id, idempotency_key) regardless.
    """
    from app.services import automation as auto_service

    if event_type not in SUPPORTED_EVENTS:
        raise ValueError(f"Growth engine does not support event {event_type!r}.")
    event = _event_for_entity(
        db,
        business_id=business_id,
        event_type=event_type,
        entity_id=entity_id,
        payload_match=dedupe_payload,
    )
    if event is None:
        event = auto_service.events.emit(
            db,
            business_id=business_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            payload=dict(payload or {}),
        )
        db.flush()
    if not settings.automation_enabled:
        return []
    if fast:
        # Public intake: queue only, worker executes (website stays fast).
        return auto_service.enqueue_for_event(
            db,
            settings,
            business_id=business_id,
            event=event,
            event_type=event_type,
            extra_context=dict(payload or {}),
            actor_user_id=actor_user_id,
        )
    return auto_service.run_rules_for_event(
        db,
        settings,
        business_id=business_id,
        event=event,
        event_type=event_type,
        extra_context=dict(payload or {}),
        actor_user_id=actor_user_id,
    )


def on_lead_created(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    lead,
    actor_user_id=None,
    fast: bool = True,
) -> list:
    """New enquiry/lead -> follow-up automation (Prime + Nest identical)."""
    phone = str(
        getattr(lead, "phone", "") or getattr(lead, "normalized_phone", "") or ""
    )
    facts = business_config_context(db, business_id=business_id)
    payload = {
        "lead_id": str(getattr(lead, "id", "")),
        "display_name": str(getattr(lead, "display_name", "") or ""),
        "name": str(getattr(lead, "display_name", "") or ""),
        "phone": phone,
        "normalized_phone": str(getattr(lead, "normalized_phone", "") or phone),
        "source": str(getattr(lead, "source", "") or ""),
        "service_interest": str(getattr(lead, "service_interest", "") or ""),
        "business": str(facts.get("business", "")),
    }
    return _dispatch(
        db,
        settings,
        business_id=business_id,
        event_type="lead.created",
        entity_type="lead",
        entity_id=getattr(lead, "id", None),
        payload=payload,
        actor_user_id=actor_user_id,
        fast=fast,
    )


def _booking_payload(db: Session, *, business_id: uuid.UUID, booking) -> dict:
    from app.repositories import contacts as contacts_repo

    phone = ""
    name = ""
    contact_id = getattr(booking, "contact_id", None)
    if contact_id is not None:
        contact = contacts_repo.get_scoped(
            db, contact_id=contact_id, business_id=business_id
        )
        if contact is not None:
            phone = str(
                getattr(contact, "phone", "")
                or getattr(contact, "normalized_phone", "")
                or ""
            )
            name = f"{getattr(contact, 'first_name', '') or ''} {getattr(contact, 'last_name', '') or ''}".strip()
    facts = business_config_context(db, business_id=business_id)
    start = getattr(booking, "requested_start_at", None)
    return {
        "booking_id": str(getattr(booking, "id", "")),
        "booking_type": str(getattr(booking, "booking_type", "") or ""),
        "display_name": name,
        "name": name,
        "phone": phone,
        "normalized_phone": phone,
        "slot": start.isoformat() if start is not None else "",
        "requested_start_at": start.isoformat() if start is not None else "",
        "title": str(getattr(booking, "title", "") or ""),
        "business": str(facts.get("business", "")),
    }


def on_booking_intake(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    booking,
    actor_user_id=None,
    fast: bool = True,
) -> list:
    """Visit/trial/enquiry request -> confirmation automation.

    The booking_type selects the event (trial.booked vs visit.booked vs
    booking.created) — terminology differences between businesses are data
    (booking_type + templates), never engine branches.
    """
    booking_type = str(getattr(booking, "booking_type", "") or "").lower()
    if booking_type == "trial":
        event_type = "trial.booked"
    elif booking_type in ("visit", "tour", "demo"):
        event_type = "visit.booked"
    else:
        event_type = "booking.created"
    payload = _booking_payload(db, business_id=business_id, booking=booking)
    return _dispatch(
        db,
        settings,
        business_id=business_id,
        event_type=event_type,
        entity_type="booking",
        entity_id=getattr(booking, "id", None),
        payload=payload,
        actor_user_id=actor_user_id,
        fast=fast,
    )


def record_trial_outcome(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    booking_id,
    outcome: str,
    actor_user_id=None,
) -> tuple[object, list]:
    """Staff-recorded trial/visit outcome -> attended / no-show automation.

    Backed by the real booking state machine: attended closes the booking
    as completed; no_show moves it to the first-class ``no_show`` status.
    Only trial/visit-type bookings qualify — anything else is rejected (no
    invented attendance).
    """
    from app.services import bookings as bookings_service

    clean = str(outcome or "").strip().lower()
    if clean not in ("attended", "no_show"):
        raise ValueError("outcome must be 'attended' or 'no_show'.")
    booking = bookings_service.get_booking(
        db, business_id=business_id, booking_id=booking_id
    )
    booking_type = str(getattr(booking, "booking_type", "") or "").lower()
    if booking_type not in ("trial", "visit", "tour", "demo", "consultation"):
        raise ValueError("Only trial/visit bookings carry trial outcomes.")
    if clean == "attended":
        booking = bookings_service.transition(
            db,
            business_id=business_id,
            booking_id=booking.id,
            to_status="completed",
            actor_user_id=actor_user_id,
        )
        event_type = "trial.attended" if booking_type == "trial" else "visit.attended"
    else:
        booking = bookings_service.transition(
            db,
            business_id=business_id,
            booking_id=booking.id,
            to_status="no_show",
            actor_user_id=actor_user_id,
        )
        event_type = "trial.no_show" if booking_type == "trial" else "visit.no_show"
    payload = _booking_payload(db, business_id=business_id, booking=booking)
    executions = _dispatch(
        db,
        settings,
        business_id=business_id,
        event_type=event_type,
        entity_type="booking",
        entity_id=getattr(booking, "id", None),
        payload=payload,
        actor_user_id=actor_user_id,
        fast=False,
    )
    return booking, executions


def on_payment_event(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    payment,
    status: str,
    actor_user_id=None,
) -> list:
    """Verified payment transition -> confirmation / recovery automation.

    ``status`` is the backend-determined payment state (paid/failed) —
    never a provider claim. Razorpay is NOT live (demo scope): this path
    consumes the deterministic payment state machine only.
    """
    clean = str(status or "").strip().lower()
    if clean not in ("paid", "failed"):
        return []
    facts = business_config_context(db, business_id=business_id)
    payload = {
        "payment_id": str(getattr(payment, "id", "")),
        "amount": str(getattr(payment, "amount", "") or ""),
        "currency": str(
            getattr(payment, "currency", "") or facts.get("currency", "INR")
        ),
        "business": str(facts.get("business", "")),
        "display_name": "",
        "name": "",
        "phone": "",
    }
    member_id = getattr(payment, "member_id", None)
    if member_id is not None:
        try:
            from app.repositories import members as members_repo

            member = members_repo.get(db, member_id=member_id, business_id=business_id)
            if member is not None:
                payload["display_name"] = str(getattr(member, "display_name", "") or "")
                payload["name"] = payload["display_name"]
                payload["phone"] = str(
                    getattr(member, "phone", "")
                    or getattr(member, "normalized_phone", "")
                    or ""
                )
                payload["normalized_phone"] = payload["phone"]
        except Exception:  # noqa: BLE001 - member link is nice-to-have
            pass
    event_type = "payment.success" if clean == "paid" else "payment.failed"
    executions = _dispatch(
        db,
        settings,
        business_id=business_id,
        event_type=event_type,
        entity_type="payment",
        entity_id=getattr(payment, "id", None),
        payload=payload,
        actor_user_id=actor_user_id,
        fast=False,
    )
    # Alias dispatch: rules may subscribe to payment.paid/payment.failed
    # (Block 8 vocab) or payment.success (Prompt 7 vocab) — both fire.
    if clean == "paid":
        executions += _dispatch(
            db,
            settings,
            business_id=business_id,
            event_type="payment.paid",
            entity_type="payment",
            entity_id=getattr(payment, "id", None),
            payload=payload,
            actor_user_id=actor_user_id,
            fast=False,
        )
    return executions


def on_membership_renewed(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    new_membership,
    old_membership_id=None,
    actor_user_id=None,
) -> list:
    """Renewal -> confirmation automation + stop pending renewal nudges."""
    if old_membership_id is not None:
        cancel_pending_renewals(
            db, business_id=business_id, membership_id=old_membership_id
        )
    facts = business_config_context(db, business_id=business_id)
    payload = {
        "membership_id": str(getattr(new_membership, "id", "")),
        "plan": str(getattr(new_membership, "plan_name_snapshot", "") or ""),
        "expiry": str(getattr(new_membership, "end_date", "") or ""),
        "business": str(facts.get("business", "")),
        "display_name": "",
        "name": "",
        "phone": "",
    }
    try:
        from app.repositories import members as members_repo

        member = members_repo.get(
            db,
            member_id=getattr(new_membership, "member_id", None),
            business_id=business_id,
        )
        if member is not None:
            payload["display_name"] = str(getattr(member, "display_name", "") or "")
            payload["name"] = payload["display_name"]
            payload["phone"] = str(
                getattr(member, "phone", "")
                or getattr(member, "normalized_phone", "")
                or ""
            )
            payload["normalized_phone"] = payload["phone"]
    except Exception:  # noqa: BLE001
        pass
    return _dispatch(
        db,
        settings,
        business_id=business_id,
        event_type="membership.renewed",
        entity_type="membership",
        entity_id=getattr(new_membership, "id", None),
        payload=payload,
        actor_user_id=actor_user_id,
        fast=False,
    )


def on_membership_expiring(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    membership,
    offset_days: int,
    actor_user_id=None,
) -> list:
    """One renewal-reminder stage -> automation (eligibility-gated).

    Guards (all deterministic, backend-owned): membership still active,
    not already renewed, recipient opted in, no recent duplicate reminder.
    A renewed membership stops pending nudges instead of sending more.
    """
    membership_id = getattr(membership, "id", None)
    if not membership_still_active(
        db, business_id=business_id, membership_id=membership_id
    ):
        return []
    if already_renewed(db, business_id=business_id, membership_id=membership_id):
        cancel_pending_renewals(
            db, business_id=business_id, membership_id=membership_id
        )
        return []
    facts = business_config_context(db, business_id=business_id)
    display_name = ""
    phone = ""
    try:
        from app.repositories import members as members_repo

        member = members_repo.get(
            db,
            member_id=getattr(membership, "member_id", None),
            business_id=business_id,
        )
        if member is not None:
            display_name = str(getattr(member, "display_name", "") or "")
            phone = str(
                getattr(member, "phone", "")
                or getattr(member, "normalized_phone", "")
                or ""
            )
    except Exception:  # noqa: BLE001
        member = None
    if not phone or not eligible_for_whatsapp(db, business_id=business_id, phone=phone):
        _audit(
            db,
            business_id=business_id,
            action="automation.skipped",
            meta={"reason": "ineligible_recipient", "event": "membership.expiring"},
        )
        return []
    if reminder_already_sent(
        db,
        business_id=business_id,
        phone=phone,
        template_code="renewal_reminder",
        since_hours=20,
    ):
        return []
    payload = {
        "membership_id": str(membership_id or ""),
        "member_id": str(getattr(membership, "member_id", "") or ""),
        "display_name": display_name,
        "name": display_name,
        "phone": phone,
        "normalized_phone": phone,
        "plan": str(getattr(membership, "plan_name_snapshot", "") or ""),
        "expiry": str(getattr(membership, "end_date", "") or ""),
        "end_date": str(getattr(membership, "end_date", "") or ""),
        "offset_days": int(offset_days),
        "business": str(facts.get("business", "")),
        "link": "",
    }
    return _dispatch(
        db,
        settings,
        business_id=business_id,
        event_type="membership.expiring",
        entity_type="membership",
        entity_id=membership_id,
        payload=payload,
        actor_user_id=actor_user_id,
        fast=False,
        dedupe_payload={"offset_days": int(offset_days)},
    )


def on_membership_expired(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    membership,
    actor_user_id=None,
) -> list:
    """Post-expiry follow-up -> automation (win-back, eligibility-gated)."""
    facts = business_config_context(db, business_id=business_id)
    display_name = ""
    phone = ""
    try:
        from app.repositories import members as members_repo

        member = members_repo.get(
            db,
            member_id=getattr(membership, "member_id", None),
            business_id=business_id,
        )
        if member is not None:
            display_name = str(getattr(member, "display_name", "") or "")
            phone = str(
                getattr(member, "phone", "")
                or getattr(member, "normalized_phone", "")
                or ""
            )
    except Exception:  # noqa: BLE001
        pass
    if not phone or not eligible_for_whatsapp(db, business_id=business_id, phone=phone):
        _audit(
            db,
            business_id=business_id,
            action="automation.skipped",
            meta={"reason": "ineligible_recipient", "event": "membership.expired"},
        )
        return []
    if reminder_already_sent(
        db,
        business_id=business_id,
        phone=phone,
        template_code="expiry_notice",
        since_hours=7 * 24,
    ):
        return []
    payload = {
        "membership_id": str(getattr(membership, "id", "") or ""),
        "display_name": display_name,
        "name": display_name,
        "phone": phone,
        "normalized_phone": phone,
        "expiry": str(getattr(membership, "end_date", "") or ""),
        "end_date": str(getattr(membership, "end_date", "") or ""),
        "business": str(facts.get("business", "")),
    }
    return _dispatch(
        db,
        settings,
        business_id=business_id,
        event_type="membership.expired",
        entity_type="membership",
        entity_id=getattr(membership, "id", None),
        payload=payload,
        actor_user_id=actor_user_id,
        fast=False,
    )


def cancel_pending_renewals(
    db: Session, *, business_id: uuid.UUID, membership_id
) -> int:
    """Stop pending renewal automation after a renewal (no post-renew spam)."""
    from app.models.automation import AutomationExecution

    try:
        needle = str(membership_id)
    except Exception:  # noqa: BLE001
        return 0
    stmt = (
        select(AutomationExecution)
        .where(
            AutomationExecution.business_id == business_id,
            AutomationExecution.status.in_(("queued", "pending", "retrying")),
            AutomationExecution.event_type == "membership.expiring",
        )
        .limit(200)
    )
    cancelled = 0
    for row in db.execute(stmt).scalars().all():
        blob = str(dict(row.input_payload or {}))
        if needle in blob:
            row.status = "cancelled"
            row.completed_at = _utcnow()
            row.error = "superseded: membership renewed"
            cancelled += 1
    if cancelled:
        db.flush()
        _audit(
            db,
            business_id=business_id,
            action="automation.completed",
            meta={"cancelled_renewals": cancelled},
        )
    return cancelled


# ---------------------------------------------------------------------------
# Scheduler detection stages (deterministic signals only)
# ---------------------------------------------------------------------------


def detect_inactive_members(
    db: Session,
    *,
    business_id: uuid.UUID,
    days: int = INACTIVITY_DAYS_DEFAULT,
    limit: int = 50,
) -> list[dict]:
    """Active members with no attendance for ``days`` (deterministic signal).

    Gemini never decides inactivity — this query does. Returns member
    descriptors (id, name, phone) the sweep turns into customer.inactive /
    member.inactive events when communication is still allowed.
    """
    from app.models.operations import Attendance, Member

    cutoff = _utcnow().date() - timedelta(days=max(1, days))
    recent_member_ids = set(
        db.execute(
            select(Attendance.member_id).where(
                Attendance.business_id == business_id,
                Attendance.attendance_date >= cutoff,
            )
        )
        .scalars()
        .all()
    )
    members = list(
        db.execute(
            select(Member)
            .where(Member.business_id == business_id, Member.status == "active")
            .order_by(Member.created_at.asc())
            .limit(limit * 4)
        )
        .scalars()
        .all()
    )
    found: list[dict] = []
    for member in members:
        if member.id in recent_member_ids:
            continue
        # Only members who existed for the whole window qualify: a member
        # created yesterday has not been "inactive for N days".
        created = getattr(member, "created_at", None)
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created.date() > cutoff:
                continue
        phone = str(
            getattr(member, "phone", "")
            or getattr(member, "normalized_phone", "")
            or ""
        )
        if not phone or not eligible_for_whatsapp(
            db, business_id=business_id, phone=phone
        ):
            continue
        if reminder_already_sent(
            db,
            business_id=business_id,
            phone=phone,
            template_code="retention_winback",
            since_hours=days * 24,
        ):
            continue
        found.append(
            {
                "member_id": str(member.id),
                "display_name": str(getattr(member, "display_name", "") or ""),
                "phone": phone,
            }
        )
        if len(found) >= limit:
            break
    return found


def detect_reminder_due_bookings(
    db: Session,
    *,
    business_id: uuid.UUID,
    horizon_hours: int = REMINDER_HORIZON_HOURS,
    limit: int = 50,
) -> list[dict]:
    """Confirmed/requested bookings starting within the horizon, unreminded."""
    from app.models.booking import Booking

    now = _utcnow()
    horizon = now + timedelta(hours=max(1, horizon_hours))
    rows = list(
        db.execute(
            select(Booking)
            .where(
                Booking.business_id == business_id,
                Booking.status.in_(("confirmed", "requested")),
                Booking.requested_start_at.is_not(None),
                Booking.requested_start_at >= now,
                Booking.requested_start_at <= horizon,
            )
            .order_by(Booking.requested_start_at.asc())
            .limit(limit * 4)
        )
        .scalars()
        .all()
    )
    due: list[dict] = []
    for booking in rows:
        payload = _booking_payload(db, business_id=business_id, booking=booking)
        phone = payload.get("phone", "")
        if not phone or not eligible_for_whatsapp(
            db, business_id=business_id, phone=phone
        ):
            continue
        if reminder_already_sent(
            db,
            business_id=business_id,
            phone=phone,
            template_code="booking_reminder",
            since_hours=48,
        ):
            continue
        booking_type = str(getattr(booking, "booking_type", "") or "").lower()
        event_type = (
            "trial.reminder_due" if booking_type == "trial" else "visit.reminder_due"
        )
        due.append({"booking": booking, "payload": payload, "event_type": event_type})
        if len(due) >= limit:
            break
    return due


def detect_seat_continuity_due(
    db: Session, *, business_id: uuid.UUID, within_days: int = 14, limit: int = 50
) -> list[dict]:
    """Active seat allocations whose membership expires soon (Nest-capable).

    Only runs meaningfully for businesses with seat_management enabled and
    real allocation rows — otherwise returns [] (no invented seat state).
    """
    from app.models.operations import Membership, SeatAllocation

    today = _utcnow().date()
    horizon = today + timedelta(days=max(1, within_days))
    allocations = list(
        db.execute(
            select(SeatAllocation)
            .where(
                SeatAllocation.business_id == business_id,
                SeatAllocation.status == "active",
            )
            .limit(limit * 4)
        )
        .scalars()
        .all()
    )
    if not allocations:
        return []
    due: list[dict] = []
    for allocation in allocations:
        membership_id = getattr(allocation, "membership_id", None)
        if membership_id is None:
            continue
        membership = db.get(Membership, membership_id)
        if membership is None or membership.business_id != business_id:
            continue
        if str(getattr(membership, "status", "")) != "active":
            continue
        end_date = getattr(membership, "end_date", None)
        if end_date is None or not (today <= end_date <= horizon):
            continue
        if already_renewed(db, business_id=business_id, membership_id=membership.id):
            continue
        try:
            from app.repositories import members as members_repo

            member = members_repo.get(
                db,
                member_id=getattr(allocation, "member_id", None),
                business_id=business_id,
            )
        except Exception:  # noqa: BLE001
            member = None
        phone = (
            str(
                getattr(member, "phone", "")
                or getattr(member, "normalized_phone", "")
                or ""
            )
            if member
            else ""
        )
        if not phone or not eligible_for_whatsapp(
            db, business_id=business_id, phone=phone
        ):
            continue
        if reminder_already_sent(
            db,
            business_id=business_id,
            phone=phone,
            template_code="seat_continuity",
            since_hours=7 * 24,
        ):
            continue
        due.append(
            {
                "allocation_id": str(allocation.id),
                "membership_id": str(membership.id),
                "member_id": str(getattr(allocation, "member_id", "")),
                "display_name": str(getattr(member, "display_name", "") or "")
                if member
                else "",
                "phone": phone,
                "end_date": end_date.isoformat(),
            }
        )
        if len(due) >= limit:
            break
    return due


def detect_failed_payments(
    db: Session, *, business_id: uuid.UUID, limit: int = 50
) -> list[dict]:
    """Failed payments needing recovery (deterministic payment state)."""
    from app.models.operations import Payment

    rows = list(
        db.execute(
            select(Payment)
            .where(Payment.business_id == business_id, Payment.status == "failed")
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "payment_id": str(payment.id),
            "amount": str(getattr(payment, "amount", "")),
            "currency": str(getattr(payment, "currency", "") or "INR"),
            "member_id": str(getattr(payment, "member_id", "") or ""),
        }
        for payment in rows
    ]


# ---------------------------------------------------------------------------
# Human handoff (AI -> staff foundation)
# ---------------------------------------------------------------------------


def create_handoff(
    db: Session,
    *,
    business_id: uuid.UUID,
    customer_name: str = "",
    customer_phone: str = "",
    conversation_id=None,
    summary_points: list[str] | None = None,
    reason: str = "",
    actor_user_id=None,
) -> object:
    """Create a staff follow-up task from an AI/staff handoff.

    The summary contains ONLY caller-verified information (passed in, never
    model-generated secrets). Internal credentials are never included —
    summary points are truncated plain text.
    """
    from app.services import tasks as tasks_service

    points = [str(p)[:300] for p in (summary_points or []) if str(p).strip()][:10]
    lines = [f"- {p}" for p in points] if points else ["- (no summary provided)"]
    description = (
        f"Handoff for {customer_name or 'customer'}"
        f"{f' ({customer_phone})' if customer_phone else ''}.\n"
        f"Reason: {reason[:300] or 'AI requested staff follow-up.'}\n"
        "Summary (verified info only):\n" + "\n".join(lines)
    )
    task = tasks_service.create_task(
        db,
        business_id=business_id,
        title=f"Handoff: follow up with {customer_name or 'customer'}",
        description=description[:2000],
        priority="high",
        created_by_user_id=actor_user_id,
    )
    if conversation_id is not None:
        try:
            from app.repositories import blocks812 as brepo

            brepo.record_delivery(
                db,
                business_id=business_id,
                fields={
                    "message_id": None,
                    "provider_message_id": f"handoff-{task.id}",
                    "status": "handoff",
                    "raw": {"task_id": str(task.id)},
                },
            )
        except Exception:  # noqa: BLE001 - handoff note is nice-to-have
            pass
    db.flush()
    _audit(
        db,
        business_id=business_id,
        action="handoff.created",
        meta={"task": str(task.id)[:36]},
    )
    return task


# ---------------------------------------------------------------------------
# Owner daily brief — optional Gemini enhancement (numbers stay authoritative)
# ---------------------------------------------------------------------------


def enhance_brief_with_gemini(
    settings: Settings,
    *,
    business_id: uuid.UUID,
    facts: dict,
) -> dict:
    """Optionally attach a short Gemini narrative to the deterministic brief.

    Architecture: deterministic analytics -> verified structured facts ->
    Gemini enhancement -> validated output. When Gemini is unavailable the
    brief works unchanged (no ``ai_summary`` key). The numbers are never
    rewritten by the model.
    """
    if not _gemini_available(settings):
        return {"ai_available": False, "ai_summary": None}
    try:
        from app.services import integration_configs as iconf
        from app.services.ai_gateway import get_gemini_service

        safe_facts = iconf.sanitize_context_for_gemini(dict(facts or {}))
        service = get_gemini_service(settings)
        result = service.chat(
            system=(
                "You write a 2-3 sentence owner brief from verified business facts. "
                "Rules: repeat ONLY the numbers given; never invent metrics, comparisons, "
                "or recommendations beyond one generic next step. Plain sentences, no formatting."
            ),
            messages=[{"role": "user", "content": f"Facts: {safe_facts}"}],
            business="unknown",
            context=safe_facts,
        )
        summary = str(getattr(result, "text", "") or "").strip()[:600]
        if len(summary) < 20:
            return {"ai_available": True, "ai_summary": None}
        return {"ai_available": True, "ai_summary": summary}
    except Exception:  # noqa: BLE001 - enhancement never breaks the brief
        return {"ai_available": False, "ai_summary": None}


# ---------------------------------------------------------------------------
# Defaults bootstrap (rules + templates + sources, idempotent)
# ---------------------------------------------------------------------------


def ensure_growth_defaults(
    db: Session, *, business_id: uuid.UUID, created_by=None
) -> dict:
    """Seed per-business growth defaults (safe to run repeatedly)."""
    from app.services import automation as auto_service
    from app.services import communications as comms
    from app.services import growth as growth_service

    rules = auto_service.ensure_default_rules(
        db, business_id=business_id, created_by=created_by
    )
    templates = comms.ensure_default_templates(db, business_id=business_id)
    sources = growth_service.ensure_default_sources(db, business_id=business_id)
    db.flush()
    return {"rules_created": rules, "templates": templates, "sources": sources}


# ---------------------------------------------------------------------------
# Event backlog drain (scheduler stage: API -> event -> worker)
# ---------------------------------------------------------------------------

# Growth event types the backlog drain picks up. Only types whose automation
# is worker-safe (queued first, executed by retry_due) belong here — staff
# synchronous paths dispatch directly and never need the drain.
DRAIN_EVENT_TYPES = (
    "lead.created",
    "trial.booked",
    "visit.booked",
    "booking.created",
    "trial.reminder_due",
    "visit.reminder_due",
    "customer.inactive",
    "member.inactive",
    "payment.success",
    "payment.paid",
    "payment.failed",
    "membership.renewed",
    "seat.continuity_due",
)


def event_has_executions(db: Session, *, business_id: uuid.UUID, event) -> bool:
    """True when automation executions already exist for one domain event."""
    from app.models.automation import AutomationExecution

    try:
        count = (
            db.execute(
                select(func.count())
                .select_from(AutomationExecution)
                .where(
                    AutomationExecution.business_id == business_id,
                    AutomationExecution.event_id == getattr(event, "id", None),
                )
            ).scalar()
            or 0
        )
        return int(count) > 0
    except Exception:  # noqa: BLE001 - lookup failure -> treat as unprocessed
        return False


def drain_event_backlog(
    db: Session, settings: Settings, *, business_id: uuid.UUID, limit: int = 20
) -> int:
    """Enqueue automation for recent growth events that have no executions.

    This is the worker side of the fast website path: public intake commits
    the domain event (+ an immediate enqueue attempt); any event still
    lacking executions — crashed request, older data, direct service writes —
    is picked up here, idempotently. Returns the number of events drained.
    """
    from app.models.operations import DomainEvent
    from app.models.automation import AutomationExecution
    from app.services import automation as auto_service

    if not settings.automation_enabled:
        return 0
    drained = 0
    try:
        cutoff = _utcnow() - timedelta(hours=48)
    except Exception:  # noqa: BLE001
        return 0
    for event_type in DRAIN_EVENT_TYPES:
        try:
            events = list(
                db.execute(
                    select(DomainEvent)
                    .where(
                        DomainEvent.business_id == business_id,
                        DomainEvent.event_type == event_type,
                        DomainEvent.created_at >= cutoff,
                    )
                    .order_by(DomainEvent.created_at.asc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
        except Exception:  # noqa: BLE001 - one type never blocks others
            continue
        for event in events:
            try:
                existing = (
                    db.execute(
                        select(func.count())
                        .select_from(AutomationExecution)
                        .where(
                            AutomationExecution.business_id == business_id,
                            AutomationExecution.event_id == event.id,
                        )
                    ).scalar()
                    or 0
                )
                if int(existing) > 0:
                    continue
                auto_service.enqueue_for_event(
                    db,
                    settings,
                    business_id=business_id,
                    event=event,
                    event_type=event_type,
                )
                drained += 1
                if drained >= limit:
                    db.flush()
                    return drained
            except Exception:  # noqa: BLE001 - per-event safety
                continue
    try:
        db.flush()
    except Exception:  # noqa: BLE001
        pass
    return drained
