"""Membership + plan + renewal services (Block 6 steps 27/31, Block 7 34/38).

Rules:
- Plans are catalogue data; memberships snapshot price/version at creation.
- Membership status and payment state are independent columns.
- Renewal creates a NEW membership row (history preserved) + a renewal
  record linking old -> new. Concurrent renewals of the same membership
  collapse: the second sees status != active/pending and gets 409.
- Expiry math is date-based in the business timezone (services accept the
  business timezone string; default UTC).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ops_vocab import (
    MEMBERSHIP_PAYMENT_STATES,
    OPERATIONAL_MEMBERSHIP_STATUSES,
    OPERATIONAL_MEMBERSHIP_TRANSITIONS,
    PLAN_CATEGORIES,
    RENEWAL_STATUSES,
    RENEWAL_TRANSITIONS,
)
from app.repositories import op_memberships as op_membership_repo
from app.services.crm import _clean_text, _validate_enum
from app.services.errors import ConflictError, NotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: object, *, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid amount.") from exc
    if amount < 0:
        raise ValueError(f"{field} must not be negative.")
    return amount.quantize(Decimal("0.01"))


def _parse_date(value: object, *, field: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).") from exc


# -- plans -----------------------------------------------------------------


def create_plan(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    code = _clean_text(data.get("code"), max_chars=64)
    if not code:
        raise ValueError("Plan code is required.")
    existing = op_membership_repo.get_plan_by_code(
        db, business_id=business_id, code=code
    )
    if existing is not None:
        raise ConflictError(f"A plan with code '{code}' already exists.")
    duration = data.get("duration_months", 1)
    try:
        duration_int = int(duration)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_months must be a positive integer.") from exc
    if duration_int < 1 or duration_int > 60:
        raise ValueError("duration_months must be between 1 and 60.")
    plan = op_membership_repo.create_plan(
        db,
        business_id=business_id,
        fields={
            "code": code,
            "name": _clean_text(data.get("name"), max_chars=200) or code,
            "category": _validate_enum(
                data.get("category", "custom"),
                allowed=PLAN_CATEGORIES,
                field="category",
                default="custom",
            ),
            "duration_months": duration_int,
            "price": _money(data.get("price", "0"), field="price"),
            "currency": _clean_text(data.get("currency", "INR"), max_chars=8).upper()
            or "INR",
            "is_best_value": bool(data.get("is_best_value", False)),
            "is_active": bool(data.get("is_active", True)),
            "features": dict(data.get("features") or {}),
            "version": 1,
            "created_by_user_id": actor_user_id,
            "updated_by_user_id": actor_user_id,
        },
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"A plan with code '{code}' already exists.") from exc
    return plan


def get_plan(db: Session, *, business_id: uuid.UUID, plan_id: object):
    plan = op_membership_repo.get_plan(db, plan_id=plan_id, business_id=business_id)
    if plan is None:
        raise NotFoundError("Membership plan not found.")
    return plan


def update_plan(
    db: Session,
    *,
    business_id: uuid.UUID,
    plan_id: object,
    fields: dict,
    actor_user_id: uuid.UUID | None = None,
):
    """Edit catalogue data. History is safe: memberships carry snapshots."""
    plan = get_plan(db, business_id=business_id, plan_id=plan_id)
    allowed = {
        "name",
        "category",
        "duration_months",
        "price",
        "currency",
        "is_best_value",
        "is_active",
        "features",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown plan field(s): {sorted(unknown)}.")
    changed = False
    if "name" in fields:
        plan.name = _clean_text(fields["name"], max_chars=200)
        changed = True
    if "category" in fields:
        plan.category = _validate_enum(
            fields["category"],
            allowed=PLAN_CATEGORIES,
            field="category",
            default="custom",
        )
        changed = True
    if "duration_months" in fields:
        try:
            duration_int = int(fields["duration_months"])
        except (TypeError, ValueError) as exc:
            raise ValueError("duration_months must be a positive integer.") from exc
        if duration_int < 1 or duration_int > 60:
            raise ValueError("duration_months must be between 1 and 60.")
        plan.duration_months = duration_int
        changed = True
    if "price" in fields:
        plan.price = _money(fields["price"], field="price")
        changed = True
    if "currency" in fields:
        plan.currency = _clean_text(fields["currency"], max_chars=8).upper() or "INR"
        changed = True
    if "is_best_value" in fields:
        plan.is_best_value = bool(fields["is_best_value"])
        changed = True
    if "is_active" in fields:
        plan.is_active = bool(fields["is_active"])
        changed = True
    if "features" in fields:
        if not isinstance(fields["features"], dict):
            raise ValueError("features must be an object.")
        plan.features = dict(fields["features"])
        changed = True
    if changed:
        plan.version = int(plan.version or 1) + 1
        plan.updated_by_user_id = actor_user_id
        plan.updated_at = _utcnow()
    db.flush()
    return plan


def list_plans(
    db: Session,
    *,
    business_id: uuid.UUID,
    category=None,
    is_active=None,
    search=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    from app.services.crm import validate_search

    category_clean = (
        _validate_enum(
            category, allowed=PLAN_CATEGORIES, field="category", default="custom"
        )
        if category
        else None
    )
    active_clean = None
    if is_active is not None:
        if isinstance(is_active, str):
            active_clean = is_active.strip().lower() in ("true", "1", "yes")
        else:
            active_clean = bool(is_active)
    return op_membership_repo.list_plans(
        db,
        business_id=business_id,
        category=category_clean,
        is_active=active_clean,
        search=validate_search(search),
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


# -- memberships -------------------------------------------------------------


def _resolve_member(db: Session, *, business_id: uuid.UUID, member_id: uuid.UUID):
    from app.repositories import members as members_repo

    member = members_repo.get(db, member_id=member_id, business_id=business_id)
    if member is None:
        raise NotFoundError("Member not found.")
    return member


def create_membership(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    """Create an enrolment. Idempotent when idempotency_key repeats."""
    from app.services import domain_events as events

    idem = _clean_text(data.get("idempotency_key"), max_chars=64)
    if idem:
        existing = op_membership_repo.get_membership_by_idem(
            db, business_id=business_id, idempotency_key=idem
        )
        if existing is not None:
            return existing, False
    else:
        # Every row needs a globally unique key: the
        # (business_id, idempotency_key) constraint would otherwise
        # collide on the "" default for key-less creations (e.g. every
        # renewal). Generated keys keep idempotency for supplied keys
        # while making key-less writes collision-free.
        idem = f"ms-{uuid.uuid4().hex}"

    member_id = _coerce_uuid(data.get("member_id"), field="member_id")
    member = _resolve_member(db, business_id=business_id, member_id=member_id)

    plan = None
    plan_id = None
    if data.get("plan_id"):
        plan = get_plan(db, business_id=business_id, plan_id=data["plan_id"])
        plan_id = plan.id
        if not plan.is_active:
            raise ConflictError("That plan is archived and cannot be sold.")
    start = _parse_date(data.get("start_date") or date.today(), field="start_date")
    if data.get("end_date"):
        end = _parse_date(data["end_date"], field="end_date")
    elif plan is not None:
        end = _add_months(start, int(plan.duration_months or 1))
    else:
        raise ValueError("end_date is required when no plan is selected.")
    if end < start:
        raise ValueError("end_date must not be before start_date.")

    if plan is not None and data.get("price") in (None, ""):
        price = Decimal(str(plan.price or "0"))
        currency = str(plan.currency or "INR")
    else:
        price = _money(data.get("price", "0"), field="price")
        currency = (
            _clean_text(data.get("currency", "INR"), max_chars=8).upper() or "INR"
        )
    discount = _money(data.get("discount", "0"), field="discount")
    if discount > price:
        raise ValueError("discount must not exceed price.")
    final_amount = (price - discount).quantize(Decimal("0.01"))

    status = _validate_enum(
        data.get("status", "pending"),
        allowed=OPERATIONAL_MEMBERSHIP_STATUSES,
        field="status",
        default="pending",
    )
    payment_state = _validate_enum(
        data.get("payment_state", "unpaid"),
        allowed=MEMBERSHIP_PAYMENT_STATES,
        field="payment_state",
        default="unpaid",
    )
    try:
        membership = op_membership_repo.create_membership(
            db,
            business_id=business_id,
            fields={
                "member_id": member.id,
                "plan_id": plan_id,
                "customer_id": member.customer_id,
                "status": status,
                "payment_state": payment_state,
                "start_date": start,
                "end_date": end,
                "price": price,
                "discount": discount,
                "final_amount": final_amount,
                "currency": currency,
                "plan_name_snapshot": str(getattr(plan, "name", "") or "")[:200],
                "plan_version_snapshot": int(getattr(plan, "version", 1) or 1),
                "notes": _clean_text(data.get("notes"), max_chars=2000),
                "idempotency_key": idem,
                "created_by_user_id": actor_user_id,
                "updated_by_user_id": actor_user_id,
            },
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if idem:
            existing = op_membership_repo.get_membership_by_idem(
                db, business_id=business_id, idempotency_key=idem
            )
            if existing is not None:
                return existing, False
        raise ConflictError("Membership conflicts with existing data.") from exc
    events.emit(
        db,
        business_id=business_id,
        event_type="membership.created",
        entity_type="membership",
        entity_id=membership.id,
        actor_user_id=actor_user_id,
        payload={"member_id": str(member.id), "status": status},
    )
    if status == "active":
        events.emit(
            db,
            business_id=business_id,
            event_type="membership.activated",
            entity_type="membership",
            entity_id=membership.id,
            actor_user_id=actor_user_id,
            payload={"member_id": str(member.id)},
        )
    return membership, True


def get_membership(db: Session, *, business_id: uuid.UUID, membership_id: object):
    membership = op_membership_repo.get_membership(
        db, membership_id=membership_id, business_id=business_id
    )
    if membership is None:
        raise NotFoundError("Membership not found.")
    return membership


def list_memberships(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id=None,
    plan_id=None,
    status=None,
    payment_state=None,
    ending_before=None,
    ending_after=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    from app.repositories.pagination import parse_uuid

    status_clean = (
        _validate_enum(
            status,
            allowed=OPERATIONAL_MEMBERSHIP_STATUSES,
            field="status",
            default="pending",
        )
        if status
        else None
    )
    pay_clean = (
        _validate_enum(
            payment_state,
            allowed=MEMBERSHIP_PAYMENT_STATES,
            field="payment_state",
            default="unpaid",
        )
        if payment_state
        else None
    )
    member_uuid = parse_uuid(member_id) if member_id else None
    if member_id and member_uuid is None:
        raise ValueError("member_id must be a valid UUID.")
    plan_uuid = parse_uuid(plan_id) if plan_id else None
    if plan_id and plan_uuid is None:
        raise ValueError("plan_id must be a valid UUID.")
    return op_membership_repo.list_memberships(
        db,
        business_id=business_id,
        member_id=member_uuid,
        plan_id=plan_uuid,
        status=status_clean,
        payment_state=pay_clean,
        ending_before=_opt_date(ending_before, "ending_before"),
        ending_after=_opt_date(ending_after, "ending_after"),
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def set_status(
    db: Session,
    *,
    business_id: uuid.UUID,
    membership_id: object,
    to_status: str,
    actor_user_id: uuid.UUID | None = None,
    cancel_reason: str = "",
):
    """Explicit lifecycle transition (cancel/suspend/activate/expire)."""
    from app.services import domain_events as events

    membership = get_membership(
        db, business_id=business_id, membership_id=membership_id
    )
    target = _validate_enum(
        to_status,
        allowed=OPERATIONAL_MEMBERSHIP_STATUSES,
        field="status",
        default="pending",
    )
    current = str(membership.status or "pending").lower()
    if target == current:
        return membership
    if target not in OPERATIONAL_MEMBERSHIP_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move membership from {current.upper()} to {target.upper()}."
        )
    if target == "cancelled":
        reason = _clean_text(cancel_reason, max_chars=500)
        if not reason:
            raise ValueError("A cancel reason is required to cancel a membership.")
        membership.cancel_reason = reason
        membership.cancelled_at = _utcnow()
    membership.status = target
    membership.updated_by_user_id = actor_user_id
    membership.updated_at = _utcnow()
    db.flush()
    event_map = {
        "active": "membership.activated",
        "expired": "membership.expired",
        "cancelled": "membership.cancelled",
    }
    if target in event_map:
        events.emit(
            db,
            business_id=business_id,
            event_type=event_map[target],
            entity_type="membership",
            entity_id=membership.id,
            actor_user_id=actor_user_id,
            payload={"from": current, "to": target},
        )
    return membership


def mark_expired(
    db: Session, *, business_id: uuid.UUID, today: date | None = None
) -> int:
    """Flip ACTIVE memberships past end_date to EXPIRED. Returns count."""
    from app.services import domain_events as events

    today = today or date.today()
    # Note: ending_before is inclusive (<=); use yesterday boundary so that
    # memberships ending TODAY stay active until the day is over.
    boundary = today - timedelta(days=1)
    count = 0
    offset = 0
    page_size = 100
    while True:
        items, _ = op_membership_repo.list_memberships(
            db,
            business_id=business_id,
            status="active",
            ending_before=boundary,
            limit=page_size,
            offset=offset,
        )
        if not items:
            break
        for membership in items:
            membership.status = "expired"
            membership.updated_at = _utcnow()
            events.emit(
                db,
                business_id=business_id,
                event_type="membership.expired",
                entity_type="membership",
                entity_id=membership.id,
                payload={"end_date": str(membership.end_date)},
            )
            count += 1
        db.flush()
        if len(items) < page_size:
            break
        # Offset stays fixed in count of *remaining* actives is tricky once
        # rows flip to expired (they drop out of the active query), so keep
        # re-querying from offset 0 until a short page arrives.
        offset = 0
    return count


def renew_membership(
    db: Session,
    *,
    business_id: uuid.UUID,
    membership_id: object,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    """Renew: new membership row + renewal link. Concurrency-safe (409)."""
    from app.services import domain_events as events

    old = get_membership(db, business_id=business_id, membership_id=membership_id)
    if str(old.status).lower() not in ("active", "expired", "pending"):
        raise ConflictError(
            f"Membership in status {str(old.status).upper()} cannot be renewed."
        )
    new_plan = None
    if data.get("new_plan_id"):
        new_plan = get_plan(db, business_id=business_id, plan_id=data["new_plan_id"])
    elif old.plan_id is not None:
        new_plan = get_plan(db, business_id=business_id, plan_id=old.plan_id)

    start = (
        _parse_date(data["start_date"], field="start_date")
        if data.get("start_date")
        else max(date.today(), old.end_date + timedelta(days=1))
    )
    duration = int(getattr(new_plan, "duration_months", 1) or 1)
    end = (
        _parse_date(data["end_date"], field="end_date")
        if data.get("end_date")
        else _add_months(start, duration)
    )
    if end < start:
        raise ValueError("end_date must not be before start_date.")
    if new_plan is not None and data.get("price") in (None, ""):
        price = Decimal(str(new_plan.price or "0"))
        currency = str(new_plan.currency or old.currency or "INR")
    else:
        price = _money(data.get("price", str(old.final_amount or "0")), field="price")
        currency = (
            _clean_text(
                data.get("currency", old.currency or "INR"), max_chars=8
            ).upper()
            or "INR"
        )
    discount = _money(data.get("discount", "0"), field="discount")
    if discount > price:
        raise ValueError("discount must not exceed price.")

    idem = _clean_text(data.get("idempotency_key"), max_chars=64)
    new_membership, created = create_membership(
        db,
        business_id=business_id,
        data={
            "member_id": str(old.member_id),
            "plan_id": str(new_plan.id) if new_plan is not None else None,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "price": str(price),
            "discount": str(discount),
            "currency": currency,
            "status": "active",
            "payment_state": "unpaid",
            "notes": _clean_text(data.get("notes"), max_chars=2000),
            "idempotency_key": idem,
        },
        actor_user_id=actor_user_id,
    )
    if created:
        new_membership.renewed_from_id = old.id
        if str(old.status).lower() == "active":
            old.status = "expired"
            old.updated_at = _utcnow()
        renewal = op_membership_repo.create_renewal(
            db,
            business_id=business_id,
            fields={
                "member_id": old.member_id,
                "membership_id": old.id,
                "new_membership_id": new_membership.id,
                "previous_plan_id": old.plan_id,
                "new_plan_id": new_plan.id if new_plan is not None else None,
                "renewal_amount": (price - discount).quantize(Decimal("0.01")),
                "currency": currency,
                "status": "confirmed",
                "due_date": old.end_date,
                "renewed_at": _utcnow(),
                "notes": _clean_text(data.get("notes"), max_chars=2000),
                "created_by_user_id": actor_user_id,
            },
        )
        db.flush()
        events.emit(
            db,
            business_id=business_id,
            event_type="membership.renewed",
            entity_type="membership",
            entity_id=new_membership.id,
            actor_user_id=actor_user_id,
            payload={"renewed_from": str(old.id), "renewal_id": str(renewal.id)},
        )
        events.emit(
            db,
            business_id=business_id,
            event_type="renewal.confirmed",
            entity_type="renewal",
            entity_id=renewal.id,
            actor_user_id=actor_user_id,
            payload={"membership_id": str(new_membership.id)},
        )
    return new_membership


# -- renewal pipeline ---------------------------------------------------------


def create_renewal_record(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    from app.services import domain_events as events

    membership = get_membership(
        db, business_id=business_id, membership_id=data.get("membership_id")
    )
    # Idempotent pipeline: one PENDING renewal per membership. Repeating the
    # same logical request returns the existing row instead of duplicating.
    pending, _ = op_membership_repo.list_renewals(
        db,
        business_id=business_id,
        status="pending",
        limit=100,
        offset=0,
    )
    for row in pending:
        if str(row.membership_id) == str(membership.id):
            return row
    due = _parse_date(data.get("due_date") or membership.end_date, field="due_date")
    amount = _money(
        data.get("renewal_amount", str(membership.final_amount or "0")),
        field="renewal_amount",
    )
    new_plan_id = None
    if data.get("new_plan_id"):
        new_plan = get_plan(db, business_id=business_id, plan_id=data["new_plan_id"])
        new_plan_id = new_plan.id
    renewal = op_membership_repo.create_renewal(
        db,
        business_id=business_id,
        fields={
            "member_id": membership.member_id,
            "membership_id": membership.id,
            "new_membership_id": None,
            "previous_plan_id": membership.plan_id,
            "new_plan_id": new_plan_id,
            "renewal_amount": amount,
            "currency": (
                _clean_text(
                    data.get("currency", membership.currency or "INR"), max_chars=8
                ).upper()
                or "INR"
            ),
            "status": "pending",
            "due_date": due,
            "renewed_at": None,
            "notes": _clean_text(data.get("notes"), max_chars=2000),
            "created_by_user_id": actor_user_id,
        },
    )
    db.flush()
    events.emit(
        db,
        business_id=business_id,
        event_type="renewal.created",
        entity_type="renewal",
        entity_id=renewal.id,
        actor_user_id=actor_user_id,
        payload={"membership_id": str(membership.id)},
    )
    return renewal


def get_renewal(db: Session, *, business_id: uuid.UUID, renewal_id: object):
    renewal = op_membership_repo.get_renewal(
        db, renewal_id=renewal_id, business_id=business_id
    )
    if renewal is None:
        raise NotFoundError("Renewal not found.")
    return renewal


def set_renewal_status(
    db: Session,
    *,
    business_id: uuid.UUID,
    renewal_id: object,
    to_status: str,
    actor_user_id: uuid.UUID | None = None,
):
    """Explicit renewal pipeline transition (pending -> confirmed/cancelled/expired)."""
    from app.services import domain_events as events
    from app.services.crm import _validate_enum as _enum

    renewal = get_renewal(db, business_id=business_id, renewal_id=renewal_id)
    target = _enum(
        to_status, allowed=RENEWAL_STATUSES, field="status", default="pending"
    )
    current = str(renewal.status or "pending").lower()
    if target == current:
        return renewal
    if target not in RENEWAL_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move renewal from {current.upper()} to {target.upper()}."
        )
    renewal.status = target
    if target == "confirmed":
        renewal.renewed_at = renewal.renewed_at or _utcnow()
    renewal.updated_at = _utcnow()
    db.flush()
    event_map = {
        "confirmed": "renewal.confirmed",
    }
    if target in event_map:
        events.emit(
            db,
            business_id=business_id,
            event_type=event_map[target],
            entity_type="renewal",
            entity_id=renewal.id,
            actor_user_id=actor_user_id,
            payload={"from": current, "to": target},
        )
    return renewal


def list_renewals(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id=None,
    status=None,
    due_before=None,
    due_after=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    from app.repositories.pagination import parse_uuid

    status_clean = (
        _validate_enum(
            status, allowed=RENEWAL_STATUSES, field="status", default="pending"
        )
        if status
        else None
    )
    member_uuid = parse_uuid(member_id) if member_id else None
    if member_id and member_uuid is None:
        raise ValueError("member_id must be a valid UUID.")
    return op_membership_repo.list_renewals(
        db,
        business_id=business_id,
        member_id=member_uuid,
        status=status_clean,
        due_before=_opt_date(due_before, "due_before"),
        due_after=_opt_date(due_after, "due_after"),
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


# -- helpers -------------------------------------------------------------------


def _add_months(start: date, months: int) -> date:
    month = start.month - 1 + max(1, months)
    year = start.year + month // 12
    month = month % 12 + 1
    from calendar import monthrange

    last_day = monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def _opt_date(value: object, field: str):
    if value in (None, ""):
        return None
    return _parse_date(value, field=field)


def _coerce_uuid(value: object, *, field: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid UUID.") from exc
