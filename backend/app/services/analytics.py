"""Intelligence & analytics (Block 12, steps 55-56).

Metric -> Trend -> Driver -> Exception -> Possible action. Every metric is
computed from source records (reproducible); AI may summarize findings but
never fabricates them. Snapshots persist for trend comparison.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.repositories import blocks812 as brepo


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_metrics(db: Session, *, business_id: uuid.UUID, days: int = 30) -> dict:
    """All metrics from actual DB records (documented formulas)."""
    from app.models.lead import Lead
    from app.models.booking import Booking
    from app.models.customer import Customer
    from app.models.operations import Attendance, Member, Membership, Payment, Renewal
    from app.models.operations import Seat, SeatAllocation

    since = _utcnow() - timedelta(days=max(1, days))
    prev_since = since - timedelta(days=max(1, days))

    def _cnt(model, start=None, end=None, extra=None):
        stmt = (
            select(func.count())
            .select_from(model)
            .where(model.business_id == business_id)
        )
        if start is not None:
            stmt = stmt.where(model.created_at >= start)
        if end is not None:
            stmt = stmt.where(model.created_at < end)
        if extra is not None:
            stmt = extra(stmt)
        return int(db.execute(stmt).scalar() or 0)

    leads = _cnt(Lead, since)
    leads_prev = _cnt(Lead, prev_since, since)
    bookings = _cnt(Booking, since)
    customers = _cnt(Customer, since)
    converted_leads = _cnt(
        Lead, since, extra=lambda s: s.where(Lead.status == "converted")
    )
    payments = list(
        db.execute(
            select(Payment).where(
                Payment.business_id == business_id,
                Payment.status == "paid",
                Payment.paid_at.is_not(None),
                Payment.paid_at >= since,
            )
        )
        .scalars()
        .all()
    )
    revenue = sum((float(p.amount or 0) for p in payments), 0.0)
    payments_prev = list(
        db.execute(
            select(Payment).where(
                Payment.business_id == business_id,
                Payment.status == "paid",
                Payment.paid_at.is_not(None),
                Payment.paid_at >= prev_since,
                Payment.paid_at < since,
            )
        )
        .scalars()
        .all()
    )
    revenue_prev = sum((float(p.amount or 0) for p in payments_prev), 0.0)
    memberships_active = int(
        db.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.business_id == business_id, Membership.status == "active")
        ).scalar()
        or 0
    )
    renewals_pending = int(
        db.execute(
            select(func.count())
            .select_from(Renewal)
            .where(Renewal.business_id == business_id, Renewal.status == "pending")
        ).scalar()
        or 0
    )
    attendance = _cnt(Attendance, since)
    members_total = _cnt(Member)
    # Seat occupancy (seat businesses; zero when no inventory — honest zeros).
    seats_total = int(
        db.execute(
            select(func.count())
            .select_from(Seat)
            .where(Seat.business_id == business_id)
        ).scalar()
        or 0
    )
    seats_occupied = int(
        db.execute(
            select(func.count())
            .select_from(SeatAllocation)
            .where(
                SeatAllocation.business_id == business_id,
                SeatAllocation.status == "active",
            )
        ).scalar()
        or 0
    )
    funnel = brepo.funnel_by_source(db, business_id=business_id)

    conversion_rate = round(converted_leads / leads * 100, 1) if leads else 0.0
    metrics = {
        "period_days": days,
        "leads": leads,
        "leads_prev": leads_prev,
        "bookings": bookings,
        "customers": customers,
        "converted_leads": converted_leads,
        "conversion_rate": conversion_rate,
        "revenue": f"{revenue:.2f}",
        "revenue_prev": f"{revenue_prev:.2f}",
        "payments": len(payments),
        "memberships_active": memberships_active,
        "renewals_pending": renewals_pending,
        "attendance": attendance,
        "members_total": members_total,
        "seats_total": seats_total,
        "seats_occupied": seats_occupied,
        "occupancy_rate": round(seats_occupied / seats_total * 100, 1)
        if seats_total
        else 0.0,
        "funnel_by_source": funnel,
        "source": "database",
        "computed_at": _utcnow().isoformat(),
    }
    period = f"{_utcnow().date().isoformat()}:{days}d"
    for key in (
        "leads",
        "bookings",
        "customers",
        "converted_leads",
        "payments",
        "memberships_active",
        "renewals_pending",
        "attendance",
    ):
        brepo.upsert_snapshot(
            db,
            business_id=business_id,
            period=period,
            metric_key=key,
            value=Decimal(str(metrics[key])),
        )
    brepo.upsert_snapshot(
        db,
        business_id=business_id,
        period=period,
        metric_key="revenue",
        value=Decimal(str(metrics["revenue"])),
    )
    db.flush()
    return metrics


def intelligence(db: Session, *, business_id: uuid.UUID, days: int = 30) -> dict:
    """Trend -> driver -> exception -> action narratives from measurements."""
    m = compute_metrics(db, business_id=business_id, days=days)
    findings: list[dict] = []

    def _pct(cur: float, prev: float) -> float:
        return round((cur - prev) / prev * 100, 1) if prev else (100.0 if cur else 0.0)

    rev, rev_prev = float(m["revenue"]), float(m["revenue_prev"])
    findings.append(
        {
            "metric": "revenue",
            "trend": f"Revenue {'increased' if rev >= rev_prev else 'decreased'} "
            f"({_pct(rev, rev_prev)}%) vs previous period.",
            "driver": _top_source_driver(m),
            "exception": None if rev else "No paid revenue recorded in this period.",
            "possible_action": "Review acquisition sources and follow up open leads."
            if rev <= rev_prev
            else "Double down on the top source.",
            "values": {"current": m["revenue"], "previous": m["revenue_prev"]},
        }
    )
    findings.append(
        {
            "metric": "leads",
            "trend": f"{m['leads']} leads ({_pct(m['leads'], m['leads_prev'])}% vs previous).",
            "driver": _top_source_driver(m),
            "exception": None if m["leads"] else "No leads recorded in this period.",
            "possible_action": "Ensure lead follow-up automation is active."
            if m["leads"]
            else "Check website intake + attribution.",
            "values": {"current": m["leads"], "previous": m["leads_prev"]},
        }
    )
    findings.append(
        {
            "metric": "renewals",
            "trend": f"{m['renewals_pending']} renewal(s) pending; {m['memberships_active']} active membership(s).",
            "driver": "Expiry-driven demand.",
            "exception": None
            if not m["renewals_pending"]
            else f"{m['renewals_pending']} pending renewal(s) need follow-up.",
            "possible_action": "Run renewal reminders for due memberships.",
            "values": {"pending": m["renewals_pending"]},
        }
    )
    if m["seats_total"]:
        findings.append(
            {
                "metric": "occupancy",
                "trend": f"Seat utilization {m['occupancy_rate']}% ({m['seats_occupied']}/{m['seats_total']}).",
                "driver": "Allocation activity.",
                "exception": None
                if m["occupancy_rate"] < 95
                else "Near-full occupancy — consider capacity.",
                "possible_action": "Release stale allocations or open new inventory."
                if m["occupancy_rate"] >= 95
                else "Steady.",
                "values": {"occupied": m["seats_occupied"], "total": m["seats_total"]},
            }
        )
    return {"metrics": m, "findings": findings}


def _top_source_driver(m: dict) -> str:
    funnel = m.get("funnel_by_source") or {}
    if not funnel:
        return "No source data recorded."
    top = max(funnel.items(), key=lambda kv: kv[1].get("leads", 0))
    return f"Most new leads came from source '{top[0]}' ({top[1].get('leads', 0)})."


def lead_intelligence(db: Session, *, business_id: uuid.UUID, lead) -> dict:
    """FACT / SIGNAL / RECOMMENDATION split (Block 10 step 49)."""
    from app.models.lead import LeadActivity

    acts = list(
        db.execute(
            select(LeadActivity)
            .where(
                LeadActivity.business_id == business_id, LeadActivity.lead_id == lead.id
            )
            .order_by(LeadActivity.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    fact = {
        "status": lead.status,
        "source": lead.source,
        "activities": len(acts),
        "last_contacted": str(lead.last_contacted_at or ""),
    }
    signals = []
    if lead.status in ("new", "contacted") and not acts:
        signals.append("No staff interaction recorded yet.")
    if lead.status == "new":
        signals.append("Fresh lead — response time matters.")
    recommendations = []
    if lead.status in ("new", "contacted"):
        recommendations.append(
            "Send follow-up on the lead's preferred channel; schedule next step."
        )
    return {"fact": fact, "signals": signals, "recommendations": recommendations}


def member_intelligence(db: Session, *, business_id: uuid.UUID, member) -> dict:
    """Engagement / inactivity / renewal-risk signals (Block 10 step 50)."""
    from app.models.operations import Attendance, Membership

    recent = _utcnow() - timedelta(days=30)
    visits = int(
        db.execute(
            select(func.count())
            .select_from(Attendance)
            .where(
                Attendance.business_id == business_id,
                Attendance.member_id == member.id,
                Attendance.checked_in_at >= recent,
            )
        ).scalar()
        or 0
    )
    memberships = list(
        db.execute(
            select(Membership)
            .where(
                Membership.business_id == business_id, Membership.member_id == member.id
            )
            .order_by(Membership.end_date.desc())
            .limit(3)
        )
        .scalars()
        .all()
    )
    fact = {
        "visits_30d": visits,
        "memberships": len(memberships),
        "status": member.status,
    }
    signals = []
    if not visits:
        signals.append(
            "AI signal: no visits in 30 days — member may need re-engagement."
        )
    for ms in memberships:
        days_left = (
            (ms.end_date - datetime.now(timezone.utc).date()).days
            if ms.end_date
            else 999
        )
        if 0 <= days_left <= 14 and ms.status == "active":
            signals.append(
                f"AI signal: membership expiring in {days_left} day(s) — renewal follow-up suggested."
            )
    recommendations = (
        ["Send renewal/re-engagement follow-up if consented."]
        if signals
        else ["Steady — no action needed."]
    )
    return {"fact": fact, "signals": signals, "recommendations": recommendations}
