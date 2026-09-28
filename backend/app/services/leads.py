"""Lead service: intake, lifecycle, assignment, notes, conversion.

Conversion is transactional: contact resolve + customer get-or-create +
lead state change + activity + notification commit atomically, and the
``uq_customers_business_contact`` constraint makes concurrent conversions
collapse to one customer row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crm_vocab import (
    LEAD_ACTIVITY_TYPES,
    LEAD_SOURCES,
    LEAD_STATUSES,
    LEAD_TERMINAL_STATUSES,
)
from app.repositories import customers as customers_repo
from app.repositories import leads as leads_repo
from app.services import normalize as norm
from app.services.crm import (
    _clean_text,
    _require_valid_email,
    _validate_enum,
    require_active_member,
    resolve_contact_for_intake,
    validate_search,
)
from app.services.errors import ConflictError, NotFoundError
from app.services.notifications import notify_assignment, notify_new_lead

# Staff-driven lifecycle. Terminal states only allow explicit reopen via
# lost -> new; converted/spam never transition out.
LEAD_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"contacted", "qualified", "lost", "spam"}),
    "contacted": frozenset({"qualified", "booked", "lost", "spam"}),
    "qualified": frozenset({"booked", "contacted", "lost", "spam"}),
    "booked": frozenset({"converted", "contacted", "lost", "spam"}),
    "converted": frozenset(),
    "lost": frozenset({"new"}),
    "spam": frozenset(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _lead_fields_from_input(data: dict, *, source_default: str = "website") -> dict:
    phone = _clean_text(data.get("phone"), max_chars=32) or None
    email = _clean_text(data.get("email"), max_chars=320) or None
    if email:
        _require_valid_email(email)
    return {
        "display_name": _clean_text(
            data.get("display_name") or data.get("name"), max_chars=200
        ),
        "phone": phone,
        "normalized_phone": norm.normalize_phone(phone),
        "email": email,
        "normalized_email": norm.normalize_email(email),
        "source": _validate_enum(
            data.get("source", source_default),
            allowed=LEAD_SOURCES,
            field="source",
            default=source_default,
        ),
        "source_detail": _clean_text(data.get("source_detail"), max_chars=200),
        "service_interest": _clean_text(
            data.get("service_interest") or data.get("interest"), max_chars=200
        ),
        "message": _clean_text(data.get("message"), max_chars=2000),
        "follow_up_at": data.get("follow_up_at"),
        "consent_marketing": bool(data.get("consent_marketing", False)),
        "landing_page": _clean_text(data.get("landing_page"), max_chars=500),
        "referrer": _clean_text(data.get("referrer"), max_chars=500),
        "utm_source": _clean_text(data.get("utm_source"), max_chars=200),
        "utm_medium": _clean_text(data.get("utm_medium"), max_chars=200),
        "utm_campaign": _clean_text(data.get("utm_campaign"), max_chars=200),
        "utm_term": _clean_text(data.get("utm_term"), max_chars=200),
        "utm_content": _clean_text(data.get("utm_content"), max_chars=200),
    }


def create_lead(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    assigned_user_id: uuid.UUID | None = None,
    routing: dict | None = None,
    settings=None,
) -> object:
    """Staff lead creation (contact resolved or created inline).

    Emits ``lead.created`` (fast domain-event row, part of the caller's
    transaction). When ``settings`` is provided, the growth engine also
    routes the event through automation (staff path: synchronous run).
    Callers that pass no settings get event-log-only behavior.
    """
    from app.services import lead_routing as routing_service

    fields = _lead_fields_from_input(data)
    if not fields["display_name"] and not fields["phone"] and not fields["email"]:
        raise ValueError("Lead needs at least a name, phone, or email.")
    resolved_contact_id = contact_id
    if resolved_contact_id is None and (fields["phone"] or fields["email"]):
        first, last = norm.split_name(fields["display_name"])
        contact = resolve_contact_for_intake(
            db,
            business_id=business_id,
            first_name=first,
            last_name=last,
            phone=fields["phone"],
            email=fields["email"],
            source=fields["source"],
        )
        resolved_contact_id = contact.id
    if resolved_contact_id is not None:
        from app.repositories import contacts as contacts_repo

        contact = contacts_repo.get_scoped(
            db, contact_id=resolved_contact_id, business_id=business_id
        )
        if contact is None:
            raise NotFoundError("Contact not found.")
    if assigned_user_id is not None:
        require_active_member(db, business_id=business_id, user_id=assigned_user_id)
        fields["assigned_user_id"] = assigned_user_id
    fields["contact_id"] = resolved_contact_id
    if routing is not None:
        fields["routed_by"] = routing_service.validate_routed_by(
            routing.get("routed_by", "staff")
        )
        fields["routing_reason"] = str(routing.get("reason", ""))[:500]
        fields["routed_at"] = routing.get("routed_at") or routing_service._utcnow()
    else:
        fields["routed_by"] = "staff"
        fields["routing_reason"] = "Created by staff in the owning business."
        fields["routed_at"] = routing_service._utcnow()
    lead = leads_repo.create(db, business_id=business_id, fields=fields)
    leads_repo.add_activity(
        db,
        business_id=business_id,
        lead_id=lead.id,
        activity_type="note",
        note="Lead created.",
        actor_user_id=actor_user_id,
    )
    if assigned_user_id is not None:
        notify_assignment(
            db,
            business_id=business_id,
            assignee_user_id=assigned_user_id,
            kind="lead",
            record_id=lead.id,
            title=f"Lead assigned: {lead.display_name or 'new lead'}",
        )
    else:
        notify_new_lead(
            db, business_id=business_id, lead_id=lead.id, lead_name=lead.display_name
        )
    db.flush()
    _emit_lead_created(
        db, business_id=business_id, lead=lead, actor_user_id=actor_user_id
    )
    if settings is not None and bool(getattr(settings, "automation_enabled", False)):
        try:
            from app.services import growth_engine as _growth

            _growth.on_lead_created(
                db,
                settings,
                business_id=business_id,
                lead=lead,
                actor_user_id=actor_user_id,
                fast=False,
            )
        except Exception:  # noqa: BLE001 - automation never breaks lead capture
            pass
    return lead


def intake_lead(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    routing: dict | None = None,
    settings=None,
) -> object:
    """Anonymous website intake: always NEW, contact resolved, staff notified.

    Emits ``lead.created``. When ``settings`` is provided (public endpoint),
    the growth engine ENQUEUES automation (fast: no provider/AI work inline —
    the worker executes). Website submission stays fast.
    """
    from app.services import lead_routing as routing_service

    fields = _lead_fields_from_input(data)
    if not fields["display_name"]:
        raise ValueError("Name is required.")
    if not fields["phone"] and not fields["email"]:
        raise ValueError("Phone or email is required.")
    first, last = norm.split_name(fields["display_name"])
    contact = resolve_contact_for_intake(
        db,
        business_id=business_id,
        first_name=first,
        last_name=last,
        phone=fields["phone"],
        email=fields["email"],
        source=fields["source"],
    )
    fields["contact_id"] = contact.id
    fields["status"] = "new"
    if routing is not None:
        fields["routed_by"] = routing_service.validate_routed_by(
            routing.get("routed_by", "slug")
        )
        fields["routing_reason"] = str(routing.get("reason", ""))[:500]
        fields["routed_at"] = routing.get("routed_at") or routing_service._utcnow()
    else:
        fields["routed_by"] = "slug"
        fields["routing_reason"] = "Public website intake via verified business slug."
        fields["routed_at"] = routing_service._utcnow()
    lead = leads_repo.create(db, business_id=business_id, fields=fields)
    leads_repo.add_activity(
        db,
        business_id=business_id,
        lead_id=lead.id,
        activity_type="note",
        note=f"Website enquiry received (source: {fields['source']}).",
    )
    notify_new_lead(
        db, business_id=business_id, lead_id=lead.id, lead_name=lead.display_name
    )
    db.flush()
    _emit_lead_created(db, business_id=business_id, lead=lead, actor_user_id=None)
    if settings is not None and bool(getattr(settings, "automation_enabled", False)):
        try:
            from app.services import growth_engine as _growth

            _growth.on_lead_created(
                db,
                settings,
                business_id=business_id,
                lead=lead,
                actor_user_id=None,
                fast=True,
            )
        except Exception:  # noqa: BLE001 - automation never breaks intake
            pass
    return lead


def _emit_lead_created(
    db: Session, *, business_id: uuid.UUID, lead, actor_user_id
) -> None:
    """Fast domain-event row for a new lead (caller's transaction, never raises)."""
    try:
        from app.services import domain_events as _events

        _events.emit(
            db,
            business_id=business_id,
            event_type="lead.created",
            entity_type="lead",
            entity_id=getattr(lead, "id", None),
            actor_user_id=actor_user_id,
            payload={
                "lead_id": str(getattr(lead, "id", "")),
                "source": str(getattr(lead, "source", "") or ""),
                "display_name": str(getattr(lead, "display_name", "") or ""),
                "phone": str(
                    getattr(lead, "phone", "")
                    or getattr(lead, "normalized_phone", "")
                    or ""
                ),
            },
        )
        db.flush()
    except Exception:  # noqa: BLE001 - event log never breaks lead capture
        pass


def get_lead(db: Session, *, business_id: uuid.UUID, lead_id: object):
    lead = leads_repo.get_scoped(
        db, lead_id=lead_id, business_id=business_id, with_relations=True
    )
    if lead is None:
        raise NotFoundError("Lead not found.")
    return lead


def list_leads(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    source: str | None = None,
    assigned_user_id: object = None,
    created_from=None,
    created_to=None,
    follow_up_from=None,
    follow_up_to=None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    from app.repositories.pagination import parse_uuid

    status_clean = (
        _validate_enum(status, allowed=LEAD_STATUSES, field="status", default="new")
        if status
        else None
    )
    source_clean = (
        _validate_enum(source, allowed=LEAD_SOURCES, field="source", default="website")
        if source
        else None
    )
    assignee = parse_uuid(assigned_user_id) if assigned_user_id else None
    if assigned_user_id and assignee is None:
        raise ValueError("assigned_user_id must be a valid UUID.")
    return leads_repo.list_scoped(
        db,
        business_id=business_id,
        status=status_clean,
        source=source_clean,
        assigned_user_id=assignee,
        created_from=created_from,
        created_to=created_to,
        follow_up_from=follow_up_from,
        follow_up_to=follow_up_to,
        search=validate_search(search),
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def update_lead(db: Session, *, business_id: uuid.UUID, lead_id: object, fields: dict):
    lead = get_lead(db, business_id=business_id, lead_id=lead_id)
    allowed = {
        "display_name",
        "phone",
        "email",
        "source",
        "source_detail",
        "service_interest",
        "message",
        "follow_up_at",
        "consent_marketing",
        "landing_page",
        "referrer",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown lead field(s): {sorted(unknown)}.")
    updates: dict = {}
    for key in (
        "display_name",
        "source_detail",
        "service_interest",
        "message",
        "landing_page",
        "referrer",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
    ):
        if key in fields:
            max_chars = (
                2000
                if key == "message"
                else 500
                if key in ("landing_page", "referrer")
                else 200
            )
            updates[key] = _clean_text(fields[key], max_chars=max_chars)
    if "phone" in fields:
        phone = _clean_text(fields["phone"], max_chars=32) or None
        updates["phone"] = phone
        updates["normalized_phone"] = norm.normalize_phone(phone)
    if "email" in fields:
        email = _clean_text(fields["email"], max_chars=320) or None
        if email:
            _require_valid_email(email)
        updates["email"] = email
        updates["normalized_email"] = norm.normalize_email(email)
    if "source" in fields:
        updates["source"] = _validate_enum(
            fields["source"], allowed=LEAD_SOURCES, field="source", default="website"
        )
    if "follow_up_at" in fields:
        updates["follow_up_at"] = fields["follow_up_at"]
    if "consent_marketing" in fields:
        updates["consent_marketing"] = bool(fields["consent_marketing"])
    leads_repo.set_fields(lead, updates)
    lead.updated_at = _utcnow()
    db.flush()
    return lead


def assign_lead(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: object,
    assignee_user_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
):
    lead = get_lead(db, business_id=business_id, lead_id=lead_id)
    require_active_member(db, business_id=business_id, user_id=assignee_user_id)
    lead.assigned_user_id = assignee_user_id
    lead.updated_at = _utcnow()
    leads_repo.add_activity(
        db,
        business_id=business_id,
        lead_id=lead.id,
        activity_type="assigned",
        note="Lead assigned.",
        actor_user_id=actor_user_id,
    )
    notify_assignment(
        db,
        business_id=business_id,
        assignee_user_id=assignee_user_id,
        kind="lead",
        record_id=lead.id,
        title=f"Lead assigned: {lead.display_name or 'new lead'}",
    )
    db.flush()
    return lead


def set_status(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: object,
    to_status: str,
    actor_user_id: uuid.UUID | None = None,
    lost_reason: str = "",
    note: str = "",
) -> object:
    lead = get_lead(db, business_id=business_id, lead_id=lead_id)
    target = _validate_enum(
        to_status, allowed=LEAD_STATUSES, field="status", default="new"
    )
    current = str(lead.status or "new").lower()
    if target == current:
        return lead
    if target not in LEAD_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move lead from {current.upper()} to {target.upper()}."
        )
    if target == "lost" and not _clean_text(lost_reason, max_chars=500):
        raise ValueError("A lost reason is required to mark a lead LOST.")
    previous = current
    lead.status = target
    lead.updated_at = _utcnow()
    if target == "lost":
        lead.lost_reason = _clean_text(lost_reason, max_chars=500)
    if target == "contacted":
        lead.last_contacted_at = _utcnow()
    activity_type = "lost" if target == "lost" else "status_changed"
    leads_repo.add_activity(
        db,
        business_id=business_id,
        lead_id=lead.id,
        activity_type=activity_type,
        note=note[:2000] or f"Status changed from {previous} to {target}.",
        actor_user_id=actor_user_id,
    )
    db.flush()
    if target == "contacted":
        try:
            from app.services import domain_events as _events

            _events.emit(
                db,
                business_id=business_id,
                event_type="lead.contacted",
                entity_type="lead",
                entity_id=lead.id,
                actor_user_id=actor_user_id,
                payload={"from": previous, "to": target},
            )
            db.flush()
        except Exception:  # noqa: BLE001 - event log never breaks transitions
            pass
    return lead


def add_note(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: object,
    note: str,
    actor_user_id: uuid.UUID | None = None,
    activity_type: str = "note",
):
    lead = get_lead(db, business_id=business_id, lead_id=lead_id)
    clean = _clean_text(note, max_chars=2000)
    if not clean:
        raise ValueError("Note must not be empty.")
    atype = _validate_enum(
        activity_type,
        allowed=LEAD_ACTIVITY_TYPES,
        field="activity type",
        default="note",
    )
    activity = leads_repo.add_activity(
        db,
        business_id=business_id,
        lead_id=lead.id,
        activity_type=atype,
        note=clean,
        actor_user_id=actor_user_id,
    )
    if atype == "contacted":
        lead.last_contacted_at = _utcnow()
    if atype == "follow_up_scheduled":
        pass  # follow-up timestamp itself is set via PATCH / follow_up_at
    db.flush()
    return activity


def list_activities(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: object,
    limit: int | None = None,
    offset: int | None = None,
):
    lead = get_lead(db, business_id=business_id, lead_id=lead_id)
    return leads_repo.list_activities(
        db, business_id=business_id, lead_id=lead.id, limit=limit, offset=offset
    )


def convert_lead(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: object,
    actor_user_id: uuid.UUID | None = None,
    customer_notes: str = "",
) -> object:
    """Convert a lead into a customer, atomically (all-or-nothing).

    Optimistic + single retry: the whole attempt runs in the caller's
    transaction (flush only, no savepoints — portable across PostgreSQL
    and SQLite). If a concurrent conversion wins the unique customer
    constraint, the attempt is rolled back and retried once; the retry
    observes the committed winner and reuses it instead of duplicating.
    Business errors (404/409/422) never trigger a retry.
    """
    try:
        return _convert_once(
            db,
            business_id=business_id,
            lead_id=lead_id,
            actor_user_id=actor_user_id,
            customer_notes=customer_notes,
        )
    except IntegrityError:
        db.rollback()  # first attempt fully undone on any backend
        return _convert_once(
            db,
            business_id=business_id,
            lead_id=lead_id,
            actor_user_id=actor_user_id,
            customer_notes=customer_notes,
        )


def _convert_once(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: object,
    actor_user_id: uuid.UUID | None = None,
    customer_notes: str = "",
) -> object:
    lead = get_lead(db, business_id=business_id, lead_id=lead_id)
    if str(lead.status).lower() == "converted":
        raise ConflictError("Lead is already converted.")
    if str(lead.status).lower() in LEAD_TERMINAL_STATUSES - {"converted", "lost"}:
        raise ConflictError(
            f"Lead in status {str(lead.status).upper()} cannot be converted."
        )
    # 1. Resolve contact (existing link, normalized match, or fresh create).
    contact = None
    if lead.contact_id is not None:
        from app.repositories import contacts as contacts_repo

        contact = contacts_repo.get_scoped(
            db, contact_id=lead.contact_id, business_id=business_id
        )
    if contact is None and (lead.normalized_phone or lead.normalized_email):
        from app.repositories import contacts as contacts_repo

        contact = contacts_repo.find_by_normalized(
            db,
            business_id=business_id,
            normalized_phone=lead.normalized_phone,
            normalized_email=lead.normalized_email,
        )
    if contact is None:
        from app.services.crm import create_contact

        first, last = norm.split_name(lead.display_name or "")
        contact = create_contact(
            db,
            business_id=business_id,
            first_name=first,
            last_name=last,
            phone=lead.phone,
            email=lead.email,
            source=lead.source or "other",
        )
        db.flush()
    # 2. Get-or-create customer (unique constraint wins concurrent races).
    customer = customers_repo.get_by_contact(
        db, business_id=business_id, contact_id=contact.id
    )
    if customer is None:
        from app.services.crm import create_customer

        customer = create_customer(
            db,
            business_id=business_id,
            contact_id=contact.id,
            customer_since=_utcnow(),
            notes=_clean_text(customer_notes, max_chars=2000),
        )
    # 3. Flip the lead (history preserved — never deleted).
    lead.customer_id = customer.id
    lead.contact_id = contact.id
    lead.status = "converted"
    lead.converted_at = _utcnow()
    lead.updated_at = _utcnow()
    leads_repo.add_activity(
        db,
        business_id=business_id,
        lead_id=lead.id,
        activity_type="converted",
        note="Lead converted to customer.",
        actor_user_id=actor_user_id,
    )
    db.flush()
    return customer
