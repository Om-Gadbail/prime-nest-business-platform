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


def renewal_buckets(db: Session, *, business_id: uuid.UUID, today: date) -> dict:
    """Pending renewal buckets (7/14/30d) + overdue + completion rate.

    Buckets are cumulative windows from ``today`` (inclusive):
    due_7d ⊆ due_14d ⊆ due_30d. ``renewal_rate`` = confirmed / total
    renewals ever (0.0 when no renewals exist — never null).
    """
    from datetime import timedelta

    base = Renewal.business_id == business_id

    def _due_count(days: int) -> int:
        horizon = today + timedelta(days=max(1, days))
        return int(
            db.execute(
                select(func.count())
                .select_from(Renewal)
                .where(
                    base,
                    Renewal.status == "pending",
                    Renewal.due_date >= today,
                    Renewal.due_date <= horizon,
                )
            ).scalar()
            or 0
        )

    def _due_amount(days: int) -> Decimal:
        horizon = today + timedelta(days=max(1, days))
        return _qsum(
            db.execute(
                select(func.coalesce(func.sum(Renewal.renewal_amount), 0)).where(
                    base,
                    Renewal.status == "pending",
                    Renewal.due_date >= today,
                    Renewal.due_date <= horizon,
                )
            ).scalar()
        )

    overdue = int(
        db.execute(
            select(func.count())
            .select_from(Renewal)
            .where(base, Renewal.status == "pending", Renewal.due_date < today)
        ).scalar()
        or 0
    )
    overdue_amount = _qsum(
        db.execute(
            select(func.coalesce(func.sum(Renewal.renewal_amount), 0)).where(
                base, Renewal.status == "pending", Renewal.due_date < today
            )
        ).scalar()
    )
    by_status = {
        str(s): int(n)
        for s, n in db.execute(
            select(Renewal.status, func.count()).where(base).group_by(Renewal.status)
        ).all()
    }
    total = sum(by_status.values())
    confirmed = by_status.get("confirmed", 0)
    return {
        "due_7d": {"count": _due_count(7), "amount": str(_due_amount(7))},
        "due_14d": {"count": _due_count(14), "amount": str(_due_amount(14))},
        "due_30d": {"count": _due_count(30), "amount": str(_due_amount(30))},
        "overdue": {"count": overdue, "amount": str(overdue_amount)},
        "by_status": by_status,
        "total": total,
        "completed": confirmed,
        "renewal_rate": round(confirmed / total, 4) if total else 0.0,
    }


# -- payment health ------------------------------------------------------------


def payment_health(
    db: Session,
    *,
    business_id: uuid.UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    attention_limit: int = 20,
) -> dict:
    """Payment status breakdown + outstanding + attention queue.

    Outstanding = pending + partially_paid + overdue (money still to collect).
    Attention items expose safe identifiers only (id, invoice_no, amount,
    status, dates, member_id) — never provider refs or secrets.
    """
    conds = [Payment.business_id == business_id]
    if start is not None:
        conds.append(Payment.created_at >= start)
    if end is not None:
        conds.append(Payment.created_at <= end)

    def _sum(*statuses: str) -> Decimal:
        return _qsum(
            db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .select_from(Payment)
                .where(*conds, Payment.status.in_(list(statuses)))
            ).scalar()
        )

    def _count(*statuses: str) -> int:
        return int(
            db.execute(
                select(func.count())
                .select_from(Payment)
                .where(*conds, Payment.status.in_(list(statuses)))
            ).scalar()
            or 0
        )

    collected = _sum("paid")
    outstanding = _qsum(_sum("pending", "partially_paid") + _sum("overdue"))
    failed = _sum("failed")
    refunded = _sum("refunded")
    by_status_rows = db.execute(
        select(Payment.status, func.count(), func.coalesce(func.sum(Payment.amount), 0))
        .where(*conds)
        .group_by(Payment.status)
    ).all()
    by_status = {
        str(s): {"count": int(c), "amount": str(_qsum(a))} for s, c, a in by_status_rows
    }
    attention_rows = (
        db.execute(
            select(Payment)
            .where(*conds, Payment.status.in_(("failed", "overdue")))
            .order_by(Payment.created_at.desc())
            .limit(max(1, min(attention_limit, 50)))
        )
        .scalars()
        .all()
    )
    attention = [
        {
            "id": str(p.id),
            "invoice_no": p.invoice_no or "",
            "amount": str(_qsum(p.amount)),
            "currency": p.currency or "INR",
            "status": str(p.status),
            "method": str(p.method),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "due_at": p.due_at.isoformat() if p.due_at else None,
            "member_id": str(p.member_id) if p.member_id else None,
        }
        for p in attention_rows
    ]
    return {
        "collected": str(collected),
        "outstanding": str(outstanding),
        "failed": str(failed),
        "failed_count": _count("failed"),
        "overdue_count": _count("overdue"),
        "refunded": str(refunded),
        "payment_count": _count(
            "paid",
            "pending",
            "partially_paid",
            "overdue",
            "failed",
            "cancelled",
            "refunded",
        ),
        "by_status": by_status,
        "attention": attention,
    }


