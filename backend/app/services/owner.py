"""Owner command-center service (Block 5, steps 22-26).

Single-business analytics require ``analytics.read`` (or the owner
dashboard permission); the COMBINED cross-business view additionally
requires ``owner.combined.read`` AND an OWNER/ADMIN role — combined
access is an explicitly authorized capability, never an accident of
being logged in. All combined queries are intentional (explicit
business-id list) and auditable (callers log owner.combined access).

Every number comes from the repositories (real DB aggregates). Empty
businesses yield zeros — never invented metrics.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.repositories import businesses as business_repo
from app.repositories import owner_analytics as analytics_repo
from app.repositories import seats as seats_repo
from app.services.business_context import BusinessContext
from app.services.errors import ForbiddenError
from decimal import Decimal as _Money

COMBINED_ALLOWED_ROLES = frozenset({"OWNER", "ADMIN"})
DEFAULT_SOON_DAYS = 7
DEFAULT_RENEWAL_WINDOW_DAYS = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_window(
    date_from: object | None, date_to: object | None, preset: str | None
) -> tuple[datetime | None, datetime | None]:
    """Resolve preset/range filters to an explicit [start, end] window."""
    now = _utcnow()
    if date_from or date_to:
        start = _coerce_dt(date_from, "date_from")
        end = _coerce_dt(date_to, "date_to")
        if start and end and end < start:
            raise ValueError("date_to must not be before date_from.")
        return start, end
    preset_clean = (preset or "30d").strip().lower()
    presets = {
        "today": 1,
        "7d": 7,
        "30d": 30,
        "month": 31,
        "quarter": 92,
    }
    if preset_clean == "all":
        return None, None
    days = presets.get(preset_clean)
    if days is None:
        raise ValueError(
            f"Unknown range preset: {preset!r}. "
            "Allowed: today, 7d, 30d, month, quarter, all (or explicit dates)."
        )
    return now - timedelta(days=days), now


def _coerce_dt(value: object | None, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{field} must be an ISO datetime.") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _today_in_business_tz(business_tz: str | None) -> date:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(str(business_tz or "UTC"))
    except Exception:  # noqa: BLE001 - fall back to UTC on bad config
        tz = timezone.utc
    return datetime.now(tz).date()


def business_overview(
    db: Session,
    *,
    ctx: BusinessContext,
    soon_days: int = DEFAULT_SOON_DAYS,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Per-business owner snapshot (single authorized business)."""
    today = _today_in_business_tz(getattr(ctx.business, "timezone", None))
    membership = analytics_repo.membership_counts(
        db, business_id=ctx.business_id, today=today, soon_days=soon_days
    )
    revenue = analytics_repo.revenue_summary(
        db, business_id=ctx.business_id, start=start, end=end
    )
    funnel = analytics_repo.lead_funnel(
        db, business_id=ctx.business_id, start=start, end=end
    )
    bookings = analytics_repo.booking_summary(
        db, business_id=ctx.business_id, start=start, end=end
    )
    attendance = analytics_repo.attendance_summary(
        db, business_id=ctx.business_id, day=today
    )
    renewals = analytics_repo.renewal_pipeline(
        db, business_id=ctx.business_id, today=today
    )
    payload: dict = {
        "business": {
            "id": str(ctx.business.id),
            "slug": ctx.business.slug,
            "name": ctx.business.name,
            "business_type": ctx.business.business_type,
        },
        "generated_at": _utcnow(),
        "membership": membership,
        "revenue": revenue,
        "leads": funnel,
        "bookings": bookings,
        "attendance_today": attendance,
        "renewals": renewals,
    }
    from app.services import capabilities as caps

    abilities = caps.get_capabilities(
        db,
        business_id=ctx.business_id,
        business_type=str(getattr(ctx.business, "business_type", "other")),
    )
    if abilities.get("seat_management"):
        payload["seats"] = seats_repo.availability_summary(
            db, business_id=ctx.business_id
        )
    return payload


