"""Contact + Customer services (Block 2 CRM foundation).

Business rules live here; SQL lives in repositories. Every lookup is scoped
to the authenticated business — cross-business rows behave as nonexistent
(uniform NotFoundError, no existence oracle).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.crm_vocab import (
    CONTACT_CHANNELS,
    CONTACT_STATUSES,
    CUSTOMER_STATUSES,
    LEAD_SOURCES,
)
from app.repositories import contacts as contacts_repo
from app.repositories import customers as customers_repo
from app.repositories import memberships as membership_repo
from app.services import normalize as norm
from app.services.errors import ConflictError, NotFoundError

SEARCH_MAX_CHARS = 64


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: object, *, max_chars: int) -> str:
    return str(value or "").strip()[:max_chars]


def validate_search(search: str | None) -> str | None:
    if search is None:
        return None
    text = str(search).strip()
    if not text:
        return None
    if len(text) > SEARCH_MAX_CHARS:
        raise ValueError(f"Search must be at most {SEARCH_MAX_CHARS} characters.")
    return text


def _validate_enum(
    value: object, *, allowed: frozenset[str], field: str, default: str
) -> str:
    text = str(value or default).strip().lower()
    if text not in allowed:
        raise ValueError(f"Unknown {field}: {value!r}. Allowed: {sorted(allowed)}.")
    return text


def create_contact(
    db: Session,
    *,
    business_id: uuid.UUID,
    first_name: str = "",
    last_name: str = "",
    phone: str | None = None,
    email: str | None = None,
    preferred_contact_channel: str = "other",
    source: str = "other",
    notes: str = "",
    status: str = "active",
):
    """Create a contact (at least a name, phone, or email is required)."""
    first = _clean_text(first_name, max_chars=100)
    last = _clean_text(last_name, max_chars=100)
    phone_clean = _clean_text(phone, max_chars=32) or None
    email_clean = _clean_text(email, max_chars=320) or None
    if not first and not last and not phone_clean and not email_clean:
        raise ValueError("Contact needs at least a name, phone, or email.")
    if email_clean:
        _require_valid_email(email_clean)
    contact = contacts_repo.create(
        db,
        business_id=business_id,
        first_name=first,
        last_name=last,
        phone=phone_clean,
        normalized_phone=norm.normalize_phone(phone_clean),
        email=email_clean,
        normalized_email=norm.normalize_email(email_clean),
        preferred_contact_channel=_validate_enum(
            preferred_contact_channel,
            allowed=CONTACT_CHANNELS,
            field="contact channel",
            default="other",
        ),
        source=_validate_enum(
            source, allowed=LEAD_SOURCES, field="source", default="other"
        ),
        notes=_clean_text(notes, max_chars=2000),
        status=_validate_enum(
            status, allowed=CONTACT_STATUSES, field="status", default="active"
        ),
    )
    db.flush()
    _link_identity(
        db,
        business_id=business_id,
        contact=contact,
        phone=phone_clean,
        email=email_clean,
    )
    return contact


def _link_identity(
    db: Session,
    *,
    business_id: uuid.UUID,
    contact: object,
    phone: str | None,
    email: str | None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Best-effort unified-identity link (Block 3).

    Runs in the caller's transaction: strict normalized matching only,
    ambiguous signals keep identities separate. A concurrent-creation
    race raises IntegrityError to the caller (safe 409; retry reuses
    the winner) — never silently merged, never hidden rollback.
    """
    from app.services import identity as identity_service

    contact_id = getattr(contact, "id", None)
    if contact_id is None:
        return
    identity_service.ensure_link_for_contact(
        db,
        business_id=business_id,
        contact_id=contact_id,
        phone=phone,
        email=email,
        actor_user_id=actor_user_id,
    )


def _require_valid_email(email: str) -> None:
    from email_validator import EmailNotValidError, validate_email

    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid email: {exc}") from exc


def get_contact(db: Session, *, business_id: uuid.UUID, contact_id: object):
    contact = contacts_repo.get_scoped(
        db, contact_id=contact_id, business_id=business_id
    )
    if contact is None:
        raise NotFoundError("Contact not found.")
    return contact


