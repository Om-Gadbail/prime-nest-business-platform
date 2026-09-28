"""Automation APIs (Block 8): rules, executions, trigger, scheduler."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.core.config import get_settings
from app.schemas.blocks812 import RuleIn, RuleOut, TriggerIn
from app.services import automation as auto_service
from app.services.authorization import AuthenticatedContext
from app.repositories import blocks812 as repo

router = APIRouter(prefix="/automation", tags=["automation"])


def _rule_out(r) -> dict:
    return {
        "id": r.id,
        "business_id": r.business_id,
        "name": r.name,
        "event_type": r.event_type,
        "is_active": r.is_active,
        "priority": r.priority,
        "conditions": dict(r.conditions or {}),
        "actions": list(r.actions or []),
        "config": dict(r.config or {}),
    }


@router.get("/rules", summary="List automation rules")
def list_rules(
    event_type: str | None = None,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("automation.read")),
):
    assert ctx.business is not None
    try:
        items, total = repo.list_rules(
            db, business_id=ctx.business.id, event_type=event_type, limit=100
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "items": [_rule_out(r) for r in items],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@router.post(
    "/rules", response_model=RuleOut, status_code=201, summary="Create automation rule"
)
def create_rule(
    payload: RuleIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("automation.manage")),
):
    assert ctx.business is not None
    try:
        row = repo.create_rule(
            db, business_id=ctx.business.id, fields=payload.model_dump()
        )
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return _rule_out(row)


@router.patch(
    "/rules/{rule_id}", response_model=RuleOut, summary="Update automation rule"
)
def update_rule(
    rule_id: str,
    payload: RuleIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("automation.manage")),
):
    assert ctx.business is not None
    from sqlalchemy import select as _select
    from app.models.automation import AutomationRule
    from app.repositories.base import apply_business_scope
    import uuid as _uuid

    try:
        rid = _uuid.UUID(str(rule_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise map_service_error(exc) from exc
    try:
        stmt = apply_business_scope(
            _select(AutomationRule), AutomationRule, ctx.business.id
        ).where(AutomationRule.id == rid)
        row = db.execute(stmt).scalars().first()
        if row is None:
            raise map_service_error(ValueError("Rule not found."))
        for k, v in payload.model_dump().items():
            setattr(row, k, v)
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return _rule_out(row)


@router.get("/executions", summary="List automation executions")
def list_executions(
    status: str | None = None,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("automation.read")),
):
    assert ctx.business is not None
    try:
        items, total = repo.list_executions(
            db, business_id=ctx.business.id, status=status, limit=100
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "items": [
            {
                "id": e.id,
                "business_id": e.business_id,
                "rule_id": e.rule_id,
                "event_type": e.event_type,
                "status": e.status,
                "attempt_count": e.attempt_count,
                "idempotency_key": e.idempotency_key,
                "correlation_id": e.correlation_id,
                "error": e.error,
            }
            for e in items
        ],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@router.post("/trigger", summary="Trigger automation for an event (tests/ops)")
def trigger(
    payload: TriggerIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("automation.manage")),
):
    assert ctx.business is not None
    try:
        execs = auto_service.dispatch_event(
            db,
            get_settings(),
            business_id=ctx.business.id,
            event_type=payload.event_type,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            actor_user_id=ctx.user.id,
            payload=dict(payload.payload or {}),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"triggered": payload.event_type, "executions": len(execs)}


@router.post("/scheduler/run", summary="Run due/retried automation (bounded)")
def scheduler_run(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("automation.manage")),
):
    assert ctx.business is not None
    try:
        ran = auto_service.retry_due(db, get_settings(), business_id=ctx.business.id)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"ran": ran}


@router.post("/seed-defaults", summary="Seed default automation rules + templates")
def seed_defaults(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("automation.manage")),
):
    assert ctx.business is not None
    try:
        from app.services import communications as comms
        from app.services import growth as growth_service

        rules = auto_service.ensure_default_rules(
            db, business_id=ctx.business.id, created_by=ctx.user.id
        )
        comms.ensure_default_templates(db, business_id=ctx.business.id)
        growth_service.ensure_default_sources(db, business_id=ctx.business.id)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"rules_created": rules}
