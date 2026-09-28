"""Notification endpoints (own + business scoped — never another user's)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.notifications import (
    NotificationOut,
    PreferenceIn,
    PreferenceOut,
    UnreadCountOut,
)
from app.services import notifications as notif_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationOut], summary="My notifications")
def list_mine(
    unread_only: bool = Query(default=False),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("notifications.read")),
) -> dict:
    assert ctx.business is not None and ctx.user is not None
    items, total = notif_service.list_mine(
        db,
        business_id=ctx.business.id,
        user_id=ctx.user.id,
        unread_only=unread_only,
        limit=paging["limit"],
        offset=paging["offset"],
    )
    return {
        "items": [NotificationOut.model_validate(i) for i in items],
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("/unread-count", response_model=UnreadCountOut, summary="Unread count")
def unread_count(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("notifications.read")),
) -> UnreadCountOut:
    assert ctx.business is not None and ctx.user is not None
    count = notif_service.unread_count(
        db, business_id=ctx.business.id, user_id=ctx.user.id
    )
    return UnreadCountOut(unread=count)


@router.post(
    "/{notification_id}/read", response_model=NotificationOut, summary="Mark read"
)
def mark_read(
    notification_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("notifications.read")),
) -> NotificationOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        notification = notif_service.mark_read(
            db,
            business_id=ctx.business.id,
            user_id=ctx.user.id,
            notification_id=notification_id,
        )
        db.commit()
        db.refresh(notification)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return NotificationOut.model_validate(notification)


@router.post("/read-all", summary="Mark all my notifications read")
def mark_all_read(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("notifications.read")),
) -> dict:
    assert ctx.business is not None and ctx.user is not None
    marked = notif_service.mark_all_read(
        db, business_id=ctx.business.id, user_id=ctx.user.id
    )
    db.commit()
    return {"marked": marked}


@router.put(
    "/preferences/{notification_type}",
    response_model=PreferenceOut,
    summary="Set my notification preference",
)
def set_preference(
    notification_type: str,
    payload: PreferenceIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("notifications.update")
    ),
) -> PreferenceOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        pref = notif_service.set_preference(
            db,
            business_id=ctx.business.id,
            user_id=ctx.user.id,
            notification_type=notification_type,
            enabled=payload.enabled,
        )
        db.commit()
        db.refresh(pref)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="notification.preference_changed",
        actor_user_id=ctx.user.id,
        entity_type="notification_preference",
        entity_id=None,
        request_id=request_id(request),
        meta={"type": notification_type, "enabled": payload.enabled},
    )
    return PreferenceOut.model_validate(pref)
