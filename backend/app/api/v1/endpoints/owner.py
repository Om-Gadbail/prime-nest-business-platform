"""Owner command-center endpoints (Block 5, Prompt 6).

Single-business views need ``owner.dashboard.read``. Any explicit ``scope``
(``all`` or a slug) additionally needs ``owner.combined.read`` AND an
OWNER/ADMIN role (enforced in the service — combined access is an
explicitly authorized capability, audited per request).
Every figure is a live DB aggregate; empty businesses return zeros.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.owner import (
    CombinedOverview,
    OwnerAlertsReport,
    OwnerAttendanceReport,
    OwnerAutomationReport,
    OwnerBusinessOverview,
    OwnerGrowthReport,
    OwnerLeadsReport,
    OwnerPaymentsReport,
    OwnerRenewalsReport,
    OwnerRevenueReport,
)
from app.services import owner as owner_service
from app.services.authorization import AuthenticatedContext
from app.services.business_context import BusinessResolver

router = APIRouter(prefix="/owner", tags=["owner"])


def _staff_ctx(ctx: AuthenticatedContext, request: Request):  # type: ignore[no-untyped-def]
    return BusinessResolver.for_staff(ctx, request_id=request_id(request))


def _audit_scope(
    db: Session,
    bctx,  # type: ignore[no-untyped-def]
    request: Request,
    entity: str,
    scope: str | None,
    snapshot: dict,
) -> None:
    """Audit combined owner access (slugs only — no secrets or PII)."""
    if scope is None:
        return
    record_audit(
        db,
        business_id=bctx.business_id,
        action="report.generated",
        actor_user_id=bctx.user_id,
        entity_type=entity,
        result="success",
        request_id=request_id(request),
        meta={
            "scope": scope,
            "businesses": sorted(
                b["business"]["slug"] for b in snapshot.get("businesses", [])
            ),
        },
    )


@router.get(
    "/overview",
    response_model=OwnerBusinessOverview,
    summary="Owner business overview (scope-aware)",
)
def overview(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    soon_days: int = Query(default=7, ge=1, le=90),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerBusinessOverview:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = owner_service._parse_window(date_from, date_to, preset)
        scoped = owner_service._single_scope_context(db, ctx=bctx, scope=scope)
        snapshot = owner_service.business_overview(
            db, ctx=scoped, soon_days=soon_days, start=start, end=end
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_overview", scope, {"businesses": []})
    return OwnerBusinessOverview(**snapshot)


@router.get(
    "/revenue",
    response_model=OwnerRevenueReport,
    summary="Owner revenue report (scope-aware)",
)
def revenue(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerRevenueReport:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = owner_service._parse_window(date_from, date_to, preset)
        scoped = owner_service._single_scope_context(db, ctx=bctx, scope=scope)
        report = owner_service.revenue_report(db, ctx=scoped, start=start, end=end)
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_revenue", scope, {"businesses": []})
    return OwnerRevenueReport(**report)


@router.get(
    "/leads",
    response_model=OwnerLeadsReport,
    summary="Owner leads/conversion report (scope-aware)",
)
def leads(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerLeadsReport:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = owner_service._parse_window(date_from, date_to, preset)
        scoped = owner_service._single_scope_context(db, ctx=bctx, scope=scope)
        report = owner_service.leads_report(db, ctx=scoped, start=start, end=end)
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_leads", scope, {"businesses": []})
    return OwnerLeadsReport(**report)


@router.get(
    "/combined",
    response_model=CombinedOverview,
    summary="Combined Prime+Nest command center (OWNER/ADMIN)",
)
def combined(
    request: Request,
    scope: str = Query(default="all", max_length=64),
    soon_days: int = Query(default=7, ge=1, le=90),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("owner.combined.read")),
) -> CombinedOverview:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = owner_service._parse_window(date_from, date_to, preset)
        snapshot = owner_service.combined_overview(
            db,
            ctx=bctx,
            scope=scope,
            start=start,
            end=end,
            soon_days=soon_days,
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    # Owner cross-business access is especially auditable: record the grant
    # set actually aggregated (slugs only — no tokens, secrets, or PII).
    record_audit(
        db,
        business_id=bctx.business_id,
        action="report.generated",
        actor_user_id=bctx.user_id,
        entity_type="owner_combined",
        result="success",
        request_id=request_id(request),
        meta={
            "scope": (scope or "all"),
            "businesses": sorted(
                b["business"]["slug"] for b in snapshot.get("businesses", [])
            ),
        },
    )
    return CombinedOverview(**snapshot)


def _window_params(
    date_from: str | None, date_to: str | None, preset: str | None
) -> tuple:  # type: ignore[no-untyped-def]
    return owner_service._parse_window(date_from, date_to, preset)


@router.get(
    "/alerts",
    response_model=OwnerAlertsReport,
    summary="Owner alerts/exceptions (rule-based, scope-aware)",
)
def alerts(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    soon_days: int = Query(default=7, ge=1, le=90),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerAlertsReport:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = _window_params(date_from, date_to, preset)
        snapshot = owner_service.alerts_report(
            db, ctx=bctx, scope=scope, start=start, end=end, soon_days=soon_days
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_alerts", scope, snapshot)
    return OwnerAlertsReport(**snapshot)


@router.get(
    "/growth",
    response_model=OwnerGrowthReport,
    summary="Owner growth: current vs previous period (scope-aware)",
)
def growth(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerGrowthReport:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = _window_params(date_from, date_to, preset)
        snapshot = owner_service.growth_report(
            db, ctx=bctx, scope=scope, start=start, end=end
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_growth", scope, snapshot)
    return OwnerGrowthReport(**snapshot)


@router.get(
    "/renewals",
    response_model=OwnerRenewalsReport,
    summary="Owner renewal buckets 7/14/30d + overdue (scope-aware)",
)
def renewals(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerRenewalsReport:
    bctx = _staff_ctx(ctx, request)
    try:
        snapshot = owner_service.renewals_report(db, ctx=bctx, scope=scope)
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_renewals", scope, snapshot)
    return OwnerRenewalsReport(**snapshot)


@router.get(
    "/payments",
    response_model=OwnerPaymentsReport,
    summary="Owner payment health + attention queue (scope-aware)",
)
def payments(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerPaymentsReport:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = _window_params(date_from, date_to, preset)
        snapshot = owner_service.payments_report(
            db, ctx=bctx, scope=scope, start=start, end=end
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_payments", scope, snapshot)
    return OwnerPaymentsReport(**snapshot)


@router.get(
    "/attendance",
    response_model=OwnerAttendanceReport,
    summary="Owner attendance trend + decline signals (scope-aware)",
)
def attendance(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    inactivity_days: int = Query(default=14, ge=1, le=90),
    date_from: str | None = Query(default=None, max_length=32),
    date_to: str | None = Query(default=None, max_length=32),
    preset: str | None = Query(default="30d", max_length=16),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerAttendanceReport:
    bctx = _staff_ctx(ctx, request)
    try:
        start, end = _window_params(date_from, date_to, preset)
        snapshot = owner_service.attendance_report(
            db, ctx=bctx, scope=scope, start=start, end=end,
            inactivity_days=inactivity_days,
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_attendance", scope, snapshot)
    return OwnerAttendanceReport(**snapshot)


@router.get(
    "/automation-health",
    response_model=OwnerAutomationReport,
    summary="Owner automation/worker health (read-only, scope-aware)",
)
def automation_health(
    request: Request,
    scope: str | None = Query(default=None, max_length=64),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("owner.dashboard.read")
    ),
) -> OwnerAutomationReport:
    bctx = _staff_ctx(ctx, request)
    try:
        snapshot = owner_service.automation_health_report(db, ctx=bctx, scope=scope)
    except Exception as exc:
        raise map_service_error(exc) from exc
    _audit_scope(db, bctx, request, "owner_automation_health", scope, snapshot)
    return OwnerAutomationReport(**snapshot)
