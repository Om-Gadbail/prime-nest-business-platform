"""Task service: business-scoped staff work items (Block 4, step 20).

Lifecycle: open -> in_progress -> completed | cancelled; completed/
cancelled reopen explicitly to open. Assignment notifies the assignee
(in-app; preference-aware; deduped per task+assignee).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ops_vocab import (
    TASK_PRIORITIES,
    TASK_RELATED_TYPES,
    TASK_STATUSES,
    TASK_TRANSITIONS,
)
from app.repositories import tasks as tasks_repo
from app.services.crm import require_active_member, validate_search
from app.services.errors import ConflictError, NotFoundError
from app.services.notifications import notify_task_assigned


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: object, *, max_chars: int) -> str:
    return str(value or "").strip()[:max_chars]


def _validate_enum(
    value: object, *, allowed: frozenset[str], field: str, default: str
) -> str:
    text = str(value or default).strip().lower()
    if text not in allowed:
        raise ValueError(f"Unknown {field}: {value!r}. Allowed: {sorted(allowed)}.")
    return text


def _validate_related(
    db: Session,
    *,
    business_id: uuid.UUID,
    related_entity_type: str | None,
    related_entity_id: object | None,
) -> tuple[str | None, uuid.UUID | None]:
    if not related_entity_type and not related_entity_id:
        return None, None
    if not related_entity_type or not related_entity_id:
        raise ValueError(
            "related_entity_type and related_entity_id must be set together."
        )
    rtype = _validate_enum(
        related_entity_type,
        allowed=TASK_RELATED_TYPES,
        field="related entity type",
        default="",
    )
    from app.repositories.pagination import parse_uuid

    rid = parse_uuid(related_entity_id)
    if rid is None:
        raise ValueError("related_entity_id must be a valid UUID.")
    exists: object | None = None
    if rtype == "lead":
        from app.repositories import leads as leads_repo

        exists = leads_repo.get_scoped(db, lead_id=rid, business_id=business_id)
    elif rtype == "booking":
        from app.repositories import bookings as bookings_repo

        exists = bookings_repo.get_scoped(db, booking_id=rid, business_id=business_id)
    elif rtype == "contact":
        from app.repositories import contacts as contacts_repo

        exists = contacts_repo.get_scoped(db, contact_id=rid, business_id=business_id)
    elif rtype == "customer":
        from app.repositories import customers as customers_repo

        exists = customers_repo.get_scoped(db, customer_id=rid, business_id=business_id)
    elif rtype == "member":
        from app.repositories import members as members_repo

        exists = members_repo.get(db, member_id=rid, business_id=business_id)
    elif rtype == "membership":
        from app.repositories import op_memberships as op_membership_repo

        exists = op_membership_repo.get_membership(
            db, membership_id=rid, business_id=business_id
        )
    elif rtype == "payment":
        from app.repositories import payments as payments_repo

        exists = payments_repo.get(db, payment_id=rid, business_id=business_id)
    elif rtype == "seat":
        from app.repositories import seats as seats_repo

        exists = seats_repo.get_seat(db, seat_id=rid, business_id=business_id)
    elif rtype == "seat_allocation":
        from app.repositories import seats as seats_repo

        exists = seats_repo.get_allocation(
            db, allocation_id=rid, business_id=business_id
        )
    elif rtype == "renewal":
        from app.repositories import op_memberships as op_membership_repo

        exists = op_membership_repo.get_renewal(
            db, renewal_id=rid, business_id=business_id
        )
    elif rtype == "approval":
        from app.repositories import approvals as approvals_repo

        exists = approvals_repo.get_approval(
            db, approval_id=rid, business_id=business_id
        )
    if exists is None:
        # Uniform 404: foreign rows behave as nonexistent (no oracle).
        raise NotFoundError("Related record not found.")
    return rtype, rid


def create_task(
    db: Session,
    *,
    business_id: uuid.UUID,
    title: str,
    description: str = "",
    priority: str = "medium",
    assigned_to_user_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    related_entity_type: str | None = None,
    related_entity_id: object | None = None,
) -> object:
    clean_title = _clean_text(title, max_chars=200)
    if not clean_title:
        raise ValueError("Task title is required.")
    if assigned_to_user_id is not None:
        require_active_member(db, business_id=business_id, user_id=assigned_to_user_id)
    rtype, rid = _validate_related(
        db,
        business_id=business_id,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    task = tasks_repo.create(
        db,
        business_id=business_id,
        fields={
            "title": clean_title,
            "description": _clean_text(description, max_chars=2000),
            "status": "open",
            "priority": _validate_enum(
                priority, allowed=TASK_PRIORITIES, field="priority", default="medium"
            ),
            "assigned_to_user_id": assigned_to_user_id,
            "created_by_user_id": created_by_user_id,
            "due_at": due_at,
            "related_entity_type": rtype,
            "related_entity_id": rid,
        },
    )
    if assigned_to_user_id is not None:
        notify_task_assigned(
            db,
            business_id=business_id,
            assignee_user_id=assigned_to_user_id,
            task_id=task.id,
            title=clean_title,
        )
    db.flush()
    return task


def get_task(db: Session, *, business_id: uuid.UUID, task_id: object):
    task = tasks_repo.get_scoped(db, task_id=task_id, business_id=business_id)
    if task is None:
        raise NotFoundError("Task not found.")
    return task


def list_tasks(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    priority: str | None = None,
    assigned_to_user_id: object = None,
    created_by_user_id: object = None,
    overdue_only: bool = False,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    related_entity_type: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    from app.repositories.pagination import parse_uuid

    status_clean = (
        _validate_enum(status, allowed=TASK_STATUSES, field="status", default="open")
        if status
        else None
    )
    priority_clean = (
        _validate_enum(
            priority, allowed=TASK_PRIORITIES, field="priority", default="medium"
        )
        if priority
        else None
    )
    assignee = parse_uuid(assigned_to_user_id) if assigned_to_user_id else None
    if assigned_to_user_id and assignee is None:
        raise ValueError("assigned_to_user_id must be a valid UUID.")
    creator = parse_uuid(created_by_user_id) if created_by_user_id else None
    if created_by_user_id and creator is None:
        raise ValueError("created_by_user_id must be a valid UUID.")
    rtype = None
    if related_entity_type:
        rtype = _validate_enum(
            related_entity_type,
            allowed=TASK_RELATED_TYPES,
            field="related entity type",
            default="",
        )
    return tasks_repo.list_scoped(
        db,
        business_id=business_id,
        status=status_clean,
        priority=priority_clean,
        assigned_to_user_id=assignee,
        created_by_user_id=creator,
        overdue_only=bool(overdue_only),
        due_from=due_from,
        due_to=due_to,
        related_entity_type=rtype,
        search=validate_search(search),
        now=_utcnow(),
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def update_task(db: Session, *, business_id: uuid.UUID, task_id: object, fields: dict):
    task = get_task(db, business_id=business_id, task_id=task_id)
    allowed = {"title", "description", "priority", "due_at", "assigned_to_user_id"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown task field(s): {sorted(unknown)}.")
    updates: dict = {}
    reassigned_to: uuid.UUID | None = None
    if "title" in fields:
        clean = _clean_text(fields["title"], max_chars=200)
        if not clean:
            raise ValueError("Task title must not be empty.")
        updates["title"] = clean
    if "description" in fields:
        updates["description"] = _clean_text(fields["description"], max_chars=2000)
    if "priority" in fields:
        updates["priority"] = _validate_enum(
            fields["priority"],
            allowed=TASK_PRIORITIES,
            field="priority",
            default="medium",
        )
    if "due_at" in fields:
        updates["due_at"] = fields["due_at"]
    if "assigned_to_user_id" in fields:
        from app.repositories.pagination import parse_uuid

        assignee = parse_uuid(fields["assigned_to_user_id"])
        if fields["assigned_to_user_id"] and assignee is None:
            raise ValueError("assigned_to_user_id must be a valid UUID or null.")
        if assignee is not None:
            require_active_member(db, business_id=business_id, user_id=assignee)
        if assignee != task.assigned_to_user_id:
            reassigned_to = assignee
        updates["assigned_to_user_id"] = assignee
    tasks_repo.set_fields(task, updates)
    task.updated_at = _utcnow()
    if reassigned_to is not None:
        notify_task_assigned(
            db,
            business_id=business_id,
            assignee_user_id=reassigned_to,
            task_id=task.id,
            title=task.title,
        )
    db.flush()
    return task


def transition(
    db: Session,
    *,
    business_id: uuid.UUID,
    task_id: object,
    to_status: str,
    actor_user_id: uuid.UUID | None = None,
) -> object:
    task = get_task(db, business_id=business_id, task_id=task_id)
    target = _validate_enum(
        to_status, allowed=TASK_STATUSES, field="status", default="open"
    )
    current = str(task.status or "open").lower()
    if target == current:
        return task
    if target not in TASK_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move task from {current.upper()} to {target.upper()}."
        )
    task.status = target
    task.updated_at = _utcnow()
    if target == "completed":
        task.completed_at = _utcnow()
        from app.services.notifications import notify_task_completed

        notify_task_completed(
            db,
            business_id=business_id,
            task_id=task.id,
            title=task.title,
            actor_user_id=actor_user_id,
        )
    if target == "open" and current in ("completed", "cancelled"):
        task.completed_at = None
    db.flush()
    return task