def revenue_report(
    db: Session,
    *,
    ctx: BusinessContext,
    start: datetime | None,
    end: datetime | None,
) -> dict:
    revenue = analytics_repo.revenue_summary(
        db, business_id=ctx.business_id, start=start, end=end
    )
    trend: list[dict] = []
    if start is not None and end is not None:
        trend = analytics_repo.revenue_by_day(
            db, business_id=ctx.business_id, start=start, end=end
        )
    return {
        "business_id": str(ctx.business_id),
        "generated_at": _utcnow(),
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "summary": revenue,
        "daily_trend": trend,
    }


def leads_report(
    db: Session,
    *,
    ctx: BusinessContext,
    start: datetime | None,
    end: datetime | None,
) -> dict:
    funnel = analytics_repo.lead_funnel(
        db, business_id=ctx.business_id, start=start, end=end
    )
    trend: list[dict] = []
    if start is not None and end is not None:
        trend = analytics_repo.lead_trend(
            db, business_id=ctx.business_id, start=start, end=end
        )
    return {
        "business_id": str(ctx.business_id),
        "generated_at": _utcnow(),
        "formulas": {
            # Documented explicitly (Block 5 step 25 requirement).
            "lead_conversion_rate": "converted_leads / eligible_leads "
            "where eligible_leads = all leads EXCEPT spam",
            "booking_conversion_rate": "converted_leads / (booked_leads + converted_leads)",
            "zero_denominator": "0.0 (never null, never invented)",
        },
        "funnel": funnel,
        "daily_trend": trend,
    }


def _authorized_business_ids(db: Session, *, ctx: BusinessContext) -> set:
    """Explicit multi-business grant set for the caller.

    Derived ONLY from the caller's ACTIVE memberships in ACTIVE businesses
    (server-side DB state). Never "every business in the registry" — a new
    business added tomorrow is invisible until an explicit membership exists.
    """
    from app.repositories import memberships as membership_repo

    grants = set()
    for membership in membership_repo.list_user_memberships(db, user_id=ctx.user_id):
        business = membership.business
        if (
            membership.status == "active"
            and business is not None
            and business.is_active
            and business.status == "active"
        ):
            grants.add(business.id)
    return grants


def _resolve_combined_businesses(
    db: Session, *, ctx: BusinessContext, scope: str | None
) -> list:
    """Explicit combined-access gate: permission + OWNER/ADMIN role + grants.

    Scope semantics:
    - ``all`` (default): aggregate ONLY the businesses the caller is an
      active member of. An owner of Prime+Nest sees Prime+Nest; an OWNER of
      Nest alone sees Nest alone.
    - ``<slug>``: single business, still through this gate; requires an
      active membership in that business (known-but-unassigned -> 403).
      Unknown slug -> 404 (no oracle beyond that).
    """
    if "owner.combined.read" not in ctx.permissions:
        raise ForbiddenError("Missing permission: owner.combined.read.")
    if (ctx.role_name or "") not in COMBINED_ALLOWED_ROLES:
        raise ForbiddenError("Combined owner view requires OWNER or ADMIN.")
    grants = _authorized_business_ids(db, ctx=ctx)
    wanted = (scope or "all").strip().lower()
    if wanted in ("all", ""):
        businesses = [
            b
            for b in business_repo.list_all(db)
            if b.id in grants and b.is_active and b.status == "active"
        ]
        if not businesses:
            raise ForbiddenError("No authorized businesses for combined view.")
        return businesses
    match = next((b for b in business_repo.list_all(db) if b.slug == wanted), None)
    if match is None:
        from app.services.errors import NotFoundError

        raise NotFoundError("Business not found.")
    if match.id not in grants:
        # Authenticated but not a member: 403 (not 404 — the slug namespace
        # itself is public, the grant is what is missing).
        raise ForbiddenError("No access to the requested business.")
    return [match]


