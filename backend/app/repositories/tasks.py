"""Task repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.task import Task
from app.repositories.base import apply_business_scope
from app.repositories.pagination import apply_sort, clamp_page

SORTABLE_TASKS = {
    "created_at": Task.created_at,
    "updated_at": Task.updated_at,
    "due_at": Task.due_at,
    "priority": Task.priority,
    "status": Task.status,
    "title": Task.title,
}


def create(db: Session, *, business_id: uuid.UUID, fields: dict) -> Task:
    task = Task(business_id=business_id, **fields)
    db.add(task)
    db.flush()
    return task


def get_scoped(db: Session, *, task_id: object, business_id: uuid.UUID) -> Task | None:
    from app.repositories.base import get_scoped as _get

    return _get(db, Task, task_id, business_id)


def set_fields(task: Task, fields: dict) -> Task:
    for key, value in fields.items():
        setattr(task, key, value)
    return task


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    priority: str | None = None,
    assigned_to_user_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID | None = None,
    overdue_only: bool = False,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    related_entity_type: str | None = None,
    search: str | None = None,
    now: datetime | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Task], int]:
    limit, offset = clamp_page(limit, offset)
    stmt = apply_business_scope(select(Task), Task, business_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if assigned_to_user_id is not None:
        stmt = stmt.where(Task.assigned_to_user_id == assigned_to_user_id)
    if created_by_user_id is not None:
        stmt = stmt.where(Task.created_by_user_id == created_by_user_id)
    if related_entity_type:
        stmt = stmt.where(Task.related_entity_type == related_entity_type)
    if due_from is not None:
        stmt = stmt.where(Task.due_at >= due_from)
    if due_to is not None:
        stmt = stmt.where(Task.due_at <= due_to)
    if overdue_only:
        ref = now
        stmt = stmt.where(
            Task.due_at.is_not(None),
            Task.due_at < ref,  # type: ignore[arg-type]
            Task.status.not_in(["completed", "cancelled"]),
        )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Task.title.ilike(like), Task.description.ilike(like)))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_TASKS,
        default=Task.created_at,
    )
    items = list(db.execute(stmt.offset(offset).limit(limit)).scalars().all())
    return items, total


def count_open_for_assignee(
    db: Session, *, business_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    stmt = (
        select(func.count())
        .select_from(Task)
        .where(
            Task.business_id == business_id,
            Task.assigned_to_user_id == user_id,
            Task.status.not_in(["completed", "cancelled"]),
        )
    )
    return int(db.execute(stmt).scalar() or 0)


def count_overdue(
    db: Session,
    *,
    business_id: uuid.UUID,
    now: datetime,
    assigned_to_user_id: uuid.UUID | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(Task)
        .where(
            Task.business_id == business_id,
            Task.due_at.is_not(None),
            Task.due_at < now,
            Task.status.not_in(["completed", "cancelled"]),
        )
    )
    if assigned_to_user_id is not None:
        stmt = stmt.where(Task.assigned_to_user_id == assigned_to_user_id)
    return int(db.execute(stmt).scalar() or 0)
