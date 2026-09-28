"""Owner analytics repository: efficient SQL aggregates (Block 5).

Every number comes from the database — no invented metrics. All queries
are business-scoped (single) or explicitly multi-business (combined owner
view, which callers gate behind ``owner.combined.read`` + OWNER/ADMIN).

Money uses NUMERIC SUM in SQL; Python only formats.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.lead import Lead
from app.models.operations import Attendance, Member, Membership, Payment, Renewal


def _qsum(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# -- membership aggregates -------------------------------------------------


def membership_counts(
    db: Session, *, business_id: uuid.UUID, today: date, soon_days: int = 7
) -> dict:
    """Active/new/expiring/expired membership + member counts."""
    from datetime import timedelta

    soon = today + timedelta(days=max(1, soon_days))
    base = Membership.business_id == business_id
    active = int(
        db.execute(
            select(func.count())
            .select_from(Membership)
            .where(base, Membership.status == "active")
        ).scalar()
        or 0
    )
    expiring = int(
        db.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                base,
                Membership.status == "active",
                Membership.end_date >= today,
                Membership.end_date <= soon,
            )
        ).scalar()
        or 0
    )
    expired = int(
        db.execute(
            select(func.count())
            .select_from(Membership)
            .where(base, Membership.status == "expired")
        ).scalar()
        or 0
    )
    active_members = int(
        db.execute(
            select(func.count())
            .select_from(Member)
            .where(Member.business_id == business_id, Member.status == "active")
        ).scalar()
        or 0
    )
    new_members = int(
        db.execute(
            select(func.count())
            .select_from(Member)
            .where(
                Member.business_id == business_id,
                Member.created_at
                >= datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            )
        ).scalar()
        or 0
    )
    by_status = {
        str(s): int(n)
        for s, n in db.execute(
            select(Membership.status, func.count())
            .where(base)
            .group_by(Membership.status)
        ).all()
    }
    return {
        "active_memberships": active,
        "active_members": active_members,
        "new_members_today": new_members,
        "expiring_soon": expiring,
        "expired": expired,
        "by_status": by_status,
        "total": sum(by_status.values()),
    }


# -- revenue aggregates -----------------------------------------------------


def revenue_summary(
    db: Session,
    *,
    business_id: uuid.UUID,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Collected/pending/overdue revenue from payment rows in a window."""
    conds = [Payment.business_id == business_id]
    if start is not None:
        conds.append(Payment.created_at >= start)
    if end is not None:
        conds.append(Payment.created_at <= end)

    def _sum(*statuses: str) -> Decimal:
        val = db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .select_from(Payment)
            .where(*conds, Payment.status.in_(list(statuses)))
        ).scalar()
        return _qsum(val)

    collected = _sum("paid")
    pending = _sum("pending", "partially_paid")
    overdue = _sum("overdue")
    refunded = _sum("refunded")
    count = int(
        db.execute(select(func.count()).select_from(Payment).where(*conds)).scalar()
        or 0
    )
    by_status_rows = db.execute(
        select(Payment.status, func.count(), func.coalesce(func.sum(Payment.amount), 0))
        .where(*conds)
        .group_by(Payment.status)
    ).all()
    by_status = {
        str(s): {"count": int(c), "amount": str(_qsum(a))} for s, c, a in by_status_rows
    }
    by_method_rows = db.execute(
        select(Payment.method, func.count(), func.coalesce(func.sum(Payment.amount), 0))
        .where(*conds, Payment.status == "paid")
        .group_by(Payment.method)
    ).all()
    by_method = {
        str(m): {"count": int(c), "amount": str(_qsum(a))} for m, c, a in by_method_rows
    }
    avg = (collected / count) if count else Decimal("0.00")
    return {
        "collected": str(collected),
        "pending": str(pending),
        "overdue": str(overdue),
        "refunded": str(refunded),
        "payment_count": count,
        "average_transaction": str(avg),
        "by_status": by_status,
        "by_method": by_method,
    }


