"""Domain-event read endpoints (business-scoped, RBAC-enforced).

Events are append-only hooks emitted by operational services. This read
surface powers the member/customer 360 timeline and owner diagnostics.
Requires ``audit.read`` (same audience as the audit feed).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.repositories import approvals as approvals_repo
from app.schemas.common import Page, list_params
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/domain-events", tags=["domain-events"])


class DomainEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    event_type: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    payload: dict = {}
    created_at: datetime


@router.get("", response_model=Page[DomainEventOut], summary="List domain events")
def list_domain_events(
    event_type: str | None = Query(default=None, max_length=64),
    entity_type: str | None = Query(default=None, max_length=48),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("audit.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = approvals_repo.list_events(
            db,
            business_id=ctx.business.id,
            event_type=event_type,
            entity_type=entity_type,
            limit=paging["limit"],
            offset=paging["offset"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "items": [DomainEventOut.model_validate(i) for i in items],
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }
