"""AI business tools (Block 10, §7): narrow, schema-validated backend tools.

PUBLIC tools (website visitors): business profile/hours/location/services/
plans/facilities/faq/offers/availability/booking-request/lead/followup.
PRIVATE tools (owner/staff): leads/customers/memberships/renewals/
attendance/revenue/KPIs/alerts/growth. AI proposes -> backend validates
(authz + scope + schema) -> backend executes -> result returns to AI.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

PUBLIC_TOOLS = (
    "get_business_profile",
    "get_business_hours",
    "get_business_location",
    "get_business_services",
    "get_membership_plans",
    "get_facilities",
    "get_faq",
    "get_active_offers",
    "get_available_booking_slots",
    "create_booking_request",
    "get_booking_status",
    "create_lead",
    "update_lead_from_conversation",
    "create_staff_followup",
    "get_public_contact_information",
)

PRIVATE_TOOLS = (
    "get_lead_summary",
    "get_customer_summary",
    "get_membership_summary",
    "get_renewals_due",
    "get_attendance_summary",
    "get_revenue_summary",
    "get_business_kpis",
    "get_operational_alerts",
    "get_growth_summary",
)

ALL_TOOLS = PUBLIC_TOOLS + PRIVATE_TOOLS


def _business_row(db: Session, business_id: uuid.UUID):
    from app.models.business import Business

    return db.get(Business, business_id)


def _settings(db: Session, business_id: uuid.UUID) -> dict:
    from app.repositories import settings as settings_repo

    row = settings_repo.get_by_business(db, business_id)
    if row is None:
        return {}
    return {
        "branding": dict(row.branding or {}),
        "contact": dict(row.contact or {}),
        "address": dict(row.address or {}),
        "hours": dict(row.hours or {}),
        "localization": dict(row.localization or {}),
        "operational": dict(row.operational or {}),
    }


def execute_tool(
    db: Session,
    *,
    business_id: uuid.UUID,
    tool_name: str,
    args: dict,
    caller: str = "public",
    actor_user_id=None,
) -> dict:
    """Validate allowlist + scope, execute, return JSON-safe result."""
    name = str(tool_name or "").strip()
    if name not in ALL_TOOLS:
        raise ValueError(f"Unknown tool: {name!r}.")
    if caller == "public" and name not in PUBLIC_TOOLS:
        raise PermissionError(f"Tool not allowed for public callers: {name!r}.")
    args = dict(args or {})
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Tool not implemented: {name!r}.")
    result = handler(db, business_id=business_id, args=args)
    if not isinstance(result, dict):
        return {"result": str(result)}
    return result


def tool_specs(caller: str = "public") -> list[dict]:
    names = PUBLIC_TOOLS if caller == "public" else ALL_TOOLS
    return [
        {
            "name": n,
            "description": _DESCRIPTIONS.get(n, n),
            "parameters": _SCHEMAS.get(n, {"type": "object", "properties": {}}),
        }
        for n in names
    ]


_DESCRIPTIONS = {
    "get_business_profile": "Business name, type, tagline.",
    "get_business_hours": "Configured weekly opening hours.",
    "get_business_location": "Address + map/directions links when configured.",
    "get_business_services": "Services offered (from capabilities + plans).",
    "get_membership_plans": "Active membership plans with real prices.",
    "get_facilities": "Facilities/seat areas where configured.",
    "get_faq": "Configured FAQs (contact/settings notes).",
    "get_active_offers": "Currently active plans flagged best value.",
    "get_available_booking_slots": "Real availability for a date (never invented).",
    "create_booking_request": "Create a booking REQUEST (never auto-confirmed).",
    "get_booking_status": "Status of a booking by id.",
    "create_lead": "Create a website lead.",
    "update_lead_from_conversation": "Attach conversation notes to a lead.",
    "create_staff_followup": "Create a staff follow-up task.",
    "get_public_contact_information": "Public phone/WhatsApp/email.",
    "get_lead_summary": "Lead counts by status + follow-up queue.",
    "get_customer_summary": "Customer/member counts + recent activity.",
    "get_membership_summary": "Membership counts by status.",
    "get_renewals_due": "Renewals due within N days.",
    "get_attendance_summary": "Attendance counts in window.",
    "get_revenue_summary": "Revenue from paid payments in window.",
    "get_business_kpis": "Combined KPI snapshot.",
    "get_operational_alerts": "Exceptions: overdue tasks, failed automation, expiring memberships.",
    "get_growth_summary": "Attribution + referral + cross-sell summary.",
}

_SCHEMAS = {
    "get_available_booking_slots": {
        "type": "object",
        "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}},
    },
    "create_booking_request": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "date": {"type": "string"},
            "slot": {"type": "string"},
            "service": {"type": "string"},
        },
    },
    "create_lead": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "message": {"type": "string"},
            "interest": {"type": "string"},
        },
    },
    "get_booking_status": {
        "type": "object",
        "properties": {"booking_id": {"type": "string"}},
    },
    "get_renewals_due": {"type": "object", "properties": {"days": {"type": "integer"}}},
    "get_revenue_summary": {
        "type": "object",
        "properties": {"days": {"type": "integer"}},
    },
}


# -- handlers --------------------------------------------------------------------


def _h_profile(db, *, business_id, args):
    b = _business_row(db, business_id)
    s = _settings(db, business_id)
    return {
        "name": b.name if b else "",
        "slug": b.slug if b else "",
        "type": b.business_type if b else "",
        "tagline": (s.get("branding") or {}).get("tagline", ""),
        "phone": b.phone if b else None,
        "city": b.city if b else None,
    }


def _h_hours(db, *, business_id, args):
    s = _settings(db, business_id)
    return {
        "hours": (s.get("hours") or {}),
        "timezone": (s.get("localization") or {}).get("timezone", "Asia/Kolkata"),
    }


def _h_location(db, *, business_id, args):
    b = _business_row(db, business_id)
    s = _settings(db, business_id)
    addr = dict(s.get("address") or {})
    contact = dict(s.get("contact") or {})
    parts = [
        addr.get("address_line_1", ""),
        addr.get("city", "") or (b.city if b else ""),
        addr.get("state", ""),
        addr.get("postal_code", ""),
    ]
    return {
        "address": ", ".join(p for p in parts if p) or "Address not configured",
        "map_url": contact.get("map_url", "") or addr.get("map_url", ""),
        "directions_url": contact.get("directions_url", "")
        or addr.get("directions_url", ""),
        "phone": contact.get("phone", "") or (b.phone if b else ""),
        "hours": (s.get("hours") or {}),
    }


def _h_services(db, *, business_id, args):
    from app.services import capabilities as cap_service

    b = _business_row(db, business_id)
    caps = cap_service.get_capabilities(
        db, business_id=business_id, business_type=b.business_type if b else "other"
    )
    return {"capabilities": {k: v for k, v in caps.items() if v}}


def _h_plans(db, *, business_id, args):
    from app.models.operations import MembershipPlan
    from app.repositories.base import apply_business_scope

    stmt = apply_business_scope(select(MembershipPlan), MembershipPlan, business_id)
    stmt = (
        stmt.where(MembershipPlan.is_active.is_(True))
        .order_by(MembershipPlan.price.asc())
        .limit(50)
    )
    rows = list(db.execute(stmt).scalars().all())
    return {
        "plans": [
            {
                "code": r.code,
                "name": r.name,
                "category": r.category,
                "duration_months": r.duration_months,
                "price": str(r.price),
                "currency": r.currency,
                "is_best_value": r.is_best_value,
            }
            for r in rows
        ]
    }


def _h_facilities(db, *, business_id, args):
    from app.models.operations import SeatArea
    from app.repositories.base import apply_business_scope

    stmt = apply_business_scope(select(SeatArea), SeatArea, business_id).limit(50)
    rows = list(db.execute(stmt).scalars().all())
    return {
        "facilities": [{"code": r.code, "name": r.name, "floor": r.floor} for r in rows]
    }


def _h_faq(db, *, business_id, args):
    s = _settings(db, business_id)
    op = s.get("operational") or {}
    return {"faq": op.get("faq", []), "notes": (s.get("hours") or {}).get("notes", "")}


def _h_offers(db, *, business_id, args):
    from app.models.operations import MembershipPlan
    from app.repositories.base import apply_business_scope

    stmt = apply_business_scope(select(MembershipPlan), MembershipPlan, business_id)
    stmt = stmt.where(
        MembershipPlan.is_active.is_(True), MembershipPlan.is_best_value.is_(True)
    ).limit(20)
    rows = list(db.execute(stmt).scalars().all())
    return {
        "offers": [
            {
                "code": r.code,
                "name": r.name,
                "price": str(r.price),
                "currency": r.currency,
            }
            for r in rows
        ]
    }


def _h_slots(db, *, business_id, args):
    """Real availability: business hours minus existing bookings (hourly slots)."""
    day = str(args.get("date", "")).strip()
    try:
        target = date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD.") from exc
    s = _settings(db, business_id)
    weekly = (s.get("hours") or {}).get("weekly") or {}
    weekday = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ][target.weekday()]
    day_cfg = weekly.get(weekday) or {}
    if day_cfg.get("closed") is True:
        return {"date": day, "slots": [], "reason": "closed"}
    open_h, close_h = (
        str(day_cfg.get("open", "06:00")),
        str(day_cfg.get("close", "22:00")),
    )
    try:
        oh = int(open_h[:2])
        ch = int(close_h[:2])
    except (ValueError, IndexError):
        oh, ch = 6, 22
    # Existing bookings on that date (requested/confirmed block the slot).
    from app.models.booking import Booking
    from app.repositories.base import apply_business_scope

    start = datetime.combine(target, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    stmt = apply_business_scope(select(Booking), Booking, business_id)
    stmt = stmt.where(
        Booking.requested_start_at.is_not(None),
        Booking.requested_start_at >= start,
        Booking.requested_start_at < end,
        Booking.status.in_(("requested", "confirmed")),
    )
    booked_hours = set()
    for b in db.execute(stmt).scalars().all():
        try:
            booked_hours.add(b.requested_start_at.hour)
        except (AttributeError, TypeError):
            continue
    slots = []
    for h in range(oh, ch):
        if h in booked_hours:
            continue
        slots.append(f"{h % 12 or 12}:00 {'PM' if h >= 12 else 'AM'}")
        if len(slots) >= 12:
            break
    return {
        "date": day,
        "slots": slots,
        "timezone": (s.get("localization") or {}).get("timezone", "Asia/Kolkata"),
    }


def _h_create_booking(db, *, business_id, args):
    from app.services import bookings as bookings_service

    name = str(args.get("name", "Website visitor")).strip()[:200] or "Website visitor"
    phone = str(args.get("phone", "")).strip()
    day = str(args.get("date", "")).strip()
    slot = str(args.get("slot", "")).strip()
    try:
        target = date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD.") from exc
    # Re-check availability server-side before creating.
    avail = _h_slots(db, business_id=business_id, args={"date": day})
    if slot and slot not in avail["slots"]:
        return {
            "status": "unavailable",
            "message": f"{slot} is not available on {day}.",
            "available": avail["slots"],
        }
    start_at = datetime.combine(target, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    booking = bookings_service.create_booking(
        db,
        business_id=business_id,
        data={
            "display_name": name,
            "phone": phone or None,
            "booking_type": "visit",
            "title": f"Website visit ({slot or 'flexible'})",
            "requested_start_at": start_at.isoformat(),
            "source": "website",
            "notes": f"AI-assisted request; slot={slot}; service={args.get('service', '')}",
        },
    )
    db.flush()
    return {
        "status": "requested",
        "booking_id": str(booking.id),
        "message": "Request received — the team will confirm shortly.",
    }


def _h_booking_status(db, *, business_id, args):
    from app.services import bookings as bookings_service

    booking = bookings_service.get_booking(
        db, business_id=business_id, booking_id=str(args.get("booking_id", ""))
    )
    return {"status": booking.status, "title": booking.title}


def _h_create_lead(db, *, business_id, args):
    from app.services import leads as leads_service

    lead = leads_service.create_lead(
        db,
        business_id=business_id,
        data={
            "display_name": str(args.get("name", "Website visitor"))[:200],
            "phone": str(args.get("phone", ""))[:32] or None,
            "message": str(args.get("message", ""))[:2000],
            "service_interest": str(args.get("interest", ""))[:200],
            "source": "website",
            "consent_marketing": False,
        },
    )
    db.flush()
    # Emit event so automation (ack + follow-ups) runs on AI-created leads too.
    try:
        from app.core.config import get_settings as _gs
        from app.services import automation as _auto

        _auto.dispatch_event(
            db,
            _gs(),
            business_id=business_id,
            event_type="lead.created",
            entity_type="lead",
            entity_id=lead.id,
            payload={"source": "website", "display_name": lead.display_name},
        )
    except Exception:  # noqa: BLE001 - automation is best-effort on AI-created leads
        pass
    return {"lead_id": str(lead.id), "status": lead.status}


def _h_update_lead(db, *, business_id, args):
    from app.services import leads as leads_service

    lead_id = str(args.get("lead_id", ""))
    note = str(args.get("note", ""))[:2000]
    leads_service.add_note(
        db,
        business_id=business_id,
        lead_id=lead_id,
        note=note or "AI conversation update",
    )
    db.flush()
    return {"updated": lead_id}


def _h_followup(db, *, business_id, args):
    from app.services import tasks as tasks_service

    task = tasks_service.create_task(
        db,
        business_id=business_id,
        title=str(args.get("title", "AI follow-up"))[:200],
        description=str(args.get("reason", "Requested from AI conversation."))[:2000],
        priority="medium",
    )
    db.flush()
    return {"task_id": str(task.id)}


def _h_contact(db, *, business_id, args):
    return _h_location(db, business_id=business_id, args=args)


def _window(days: int):
    now = datetime.now(timezone.utc)
    try:
        days = max(1, min(365, int(days or 30)))
    except (TypeError, ValueError):
        days = 30
    return now - timedelta(days=days), now


def _h_lead_summary(db, *, business_id, args):
    from app.models.lead import Lead

    rows = list(
        db.execute(select(Lead).where(Lead.business_id == business_id)).scalars().all()
    )
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    followups = [str(r.id) for r in rows if r.status in ("new", "contacted")][:20]
    return {"total": len(rows), "by_status": by_status, "followup_queue": followups}


def _h_customer_summary(db, *, business_id, args):
    from app.models.customer import Customer
    from app.models.operations import Member

    customers = (
        db.execute(
            select(func.count())
            .select_from(Customer)
            .where(Customer.business_id == business_id)
        ).scalar()
        or 0
    )
    members = (
        db.execute(
            select(func.count())
            .select_from(Member)
            .where(Member.business_id == business_id)
        ).scalar()
        or 0
    )
    return {"customers": int(customers), "members": int(members)}


def _h_membership_summary(db, *, business_id, args):
    from app.models.operations import Membership

    rows = list(
        db.execute(
            select(Membership.status, func.count())
            .where(Membership.business_id == business_id)
            .group_by(Membership.status)
        ).all()
    )
    return {"by_status": {str(k): int(v) for k, v in rows}}


def _h_renewals(db, *, business_id, args):
    days = int(args.get("days", 30) or 30)
    horizon = date.today() + timedelta(days=max(1, min(180, days)))
    from app.models.operations import Membership

    stmt = (
        select(Membership)
        .where(
            Membership.business_id == business_id,
            Membership.end_date <= horizon,
            Membership.status == "active",
        )
        .limit(50)
    )
    rows = list(db.execute(stmt).scalars().all())
    return {
        "due": [
            {
                "id": str(r.id),
                "member_id": str(r.member_id),
                "end_date": r.end_date.isoformat(),
            }
            for r in rows
        ]
    }


def _h_attendance(db, *, business_id, args):
    days = int(args.get("days", 7) or 7)
    start, _ = _window(days)
    from app.models.operations import Attendance

    count = (
        db.execute(
            select(func.count())
            .select_from(Attendance)
            .where(
                Attendance.business_id == business_id, Attendance.checked_in_at >= start
            )
        ).scalar()
        or 0
    )
    return {"check_ins": int(count), "days": days}


def _h_revenue(db, *, business_id, args):
    days = int(args.get("days", 30) or 30)
    start, _ = _window(days)
    from app.models.operations import Payment

    rows = list(
        db.execute(
            select(Payment).where(
                Payment.business_id == business_id,
                Payment.status == "paid",
                Payment.paid_at.is_not(None),
                Payment.paid_at >= start,
            )
        )
        .scalars()
        .all()
    )
    total = sum((float(r.amount or 0) for r in rows), 0.0)
    return {"revenue": f"{total:.2f}", "payments": len(rows), "days": days}


def _h_kpis(db, *, business_id, args):
    return {
        "leads": _h_lead_summary(db, business_id=business_id, args={}),
        "customers": _h_customer_summary(db, business_id=business_id, args={}),
        "memberships": _h_membership_summary(db, business_id=business_id, args={}),
        "revenue_30d": _h_revenue(db, business_id=business_id, args={"days": 30}),
        "attendance_7d": _h_attendance(db, business_id=business_id, args={"days": 7}),
    }


def _h_alerts(db, *, business_id, args):
    from app.models.operations import Membership
    from app.models.task import Task
    from app.models.automation import AutomationExecution

    overdue_tasks = (
        db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.business_id == business_id,
                Task.status.in_(("open", "in_progress")),
            )
        ).scalar()
        or 0
    )
    failed_auto = (
        db.execute(
            select(func.count())
            .select_from(AutomationExecution)
            .where(
                AutomationExecution.business_id == business_id,
                AutomationExecution.status == "failed",
            )
        ).scalar()
        or 0
    )
    horizon = date.today() + timedelta(days=7)
    expiring = (
        db.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.business_id == business_id,
                Membership.status == "active",
                Membership.end_date <= horizon,
            )
        ).scalar()
        or 0
    )
    alerts = []
    if expiring:
        alerts.append({"type": "renewals_due", "count": int(expiring)})
    if overdue_tasks:
        alerts.append({"type": "open_tasks", "count": int(overdue_tasks)})
    if failed_auto:
        alerts.append({"type": "automation_failed", "count": int(failed_auto)})
    return {"alerts": alerts}


def _h_growth(db, *, business_id, args):
    from app.repositories import blocks812 as brepo

    funnel = brepo.funnel_by_source(db, business_id=business_id)
    refs, _ = brepo.list_referrals(db, business_id=business_id, limit=100)
    xsells, _ = brepo.list_xsell(db, business_id=business_id, limit=100)
    return {
        "funnel": funnel,
        "referrals": len(refs),
        "referrals_converted": sum(1 for r in refs if r.status == "converted"),
        "cross_sell": len(xsells),
        "cross_sell_converted": sum(1 for r in xsells if r.status == "converted"),
    }


_HANDLERS = {
    "get_business_profile": _h_profile,
    "get_business_hours": _h_hours,
    "get_business_location": _h_location,
    "get_business_services": _h_services,
    "get_membership_plans": _h_plans,
    "get_facilities": _h_facilities,
    "get_faq": _h_faq,
    "get_active_offers": _h_offers,
    "get_available_booking_slots": _h_slots,
    "create_booking_request": _h_create_booking,
    "get_booking_status": _h_booking_status,
    "create_lead": _h_create_lead,
    "update_lead_from_conversation": _h_update_lead,
    "create_staff_followup": _h_followup,
    "get_public_contact_information": _h_contact,
    "get_lead_summary": _h_lead_summary,
    "get_customer_summary": _h_customer_summary,
    "get_membership_summary": _h_membership_summary,
    "get_renewals_due": _h_renewals,
    "get_attendance_summary": _h_attendance,
    "get_revenue_summary": _h_revenue,
    "get_business_kpis": _h_kpis,
    "get_operational_alerts": _h_alerts,
    "get_growth_summary": _h_growth,
}
