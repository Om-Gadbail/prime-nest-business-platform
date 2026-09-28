"""Dashboard repository: efficient business-scoped SQL aggregates.

All counts use SQL COUNT / GROUP BY — the API never downloads whole
tables to compute numbers. No business logic here (services own that).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.lead import Lead, LeadActivity
from app.models.task import Task


def count(db: Session, stmt) -> int:  # type: ignore[no-untyped-def]
    return int(db.execute(stmt).scalar() or 0)


def count_new_leads(db: Session, *, business_id: uuid.UUID) -> int:
    return count(
        db,
        select(func.count())
        .select_from(Lead)
        .where(Lead.business_id == business_id, Lead.status == "new"),
    )


def count_followups_due(db: Session, *, business_id: uuid.UUID, now: datetime) -> int:
    from datetime import timedelta

    return count(
        db,
        select(func.count())
        .select_from(Lead)
        .where(
            Lead.business_id == business_id,
            Lead.follow_up_at.is_not(None),
            Lead.follow_up_at <= now + timedelta(days=1),
            Lead.status.not_in(["converted", "lost", "spam"]),
        ),
    )


def count_leads_since(db: Session, *, business_id: uuid.UUID, since: datetime) -> int:
    return count(
        db,
        select(func.count())
        .select_from(Lead)
        .where(Lead.business_id == business_id, Lead.created_at >= since),
    )


def count_bookings_by_status(
    db: Session, *, business_id: uuid.UUID, status: str
) -> int:
    return count(
        db,
        select(func.count())
        .select_from(Booking)
        .where(Booking.business_id == business_id, Booking.status == status),
    )


def count_bookings_since(
    db: Session, *, business_id: uuid.UUID, since: datetime
) -> int:
    return count(
        db,
        select(func.count())
        .select_from(Booking)
        .where(Booking.business_id == business_id, Booking.created_at >= since),
    )


def count_open_tasks(db: Session, *, business_id: uuid.UUID) -> int:
    return count(
        db,
        select(func.count())
        .select_from(Task)
        .where(
            Task.business_id == business_id,
            Task.status.not_in(["completed", "cancelled"]),
        ),
    )


def recent_leads(db: Session, *, business_id: uuid.UUID, limit: int = 5) -> list[Lead]:
    stmt = (
        select(Lead)
        .where(Lead.business_id == business_id)
        .order_by(Lead.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def recent_lead_activities(
    db: Session, *, business_id: uuid.UUID, limit: int = 8
) -> list[LeadActivity]:
    stmt = (
        select(LeadActivity)
        .where(LeadActivity.business_id == business_id)
        .order_by(LeadActivity.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def leads_by_status(db: Session, *, business_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(Lead.status, func.count())
        .where(Lead.business_id == business_id)
        .group_by(Lead.status)
    ).all()
    return {str(status): int(n) for status, n in rows}


def bookings_by_status(db: Session, *, business_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(Booking.status, func.count())
        .where(Booking.business_id == business_id)
        .group_by(Booking.status)
    ).all()
    return {str(status): int(n) for status, n in rows}
