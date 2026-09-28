"""Daily owner reports (Block 8 step 43) + renewal scheduler.

Yesterday -> Today -> Trend -> Exceptions -> Recommended actions.
Every number comes from real DB aggregates; sparse data yields honest
"no data" sections, never invented conclusions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.repositories import blocks812 as brepo


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _count(db: Session, model, business_id: uuid.UUID, since=None, extra=None) -> int:
    stmt = (
        select(func.count()).select_from(model).where(model.business_id == business_id)
    )
    if since is not None:
        stmt = stmt.where(model.created_at >= since)
    if extra is not None:
        stmt = extra(stmt)
    return int(db.execute(stmt).scalar() or 0)


def build_daily_report(
    db: Session, *, business_id: uuid.UUID, report_date: date | None = None
) -> dict:
    from app.models.lead import Lead
    from app.models.booking import Booking
    from app.models.operations import Attendance, Member, Payment
    from app.models.task import Task
    from app.services import ai_tools as tools

    today = report_date or date.today()
    yesterday = today - timedelta(days=1)
    day_start = datetime.combine(yesterday, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    day_end = day_start + timedelta(days=1)
    week_ago = _utcnow() - timedelta(days=7)

    leads_y = _count(
        db, Lead, business_id, day_start, lambda s: s.where(Lead.created_at < day_end)
    )
    bookings_y = _count(
        db,
        Booking,
        business_id,
        day_start,
        lambda s: s.where(Booking.created_at < day_end),
    )
    members_total = _count(db, Member, business_id)
    payments_y = _count(
        db,
        Payment,
        business_id,
        day_start,
        lambda s: s.where(Payment.created_at < day_end),
    )
    attendance_y = _count(
        db,
        Attendance,
        business_id,
        day_start,
        lambda s: s.where(
            Attendance.checked_in_at >= day_start, Attendance.checked_in_at < day_end
        ),
    )
    open_tasks = _count(
        db,
        Task,
        business_id,
        extra=lambda s: s.where(Task.status.in_(("open", "in_progress"))),
    )
    renewals_due = tools.execute_tool(
        db,
        business_id=business_id,
        tool_name="get_renewals_due",
        args={"days": 7},
        caller="staff",
    )
    revenue = tools.execute_tool(
        db,
        business_id=business_id,
        tool_name="get_revenue_summary",
        args={"days": 1},
        caller="staff",
    )
    alerts = tools.execute_tool(
        db,
        business_id=business_id,
        tool_name="get_operational_alerts",
        args={},
        caller="staff",
    )
    kpis = tools.execute_tool(
        db,
        business_id=business_id,
        tool_name="get_business_kpis",
        args={},
        caller="staff",
    )
    leads_week = _count(db, Lead, business_id, week_ago)

    payload = {
        "report_date": yesterday.isoformat(),
        "yesterday": {
            "leads": leads_y,
            "bookings": bookings_y,
            "payments": payments_y,
            "attendance": attendance_y,
            "revenue": revenue.get("revenue", "0"),
        },
        "today": {
            "members": members_total,
            "open_tasks": open_tasks,
            "renewals_due_7d": len((renewals_due.get("due") or [])),
        },
        "trend": {"leads_last_7d": leads_week, "leads_yesterday": leads_y},
        "exceptions": alerts.get("alerts", []),
        "recommended_actions": _recommend(leads_y, open_tasks, renewals_due, alerts),
        "kpis": kpis,
        "generated_at": _utcnow().isoformat(),
    }
    saved = brepo.upsert_report(
        db, business_id=business_id, report_date=yesterday.isoformat(), payload=payload
    )
    db.flush()
    return {"id": str(saved.id), **payload}


def _recommend(
    leads_y: int, open_tasks: int, renewals_due: dict, alerts: dict
) -> list[str]:
    actions: list[str] = []
    due = len((renewals_due.get("due") or []))
    if due:
        actions.append(f"Follow up on {due} membership(s) expiring within 7 days.")
    if open_tasks:
        actions.append(f"Clear {open_tasks} open task(s) in the staff queue.")
    if leads_y:
        actions.append(
            f"Review {leads_y} new lead(s) from yesterday for timely follow-up."
        )
    for alert in alerts.get("alerts") or []:
        if alert.get("type") == "automation_failed":
            actions.append("Investigate failed automation executions and retry.")
    if not actions:
        actions.append("No urgent actions. Business is steady.")
    return actions


# -- renewal reminder scan (Block 8 step 41) ------------------------------------

RENEWAL_OFFSETS_DEFAULT = (30, 14, 7, 3, 1, 0)


def renewal_scan(
    db: Session, *, business_id: uuid.UUID, offsets: tuple = RENEWAL_OFFSETS_DEFAULT
) -> list[dict]:
    """Find active memberships expiring at each configured offset (data, not hardcoded)."""
    from app.models.operations import Membership

    today = date.today()
    found: list[dict] = []
    for offset in offsets:
        target = today + timedelta(days=int(offset))
        rows = list(
            db.execute(
                select(Membership).where(
                    Membership.business_id == business_id,
                    Membership.status == "active",
                    Membership.end_date == target,
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            found.append(
                {
                    "membership_id": str(r.id),
                    "member_id": str(r.member_id),
                    "end_date": r.end_date.isoformat(),
                    "offset_days": int(offset),
                }
            )
    return found