# -- attendance window ---------------------------------------------------------


def count_members_created(
    db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime
) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(Member)
            .where(
                Member.business_id == business_id,
                Member.created_at >= start,
                Member.created_at <= end,
            )
        ).scalar()
        or 0
    )


def count_renewals_confirmed(
    db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime
) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(Renewal)
            .where(
                Renewal.business_id == business_id,
                Renewal.status == "confirmed",
                Renewal.renewed_at.is_not(None),
                Renewal.renewed_at >= start,
                Renewal.renewed_at <= end,
            )
        ).scalar()
        or 0
    )


def count_attendance_between(
    db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime
) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(Attendance)
            .where(
                Attendance.business_id == business_id,
                Attendance.checked_in_at >= start,
                Attendance.checked_in_at <= end,
            )
        ).scalar()
        or 0
    )


def attendance_window(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date,
    end_date: date,
    inactivity_days: int = 14,
    decline_min_visits: int = 4,
    decline_ratio: float = 0.5,
) -> dict:
    """Window attendance trend + rule-based decline/inactivity signals.

    Decline rule (transparent, not predictive): split the window into two
    halves; a member with >= ``decline_min_visits`` visits in the first half
    and fewer than ``decline_ratio`` × first-half visits in the second half
    is flagged ``declining``. Inactive = active member with zero visits in
    the window (only evaluated when the window spans >= ``inactivity_days``;
    otherwise reported as ``evaluated: False`` with an honest reason
    instead of a misleading zero).
    """
    from datetime import timedelta

    span_days = max(1, (end_date - start_date).days + 1)
    mid = start_date + timedelta(days=span_days // 2)
    day_col = func.date(Attendance.checked_in_at)
    trend_rows = db.execute(
        select(day_col.label("day"), func.count().label("count"))
        .where(
            Attendance.business_id == business_id,
            Attendance.checked_in_at >= datetime.combine(
                start_date, datetime.min.time(), tzinfo=timezone.utc
            ),
            Attendance.checked_in_at
            <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc),
        )
        .group_by(day_col)
        .order_by(day_col.asc())
    ).all()
    trend = [{"date": str(r.day), "count": int(r.count)} for r in trend_rows]
    total = sum(t["count"] for t in trend)
    member_rows = db.execute(
        select(Attendance.member_id, func.count().label("count"))
        .where(
            Attendance.business_id == business_id,
            Attendance.attendance_date >= start_date,
            Attendance.attendance_date <= end_date,
        )
        .group_by(Attendance.member_id)
    ).all()
    active_members = len(member_rows)
    first_rows = {
        str(m): int(c)
        for m, c in db.execute(
            select(Attendance.member_id, func.count().label("count"))
            .where(
                Attendance.business_id == business_id,
                Attendance.attendance_date >= start_date,
                Attendance.attendance_date < mid,
            )
            .group_by(Attendance.member_id)
        ).all()
    }
    second_rows = {
        str(m): int(c)
        for m, c in db.execute(
            select(Attendance.member_id, func.count().label("count"))
            .where(
                Attendance.business_id == business_id,
                Attendance.attendance_date >= mid,
                Attendance.attendance_date <= end_date,
            )
            .group_by(Attendance.member_id)
        ).all()
    }
    declining = [
        {
            "member_id": mid_key,
            "first_half_visits": first_n,
            "second_half_visits": second_rows.get(mid_key, 0),
        }
        for mid_key, first_n in first_rows.items()
        if first_n >= decline_min_visits
        and second_rows.get(mid_key, 0) < first_n * decline_ratio
    ]
    declining.sort(key=lambda d: d["first_half_visits"] - d["second_half_visits"])
    inactive: dict = {"evaluated": False, "reason": None, "count": 0, "sample": []}
    if span_days >= max(1, inactivity_days):
        visited = {str(m) for m, _ in member_rows}
        inactive_ids = [
            str(mid)
            for mid in db.execute(
                select(Member.id).where(
                    Member.business_id == business_id, Member.status == "active"
                )
            ).scalars()
        ]
        missing = [i for i in inactive_ids if i not in visited]
        inactive = {
            "evaluated": True,
            "reason": None,
            "count": len(missing),
            "sample": missing[:50],
        }
    else:
        inactive["reason"] = (
            f"Window spans {span_days}d; inactivity needs >={inactivity_days}d."
        )
    return {
        "total": total,
        "days": span_days,
        "avg_per_day": round(total / span_days, 2) if span_days else 0.0,
        "active_members": active_members,
        "visits_per_member": round(total / active_members, 2) if active_members else 0.0,
        "daily_trend": trend,
        "declining": declining[:50],
        "declining_count": len(declining),
        "inactive": inactive,
    }