def update_contact(
    db: Session, *, business_id: uuid.UUID, contact_id: object, fields: dict
):
    contact = get_contact(db, business_id=business_id, contact_id=contact_id)
    allowed = {
        "first_name",
        "last_name",
        "phone",
        "email",
        "preferred_contact_channel",
        "source",
        "notes",
        "status",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown contact field(s): {sorted(unknown)}.")
    updates: dict = {}
    if "first_name" in fields:
        updates["first_name"] = _clean_text(fields["first_name"], max_chars=100)
    if "last_name" in fields:
        updates["last_name"] = _clean_text(fields["last_name"], max_chars=100)
    if "phone" in fields:
        phone_clean = _clean_text(fields["phone"], max_chars=32) or None
        updates["phone"] = phone_clean
        updates["normalized_phone"] = norm.normalize_phone(phone_clean)
    if "email" in fields:
        email_clean = _clean_text(fields["email"], max_chars=320) or None
        if email_clean:
            _require_valid_email(email_clean)
        updates["email"] = email_clean
        updates["normalized_email"] = norm.normalize_email(email_clean)
    if "preferred_contact_channel" in fields:
        updates["preferred_contact_channel"] = _validate_enum(
            fields["preferred_contact_channel"],
            allowed=CONTACT_CHANNELS,
            field="contact channel",
            default="other",
        )
    if "source" in fields:
        updates["source"] = _validate_enum(
            fields["source"], allowed=LEAD_SOURCES, field="source", default="other"
        )
    if "notes" in fields:
        updates["notes"] = _clean_text(fields["notes"], max_chars=2000)
    if "status" in fields:
        updates["status"] = _validate_enum(
            fields["status"], allowed=CONTACT_STATUSES, field="status", default="active"
        )
    contacts_repo.set_fields(contact, updates)
    contacts_repo.touch_updated(contact, now=_utcnow())
    db.flush()
    _link_identity(
        db,
        business_id=business_id,
        contact=contact,
        phone=contact.phone,
        email=contact.email,
    )
    return contact


def list_contacts(
    db: Session,
    *,
    business_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    status_clean = (
        _validate_enum(
            status, allowed=CONTACT_STATUSES, field="status", default="active"
        )
        if status
        else None
    )
    return contacts_repo.list_scoped(
        db,
        business_id=business_id,
        search=validate_search(search),
        status=status_clean,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def resolve_contact_for_intake(
    db: Session,
    *,
    business_id: uuid.UUID,
    first_name: str,
    last_name: str,
    phone: str | None,
    email: str | None,
    source: str,
) -> object:
    """Reuse an existing contact on normalized match, else create one."""
    phone_clean = _clean_text(phone, max_chars=32) or None
    email_clean = _clean_text(email, max_chars=320) or None
    existing = contacts_repo.find_by_normalized(
        db,
        business_id=business_id,
        normalized_phone=norm.normalize_phone(phone_clean),
        normalized_email=norm.normalize_email(email_clean),
    )
    if existing is not None:
        # Backfill the identity link for pre-identity rows (idempotent).
        _link_identity(
            db,
            business_id=business_id,
            contact=existing,
            phone=phone_clean,
            email=email_clean,
        )
        return existing
    return create_contact(
        db,
        business_id=business_id,
        first_name=first_name,
        last_name=last_name,
        phone=phone_clean,
        email=email_clean,
        source=source,
    )


def create_customer(
    db: Session,
    *,
    business_id: uuid.UUID,
    contact_id: uuid.UUID,
    status: str = "active",
    customer_since: datetime | None = None,
    notes: str = "",
):
    """Create a customer for a contact that belongs to this business."""
    contact = contacts_repo.get_scoped(
        db, contact_id=contact_id, business_id=business_id
    )
    if contact is None:
        raise NotFoundError("Contact not found.")
    existing = customers_repo.get_by_contact(
        db, business_id=business_id, contact_id=contact.id
    )
    if existing is not None:
        raise ConflictError("A customer already exists for this contact.")
    customer = customers_repo.create(
        db,
        business_id=business_id,
        contact_id=contact.id,
        status=_validate_enum(
            status, allowed=CUSTOMER_STATUSES, field="status", default="active"
        ),
        customer_since=customer_since,
        notes=_clean_text(notes, max_chars=2000),
    )
    # Flush only (the caller commits). A concurrent duplicate insert raises
    # IntegrityError on the unique constraint — routers map it to a safe
    # 409 so the loser retries and reuses the winner via get_by_contact.
    db.flush()
    return customer


def get_customer(db: Session, *, business_id: uuid.UUID, customer_id: object):
    customer = customers_repo.get_scoped(
        db, customer_id=customer_id, business_id=business_id, with_contact=True
    )
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


def update_customer(
    db: Session, *, business_id: uuid.UUID, customer_id: object, fields: dict
):
    customer = get_customer(db, business_id=business_id, customer_id=customer_id)
    allowed = {"status", "notes", "customer_since"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown customer field(s): {sorted(unknown)}.")
    if "status" in fields:
        customer.status = _validate_enum(
            fields["status"],
            allowed=CUSTOMER_STATUSES,
            field="status",
            default="active",
        )
    if "notes" in fields:
        customer.notes = _clean_text(fields["notes"], max_chars=2000)
    if "customer_since" in fields:
        customer.customer_since = fields["customer_since"]
    customer.updated_at = _utcnow()
    db.flush()
    return customer


def list_customers(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    status_clean = (
        _validate_enum(
            status, allowed=CUSTOMER_STATUSES, field="status", default="active"
        )
        if status
        else None
    )
    return customers_repo.list_scoped(
        db,
        business_id=business_id,
        status=status_clean,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def require_active_member(db: Session, *, business_id: uuid.UUID, user_id: uuid.UUID):
    """Validate an assignee belongs to this business (uniform NotFoundError)."""
    membership = membership_repo.get_membership(
        db, user_id=user_id, business_id=business_id
    )
    if membership is None or membership.status != "active":
        raise NotFoundError("Assignee is not an active member of this business.")
    return membership