def _single_scope_context(
    db: Session, *, ctx: BusinessContext, scope: str | None
) -> BusinessContext:
    """Pin a single-business context to an authorized slug scope.

    ``scope=None`` keeps the caller's token business. A slug goes through
    the combined gate (membership grant required; unknown slug -> 404,
    known-but-unassigned -> 403). ``scope=all`` is rejected here — the
    multi-business shape belongs to the combined/scope-aware endpoints.
    """
    if scope is None:
        return ctx
    if (scope or "").strip().lower() == "all":
        raise ValueError(
            "scope=all is multi-business; use /owner/combined or the "
            "scope-aware reports (alerts, growth, renewals, payments, "
            "attendance, automation-health)."
        )
    targets = _resolve_combined_businesses(db, ctx=ctx, scope=scope)
    target = targets[0]
    if target.id == ctx.business_id:
        return ctx
    import dataclasses

    from app.repositories import memberships as membership_repo

    member = membership_repo.get_membership(
        db, user_id=ctx.user_id, business_id=target.id
    )
    return dataclasses.replace(
        ctx, business=target, membership=(member or ctx.membership)
    )


def _resolve_scope_businesses(
    db: Session, *, ctx: BusinessContext, scope: str | None
) -> tuple[list, bool]:
    """Resolve target businesses for scope-aware owner endpoints.

    Returns (businesses, is_combined). ``scope=None`` means the caller's
    current token business (single-business path; ``owner.dashboard.read``
    suffices). Any explicit scope (``all`` or a slug) goes through the
    full combined gate (``owner.combined.read`` + OWNER/ADMIN + grants).
    """
    if scope is None:
        if ctx.business is None:
            raise ForbiddenError("No business context.")
        return [ctx.business], False
    return _resolve_combined_businesses(db, ctx=ctx, scope=scope), True


