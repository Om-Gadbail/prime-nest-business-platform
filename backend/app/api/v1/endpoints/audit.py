"""Audit-event endpoints (read-only, business-scoped, RBAC-enforced).

No create/update/delete contracts exist: the audit log is append-only.
Requires ``audit.read`` (OWNER/ADMIN/MANAGER/STAFF; VIEWER is denied —
unrestricted audit access is not read-only dashboard data).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.schemas.audit import AuditEventOut
from app.schemas.common import Page, list_params
from app.services import audit as audit_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=Page[AuditEventOut], summary="List audit events")
def list_events(
    action: str | None = Query(default=None, max_length=64),
    actor_user_id: str | None = Query(default=None, max_length=64),
    entity_type: str | None = Query(default=None, max_length=48),
    entity_id: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=16),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    search: str | None = Query(default=None, max_length=64),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("audit.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = audit_service.list_events(
            db,
            business_id=ctx.business.id,
            action=action,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            result=result,
            created_from=created_from,
            created_to=created_to,
            search=search,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "items": [AuditEventOut.model_validate(i) for i in items],
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("/{event_id}", response_model=AuditEventOut, summary="Get audit event")
def get_event(
    event_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("audit.read")),
) -> AuditEventOut:
    assert ctx.business is not None
    try:
        event = audit_service.get_event(
            db, business_id=ctx.business.id, event_id=event_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return AuditEventOut.model_validate(event)
