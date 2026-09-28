"""Audit-event repository: append-only reads/writes (Block 4).

No UPDATE/DELETE helpers exist by design — audit rows are immutable
through application code. Retention/purge (if ever needed) belongs to
ops tooling with explicit approval, not to request handlers.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.repositories.pagination import apply_sort, clamp_page


def create(
    db: Session,
    *,
    business_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    result: str,
    request_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    meta: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        business_id=business_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        result=result,
        request_id=request_id or "-",
        ip_address=ip_address,
        user_agent=(user_agent or "")[:300] or None,
        meta=dict(meta or {}),
    )
    db.add(event)
    db.flush()
    return event


_SORTABLE = None  # resolved lazily (model columns) in list_scoped


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    result: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[AuditEvent], int]:
    limit, offset = clamp_page(limit, offset)
    stmt = select(AuditEvent).where(AuditEvent.business_id == business_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if actor_user_id is not None:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if result:
        stmt = stmt.where(AuditEvent.result == result)
    if created_from is not None:
        stmt = stmt.where(AuditEvent.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(AuditEvent.created_at <= created_to)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (AuditEvent.action.like(like))
            | (AuditEvent.request_id.like(like))
            | (AuditEvent.entity_type.like(like))
        )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    allowed = {
        "created_at": AuditEvent.created_at,
        "action": AuditEvent.action,
        "result": AuditEvent.result,
    }
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=allowed,
        default=AuditEvent.created_at,
    )
    items = list(db.execute(stmt.offset(offset).limit(limit)).scalars().all())
    return items, total


def get_scoped(
    db: Session, *, event_id: object, business_id: uuid.UUID
) -> AuditEvent | None:
    try:
        wanted = (
            event_id if isinstance(event_id, uuid.UUID) else uuid.UUID(str(event_id))
        )
    except (ValueError, AttributeError, TypeError):
        return None
    stmt = select(AuditEvent).where(
        AuditEvent.id == wanted, AuditEvent.business_id == business_id
    )
    return db.execute(stmt).scalars().first()
