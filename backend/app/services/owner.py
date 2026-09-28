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
    for entry in rollup["businesses"]:
        biz = slug_by_id.get(entry["business_id"])
        today = _today_in_business_tz(getattr(biz, "timezone", None) if biz else None)
        bid = uuid.UUID(entry["business_id"])
        membership = analytics_repo.membership_counts(
            db, business_id=bid, today=today, soon_days=soon_days
        )
        attendance = analytics_repo.attendance_summary(db, business_id=bid, day=today)
        renewals = analytics_repo.renewal_pipeline(db, business_id=bid, today=today)
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
    return {
        "generated_at": _utcnow(),
        "scope": (scope or "all"),
        "totals": rollup["totals"],
        "businesses": per_business,
    }
