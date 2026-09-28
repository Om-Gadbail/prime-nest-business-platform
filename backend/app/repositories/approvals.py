"""Approval + domain-event repositories: SQL only, scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.operations import Approval, DomainEvent
from app.repositories.base import apply_business_scope, get_scoped
from app.repositories.pagination import apply_sort, clamp_page

SORTABLE_APPROVALS = {
    "created_at": Approval.created_at,
    "status": Approval.status,
}

SORTABLE_EVENTS = {
    "created_at": DomainEvent.created_at,
}


def create_approval(db: Session, *, business_id: uuid.UUID, fields: dict) -> Approval:
    approval = Approval(business_id=business_id, **fields)
    db.add(approval)
    db.flush()
    return approval


def get_approval(
    db: Session, *, approval_id: object, business_id: uuid.UUID
) -> Approval | None:
    return get_scoped(db, Approval, approval_id, business_id)


def list_approvals(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    entity_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Approval], int]:
    stmt = apply_business_scope(select(Approval), Approval, business_id)
    if status:
        stmt = stmt.where(Approval.status == status)
    if entity_type:
        stmt = stmt.where(Approval.entity_type == entity_type)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_APPROVALS,
        default=Approval.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def record_event(
    db: Session,
    *,
    business_id: uuid.UUID,
    event_type: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    payload: dict | None = None,
    created_at: datetime | None = None,
) -> DomainEvent:
    from datetime import timezone as _tz

    event = DomainEvent(
        business_id=business_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        payload=dict(payload or {}),
        created_at=created_at or datetime.now(_tz.utc),
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session,
    *,
    business_id: uuid.UUID,
    event_type: str | None = None,
    entity_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[DomainEvent], int]:
    stmt = apply_business_scope(select(DomainEvent), DomainEvent, business_id)
    if event_type:
        stmt = stmt.where(DomainEvent.event_type == event_type)
    if entity_type:
        stmt = stmt.where(DomainEvent.entity_type == entity_type)
    stmt = stmt.order_by(DomainEvent.created_at.desc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total
