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
    idempotency_key: str = "",
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
    # Safe request-level idempotency: a caller-supplied key (e.g. automation
    # execution id, webhook wamid, or client token) returns the existing row
    # WITHOUT re-sending when the same logical message is retried. Stored in
    # ``meta.idempotency_key`` (no schema change; portable across SQLite/PG).
    idem = (idempotency_key or "").strip()[:128]
    if idem:
        existing_idem = repo.get_message_by_idempotency(
            db, business_id=business_id, idempotency_key=idem
        )
        if existing_idem is not None:
            return existing_idem
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
    except MessagingError as exc:
        # Never falsely report delivered: persist an honest FAILED row (no
        # provider_message_id — Meta never accepted it, so there is none)
        # with a credential-free failure reason, then re-raise.
        safe_reason = str(exc)[:300] if str(exc) else "provider_failed"
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
                "provider_message_id": None,
                "automation_id": automation_id,
                "ai_run_id": ai_run_id,
                "meta": {
                    "error": safe_reason,
                    **({"idempotency_key": idem} if idem else {}),
                },
            },
        )
        db.flush()
        raise
    # Idempotency: duplicate provider id -> return existing row (Meta
    # redelivery or transport retry that actually sent twice must not
    # create two logical messages).
    existing = repo.get_message_by_provider(
        db, business_id=business_id, provider_message_id=result.provider_message_id
    )
    if existing is not None:
        return existing
    raw = dict(result.raw or {})
    if idem:
        raw["idempotency_key"] = idem
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
            "meta": raw,
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


def _link_conversation_subject(
    db: Session, *, business_id, conv, phone: str
) -> None:
    """Best-effort lead/contact/customer association for a conversation.

    Matches the sender phone against business-scoped leads/contacts/
    customers (exact phone match) and fills empty FK slots. Never raises;
    never overwrites an existing link (first link wins, staff can correct).
    """
    phone_clean = (phone or "").strip()
    if not phone_clean:
        return
    try:
        if getattr(conv, "lead_id", None) is None:
            from sqlalchemy import select as _select

            from app.models.lead import Lead

            lead = (
                db.execute(
                    _select(Lead)
                    .where(
                        Lead.business_id == business_id,
                        Lead.phone == phone_clean,
                    )
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if lead is not None:
                conv.lead_id = lead.id
    except Exception:  # noqa: BLE001 - linking never breaks inbound
        pass
    try:
        if getattr(conv, "contact_id", None) is None:
            from sqlalchemy import select as _select2

            from app.models.contact import Contact

            contact = (
                db.execute(
                    _select2(Contact)
                    .where(
                        Contact.business_id == business_id,
                        Contact.phone == phone_clean,
                    )
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if contact is not None:
                conv.contact_id = contact.id
    except Exception:  # noqa: BLE001 - linking never breaks inbound
        pass
    try:
        if getattr(conv, "customer_id", None) is None:
            # Customers link via their contact (customers carry no phone
            # column): match the contact by phone, then its customer row.
            from sqlalchemy import select as _select3

            from app.models.contact import Contact as _Contact3
            from app.models.customer import Customer

            contact_row = (
                db.execute(
                    _select3(_Contact3)
                    .where(
                        _Contact3.business_id == business_id,
                        _Contact3.phone == phone_clean,
                    )
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if contact_row is not None:
                customer = (
                    db.execute(
                        _select3(Customer)
                        .where(
                            Customer.business_id == business_id,
                            Customer.contact_id == contact_row.id,
                        )
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if customer is not None:
                    conv.customer_id = customer.id
    except Exception:  # noqa: BLE001 - linking never breaks inbound
        pass


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
    occurred_at=None,
) -> object | None:
    """Inbound handler: dedupes on provider id, links/creates conversation.

    Returns None when there is no usable sender identity (unknown phone):
    the webhook acks without creating empty-identity conversations.
    Timestamp (Meta ``timestamp``) is preserved as the message ``created_at``
    when valid; otherwise the DB default applies. Contact/lead/customer
    association is resolved best-effort by sender phone.
    """
    sender_clean = (sender or external_id or "").strip()
    if not sender_clean:
        return None
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
        external_id=(external_id or sender_clean)[:200],
        subject_name=sender_clean[:200],
        subject_phone=sender_clean[:32],
    )
    _link_conversation_subject(db, business_id=business_id, conv=conv, phone=sender_clean)
    conv.last_message_at = _utcnow()
    fields: dict = {
        "conversation_id": conv.id,
        "direction": "inbound",
        "channel": channel,
        "sender": sender_clean[:200],
        "recipient": "business",
        "body": (body or "")[:MAX_BODY],
        "status": "delivered",
        "provider": channel,
        "provider_message_id": provider_message_id or f"in-{uuid.uuid4().hex[:12]}",
        "meta": dict(raw or {}),
    }
    if occurred_at is not None:
        try:
            from datetime import timezone as _tz

            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=_tz.utc)
            fields["created_at"] = occurred_at
        except Exception:  # noqa: BLE001 - bad timestamp falls back to default
            pass
    msg = repo.create_message(
        db,
        business_id=business_id,
        fields=fields,
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
    # -- Prompt 7 growth + retention templates (generic; business name and
    # -- verified facts are injected per business — never hardcoded) --
    "trial_noshow": {
        "channel": "whatsapp",
        "name": "Missed trial/visit follow-up",
        "body": "Hi {{name}}, we missed you at {{business}} for your visit ({{slot}}). Reply RESCHEDULE and we will find a new time.",
        "variables": ["name", "business", "slot"],
    },
    "retention_winback": {
        "channel": "whatsapp",
        "name": "Inactive member win-back",
        "body": "Hi {{name}}, we have not seen you at {{business}} for a while. Reply VISIT and our team will help you restart.",
        "variables": ["name", "business"],
    },
    "payment_confirm": {
        "channel": "whatsapp",
        "name": "Payment confirmation",
        "body": "Hi {{name}}, we received your payment of {{amount}} {{currency}} at {{business}}. Thank you!",
        "variables": ["name", "amount", "currency", "business"],
    },
    "payment_recovery": {
        "channel": "whatsapp",
        "name": "Failed payment recovery",
        "body": "Hi {{name}}, your payment of {{amount}} {{currency}} at {{business}} did not go through. Reply RETRY and we will help.",
        "variables": ["name", "amount", "currency", "business"],
    },
    "seat_continuity": {
        "channel": "whatsapp",
        "name": "Seat continuity reminder",
        "body": "Hi {{name}}, your seat at {{business}} is linked to a membership expiring on {{expiry}}. Renew to keep your seat.",
        "variables": ["name", "business", "expiry"],
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
