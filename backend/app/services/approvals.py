"""Approval service: owner approval/control foundation (Block 5).

Sensitive operations (refunds beyond policy, destructive changes, …)
enter as PENDING requests; only OWNER/ADMIN (approvals.manage) decide.
Terminal decisions are final — no silent re-open.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ops_vocab import (
    APPROVAL_ACTIONS,
    APPROVAL_STATUSES,
    APPROVAL_TRANSITIONS,
)
from app.repositories import approvals as approvals_repo
from app.services.crm import _clean_text, _validate_enum
from app.services.errors import ConflictError, NotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def request_approval(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    from app.services import domain_events as events

    entity_type = _clean_text(data.get("entity_type"), max_chars=48)
    if not entity_type:
        raise ValueError("entity_type is required.")
    entity_id = None
    if data.get("entity_id"):
        try:
            entity_id = (
                data["entity_id"]
                if isinstance(data["entity_id"], uuid.UUID)
                else uuid.UUID(str(data["entity_id"]))
            )
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("entity_id must be a valid UUID.") from exc
    approval = approvals_repo.create_approval(
        db,
        business_id=business_id,
        fields={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": _validate_enum(
                data.get("action", "approve"),
                allowed=APPROVAL_ACTIONS,
                field="action",
                default="approve",
            ),
            "status": "pending",
            "title": _clean_text(data.get("title"), max_chars=200) or entity_type,
            "reason": _clean_text(data.get("reason"), max_chars=2000),
            "meta": dict(data.get("meta") or {}),
            "requested_by_user_id": actor_user_id,
        },
    )
    db.flush()
    events.emit(
        db,
        business_id=business_id,
        event_type="approval.requested",
        entity_type="approval",
        entity_id=approval.id,
        actor_user_id=actor_user_id,
        payload={"entity_type": entity_type},
    )
    return approval


def get_approval(db: Session, *, business_id: uuid.UUID, approval_id: object):
    approval = approvals_repo.get_approval(
        db, approval_id=approval_id, business_id=business_id
    )
    if approval is None:
        raise NotFoundError("Approval not found.")
    return approval


def decide(
    db: Session,
    *,
    business_id: uuid.UUID,
    approval_id: object,
    to_status: str,
    actor_user_id: uuid.UUID | None = None,
    decision_note: str = "",
):
    from app.services import domain_events as events

    approval = get_approval(db, business_id=business_id, approval_id=approval_id)
    target = _validate_enum(
        to_status, allowed=APPROVAL_STATUSES, field="status", default="pending"
    )
    current = str(approval.status or "pending").lower()
    if target == current:
        return approval
    if target not in APPROVAL_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move approval from {current.upper()} to {target.upper()}."
        )
    if (
        target in ("approved", "rejected")
        and actor_user_id == approval.requested_by_user_id
    ):
        raise ConflictError("Requester cannot decide their own approval.")
    approval.status = target
    approval.decided_by_user_id = actor_user_id
    approval.decided_at = _utcnow()
    approval.decision_note = _clean_text(decision_note, max_chars=2000)
    approval.updated_at = _utcnow()
    db.flush()
    events.emit(
        db,
        business_id=business_id,
        event_type="approval.decided",
        entity_type="approval",
        entity_id=approval.id,
        actor_user_id=actor_user_id,
        payload={"decision": target},
    )
    return approval


def list_approvals(
    db: Session,
    *,
    business_id: uuid.UUID,
    status=None,
    entity_type=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    status_clean = (
        _validate_enum(
            status, allowed=APPROVAL_STATUSES, field="status", default="pending"
        )
        if status
        else None
    )
    entity_clean = (
        _clean_text(entity_type, max_chars=48) or None if entity_type else None
    )
    return approvals_repo.list_approvals(
        db,
        business_id=business_id,
        status=status_clean,
        entity_type=entity_clean,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )
