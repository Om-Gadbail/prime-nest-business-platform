"""Approval endpoints (owner control foundation)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.operations import ApprovalDecideIn, ApprovalOut, ApprovalRequestIn
from app.services import approvals as approvals_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("", response_model=Page[ApprovalOut], summary="List approvals")
def list_approvals(
    status: str | None = Query(default=None, max_length=32),
    entity_type: str | None = Query(default=None, max_length=48),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("approvals.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = approvals_service.list_approvals(
            db,
            business_id=ctx.business.id,
            status=status,
            entity_type=entity_type,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([ApprovalOut.model_validate(i) for i in items], total, paging)


@router.post(
    "", response_model=ApprovalOut, summary="Request approval", status_code=201
)
def request_approval(
    payload: ApprovalRequestIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("approvals.read")),
) -> ApprovalOut:
    """Any staff with read access can REQUEST; only managers decide."""
    assert ctx.business is not None and ctx.user is not None
    try:
        approval = approvals_service.request_approval(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(approval)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="approval.requested",
        actor_user_id=ctx.user.id,
        entity_type="approval",
        entity_id=approval.id,
        request_id=request_id(request),
    )
    return ApprovalOut.model_validate(approval)


@router.get("/{approval_id}", response_model=ApprovalOut, summary="Get approval")
def get_approval(
    approval_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("approvals.read")),
) -> ApprovalOut:
    assert ctx.business is not None
    try:
        approval = approvals_service.get_approval(
            db, business_id=ctx.business.id, approval_id=approval_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return ApprovalOut.model_validate(approval)


@router.post(
    "/{approval_id}/decide", response_model=ApprovalOut, summary="Decide approval"
)
def decide_approval(
    approval_id: str,
    payload: ApprovalDecideIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("approvals.manage")),
) -> ApprovalOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        approval = approvals_service.decide(
            db,
            business_id=ctx.business.id,
            approval_id=approval_id,
            to_status=payload.status,
            actor_user_id=ctx.user.id,
            decision_note=payload.decision_note,
        )
        db.commit()
        db.refresh(approval)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="approval.decided",
        actor_user_id=ctx.user.id,
        entity_type="approval",
        entity_id=approval.id,
        request_id=request_id(request),
        meta={"decision": str(approval.status)},
    )
    return ApprovalOut.model_validate(approval)
