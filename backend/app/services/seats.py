"""Seat + allocation service (Block 7 steps 35-36).

Exclusivity contract: at most one ACTIVE allocation per seat AND per
member. The service pre-checks for friendly 409s, but the PARTIAL UNIQUE
INDEXES are the real guarantee — concurrent transactions that both pass
the check still collapse on commit (IntegrityError -> 409, loser retries
and observes the winner).

Membership expiry NEVER deletes seat history: release/transfer are
explicit operations; expired memberships keep their (released) rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.operations import SeatAllocation
from app.models.ops_vocab import SEAT_STATUSES, SEAT_TYPES
from app.repositories import seats as seats_repo
from app.services.crm import _clean_text, _validate_enum
from app.services.errors import ConflictError, NotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -- areas ---------------------------------------------------------------


def create_area(db: Session, *, business_id: uuid.UUID, data: dict):
    code = _clean_text(data.get("code"), max_chars=64)
    if not code:
        raise ValueError("Area code is required.")
    rows, _ = seats_repo.list_areas(db, business_id=business_id, limit=100, offset=0)
    if any(a.code == code for a in rows):
        raise ConflictError(f"A seat area with code '{code}' already exists.")
    try:
        area = seats_repo.create_area(
            db,
            business_id=business_id,
            fields={
                "code": code,
                "name": _clean_text(data.get("name"), max_chars=200) or code,
                "floor": _clean_text(data.get("floor"), max_chars=64),
                "description": _clean_text(data.get("description"), max_chars=500),
            },
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"A seat area with code '{code}' already exists.") from exc
    return area


def list_areas(db: Session, *, business_id: uuid.UUID, limit=None, offset=None):
    return seats_repo.list_areas(
        db, business_id=business_id, limit=limit, offset=offset
    )


# -- seats -----------------------------------------------------------------


def create_seat(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    number = _clean_text(data.get("seat_number"), max_chars=64)
    if not number:
        raise ValueError("seat_number is required.")
    area_id = None
    if data.get("area_id"):
        try:
            area_uuid = (
                data["area_id"]
                if isinstance(data["area_id"], uuid.UUID)
                else uuid.UUID(str(data["area_id"]))
            )
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("area_id must be a valid UUID.") from exc
        area = seats_repo.get_area(db, area_id=area_uuid, business_id=business_id)
        if area is None:
            raise NotFoundError("Seat area not found.")
        area_id = area.id
    seat_type = _validate_enum(
        data.get("seat_type", "regular"),
        allowed=SEAT_TYPES,
        field="seat_type",
        default="regular",
    )
    status = _validate_enum(
        data.get("status", "available"),
        allowed=SEAT_STATUSES,
        field="status",
        default="available",
    )
    try:
        seat = seats_repo.create_seat(
            db,
            business_id=business_id,
            fields={
                "area_id": area_id,
                "seat_number": number,
                "seat_type": seat_type,
                "status": status,
                "notes": _clean_text(data.get("notes"), max_chars=500),
                "created_by_user_id": actor_user_id,
            },
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Seat '{number}' already exists.") from exc
    return seat


def get_seat(db: Session, *, business_id: uuid.UUID, seat_id: object):
    seat = seats_repo.get_seat(db, seat_id=seat_id, business_id=business_id)
    if seat is None:
        raise NotFoundError("Seat not found.")
    return seat


def update_seat(
    db: Session,
    *,
    business_id: uuid.UUID,
    seat_id: object,
    fields: dict,
):
    seat = get_seat(db, business_id=business_id, seat_id=seat_id)
    allowed = {"seat_type", "status", "notes", "area_id"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown seat field(s): {sorted(unknown)}.")
    if "seat_type" in fields:
        seat.seat_type = _validate_enum(
            fields["seat_type"],
            allowed=SEAT_TYPES,
            field="seat_type",
            default="regular",
        )
    if "status" in fields:
        new_status = _validate_enum(
            fields["status"],
            allowed=SEAT_STATUSES,
            field="status",
            default="available",
        )
        if new_status != "available" and _has_active_allocation(
            db, business_id=business_id, seat_id=seat.id
        ):
            raise ConflictError(
                "Seat has an ACTIVE allocation; release it before "
                "blocking or maintaining the seat."
            )
        seat.status = new_status
    if "notes" in fields:
        seat.notes = _clean_text(fields["notes"], max_chars=500)
    if "area_id" in fields:
        if fields["area_id"] in (None, ""):
            seat.area_id = None
        else:
            try:
                area_uuid = (
                    fields["area_id"]
                    if isinstance(fields["area_id"], uuid.UUID)
                    else uuid.UUID(str(fields["area_id"]))
                )
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError("area_id must be a valid UUID.") from exc
            area = seats_repo.get_area(db, area_id=area_uuid, business_id=business_id)
            if area is None:
                raise NotFoundError("Seat area not found.")
            seat.area_id = area.id
    seat.updated_at = _utcnow()
    db.flush()
    return seat


def list_seats(
    db: Session,
    *,
    business_id: uuid.UUID,
    area_id=None,
    status=None,
    seat_type=None,
    search=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    from app.repositories.pagination import parse_uuid
    from app.services.crm import validate_search

    area_uuid = parse_uuid(area_id) if area_id else None
    if area_id and area_uuid is None:
        raise ValueError("area_id must be a valid UUID.")
    status_clean = (
        _validate_enum(
            status, allowed=SEAT_STATUSES, field="status", default="available"
        )
        if status
        else None
    )
    type_clean = (
        _validate_enum(
            seat_type, allowed=SEAT_TYPES, field="seat_type", default="regular"
        )
        if seat_type
        else None
    )
    return seats_repo.list_seats(
        db,
        business_id=business_id,
        area_id=area_uuid,
        status=status_clean,
        seat_type=type_clean,
        search=validate_search(search),
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def availability(db: Session, *, business_id: uuid.UUID) -> dict:
    return seats_repo.availability_summary(db, business_id=business_id)


def available_seats(
    db: Session, *, business_id: uuid.UUID, seat_type=None, area_id=None, limit=50
):
    from app.repositories.pagination import parse_uuid

    type_clean = (
        _validate_enum(
            seat_type, allowed=SEAT_TYPES, field="seat_type", default="regular"
        )
        if seat_type
        else None
    )
    area_uuid = parse_uuid(area_id) if area_id else None
    if area_id and area_uuid is None:
        raise ValueError("area_id must be a valid UUID.")
    return seats_repo.search_available(
        db,
        business_id=business_id,
        seat_type=type_clean,
        area_id=area_uuid,
        limit=limit,
    )


# -- allocations --------------------------------------------------------------


def _has_active_allocation(
    db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID
) -> bool:
    return (
        seats_repo.active_for_seat(db, business_id=business_id, seat_id=seat_id)
        is not None
    )


def _resolve_member(db: Session, *, business_id: uuid.UUID, member_id: object):
    from app.repositories import members as members_repo

    try:
        member_uuid = (
            member_id if isinstance(member_id, uuid.UUID) else uuid.UUID(str(member_id))
        )
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("member_id must be a valid UUID.") from exc
    member = members_repo.get(db, member_id=member_uuid, business_id=business_id)
    if member is None:
        raise NotFoundError("Member not found.")
    return member


def allocate_seat(
    db: Session,
    *,
    business_id: uuid.UUID,
    seat_id: object,
    member_id: object,
    membership_id: object | None = None,
    notes: str = "",
    actor_user_id: uuid.UUID | None = None,
):
    """Assign an exclusive seat. Race-safe via partial unique indexes."""
    from app.services import domain_events as events

    seat = get_seat(db, business_id=business_id, seat_id=seat_id)
    member = _resolve_member(db, business_id=business_id, member_id=member_id)
    if seat.status != "available":
        raise ConflictError(
            f"Seat '{seat.seat_number}' is {str(seat.status).upper()}; "
            "only AVAILABLE seats can be allocated."
        )
    if (
        seats_repo.active_for_seat(db, business_id=business_id, seat_id=seat.id)
        is not None
    ):
        raise ConflictError(f"Seat '{seat.seat_number}' is already allocated.")
    if (
        seats_repo.active_for_member(db, business_id=business_id, member_id=member.id)
        is not None
    ):
        raise ConflictError("That member already holds an active seat.")

    ms_uuid = None
    if membership_id:
        from app.repositories import op_memberships as op_membership_repo

        try:
            ms_uuid = (
                membership_id
                if isinstance(membership_id, uuid.UUID)
                else uuid.UUID(str(membership_id))
            )
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("membership_id must be a valid UUID.") from exc
        ms = op_membership_repo.get_membership(
            db, membership_id=ms_uuid, business_id=business_id
        )
        if ms is None:
            raise NotFoundError("Membership not found.")
        if ms.member_id != member.id:
            raise ConflictError("Membership does not belong to this member.")
        if str(ms.status or "").lower() != "active":
            raise ConflictError(
                f"Membership is {str(ms.status).upper()}; only ACTIVE "
                "memberships permit seat allocation."
            )
    try:
        allocation = SeatAllocation(
            business_id=business_id,
            seat_id=seat.id,
            member_id=member.id,
            membership_id=ms_uuid,
            status="active",
            allocated_at=_utcnow(),
            notes=_clean_text(notes, max_chars=500),
            allocated_by_user_id=actor_user_id,
        )
        db.add(allocation)
        seat.status = "occupied"
        db.flush()
    except IntegrityError as exc:
        # Lost the race: another transaction allocated first. Surface 409;
        # the caller can re-read availability (the winner is committed).
        db.rollback()
        raise ConflictError(
            "Seat was just allocated by another request. Please pick a different seat."
        ) from exc
    events.emit(
        db,
        business_id=business_id,
        event_type="seat.allocated",
        entity_type="seat_allocation",
        entity_id=allocation.id,
        actor_user_id=actor_user_id,
        payload={"seat_id": str(seat.id), "member_id": str(member.id)},
    )
    return allocation


def release_seat(
    db: Session,
    *,
    business_id: uuid.UUID,
    allocation_id: object,
    actor_user_id: uuid.UUID | None = None,
):
    """Release an ACTIVE allocation. History row is preserved (never deleted)."""
    from app.services import domain_events as events

    allocation = seats_repo.get_allocation(
        db, allocation_id=allocation_id, business_id=business_id
    )
    if allocation is None:
        raise NotFoundError("Seat allocation not found.")
    if str(allocation.status).lower() != "active":
        raise ConflictError("Only ACTIVE allocations can be released.")
    allocation.status = "released"
    allocation.released_at = _utcnow()
    allocation.released_by_user_id = actor_user_id
    seat = get_seat(db, business_id=business_id, seat_id=allocation.seat_id)
    if seat.status == "occupied":
        seat.status = "available"
    db.flush()
    events.emit(
        db,
        business_id=business_id,
        event_type="seat.released",
        entity_type="seat_allocation",
        entity_id=allocation.id,
        actor_user_id=actor_user_id,
        payload={"seat_id": str(allocation.seat_id)},
    )
    return allocation


def transfer_seat(
    db: Session,
    *,
    business_id: uuid.UUID,
    allocation_id: object,
    to_member_id: object,
    actor_user_id: uuid.UUID | None = None,
):
    """Controlled reallocation: release old + allocate new, atomically."""
    from app.services import domain_events as events

    allocation = seats_repo.get_allocation(
        db, allocation_id=allocation_id, business_id=business_id
    )
    if allocation is None:
        raise NotFoundError("Seat allocation not found.")
    if str(allocation.status).lower() != "active":
        raise ConflictError("Only ACTIVE allocations can be transferred.")
    new_member = _resolve_member(db, business_id=business_id, member_id=to_member_id)
    if (
        seats_repo.active_for_member(
            db, business_id=business_id, member_id=new_member.id
        )
        is not None
    ):
        raise ConflictError("The target member already holds an active seat.")
    allocation.status = "transferred"
    allocation.released_at = _utcnow()
    allocation.released_by_user_id = actor_user_id
    try:
        replacement = SeatAllocation(
            business_id=business_id,
            seat_id=allocation.seat_id,
            member_id=new_member.id,
            membership_id=allocation.membership_id,
            status="active",
            allocated_at=_utcnow(),
            notes=f"Transferred from member {allocation.member_id}.",
            allocated_by_user_id=actor_user_id,
        )
        db.add(replacement)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Seat transfer conflicts with existing data.") from exc
    events.emit(
        db,
        business_id=business_id,
        event_type="seat.transferred",
        entity_type="seat_allocation",
        entity_id=replacement.id,
        actor_user_id=actor_user_id,
        payload={
            "seat_id": str(allocation.seat_id),
            "from_member": str(allocation.member_id),
            "to_member": str(new_member.id),
        },
    )
    return replacement


def list_allocations(
    db: Session,
    *,
    business_id: uuid.UUID,
    seat_id=None,
    member_id=None,
    status=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    from app.repositories.pagination import parse_uuid

    seat_uuid = parse_uuid(seat_id) if seat_id else None
    if seat_id and seat_uuid is None:
        raise ValueError("seat_id must be a valid UUID.")
    member_uuid = parse_uuid(member_id) if member_id else None
    if member_id and member_uuid is None:
        raise ValueError("member_id must be a valid UUID.")
    return seats_repo.list_allocations(
        db,
        business_id=business_id,
        seat_id=seat_uuid,
        member_id=member_uuid,
        status=status,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )
