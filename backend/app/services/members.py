"""Member service: operational member profiles over the CRM identity.

A member profile extends (never duplicates) the CRM: when a ``customer_id``
is supplied it must belong to the same business, and at most one member
profile exists per customer per business (unique constraint + pre-check).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crm_vocab import LEAD_SOURCES
from app.models.ops_vocab import MEMBER_STATUSES
from app.repositories import members as members_repo
from app.services import normalize as norm
from app.services.crm import _clean_text, _require_valid_email, _validate_enum
from app.services.errors import ConflictError, NotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_member(db: Session, *, business_id: uuid.UUID, member_id: object):
    member = members_repo.get(db, member_id=member_id, business_id=business_id)
    if member is None:
        raise NotFoundError("Member not found.")
    return member


def list_members(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    source: str | None = None,
    search: str | None = None,
    created_from=None,
    created_to=None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    from app.services.crm import validate_search

    status_clean = (
        _validate_enum(
            status, allowed=MEMBER_STATUSES, field="status", default="active"
        )
        if status
        else None
    )
    source_clean = (
        _validate_enum(source, allowed=LEAD_SOURCES, field="source", default="other")
        if source
        else None
    )
    return members_repo.list_scoped(
        db,
        business_id=business_id,
        status=status_clean,
        source=source_clean,
        search=validate_search(search),
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def create_member(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    """Create a member profile, optionally linked to CRM rows."""
    from app.repositories import contacts as contacts_repo
    from app.repositories import customers as customers_repo
    from app.repositories import leads as leads_repo

    display_name = _clean_text(
        data.get("display_name") or data.get("name"), max_chars=200
    )
    phone = _clean_text(data.get("phone"), max_chars=32) or None
    email = _clean_text(data.get("email"), max_chars=320) or None
    if email:
        _require_valid_email(email)
    if not display_name and not phone and not email:
        raise ValueError("Member needs at least a name, phone, or email.")

    customer_id = (
        _coerce_uuid(data.get("customer_id")) if data.get("customer_id") else None
    )
    contact_id = (
        _coerce_uuid(data.get("contact_id")) if data.get("contact_id") else None
    )
    lead_id = _coerce_uuid(data.get("lead_id")) if data.get("lead_id") else None

    contact = None
    if customer_id is not None:
        customer = customers_repo.get_scoped(
            db, customer_id=customer_id, business_id=business_id
        )
        if customer is None:
            raise NotFoundError("Customer not found.")
        existing = members_repo.get_by_customer(
            db, business_id=business_id, customer_id=customer.id
        )
        if existing is not None:
            raise ConflictError("A member profile already exists for this customer.")
        contact_id = contact_id or customer.contact_id
    if contact_id is not None:
        contact = contacts_repo.get_scoped(
            db, contact_id=contact_id, business_id=business_id
        )
        if contact is None:
            raise NotFoundError("Contact not found.")
    if lead_id is not None:
        lead = leads_repo.get_scoped(db, lead_id=lead_id, business_id=business_id)
        if lead is None:
            raise NotFoundError("Lead not found.")

    emergency_phone = (
        _clean_text(data.get("emergency_contact_phone"), max_chars=32) or None
    )
    try:
        member = members_repo.create(
            db,
            business_id=business_id,
            fields={
                "customer_id": customer_id,
                "contact_id": contact_id if contact is not None else contact_id,
                "lead_id": lead_id,
                "display_name": display_name,
                "phone": phone,
                "normalized_phone": norm.normalize_phone(phone),
                "email": email,
                "normalized_email": norm.normalize_email(email),
                "status": _validate_enum(
                    data.get("status", "active"),
                    allowed=MEMBER_STATUSES,
                    field="status",
                    default="active",
                ),
                "source": _validate_enum(
                    data.get("source", "other"),
                    allowed=LEAD_SOURCES,
                    field="source",
                    default="other",
                ),
                "emergency_contact_name": _clean_text(
                    data.get("emergency_contact_name"), max_chars=200
                ),
                "emergency_contact_phone": emergency_phone,
                "seat_preference": _clean_text(
                    data.get("seat_preference"), max_chars=200
                ),
                "notes": _clean_text(data.get("notes"), max_chars=2000),
                "created_by_user_id": actor_user_id,
                "updated_by_user_id": actor_user_id,
            },
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "A member profile already exists for this customer."
        ) from exc
    from app.services import domain_events as events

    events.emit(
        db,
        business_id=business_id,
        event_type="member.created",
        entity_type="member",
        entity_id=member.id,
        actor_user_id=actor_user_id,
        payload={"member_id": str(member.id)},
    )
    return member


def update_member(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id: object,
    fields: dict,
    actor_user_id: uuid.UUID | None = None,
):
    member = get_member(db, business_id=business_id, member_id=member_id)
    allowed = {
        "display_name",
        "phone",
        "email",
        "status",
        "source",
        "emergency_contact_name",
        "emergency_contact_phone",
        "seat_preference",
        "notes",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown member field(s): {sorted(unknown)}.")
    updates: dict = {}
    if "display_name" in fields:
        updates["display_name"] = _clean_text(fields["display_name"], max_chars=200)
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
    if "status" in fields:
        updates["status"] = _validate_enum(
            fields["status"],
            allowed=MEMBER_STATUSES,
            field="status",
            default="active",
        )
    if "source" in fields:
        updates["source"] = _validate_enum(
            fields["source"],
            allowed=LEAD_SOURCES,
            field="source",
            default="other",
        )
    for key in (
        "emergency_contact_name",
        "emergency_contact_phone",
        "seat_preference",
        "notes",
    ):
        if key in fields:
            max_chars = 2000 if key == "notes" else 200
            updates[key] = _clean_text(fields[key], max_chars=max_chars) or (
                None
                if key == "emergency_contact_phone"
                else _clean_text(fields[key], max_chars=max_chars)
            )
    for key, value in updates.items():
        setattr(member, key, value)
    member.updated_by_user_id = actor_user_id
    member.updated_at = _utcnow()
    db.flush()
    return member


def member_profile(db: Session, *, business_id: uuid.UUID, member_id: object) -> dict:
    """Full operational profile: member + current/history + money + visits."""
    from app.repositories import attendance as attendance_repo
    from app.repositories import op_memberships as op_membership_repo
    from app.repositories import payments as payments_repo
    from app.repositories import seats as seats_repo

    member = get_member(db, business_id=business_id, member_id=member_id)
    memberships, _ = op_membership_repo.list_memberships(
        db,
        business_id=business_id,
        member_id=member.id,
        limit=100,
        offset=0,
        sort="start_date",
        direction="desc",
    )
    payments, _ = payments_repo.list_scoped(
        db, business_id=business_id, member_id=member.id, limit=100, offset=0
    )
    visits, _ = attendance_repo.list_scoped(
        db,
        business_id=business_id,
        member_id=member.id,
        limit=50,
        offset=0,
        sort="attendance_date",
        direction="desc",
    )
    renewals, _ = op_membership_repo.list_renewals(
        db, business_id=business_id, member_id=member.id, limit=50, offset=0
    )
    allocation = seats_repo.active_for_member(
        db, business_id=business_id, member_id=member.id
    )
    current = next((m for m in memberships if m.status == "active"), None)
    return {
        "member": member,
        "current_membership": current,
        "memberships": memberships,
        "payments": payments,
        "attendance": visits,
        "renewals": renewals,
        "active_seat_allocation": allocation,
    }


def _coerce_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"Invalid UUID: {value!r}.") from exc
