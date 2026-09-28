"""Owner command-center endpoints (Block 5, steps 22-26).

Single-business views need ``owner.dashboard.read``; the COMBINED view
needs ``owner.combined.read`` AND an OWNER/ADMIN role (enforced in the
service — combined access is an explicitly authorized capability).
Every figure is a live DB aggregate; empty businesses return zeros.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.owner import (
    CombinedOverview,
    OwnerBusinessOverview,
    OwnerLeadsReport,
    OwnerRevenueReport,
)
from app.services import owner as owner_service
from app.services.authorization import AuthenticatedContext
from app.services.business_context import BusinessResolver

router = APIRouter(prefix="/owner", tags=["owner"])


def _staff_ctx(ctx: AuthenticatedContext, request: Request):  # type: ignore[no-untyped-def]
    return BusinessResolver.for_staff(ctx, request_id=request_id(request))


@router.get(
    "/overview",
    response_model=OwnerBusinessOverview,
    summary="Owner business overview",
)
def overview(
    request: Request,
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
        snapshot = owner_service.business_overview(
            db, ctx=bctx, soon_days=soon_days, start=start, end=end
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return OwnerBusinessOverview(**snapshot)


@router.get(
    "/revenue", response_model=OwnerRevenueReport, summary="Owner revenue report"
)
def revenue(
    request: Request,
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
        report = owner_service.revenue_report(db, ctx=bctx, start=start, end=end)
    except Exception as exc:
        raise map_service_error(exc) from exc
    return OwnerRevenueReport(**report)


@router.get(
    "/leads", response_model=OwnerLeadsReport, summary="Owner leads/conversion report"
)
def leads(
    request: Request,
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
        report = owner_service.leads_report(db, ctx=bctx, start=start, end=end)
    except Exception as exc:
        raise map_service_error(exc) from exc
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