# -- lead exceptions -------------------------------------------------------------


_LEAD_TERMINAL = ("converted", "lost", "spam")


def lead_exceptions(
    db: Session,
    *,
    business_id: uuid.UUID,
    now: datetime,
    stale_hours: int = 72,
    uncontacted_hours: int = 24,
    sample_limit: int = 20,
) -> dict:
    """Stale / uncontacted / follow-up-overdue lead queues for owners."""
    from datetime import timedelta

    stale_cutoff = now - timedelta(hours=max(1, stale_hours))
    uncontacted_cutoff = now - timedelta(hours=max(1, uncontacted_hours))

    def _sample(stmt_extra) -> list[dict]:
        rows = (
            db.execute(
                select(Lead)
                .where(Lead.business_id == business_id, stmt_extra)
                .order_by(Lead.created_at.asc())
                .limit(max(1, min(sample_limit, 50)))
            )
            .scalars()
            .all()
        )
        out = []
        for lead in rows:
            created = lead.created_at
            age_days = (
                round((now - created).total_seconds() / 86400, 1)
                if created is not None
                else None
            )
            out.append(
                {
                    "id": str(lead.id),
                    "display_name": (lead.display_name or "")[:120],
                    "status": str(lead.status),
                    "source": str(lead.source or "unknown"),
                    "created_at": created.isoformat() if created else None,
                    "age_days": age_days,
                }
            )
        return out

    from sqlalchemy import and_, or_

    stale_conds = and_(
        Lead.status.in_(("new", "contacted")), Lead.created_at < stale_cutoff
    )
    stale_count = int(
        db.execute(
            select(func.count())
            .select_from(Lead)
            .where(Lead.business_id == business_id, stale_conds)
        ).scalar()
        or 0
    )
    uncontacted_conds = and_(
        Lead.status == "new",
        Lead.last_contacted_at.is_(None),
        Lead.created_at < uncontacted_cutoff,
    )
    uncontacted_count = int(
        db.execute(
            select(func.count())
            .select_from(Lead)
            .where(Lead.business_id == business_id, uncontacted_conds)
        ).scalar()
        or 0
    )
    overdue_conds = and_(
        Lead.follow_up_at.is_not(None),
        Lead.follow_up_at < now,
        Lead.status.not_in(_LEAD_TERMINAL),
    )
    overdue_count = int(
        db.execute(
            select(func.count())
            .select_from(Lead)
            .where(Lead.business_id == business_id, overdue_conds)
        ).scalar()
        or 0
    )
    _ = or_  # keep import surface explicit for future composite rules
    return {
        "stale_leads": {
            "count": stale_count,
            "hours_threshold": stale_hours,
            "sample": _sample(stale_conds) if stale_count else [],
        },
        "uncontacted_leads": {
            "count": uncontacted_count,
            "hours_threshold": uncontacted_hours,
            "sample": _sample(uncontacted_conds) if uncontacted_count else [],
        },
        "followup_overdue": {
            "count": overdue_count,
            "sample": _sample(overdue_conds) if overdue_count else [],
        },
    }


