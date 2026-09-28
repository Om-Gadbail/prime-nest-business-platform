"""Task endpoints (staff, business-scoped, RBAC-enforced)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.tasks import (
    TaskAssignIn,
    TaskCreate,
    TaskOut,
    TaskStatusIn,
    TaskUpdate,
)
from app.services import tasks as tasks_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("", response_model=Page[TaskOut], summary="List tasks")
def list_tasks(
    status: str | None = Query(default=None, max_length=32),
    priority: str | None = Query(default=None, max_length=16),
    assigned_to_user_id: str | None = Query(default=None, max_length=64),
    created_by_user_id: str | None = Query(default=None, max_length=64),
    overdue_only: bool = Query(default=False),
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    related_entity_type: str | None = Query(default=None, max_length=48),
    search: str | None = Query(default=None, max_length=64),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("tasks.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = tasks_service.list_tasks(
            db,
            business_id=ctx.business.id,
            status=status,
            priority=priority,
            assigned_to_user_id=assigned_to_user_id,
            created_by_user_id=created_by_user_id,
            overdue_only=overdue_only,
            due_from=due_from,
            due_to=due_to,
            related_entity_type=related_entity_type,
            search=search,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([TaskOut.model_validate(i) for i in items], total, paging)


@router.post("", response_model=TaskOut, summary="Create task", status_code=201)
def create_task(
    payload: TaskCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("tasks.create")),
) -> TaskOut:
    assert ctx.business is not None and ctx.user is not None
    data = payload.model_dump(exclude_unset=True)
    try:
        task = tasks_service.create_task(
            db,
            business_id=ctx.business.id,
            title=data.get("title", ""),
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            assigned_to_user_id=data.get("assigned_to_user_id"),
            created_by_user_id=ctx.user.id,
            due_at=data.get("due_at"),
            related_entity_type=data.get("related_entity_type"),
            related_entity_id=data.get("related_entity_id"),
        )
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="task.created",
        actor_user_id=ctx.user.id,
        entity_type="task",
        entity_id=task.id,
        request_id=_rid(request),
    )
    return TaskOut.model_validate(task)


@router.get("/{task_id}", response_model=TaskOut, summary="Get task")
def get_task(
    task_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("tasks.read")),
) -> TaskOut:
    assert ctx.business is not None
    try:
        task = tasks_service.get_task(db, business_id=ctx.business.id, task_id=task_id)
    except Exception as exc:
        raise map_service_error(exc) from exc
    return TaskOut.model_validate(task)


@router.patch("/{task_id}", response_model=TaskOut, summary="Update task")
def update_task(
    task_id: str,
    payload: TaskUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("tasks.update")),
) -> TaskOut:
    assert ctx.business is not None and ctx.user is not None
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    try:
        task = tasks_service.update_task(
            db, business_id=ctx.business.id, task_id=task_id, fields=fields
        )
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="task.updated",
        actor_user_id=ctx.user.id,
        entity_type="task",
        entity_id=task.id,
        request_id=_rid(request),
    )
    return TaskOut.model_validate(task)


@router.post("/{task_id}/assign", response_model=TaskOut, summary="Assign task")
def assign_task(
    task_id: str,
    payload: TaskAssignIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("tasks.update")),
) -> TaskOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        task = tasks_service.update_task(
            db,
            business_id=ctx.business.id,
            task_id=task_id,
            fields={"assigned_to_user_id": payload.assigned_to_user_id},
        )
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="task.assigned",
        actor_user_id=ctx.user.id,
        entity_type="task",
        entity_id=task.id,
        request_id=_rid(request),
        meta={"assigned_to": str(payload.assigned_to_user_id)},
    )
    return TaskOut.model_validate(task)


@router.post("/{task_id}/status", response_model=TaskOut, summary="Change task status")
def change_status(
    task_id: str,
    payload: TaskStatusIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("tasks.update")),
) -> TaskOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        task = tasks_service.transition(
            db,
            business_id=ctx.business.id,
            task_id=task_id,
            to_status=payload.status,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    action = (
        "task.completed"
        if str(task.status) == "completed"
        else ("task.reopened" if str(task.status) == "open" else "task.updated")
    )
    record_audit(
        db,
        business_id=ctx.business.id,
        action=action,
        actor_user_id=ctx.user.id,
        entity_type="task",
        entity_id=task.id,
        request_id=_rid(request),
        meta={"status": str(task.status)},
    )
    return TaskOut.model_validate(task)


def _rid(request: object) -> str:
    try:
        return request_id(request)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return "-"