def _pct_change(current: float, previous: float | None) -> float | None:
    """Percent change vs previous period; None when there is no baseline.

    A zero denominator never yields a percentage (that would be invented
    precision); callers render "no prior data" instead.
    """
    if previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _prev_window(
    start: datetime | None, end: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Mirror [start, end] to the immediately preceding equal-length window."""
    if start is None or end is None or end <= start:
        return None, None
    length = end - start
    return start - length, start


def growth_report(
    db: Session,
    *,
    ctx: BusinessContext,
    scope: str | None,
    start: datetime | None,
    end: datetime | None,
) -> dict:
    """Current vs previous-period growth for revenue/leads/members/renewals.

    Comparison uses the immediately preceding equal-length window. When the
    window is open-ended (preset=all) there is no previous period and every
    ``previous``/``delta_pct`` is null — rendered as "no prior data".
    """
    businesses, is_combined = _resolve_scope_businesses(db, ctx=ctx, scope=scope)
    prev_start, prev_end = _prev_window(start, end)
    bounded = start is not None and end is not None

    def _one(bid) -> dict:
        cur_rev = analytics_repo.revenue_summary(
            db, business_id=bid, start=start, end=end
        )
        cur_funnel = analytics_repo.lead_funnel(
            db, business_id=bid, start=start, end=end
        )
        cur_confirmed = (
            analytics_repo.count_renewals_confirmed(
                db, business_id=bid, start=start, end=end
            )
            if bounded
            else None
        )
        cur_att = (
            analytics_repo.count_attendance_between(
                db, business_id=bid, start=start, end=end
            )
            if bounded
            else None
        )
        cur_members = (
            analytics_repo.count_members_created(
                db, business_id=bid, start=start, end=end
            )
            if bounded
            else None
        )
        if prev_start is not None and prev_end is not None:
            prev_rev = analytics_repo.revenue_summary(
                db, business_id=bid, start=prev_start, end=prev_end
            )
            prev_funnel = analytics_repo.lead_funnel(
                db, business_id=bid, start=prev_start, end=prev_end
            )
            prev_confirmed: int | None = analytics_repo.count_renewals_confirmed(
                db, business_id=bid, start=prev_start, end=prev_end
            )
            prev_members: int | None = analytics_repo.count_members_created(
                db, business_id=bid, start=prev_start, end=prev_end
            )
            prev_att: int | None = analytics_repo.count_attendance_between(
                db, business_id=bid, start=prev_start, end=prev_end
            )
        else:
            prev_rev = None
            prev_funnel = None
            prev_confirmed = None
            prev_members = None
            prev_att = None
        collected = _Money(str(cur_rev["collected"]))
        prev_collected = (
            _Money(str(prev_rev["collected"])) if prev_rev is not None else None
        )
        return {
            "revenue": {
                "current": str(collected),
                "previous": str(prev_collected) if prev_collected is not None else None,
                "delta": str(collected - (prev_collected or _Money("0")))
                if prev_rev is not None
                else None,
                "delta_pct": _pct_change(float(collected), float(prev_collected) if prev_collected is not None else None),
            },
            "leads": {
                "current": cur_funnel["total"],
                "previous": prev_funnel["total"] if prev_funnel is not None else None,
                "delta": (cur_funnel["total"] - prev_funnel["total"])
                if prev_funnel is not None
                else None,
                "delta_pct": _pct_change(
                    cur_funnel["total"],
                    prev_funnel["total"] if prev_funnel is not None else None,
                ),
            },
            "conversions": {
                "current": cur_funnel["converted"],
                "previous": prev_funnel["converted"] if prev_funnel is not None else None,
                "conversion_rate": cur_funnel["lead_conversion_rate"],
                "previous_conversion_rate": prev_funnel["lead_conversion_rate"]
                if prev_funnel is not None
                else None,
            },
            "new_members": {
                "current": cur_members,
                "previous": prev_members,
                "delta_pct": _pct_change(cur_members or 0, prev_members)
                if cur_members is not None
                else None,
            },
            "renewals_confirmed": {"current": cur_confirmed, "previous": prev_confirmed},
            "attendance": {
                "current": cur_att,
                "previous": prev_att,
                "delta_pct": _pct_change(cur_att or 0, prev_att)
                if cur_att is not None
                else None,
            },
        }

    per_business = []
    for biz in businesses:
        per_business.append(
            {
                "business": {
                    "id": str(biz.id),
                    "slug": getattr(biz, "slug", ""),
                    "name": getattr(biz, "name", ""),
                    "business_type": getattr(biz, "business_type", ""),
                },
                "metrics": _one(biz.id),
            }
        )
    return {
        "generated_at": _utcnow(),
        "scope": scope if scope is not None else "current",
        "combined": is_combined,
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "previous_start": prev_start.isoformat() if prev_start else None,
            "previous_end": prev_end.isoformat() if prev_end else None,
        },
        "businesses": per_business,
    }


def renewals_report(
    db: Session, *, ctx: BusinessContext, scope: str | None
) -> dict:
    """Renewal buckets (7/14/30d) + overdue + completion rate per business."""
    businesses, is_combined = _resolve_scope_businesses(db, ctx=ctx, scope=scope)
    items = []
    for biz in businesses:
        today = _today_in_business_tz(getattr(biz, "timezone", None))
        buckets = analytics_repo.renewal_buckets(db, business_id=biz.id, today=today)
        items.append(
            {
                "business": {
                    "id": str(biz.id),
                    "slug": getattr(biz, "slug", ""),
                    "name": getattr(biz, "name", ""),
                    "business_type": getattr(biz, "business_type", ""),
                },
                "buckets": buckets,
            }
        )
    return {
        "generated_at": _utcnow(),
        "scope": scope if scope is not None else "current",
        "combined": is_combined,
        "businesses": items,
    }


def payments_report(
    db: Session,
    *,
    ctx: BusinessContext,
    scope: str | None,
    start: datetime | None,
    end: datetime | None,
) -> dict:
    """Payment health: collected/outstanding/failed + attention queue."""
    businesses, is_combined = _resolve_scope_businesses(db, ctx=ctx, scope=scope)
    items = []
    for biz in businesses:
        health = analytics_repo.payment_health(
            db, business_id=biz.id, start=start, end=end
        )
        items.append(
            {
                "business": {
                    "id": str(biz.id),
                    "slug": getattr(biz, "slug", ""),
                    "name": getattr(biz, "name", ""),
                    "business_type": getattr(biz, "business_type", ""),
                },
                "health": health,
            }
        )
    return {
        "generated_at": _utcnow(),
        "scope": scope if scope is not None else "current",
        "combined": is_combined,
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "businesses": items,
    }


def attendance_report(
    db: Session,
    *,
    ctx: BusinessContext,
    scope: str | None,
    start: datetime | None,
    end: datetime | None,
    inactivity_days: int = 14,
) -> dict:
    """Attendance trend + transparent decline/inactivity signals per business."""
    businesses, is_combined = _resolve_scope_businesses(db, ctx=ctx, scope=scope)
    # Window bounds are business-local calendar days (same convention as
    # attendance dating): the default trailing window ends on the latest
    # business "today" so near-midnight visits are never cut off.
    local_today = max(
        _today_in_business_tz(getattr(b, "timezone", None)) for b in businesses
    )
    local_today = max(
        _today_in_business_tz(getattr(b, "timezone", None)) for b in businesses
    )
    if end is not None:
        # Attendance is dated in business-local days while preset windows are
        # UTC-anchored: never cut off visits dated "today" in business terms.
        end_date = max(end.date(), local_today)
    else:
        end_date = local_today
    if start is not None:
        start_date = start.date()
    else:
        start_date = end_date - timedelta(days=30)
    if end_date < start_date:
        raise ValueError("date_to must not be before date_from.")
    items = []
    for biz in businesses:
        window = analytics_repo.attendance_window(
            db,
            business_id=biz.id,
            start_date=start_date,
            end_date=end_date,
            inactivity_days=max(1, min(inactivity_days, 90)),
        )
        items.append(
            {
                "business": {
                    "id": str(biz.id),
                    "slug": getattr(biz, "slug", ""),
                    "name": getattr(biz, "name", ""),
                    "business_type": getattr(biz, "business_type", ""),
                },
                "attendance": window,
            }
        )
    return {
        "generated_at": _utcnow(),
        "scope": scope if scope is not None else "current",
        "combined": is_combined,
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "businesses": items,
    }


def automation_health_report(
    db: Session, *, ctx: BusinessContext, scope: str | None
) -> dict:
    """Read-only automation/worker health per business (no engine here)."""
    businesses, is_combined = _resolve_scope_businesses(db, ctx=ctx, scope=scope)
    items = []
    for biz in businesses:
        items.append(
            {
                "business": {
                    "id": str(biz.id),
                    "slug": getattr(biz, "slug", ""),
                    "name": getattr(biz, "name", ""),
                    "business_type": getattr(biz, "business_type", ""),
                },
                "health": analytics_repo.automation_health(db, business_id=biz.id),
            }
        )
    return {
        "generated_at": _utcnow(),
        "scope": scope if scope is not None else "current",
        "combined": is_combined,
        "businesses": items,
    }


def alerts_report(
    db: Session,
    *,
    ctx: BusinessContext,
    scope: str | None,
    start: datetime | None,
    end: datetime | None,
    soon_days: int = DEFAULT_SOON_DAYS,
) -> dict:
    """Deterministic owner alerts: finance/membership/leads/automation.

    Every alert is a rule over live aggregates — no ML, no prediction.
    ``critical`` is reserved for failure spikes (>=5 failed payments or >=5
    failed automation executions in 24h); everything else is warning/info.
    Empty businesses yield zero alerts, never invented ones.
    """
    businesses, is_combined = _resolve_scope_businesses(db, ctx=ctx, scope=scope)
    now = _utcnow()
    alerts: list[dict] = []

    def _add(biz, severity, category, title, detail, count, drill):
        alerts.append(
            {
                "severity": severity,
                "business": {
                    "id": str(biz.id),
                    "slug": getattr(biz, "slug", ""),
                    "name": getattr(biz, "name", ""),
                },
                "category": category,
                "title": title,
                "detail": detail,
                "count": count,
                "observed_at": now,
                "drill": drill,
            }
        )

    for biz in businesses:
        today = _today_in_business_tz(getattr(biz, "timezone", None))
        membership = analytics_repo.membership_counts(
            db, business_id=biz.id, today=today, soon_days=soon_days
        )
        buckets = analytics_repo.renewal_buckets(db, business_id=biz.id, today=today)
        health = analytics_repo.payment_health(
            db, business_id=biz.id, start=start, end=end
        )
        exceptions = analytics_repo.lead_exceptions(db, business_id=biz.id, now=now)
        auto = analytics_repo.automation_health(db, business_id=biz.id)

        failed_n = int(health["failed_count"])
        if failed_n >= 5:
            _add(biz, "critical", "finance",
                 f"{failed_n} failed payments need recovery",
                 "Failed payments require explicit staff retry before returning to pending.",
                 failed_n, "payments")
        elif failed_n > 0:
            _add(biz, "warning", "finance",
                 f"{failed_n} failed payment{'s' if failed_n != 1 else ''}",
                 "Review the payment attention queue and retry or write off.",
                 failed_n, "payments")
        overdue_pay_n = int(health["overdue_count"])
        if overdue_pay_n > 0:
            _add(biz, "warning", "finance",
                 f"{overdue_pay_n} overdue payment{'s' if overdue_pay_n != 1 else ''} "
                 f"({health['outstanding']} outstanding)",
                 "Outstanding dues should be followed up before the next billing cycle.",
                 overdue_pay_n, "payments")
        if int(buckets["overdue"]["count"]) > 0:
            _add(biz, "warning", "membership",
                 f"{buckets['overdue']['count']} renewals overdue ({buckets['overdue']['amount']})",
                 "Overdue renewals risk lapsing into expired memberships.",
                 int(buckets["overdue"]["count"]), "renewals")
        if int(buckets["due_7d"]["count"]) > 0:
            _add(biz, "info", "membership",
                 f"{buckets['due_7d']['count']} renewals due within 7 days",
                 "Upcoming renewals worth a proactive reminder.",
                 int(buckets["due_7d"]["count"]), "renewals")
        if int(membership["expiring_soon"]) > 0:
            _add(biz, "info" if int(membership["expiring_soon"]) < 10 else "warning",
                 "membership",
                 f"{membership['expiring_soon']} memberships expiring within {soon_days} days",
                 "Expiring memberships feed the renewal pipeline.",
                 int(membership["expiring_soon"]), "members")
        if int(membership["expired"]) > 0:
            _add(biz, "info", "membership",
                 f"{membership['expired']} expired memberships on record",
                 "Expired memberships are win-back candidates, not active capacity.",
                 int(membership["expired"]), "members")
        stale_n = int(exceptions["stale_leads"]["count"])
        if stale_n > 0:
            _add(biz, "info", "leads",
                 f"{stale_n} stale lead{'s' if stale_n != 1 else ''} (>72h in new/contacted)",
                 "Stale leads are losing attention; assign or nurture them.",
                 stale_n, "leads")
        uncontacted_n = int(exceptions["uncontacted_leads"]["count"])
        if uncontacted_n > 0:
            _add(biz, "warning", "leads",
                 f"{uncontacted_n} never-contacted lead{'s' if uncontacted_n != 1 else ''}",
                 "New leads with no contact after 24h need a first touch.",
                 uncontacted_n, "leads")
        overdue_fu = int(exceptions["followup_overdue"]["count"])
        if overdue_fu > 0:
            _add(biz, "warning", "leads",
                 f"{overdue_fu} lead follow-up{'s' if overdue_fu != 1 else ''} overdue",
                 "Promised follow-ups past their due time.",
                 overdue_fu, "leads")
        failed_auto = int(auto["failed_24h"])
        if failed_auto >= 5:
            _add(biz, "critical", "automation",
                 f"{failed_auto} automation executions failed in 24h",
                 "Repeated automation failures need operator review of rules and inputs.",
                 failed_auto, "automation")
        elif failed_auto > 0:
            _add(biz, "warning", "automation",
                 f"{failed_auto} automation execution{'s' if failed_auto != 1 else ''} failed in 24h",
                 "Check the failed executions before retry budgets exhaust.",
                 failed_auto, "automation")

    rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (rank.get(a["severity"], 3), -a["count"]))
    return {
        "generated_at": now,
        "scope": scope if scope is not None else "current",
        "combined": is_combined,
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "rules": {
            "critical_when": "failed payments >= 5 OR failed automation executions >= 5 in 24h",
            "stale_lead_hours": 72,
            "uncontacted_hours": 24,
        },
        "total": len(alerts),
        "alerts": alerts[:100],
    }


def combined_overview(
    db: Session,
    *,
    ctx: BusinessContext,
    scope: str | None,
    start: datetime | None,
    end: datetime | None,
    soon_days: int = DEFAULT_SOON_DAYS,
) -> dict:
    """Prime + Nest (+ future) combined command center (explicitly gated)."""
    businesses = _resolve_combined_businesses(db, ctx=ctx, scope=scope)
    ids = [b.id for b in businesses]
    rollup = analytics_repo.combined_totals(db, business_ids=ids, start=start, end=end)
    per_business: list[dict] = []
    slug_by_id = {str(b.id): b for b in businesses}
    portfolio = {
        "active_memberships": 0,
        "active_members": 0,
        "bookings": 0,
        "attendance_today": 0,
        "renewals_due_soon": 0,
        "renewals_overdue": 0,
        "outstanding": _Money("0.00"),
    }
    for entry in rollup["businesses"]:
        biz = slug_by_id.get(entry["business_id"])
        today = _today_in_business_tz(getattr(biz, "timezone", None) if biz else None)
        bid = uuid.UUID(entry["business_id"])
        membership = analytics_repo.membership_counts(
            db, business_id=bid, today=today, soon_days=soon_days
        )
        attendance = analytics_repo.attendance_summary(db, business_id=bid, day=today)
        renewals = analytics_repo.renewal_pipeline(db, business_id=bid, today=today)
        bookings = analytics_repo.booking_summary(
            db, business_id=bid, start=start, end=end
        )
        rev = entry["revenue"]
        portfolio["active_memberships"] += int(membership.get("active_memberships", 0))
        portfolio["active_members"] += int(membership.get("active_members", 0))
        portfolio["bookings"] += int(bookings.get("total", 0))
        portfolio["attendance_today"] += int(attendance.get("total", 0))
        portfolio["renewals_due_soon"] += int(renewals.get("due_soon", 0))
        portfolio["renewals_overdue"] += int(renewals.get("overdue", 0))
        portfolio["outstanding"] += _Money(str(rev.get("pending", "0"))) + _Money(
            str(rev.get("overdue", "0"))
        )
        item = {
            "business": {
                "id": entry["business_id"],
                "slug": getattr(biz, "slug", ""),
                "name": getattr(biz, "name", ""),
                "business_type": getattr(biz, "business_type", ""),
            },
            "revenue": entry["revenue"],
            "leads": entry["leads"],
            "membership": membership,
            "attendance_today": attendance,
            "renewals": renewals,
        }
        from app.services import capabilities as caps

        if caps.get_capabilities(
            db,
            business_id=bid,
            business_type=str(getattr(biz, "business_type", "other") or "other"),
        ).get("seat_management"):
            item["seats"] = seats_repo.availability_summary(db, business_id=bid)
        per_business.append(item)
    totals = dict(rollup["totals"])
    totals["active_memberships"] = portfolio["active_memberships"]
    totals["active_members"] = portfolio["active_members"]
    totals["bookings"] = portfolio["bookings"]
    totals["attendance_today"] = portfolio["attendance_today"]
    totals["renewals_due_soon"] = portfolio["renewals_due_soon"]
    totals["renewals_overdue"] = portfolio["renewals_overdue"]
    totals["outstanding"] = str(portfolio["outstanding"])
    return {
        "generated_at": _utcnow(),
        "scope": (scope or "all"),
        "totals": totals,
        "businesses": per_business,
    }