def revenue_by_day(
    db: Session,
    *,
    business_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Paid revenue grouped per calendar day (Postgres + SQLite portable)."""
    day = func.date(Payment.paid_at)
    rows = db.execute(
        select(
            day.label("day"),
            func.count().label("count"),
            func.coalesce(func.sum(Payment.amount), 0).label("total"),
        )
        .where(
            Payment.business_id == business_id,
            Payment.status == "paid",
            Payment.paid_at.is_not(None),
            Payment.paid_at >= start,
            Payment.paid_at <= end,
        )
        .group_by(day)
        .order_by(day.asc())
    ).all()
    return [
        {"date": str(r.day), "count": int(r.count), "amount": str(_qsum(r.total))}
        for r in rows
    ]


# -- lead / conversion aggregates --------------------------------------------
#
# Formulas (documented, explicit denominators):
#   lead_conversion_rate = converted / eligible
#     where eligible = all leads EXCEPT spam (spam is noise, not demand).
#   booking_conversion_rate = converted / booked
#     where booked = leads currently in status 'booked' + converted leads
#     that passed through booking (approximated as converted with a booking
#     link is out of scope: denominator = booked + converted).
# Zero denominators yield 0.0 (never null, never invented).

CONVERTIBLE_EXCLUDED = ("spam",)


def lead_funnel(
    db: Session,
    *,
    business_id: uuid.UUID,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    conds = [Lead.business_id == business_id]
    if start is not None:
        conds.append(Lead.created_at >= start)
    if end is not None:
        conds.append(Lead.created_at <= end)
    by_status = {
        str(s): int(n)
        for s, n in db.execute(
            select(Lead.status, func.count()).where(*conds).group_by(Lead.status)
        ).all()
    }
    total = sum(by_status.values())
    converted = by_status.get("converted", 0)
    eligible = total - by_status.get("spam", 0)
    conversion_rate = (converted / eligible) if eligible else 0.0
    booked = by_status.get("booked", 0)
    booking_denom = booked + converted
    booking_rate = (converted / booking_denom) if booking_denom else 0.0
    by_source = {
        str(s): int(n)
        for s, n in db.execute(
            select(Lead.source, func.count()).where(*conds).group_by(Lead.source)
        ).all()
    }
    return {
        "total": total,
        "by_status": by_status,
        "by_source": by_source,
        "converted": converted,
        "eligible": eligible,
        "lead_conversion_rate": round(conversion_rate, 4),
        "booked": booked,
        "booking_conversion_rate": round(booking_rate, 4),
    }


def lead_trend(
    db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime
) -> list[dict]:
    day = func.date(Lead.created_at)
    rows = db.execute(
        select(day.label("day"), func.count().label("count"))
        .where(
            Lead.business_id == business_id,
            Lead.created_at >= start,
            Lead.created_at <= end,
        )
        .group_by(day)
        .order_by(day.asc())
    ).all()
    return [{"date": str(r.day), "count": int(r.count)} for r in rows]


def booking_summary(
    db: Session,
    *,
    business_id: uuid.UUID,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    conds = [Booking.business_id == business_id]
    if start is not None:
        conds.append(Booking.created_at >= start)
    if end is not None:
        conds.append(Booking.created_at <= end)
    by_status = {
        str(s): int(n)
        for s, n in db.execute(
            select(Booking.status, func.count()).where(*conds).group_by(Booking.status)
        ).all()
    }
    return {"by_status": by_status, "total": sum(by_status.values())}


# -- attendance aggregates ----------------------------------------------------


def attendance_summary(
    db: Session,
    *,
    business_id: uuid.UUID,
    day: date | None = None,
    day_from: date | None = None,
    day_to: date | None = None,
) -> dict:
    conds = [Attendance.business_id == business_id]
    if day is not None:
        conds.append(Attendance.attendance_date == day)
    if day_from is not None:
        conds.append(Attendance.attendance_date >= day_from)
    if day_to is not None:
        conds.append(Attendance.attendance_date <= day_to)
    total = int(
        db.execute(select(func.count()).select_from(Attendance).where(*conds)).scalar()
        or 0
    )
    checked_in_now = None
    if day is not None:
        checked_in_now = int(
            db.execute(
                select(func.count())
                .select_from(Attendance)
                .where(*conds, Attendance.checked_out_at.is_(None))
            ).scalar()
            or 0
        )
    by_source = {
        str(s): int(n)
        for s, n in db.execute(
            select(Attendance.source, func.count())
            .where(*conds)
            .group_by(Attendance.source)
        ).all()
    }
    return {
        "total": total,
        "currently_checked_in": checked_in_now,
        "by_source": by_source,
    }


# -- renewal pipeline -----------------------------------------------------------


def renewal_pipeline(
    db: Session, *, business_id: uuid.UUID, today: date, soon_days: int = 30
) -> dict:
    from datetime import timedelta

    soon = today + timedelta(days=max(1, soon_days))
    base = Renewal.business_id == business_id
    by_status = {
        str(s): int(n)
        for s, n in db.execute(
            select(Renewal.status, func.count()).where(base).group_by(Renewal.status)
        ).all()
    }
    due_soon = int(
        db.execute(
            select(func.count())
            .select_from(Renewal)
            .where(
                base,
                Renewal.status == "pending",
                Renewal.due_date >= today,
                Renewal.due_date <= soon,
            )
        ).scalar()
        or 0
    )
    overdue_renewals = int(
        db.execute(
            select(func.count())
            .select_from(Renewal)
            .where(base, Renewal.status == "pending", Renewal.due_date < today)
        ).scalar()
        or 0
    )
    amount_due = _qsum(
        db.execute(
            select(func.coalesce(func.sum(Renewal.renewal_amount), 0)).where(
                base, Renewal.status == "pending"
            )
        ).scalar()
    )
    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "due_soon": due_soon,
        "overdue": overdue_renewals,
        "pending_amount": str(amount_due),
    }


# -- combined (multi-business, owner-gated) ---------------------------------------


def combined_totals(
    db: Session,
    *,
    business_ids: list[uuid.UUID],
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Cross-business rollup. Caller MUST hold owner.combined.read + role gate."""
    if not business_ids:
        return {"businesses": [], "totals": {}}
    per: list[dict] = []
    totals = {
        "collected": Decimal("0.00"),
        "pending": Decimal("0.00"),
        "overdue": Decimal("0.00"),
        "payments": 0,
        "leads": 0,
        "converted": 0,
        "active_memberships": 0,
        "active_members": 0,
    }
    for bid in business_ids:
        rev = revenue_summary(db, business_id=bid, start=start, end=end)
        funnel = lead_funnel(db, business_id=bid, start=start, end=end)
        per.append(
            {
                "business_id": str(bid),
                "revenue": rev,
                "leads": funnel,
            }
        )
        totals["collected"] += _qsum(rev["collected"])
        totals["pending"] += _qsum(rev["pending"])
        totals["overdue"] += _qsum(rev["overdue"])
        totals["payments"] += int(rev["payment_count"])
        totals["leads"] += int(funnel["total"])
        totals["converted"] += int(funnel["converted"])
    eligible = totals["leads"]
    totals["lead_conversion_rate"] = (
        round(totals["converted"] / eligible, 4) if eligible else 0.0
    )
    totals["collected"] = str(totals["collected"])
    totals["pending"] = str(totals["pending"])
    totals["overdue"] = str(totals["overdue"])
    return {"businesses": per, "totals": totals}
