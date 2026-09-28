"""Booking service: requests, staff lifecycle, public intake.

Public intake always creates REQUESTED. Confirmation is an explicit staff
action — the API never implies availability.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.crm_vocab import BOOKING_STATUSES, BOOKING_TRANSITIONS, BOOKING_TYPES
from app.models.crm_vocab import LEAD_SOURCES
from app.repositories import bookings as bookings_repo
from app.services.crm import (
    _clean_text,
    _require_valid_email,
    _validate_enum,
    require_active_member,
    resolve_contact_for_intake,
)
from app.services import normalize as norm
from app.services.errors import ConflictError, NotFoundError
from app.services.notifications import notify_assignment, notify_new_booking

# Sane absolute bounds for requested timestamps (UTC).
_MIN_DATE = datetime(2000, 1, 1, tzinfo=timezone.utc)
_MAX_DATE = datetime(2100, 1, 1, tzinfo=timezone.utc)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime | None, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _validate_window(
    start: datetime | None, end: datetime | None
) -> tuple[datetime | None, datetime | None]:
    start = _ensure_aware(start, field="requested_start_at")
    end = _ensure_aware(end, field="requested_end_at")
    for value, field in ((start, "requested_start_at"), (end, "requested_end_at")):
        if value is not None and not (_MIN_DATE <= value <= _MAX_DATE):
            raise ValueError(f"{field} is outside the sane range 2000..2100.")
    if start is not None and end is not None and not (start < end):
        raise ValueError("requested_start_at must be before requested_end_at.")
    return start, end


def _booking_fields(data: dict) -> dict:
    email = _clean_text(data.get("email"), max_chars=320) or None
    if email:
        _require_valid_email(email)
    phone = _clean_text(data.get("phone"), max_chars=32) or None
    start, end = _validate_window(
        data.get("requested_start_at"), data.get("requested_end_at")
    )
    return {
        "booking_type": _validate_enum(
            data.get("booking_type", "enquiry"),
            allowed=BOOKING_TYPES,
            field="booking type",
            default="enquiry",
        ),
        "title": _clean_text(data.get("title") or data.get("service"), max_chars=200),
        "requested_start_at": start,
        "requested_end_at": end,
        "notes": _clean_text(data.get("notes") or data.get("message"), max_chars=2000),
        "source": _validate_enum(
            data.get("source", "website"),
            allowed=LEAD_SOURCES,
            field="source",
            default="website",
        ),
        "phone": phone,
        "email": email,
    }


def create_booking(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
    assigned_user_id: uuid.UUID | None = None,
    status: str = "requested",
    settings=None,
) -> object:
    """Staff booking creation.

    Emits ``booking.created`` (+ ``trial.booked``/``visit.booked`` for
    trial/visit types). With ``settings``, the growth engine routes the
    event through automation synchronously (staff path).
    """
    fields = _booking_fields(data)
    status_clean = _validate_enum(
        status, allowed=BOOKING_STATUSES, field="status", default="requested"
    )
    resolved_contact_id = contact_id
    if resolved_contact_id is None and (
        fields["phone"]
        or fields["email"]
        or data.get("display_name")
        or data.get("name")
    ):
        first, last = norm.split_name(
            str(data.get("display_name") or data.get("name") or "")
        )
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

        if (
            contacts_repo.get_scoped(
                db, contact_id=resolved_contact_id, business_id=business_id
            )
            is None
        ):
            raise NotFoundError("Contact not found.")
    resolved_lead_id = None
    if lead_id is not None:
        from app.repositories import leads as leads_repo

        lead = leads_repo.get_scoped(db, lead_id=lead_id, business_id=business_id)
        if lead is None:
            raise NotFoundError("Lead not found.")
        resolved_lead_id = lead.id
        if resolved_contact_id is None and lead.contact_id is not None:
            resolved_contact_id = lead.contact_id
    if assigned_user_id is not None:
        require_active_member(db, business_id=business_id, user_id=assigned_user_id)
    fields.pop("phone")
    fields.pop("email")
    fields["status"] = status_clean
    fields["contact_id"] = resolved_contact_id
    fields["lead_id"] = resolved_lead_id
    fields["assigned_user_id"] = assigned_user_id
    booking = bookings_repo.create(db, business_id=business_id, fields=fields)
    if assigned_user_id is not None:
        notify_assignment(
            db,
            business_id=business_id,
            assignee_user_id=assigned_user_id,
            kind="booking",
            record_id=booking.id,
            title=f"Booking assigned: {booking.title or 'new request'}",
        )
    else:
        notify_new_booking(
            db,
            business_id=business_id,
            booking_id=booking.id,
            title=booking.title or "new request",
        )
    db.flush()
    _emit_booking_events(
        db, business_id=business_id, booking=booking, actor_user_id=actor_user_id
    )
    if settings is not None and bool(getattr(settings, "automation_enabled", False)):
        try:
            from app.services import growth_engine as _growth

            _growth.on_booking_intake(
                db,
                settings,
                business_id=business_id,
                booking=booking,
                actor_user_id=actor_user_id,
                fast=False,
            )
        except Exception:  # noqa: BLE001 - automation never breaks booking
            pass
    return booking


def _emit_booking_events(
    db: Session, *, business_id: uuid.UUID, booking, actor_user_id
) -> None:
    """Fast domain-event rows for a booking intake (never raises)."""
    try:
        from app.services import domain_events as _events

        booking_type = str(getattr(booking, "booking_type", "") or "").lower()
        _events.emit(
            db,
            business_id=business_id,
            event_type="booking.created",
            entity_type="booking",
            entity_id=getattr(booking, "id", None),
            actor_user_id=actor_user_id,
            payload={
                "booking_id": str(getattr(booking, "id", "")),
                "booking_type": booking_type,
                "status": str(getattr(booking, "status", "") or ""),
            },
        )
        if booking_type == "trial":
            _events.emit(
                db,
                business_id=business_id,
                event_type="trial.booked",
                entity_type="booking",
                entity_id=getattr(booking, "id", None),
                actor_user_id=actor_user_id,
                payload={"booking_id": str(getattr(booking, "id", ""))},
            )
        elif booking_type in ("visit", "tour", "demo"):
            _events.emit(
                db,
                business_id=business_id,
                event_type="visit.booked",
                entity_type="booking",
                entity_id=getattr(booking, "id", None),
                actor_user_id=actor_user_id,
                payload={"booking_id": str(getattr(booking, "id", ""))},
            )
        db.flush()
    except Exception:  # noqa: BLE001 - event log never breaks booking
        pass


def intake_booking(
    db: Session, *, business_id: uuid.UUID, data: dict, settings=None
) -> object:
    """Anonymous booking request: contact resolved, status forced REQUESTED.

    Emits intake events; with ``settings`` the growth engine ENQUEUES
    automation (fast website path — worker executes Gemini/provider work).
    """
    name = _clean_text(data.get("display_name") or data.get("name"), max_chars=200)
    if not name:
        raise ValueError("Name is required.")
    phone = _clean_text(data.get("phone"), max_chars=32) or None
    email = _clean_text(data.get("email"), max_chars=320) or None
    if not phone and not email:
        raise ValueError("Phone or email is required.")
    first, last = norm.split_name(name)
    contact = resolve_contact_for_intake(
        db,
        business_id=business_id,
        first_name=first,
        last_name=last,
        phone=phone,
        email=email,
        source=_validate_enum(
            data.get("source", "website"),
            allowed=LEAD_SOURCES,
            field="source",
            default="website",
        ),
    )
    # Optionally link a recent matching lead (same normalized contact ref).
    lead_id = None
    from app.repositories import leads as leads_repo

    if contact.normalized_phone or contact.normalized_email:
        items, _ = leads_repo.list_scoped(
            db,
            business_id=business_id,
            search=(contact.normalized_phone or contact.normalized_email or "")[:64],
            limit=1,
            offset=0,
        )
        if items:
            lead_id = items[0].id
    booking = create_booking(
        db,
        business_id=business_id,
        data=data,
        contact_id=contact.id,
        lead_id=lead_id,
        status="requested",
    )
    if settings is not None and bool(getattr(settings, "automation_enabled", False)):
        try:
            from app.services import growth_engine as _growth

            _growth.on_booking_intake(
                db,
                settings,
                business_id=business_id,
                booking=booking,
                actor_user_id=None,
                fast=True,
            )
        except Exception:  # noqa: BLE001 - automation never breaks intake
            pass
    return booking


def get_booking(db: Session, *, business_id: uuid.UUID, booking_id: object):
    booking = bookings_repo.get_scoped(
        db, booking_id=booking_id, business_id=business_id
    )
    if booking is None:
        raise NotFoundError("Booking not found.")
    return booking


def list_bookings(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    booking_type: str | None = None,
    assigned_user_id: object = None,
    start_from=None,
    start_to=None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    from app.repositories.pagination import parse_uuid

    status_clean = (
        _validate_enum(
            status, allowed=BOOKING_STATUSES, field="status", default="requested"
        )
        if status
        else None
    )
    type_clean = (
        _validate_enum(
            booking_type,
            allowed=BOOKING_TYPES,
            field="booking type",
            default="enquiry",
        )
        if booking_type
        else None
    )
    assignee = parse_uuid(assigned_user_id) if assigned_user_id else None
    if assigned_user_id and assignee is None:
        raise ValueError("assigned_user_id must be a valid UUID.")
    return bookings_repo.list_scoped(
        db,
        business_id=business_id,
        status=status_clean,
        booking_type=type_clean,
        assigned_user_id=assignee,
        start_from=start_from,
        start_to=start_to,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def update_booking(
    db: Session, *, business_id: uuid.UUID, booking_id: object, fields: dict
):
    booking = get_booking(db, business_id=business_id, booking_id=booking_id)
    allowed = {
        "title",
        "booking_type",
        "requested_start_at",
        "requested_end_at",
        "notes",
        "assigned_user_id",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown booking field(s): {sorted(unknown)}.")
    updates: dict = {}
    if "title" in fields:
        updates["title"] = _clean_text(fields["title"], max_chars=200)
    if "booking_type" in fields:
        updates["booking_type"] = _validate_enum(
            fields["booking_type"],
            allowed=BOOKING_TYPES,
            field="booking type",
            default="enquiry",
        )
    if "notes" in fields:
        updates["notes"] = _clean_text(fields["notes"], max_chars=2000)
    if "requested_start_at" in fields or "requested_end_at" in fields:
        start, end = _validate_window(
            fields.get("requested_start_at", booking.requested_start_at),
            fields.get("requested_end_at", booking.requested_end_at),
        )
        updates["requested_start_at"] = start
        updates["requested_end_at"] = end
    if "assigned_user_id" in fields:
        from app.repositories.pagination import parse_uuid

        assignee = parse_uuid(fields["assigned_user_id"])
        if fields["assigned_user_id"] and assignee is None:
            raise ValueError("assigned_user_id must be a valid UUID or null.")
        if assignee is not None:
            require_active_member(db, business_id=business_id, user_id=assignee)
        updates["assigned_user_id"] = assignee
    bookings_repo.set_fields(booking, updates)
    booking.updated_at = _utcnow()
    db.flush()
    return booking


def transition(
    db: Session,
    *,
    business_id: uuid.UUID,
    booking_id: object,
    to_status: str,
    actor_user_id: uuid.UUID | None = None,
    cancellation_reason: str = "",
    settings=None,
) -> object:
    """Staff booking transition + lifecycle events (confirmation/outcome).

    Emits ``booking.confirmed`` / ``booking.completed`` /
    ``booking.cancelled``. With ``settings``, routes synchronously through
    automation (staff path: confirmation message sent immediately).
    """
    booking = get_booking(db, business_id=business_id, booking_id=booking_id)
    target = _validate_enum(
        to_status, allowed=BOOKING_STATUSES, field="status", default="requested"
    )
    current = str(booking.status or "requested").lower()
    if target == current:
        return booking
    if target not in BOOKING_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move booking from {current.upper()} to {target.upper()}."
        )
    if target == "cancelled" and not _clean_text(cancellation_reason, max_chars=500):
        raise ValueError("A cancellation reason is required to cancel a booking.")
    booking.status = target
    booking.updated_at = _utcnow()
    if target == "cancelled":
        booking.cancellation_reason = _clean_text(cancellation_reason, max_chars=500)
    db.flush()
    _emit_transition_event(
        db,
        business_id=business_id,
        booking=booking,
        from_status=current,
        to_status=target,
        actor_user_id=actor_user_id,
    )
    if settings is not None and bool(getattr(settings, "automation_enabled", False)):
        try:
            from app.services import automation as _auto
            from app.services import growth_engine as _growth

            payload = _growth._booking_payload(
                db, business_id=business_id, booking=booking
            )
            event_map = {
                "confirmed": "booking.confirmed",
                "completed": "booking.completed",
                "cancelled": "booking.cancelled",
                "no_show": "booking.no_show",
            }
            if target in event_map:
                _auto.dispatch_event(
                    db,
                    settings,
                    business_id=business_id,
                    event_type=event_map[target],
                    entity_type="booking",
                    entity_id=booking.id,
                    actor_user_id=actor_user_id,
                    payload=payload,
                )
            # Trial/visit outcome automation for trial-type bookings
            # (reschedule follow-up on no-show; observable attended event).
            booking_type = str(getattr(booking, "booking_type", "") or "").lower()
            if booking_type in ("trial", "visit", "tour", "demo") and target in (
                "completed",
                "no_show",
            ):
                outcome_event = (
                    "trial.attended"
                    if (booking_type == "trial" and target == "completed")
                    else "trial.no_show"
                    if (booking_type == "trial")
                    else "visit.attended"
                    if target == "completed"
                    else "visit.no_show"
                )
                _growth._dispatch(
                    db,
                    settings,
                    business_id=business_id,
                    event_type=outcome_event,
                    entity_type="booking",
                    entity_id=booking.id,
                    payload=payload,
                    actor_user_id=actor_user_id,
                    fast=False,
                )
        except Exception:  # noqa: BLE001 - automation never breaks transition
            pass
    return booking


def _emit_transition_event(
    db: Session,
    *,
    business_id: uuid.UUID,
    booking,
    from_status: str,
    to_status: str,
    actor_user_id,
) -> None:
    try:
        from app.services import domain_events as _events

        event_map = {
            "confirmed": "booking.confirmed",
            "completed": "booking.completed",
            "cancelled": "booking.cancelled",
            "no_show": "booking.no_show",
        }
        if to_status in event_map:
            _events.emit(
                db,
                business_id=business_id,
                event_type=event_map[to_status],
                entity_type="booking",
                entity_id=getattr(booking, "id", None),
                actor_user_id=actor_user_id,
                payload={
                    "from": from_status,
                    "to": to_status,
                    "booking_type": str(getattr(booking, "booking_type", "") or ""),
                },
            )
            db.flush()
    except Exception:  # noqa: BLE001 - event log never breaks transition
        pass
