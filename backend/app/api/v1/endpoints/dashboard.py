"""Dashboard endpoints (business-scoped operational snapshots).

One reusable surface for the Prime and Nest staff dashboards (and future
businesses): overview aggregates, status summaries, and the activity
feed. All counts are server-side SQL aggregates — the frontend never
downloads whole tables to compute numbers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.schemas.audit import AuditEventOut
from app.schemas.common import Page, list_params
from app.schemas.ops import (
    DashboardOverviewOut,
    StatusSummaryOut,
)
from app.services import dashboard as dashboard_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/overview", response_model=DashboardOverviewOut, summary="Dashboard overview"
)
def overview(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("dashboard.read")),
) -> DashboardOverviewOut:
    assert ctx.business is not None and ctx.user is not None
    snapshot = dashboard_service.overview(
        db, business_id=ctx.business.id, user_id=ctx.user.id
    )
    return DashboardOverviewOut(**snapshot)


@router.get(
    "/leads/summary", response_model=StatusSummaryOut, summary="Lead status summary"
)
def leads_summary(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.read")),
) -> StatusSummaryOut:
    assert ctx.business is not None
    return StatusSummaryOut(
        **dashboard_service.leads_summary(db, business_id=ctx.business.id)
    )


@router.get(
    "/bookings/summary",
    response_model=StatusSummaryOut,
    summary="Booking status summary",
)
def bookings_summary(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.read")),
) -> StatusSummaryOut:
    assert ctx.business is not None
    return StatusSummaryOut(
        **dashboard_service.bookings_summary(db, business_id=ctx.business.id)
    )


@router.get("/activity", response_model=Page[AuditEventOut], summary="Activity feed")
def activity(
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("audit.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = dashboard_service.activity_feed(
            db,
            business_id=ctx.business.id,
            limit=paging["limit"],
            offset=paging["offset"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "items": [AuditEventOut.model_validate(i) for i in items],
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("/tasks", summary="My task workload")
def my_tasks(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("tasks.read")),
) -> dict:
    """Workload counters for the dashboard header/task center."""
    assert ctx.business is not None and ctx.user is not None
    from datetime import datetime, timezone

    from app.repositories import tasks as tasks_repo

    now = datetime.now(timezone.utc)
    return {
        "mine_open": tasks_repo.count_open_for_assignee(
            db, business_id=ctx.business.id, user_id=ctx.user.id
        ),
        "mine_overdue": tasks_repo.count_overdue(
            db,
            business_id=ctx.business.id,
            now=now,
            assigned_to_user_id=ctx.user.id,
        ),
        "unread_notifications": dashboard_service.overview(
            db, business_id=ctx.business.id, user_id=ctx.user.id
        )["notifications"]["unread"],
    }


@router.get("/notifications", summary="Notification center snapshot")
def notifications_snapshot(
    unread_only: bool = Query(default=True),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("notifications.read")),
) -> dict:
    from app.services import notifications as notif_service

    assert ctx.business is not None and ctx.user is not None
    items, total = notif_service.list_mine(
        db,
        business_id=ctx.business.id,
        user_id=ctx.user.id,
        unread_only=unread_only,
        limit=20,
        offset=0,
    )
    from app.schemas.notifications import NotificationOut

    return {
        "unread": notif_service.unread_count(
            db, business_id=ctx.business.id, user_id=ctx.user.id
        ),
        "items": [NotificationOut.model_validate(i) for i in items],
        "total": total,
    }
