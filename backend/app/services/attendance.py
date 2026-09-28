"""Attendance service: check-in / check-out (Block 6 step 30, Block 7 step 37).

One row per member per day (unique constraint). Repeat check-ins on the
same day return the existing row (idempotent) instead of duplicating.
Check-out closes the day's row. Future QR/kiosk/mobile channels plug in
via ``source`` — no hardware logic here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ops_vocab import ATTENDANCE_SOURCES
from app.repositories import attendance as attendance_repo
from app.services.crm import _clean_text, _validate_enum
from app.services.errors import ConflictError, NotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _business_today(db: Session, business_id: uuid.UUID) -> date:
    """Business-local "today" for attendance dating.

    Check-ins without an explicit date belong to the business's calendar
    day, not UTC — otherwise visits near midnight land on the wrong day in
    owner/staff "today" views (which aggregate in business TZ).
    """
    try:
        from zoneinfo import ZoneInfo

        from app.repositories import businesses as business_repo

        biz = business_repo.get_by_id(db, business_id)
        tz = ZoneInfo(str(getattr(biz, "timezone", None) or "UTC"))
    except Exception:  # noqa: BLE001 - fall back to UTC on bad config
        tz = timezone.utc
    return datetime.now(tz).date()


def _parse_day(value: object, today: date | None = None) -> date:
    if value in (None, ""):
        return today or _utcnow().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise ValueError("attendance_date must be an ISO date (YYYY-MM-DD).") from exc


def get_record(db: Session, *, business_id: uuid.UUID, attendance_id: object):
    row = attendance_repo.get(db, attendance_id=attendance_id, business_id=business_id)
    if row is None:
        raise NotFoundError("Attendance record not found.")
    return row


def check_in(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id: object,
    data: dict | None = None,
    actor_user_id: uuid.UUID | None = None,
):
    """Check a member in. Same-day repeat returns the existing row."""
    from app.repositories import members as members_repo
    from app.services import domain_events as events

    data = data or {}
    try:
        member_uuid = (
            member_id if isinstance(member_id, uuid.UUID) else uuid.UUID(str(member_id))
        )
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("member_id must be a valid UUID.") from exc
    member = members_repo.get(db, member_id=member_uuid, business_id=business_id)
    if member is None:
        raise NotFoundError("Member not found.")
    day = _parse_day(data.get("attendance_date"), _business_today(db, business_id))
    if day > _business_today(db, business_id):
        raise ValueError("attendance_date must not be in the future.")
    source = _validate_enum(
        data.get("source", "manual"),
        allowed=ATTENDANCE_SOURCES,
        field="source",
        default="manual",
    )
    seat_id = None
    if data.get("seat_id"):
        from app.repositories import seats as seats_repo

        try:
            seat_uuid = (
                data["seat_id"]
                if isinstance(data["seat_id"], uuid.UUID)
                else uuid.UUID(str(data["seat_id"]))
            )
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("seat_id must be a valid UUID.") from exc
        seat = seats_repo.get_seat(db, seat_id=seat_uuid, business_id=business_id)
        if seat is None:
            raise NotFoundError("Seat not found.")
        seat_id = seat.id

    membership_id = None
    if data.get("membership_id"):
        from app.repositories import op_memberships as op_membership_repo

        try:
            ms_uuid = (
                data["membership_id"]
                if isinstance(data["membership_id"], uuid.UUID)
                else uuid.UUID(str(data["membership_id"]))
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
                "memberships permit check-in."
            )
        membership_id = ms.id
    else:
        from app.repositories import op_memberships as op_membership_repo

        current = op_membership_repo.active_for_member(
            db, business_id=business_id, member_id=member.id
        )
        if current is not None:
            membership_id = current.id
        else:
            # Entitlement gate: a member WITH membership history but NO
            # active membership is expired/cancelled -> deny. A member with
            # zero memberships is a trial/walk-in -> allow (no ledger yet).
            prior, _ = op_membership_repo.list_memberships(
                db,
                business_id=business_id,
                member_id=member.id,
                limit=1,
                offset=0,
            )
            if prior:
                raise ConflictError(
                    "No ACTIVE membership; check-in denied for "
                    "expired/cancelled entitlement."
                )
            membership_id = None

    existing = attendance_repo.get_for_day(
        db, business_id=business_id, member_id=member.id, attendance_date=day
    )
    if existing is not None:
        return existing, False
    try:
        row = attendance_repo.create(
            db,
            business_id=business_id,
            fields={
                "member_id": member.id,
                "membership_id": membership_id,
                "seat_id": seat_id,
                "attendance_date": day,
                "checked_in_at": _utcnow(),
                "checked_out_at": None,
                "source": source,
                "notes": _clean_text((data or {}).get("notes"), max_chars=500),
                "created_by_user_id": actor_user_id,
            },
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        winner = attendance_repo.get_for_day(
            db, business_id=business_id, member_id=member.id, attendance_date=day
        )
        if winner is not None:
            return winner, False
        raise ConflictError("Check-in conflicts with existing data.") from exc
    events.emit(
        db,
        business_id=business_id,
        event_type="attendance.checked_in",
        entity_type="attendance",
        entity_id=row.id,
        actor_user_id=actor_user_id,
        payload={"member_id": str(member.id), "date": str(day), "source": source},
    )
    return row, True


def check_out(
    db: Session,
    *,
    business_id: uuid.UUID,
    attendance_id: object,
    actor_user_id: uuid.UUID | None = None,
):
    from app.services import domain_events as events

    row = get_record(db, business_id=business_id, attendance_id=attendance_id)
    if row.checked_out_at is not None:
        return row, False
    now = _utcnow()
    row.checked_out_at = now
    checked_in = row.checked_in_at
    if checked_in is not None and checked_in.tzinfo is None:
        # SQLite returns naive datetimes for TZ-aware columns; Postgres
        # returns aware ones. Normalize (stored values are UTC) so the
        # guard below never crashes on either backend.
        checked_in = checked_in.replace(tzinfo=timezone.utc)
    if checked_in is not None and row.checked_out_at < checked_in:
        row.checked_out_at = checked_in
    db.flush()
    events.emit(
        db,
        business_id=business_id,
        event_type="attendance.checked_out",
        entity_type="attendance",
        entity_id=row.id,
        actor_user_id=actor_user_id,
        payload={"member_id": str(row.member_id)},
    )
    return row, True


def correct_record(
    db: Session,
    *,
    business_id: uuid.UUID,
    attendance_id: object,
    fields: dict,
    actor_user_id: uuid.UUID | None = None,
):
    """Staff correction (notes/source/seat only — times stay factual)."""
    row = get_record(db, business_id=business_id, attendance_id=attendance_id)
    allowed = {"notes", "source", "seat_id"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown attendance field(s): {sorted(unknown)}.")
    if "notes" in fields:
        row.notes = _clean_text(fields["notes"], max_chars=500)
    if "source" in fields:
        row.source = _validate_enum(
            fields["source"],
            allowed=ATTENDANCE_SOURCES,
            field="source",
            default="manual",
        )
    if "seat_id" in fields:
        if fields["seat_id"] in (None, ""):
            row.seat_id = None
        else:
            from app.repositories import seats as seats_repo

            try:
                seat_uuid = (
                    fields["seat_id"]
                    if isinstance(fields["seat_id"], uuid.UUID)
                    else uuid.UUID(str(fields["seat_id"]))
                )
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError("seat_id must be a valid UUID.") from exc
            seat = seats_repo.get_seat(db, seat_id=seat_uuid, business_id=business_id)
            if seat is None:
                raise NotFoundError("Seat not found.")
            row.seat_id = seat.id
    row.updated_at = _utcnow()
    db.flush()
    return row


def list_records(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id=None,
    day=None,
    day_from=None,
    day_to=None,
    open_only=False,
    source=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    from app.repositories.pagination import parse_uuid

    member_uuid = parse_uuid(member_id) if member_id else None
    if member_id and member_uuid is None:
        raise ValueError("member_id must be a valid UUID.")
    source_clean = (
        _validate_enum(
            source, allowed=ATTENDANCE_SOURCES, field="source", default="manual"
        )
        if source
        else None
    )
    return attendance_repo.list_scoped(
        db,
        business_id=business_id,
        member_id=member_uuid,
        day=_opt_day(day),
        day_from=_opt_day(day_from),
        day_to=_opt_day(day_to),
        open_only=bool(open_only),
        source=source_clean,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def _opt_day(value: object):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise ValueError("Date filters must be ISO dates (YYYY-MM-DD).") from exc
