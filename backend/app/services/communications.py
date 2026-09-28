"""Communication service (Block 9): templates, preferences, send pipeline.

Respects opt-in/opt-out before sending. Every send persists a ``messages``
row + conversation touch + delivery event. Idempotent on
(business_id, provider_message_id).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories import blocks812 as repo
from app.services.messaging import MessagingError, get_messaging_provider

MAX_BODY = 4000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def render_template(body: str, variables: dict) -> str:
    out = str(body or "")
    for key, value in dict(variables or {}).items():
        out = out.replace("{{" + str(key) + "}}", str(value))
    return out[:MAX_BODY]


def is_eligible(
    db: Session, *, business_id: uuid.UUID, channel: str, address: str
) -> bool:
    pref = repo.get_preference(
        db, business_id=business_id, channel=channel, address=address
    )
    if pref is None:
        return True  # no explicit opt-out -> eligible (transactional default)
    return bool(pref.opt_in)


def send_message(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    channel: str,
    to: str,
    body: str,
    template_code: str = "",
    variables: dict | None = None,
    conversation_id=None,
    lead_id=None,
    contact_id=None,
    customer_id=None,
    sender: str = "business",
    automation_id=None,
    ai_run_id=None,
    provider_name: str = "",
) -> object:
    channel = (channel or "whatsapp").strip().lower()
    to_clean = (to or "").strip()
    if not to_clean:
        raise ValueError("Recipient address is required.")
    if not is_eligible(db, business_id=business_id, channel=channel, address=to_clean):
        raise ValueError("Recipient has opted out of this channel.")
    body = (body or "")[:MAX_BODY]
    if not body and not template_code:
        raise ValueError("Message body or template_code is required.")
    # Business-scoped provider resolution (Pre-Prompt-7): the sending
    # business's OWN WhatsApp credentials win; without a live business
    # config the demo-safe log provider records the message (auditable)
    # instead of failing the workflow — and NEVER another tenant's creds.
    from app.repositories import businesses as _business_repo
    from app.services.messaging import get_messaging_provider_for_business

    try:
        _business = _business_repo.get_by_id(db, business_id)
    except Exception:  # noqa: BLE001 - lookup failure -> safe log fallback
        _business = None
    if _business is not None:
        provider = get_messaging_provider_for_business(
            settings,
            _business,
            provider_name or "",
        )
    else:
        provider = get_messaging_provider(
            settings,
            provider_name or ("whatsapp" if settings.whatsapp_enabled else "log"),
        )
    if channel != "whatsapp" and provider.name == "whatsapp":
        from app.services.messaging import LogProvider

        provider = LogProvider()
    try:
        result = provider.send(
            to=to_clean, body=body, template_code=template_code, variables=variables
        )
    except MessagingError:
        msg = repo.create_message(
            db,
            business_id=business_id,
            fields={
                "conversation_id": conversation_id,
                "direction": "outbound",
                "channel": channel,
                "sender": sender,
                "recipient": to_clean,
                "body": body,
                "template_code": template_code,
                "status": "failed",
                "provider": provider.name,
                "provider_message_id": f"failed-{uuid.uuid4().hex[:12]}",
                "automation_id": automation_id,
                "ai_run_id": ai_run_id,
                "meta": {"error": "provider_failed"},
            },
        )
        db.flush()
        raise
    # Idempotency: duplicate provider id -> return existing row.
    existing = repo.get_message_by_provider(
        db, business_id=business_id, provider_message_id=result.provider_message_id
    )
    if existing is not None:
        return existing
    msg = repo.create_message(
        db,
        business_id=business_id,
        fields={
            "conversation_id": conversation_id,
            "direction": "outbound",
            "channel": channel,
            "sender": sender,
            "recipient": to_clean,
            "body": body,
            "template_code": template_code,
            "status": result.status,
            "provider": result.provider,
            "provider_message_id": result.provider_message_id,
            "automation_id": automation_id,
            "ai_run_id": ai_run_id,
            "meta": result.raw,
        },
    )
    repo.record_delivery(
        db,
        business_id=business_id,
        fields={
            "message_id": msg.id,
            "provider_message_id": result.provider_message_id,
            "status": result.status,
            "raw": result.raw,
        },
    )
    db.flush()
    return msg


def record_inbound(
    db: Session,
    *,
    business_id: uuid.UUID,
    channel: str,
    external_id: str,
    sender: str,
    body: str,
    provider_message_id: str,
    raw: dict | None = None,
) -> object:
    """Inbound handler: dedupes on provider id, links/creates conversation."""
    if provider_message_id:
        existing = repo.get_message_by_provider(
            db, business_id=business_id, provider_message_id=provider_message_id
        )
        if existing is not None:
            return existing
    conv = repo.get_or_create_conversation(
        db,
        business_id=business_id,
        channel=channel,
        external_id=external_id or sender,
        subject_name=sender,
        subject_phone=sender,
    )
    conv.last_message_at = _utcnow()
    msg = repo.create_message(
        db,
        business_id=business_id,
        fields={
            "conversation_id": conv.id,
            "direction": "inbound",
            "channel": channel,
            "sender": sender,
            "recipient": "business",
            "body": (body or "")[:MAX_BODY],
            "status": "delivered",
            "provider": channel,
            "provider_message_id": provider_message_id or f"in-{uuid.uuid4().hex[:12]}",
            "meta": dict(raw or {}),
        },
    )
    db.flush()
    return msg


DEFAULT_TEMPLATES: dict[str, dict] = {
    "lead_ack": {
        "channel": "whatsapp",
        "name": "New lead acknowledgement",
        "body": "Hi {{name}}! Thanks for reaching out to {{business}}. We received your enquiry and our team will contact you shortly.",
        "variables": ["name", "business"],
    },
    "trial_confirm": {
        "channel": "whatsapp",
        "name": "Trial/visit confirmation",
        "body": "Hi {{name}}! Your visit to {{business}} is noted for {{slot}}. Reply YES to confirm.",
        "variables": ["name", "business", "slot"],
    },
    "booking_reminder": {
        "channel": "whatsapp",
        "name": "Booking reminder",
        "body": "Reminder: you have a visit at {{business}} on {{slot}}. Reply to reschedule.",
        "variables": ["business", "slot"],
    },
    "followup_1": {
        "channel": "whatsapp",
        "name": "Lead follow-up 1",
        "body": "Hi {{name}}, just following up on your enquiry with {{business}}. Are you still interested?",
        "variables": ["name", "business"],
    },
    "followup_2": {
        "channel": "whatsapp",
        "name": "Lead follow-up 2 (escalation)",
        "body": "Hi {{name}}, last check-in from {{business}}. Reply STOP to opt out, or tell us a good time to call.",
        "variables": ["name", "business"],
    },
    "membership_confirm": {
        "channel": "whatsapp",
        "name": "Membership confirmation",
        "body": "Welcome to {{business}}, {{name}}! Your membership {{plan}} is active till {{expiry}}.",
        "variables": ["name", "business", "plan", "expiry"],
    },
    "renewal_reminder": {
        "channel": "whatsapp",
        "name": "Renewal reminder",
        "body": "Hi {{name}}, your {{business}} membership expires on {{expiry}}. Renew here: {{link}}",
        "variables": ["name", "business", "expiry", "link"],
    },
    "expiry_notice": {
        "channel": "whatsapp",
        "name": "Expiry notice",
        "body": "Hi {{name}}, your {{business}} membership expired on {{expiry}}. Reply RENEW and we will help.",
        "variables": ["name", "business", "expiry"],
    },
    "review_request": {
        "channel": "whatsapp",
        "name": "Review request (neutral)",
        "body": "Hi {{name}}, thanks for visiting {{business}}! Would you share your honest feedback here: {{link}}",
        "variables": ["name", "business", "link"],
    },
}


def ensure_default_templates(db: Session, *, business_id: uuid.UUID) -> int:
    count = 0
    for code, spec in DEFAULT_TEMPLATES.items():
        repo.upsert_template(db, business_id=business_id, code=code, fields=dict(spec))
        count += 1
    db.flush()
    return count


def resolve_business_for_phone_number_id(
    db: Session, settings: Settings, *, phone_number_id: str
):
    """Map a Meta ``phone_number_id`` to its business (no hardcoded branches).

    Resolution order (first hit wins):
    0. Business-scoped env (``PRIME_WHATSAPP_PHONE_NUMBER_ID`` /
       ``NEST_WHATSAPP_PHONE_NUMBER_ID``) — credential-bound, strongest
       signal: the phone id belongs to the business whose credentials hold it.
    1. Per-business ``business_settings.operational.whatsapp.phone_number_id``
       (owner-configured; supports distinct Prime/Nest numbers).
    2. ``WHATSAPP_PHONE_NUMBER_MAP`` env (``"prime:ID,nest:ID"`` → slug lookup).
    3. Single-number fallback: ``WHATSAPP_PHONE_NUMBER_ID`` matches → None
       (ambiguous without a slug; caller must supply the demo ``business_slug``).

    Returns the ``Business`` row or None (never raises; webhook treats None
    as "no business" and acks safely without creating records).
    """
    pid = (phone_number_id or "").strip()
    if not pid:
        return None
    # 0. Credential-bound business-scoped env mapping (isolation-first).
    try:
        from app.services import integration_configs as _iconf

        scoped = _iconf.business_phone_number_ids(settings)
        scope_key = scoped.get(pid, "")
        if scope_key:
            from app.repositories import businesses as _brepo

            business = _brepo.get_by_slug(db, scope_key)
            if (
                business is not None
                and getattr(business, "is_active", False)
                and getattr(business, "status", "") == "active"
            ):
                return business
            return None
    except Exception:  # noqa: BLE001 - resolution must never 500 the webhook
        return None
    try:
        from sqlalchemy import select as _select
        from app.models.business import Business as _Business
        from app.models.business_settings import BusinessSettings as _Settings

        rows = list(
            db.execute(
                _select(_Business, _Settings).join(
                    _Settings, _Settings.business_id == _Business.id, isouter=True
                )
            ).all()
        )
        for business, srow in rows:
            operational = dict(getattr(srow, "operational", None) or {})
            wa = (
                operational.get("whatsapp", {})
                if isinstance(operational.get("whatsapp"), dict)
                else {}
            )
            configured = str(wa.get("phone_number_id", "") or "").strip()
            if configured and configured == pid:
                if (
                    getattr(business, "is_active", False)
                    and getattr(business, "status", "") == "active"
                ):
                    return business
                return None
    except Exception:  # noqa: BLE001 - resolution must never 500 the webhook
        return None
    try:
        slug = settings.whatsapp_phone_map.get(pid, "")
        if slug:
            from app.repositories import businesses as _brepo

            business = _brepo.get_by_slug(db, slug)
            if (
                business is not None
                and getattr(business, "is_active", False)
                and getattr(business, "status", "") == "active"
            ):
                return business
            return None
    except Exception:  # noqa: BLE001
        return None
    return None


def extract_phone_number_ids(payload: dict) -> list[str]:
    """Collect ``metadata.phone_number_id`` values from a Meta webhook payload."""
    found: list[str] = []
    try:
        for entry in payload.get("entry", []) or []:
            for change in (entry or {}).get("changes", []) or []:
                value = (change or {}).get("value", {}) or {}
                metadata = value.get("metadata", {}) or {}
                pid = str(metadata.get("phone_number_id", "") or "").strip()
                if pid and pid not in found:
                    found.append(pid)
    except Exception:  # noqa: BLE001 - vendor shape drift -> empty
        return []
    return found