# -- automation health -------------------------------------------------------------


def automation_health(db: Session, *, business_id: uuid.UUID) -> dict:
    """Read-only automation/worker/scheduler health from execution records.

    No workflow engine here — just the truth from ``automation_rules`` and
    ``automation_executions``. When nothing ever ran, every timestamp is
    null and ``evaluated`` explains why instead of inventing health.
    """
    from datetime import timedelta

    from app.models.automation import AutomationExecution, AutomationRule

    rules_total = int(
        db.execute(
            select(func.count())
            .select_from(AutomationRule)
            .where(AutomationRule.business_id == business_id)
        ).scalar()
        or 0
    )
    rules_active = int(
        db.execute(
            select(func.count())
            .select_from(AutomationRule)
            .where(
                AutomationRule.business_id == business_id,
                AutomationRule.is_active.is_(True),
            )
        ).scalar()
        or 0
    )
    by_status = {
        str(s): int(n)
        for s, n in db.execute(
            select(AutomationExecution.status, func.count())
            .where(AutomationExecution.business_id == business_id)
            .group_by(AutomationExecution.status)
        ).all()
    }
    total_exec = sum(by_status.values())
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    failed_24h = int(
        db.execute(
            select(func.count())
            .select_from(AutomationExecution)
            .where(
                AutomationExecution.business_id == business_id,
                AutomationExecution.status == "failed",
                AutomationExecution.created_at >= day_ago,
            )
        ).scalar()
        or 0
    )
    last_success = db.execute(
        select(func.max(AutomationExecution.completed_at)).where(
            AutomationExecution.business_id == business_id,
            AutomationExecution.status == "succeeded",
        )
    ).scalar()
    last_failure = db.execute(
        select(func.max(AutomationExecution.created_at)).where(
            AutomationExecution.business_id == business_id,
            AutomationExecution.status == "failed",
        )
    ).scalar()
    pending_retry = sum(by_status.get(s, 0) for s in ("pending", "retrying", "running"))
    evaluated = total_exec > 0 or rules_total > 0
    return {
        "rules_total": rules_total,
        "rules_active": rules_active,
        "executions_total": total_exec,
        "executions_by_status": by_status,
        "failed_24h": failed_24h,
        "pending_retry": pending_retry,
        "last_success_at": last_success.isoformat() if last_success else None,
        "last_failure_at": last_failure.isoformat() if last_failure else None,
        "evaluated": evaluated,
        "note": None
        if evaluated
        else "No automation rules or executions recorded for this business.",
    }


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
        "eligible": 0,
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
        totals["eligible"] += int(funnel["eligible"])
    eligible = totals["eligible"]
    totals["lead_conversion_rate"] = (
        round(totals["converted"] / eligible, 4) if eligible else 0.0
    )
    totals["collected"] = str(totals["collected"])
    totals["pending"] = str(totals["pending"])
    totals["overdue"] = str(totals["overdue"])
    return {"businesses": per, "totals": totals}
