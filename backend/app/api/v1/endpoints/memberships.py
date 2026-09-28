"""Membership + plan + renewal endpoints (staff, scoped, RBAC-enforced)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.core.config import get_settings
from app.schemas.common import Page, list_params
from app.schemas.operations import (
    MembershipCreate,
    MembershipOut,
    MembershipRenewIn,
    MembershipStatusIn,
    PlanCreate,
    PlanOut,
    PlanUpdate,
    RenewalCreate,
    RenewalOut,
    RenewalStatusIn,
)
from app.services import memberships as membership_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(tags=["memberships"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


# -- plans -------------------------------------------------------------------


@router.get("/membership-plans", response_model=Page[PlanOut], summary="List plans")
def list_plans(
    category: str | None = Query(default=None, max_length=32),
    is_active: bool | None = None,
    search: str | None = Query(default=None, max_length=64),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("membership_plans.read")
    ),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = membership_service.list_plans(
            db,
            business_id=ctx.business.id,
            category=category,
            is_active=is_active,
            search=search,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([PlanOut.model_validate(i) for i in items], total, paging)


@router.post(
    "/membership-plans",
    response_model=PlanOut,
    summary="Create plan (owner/admin)",
    status_code=201,
)
def create_plan(
    payload: PlanCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("membership_plans.manage")
    ),
) -> PlanOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        plan = membership_service.create_plan(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(plan)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="membership_plan.created",
        actor_user_id=ctx.user.id,
        entity_type="membership_plan",
        entity_id=plan.id,
        request_id=request_id(request),
    )
    return PlanOut.model_validate(plan)


@router.get("/membership-plans/{plan_id}", response_model=PlanOut, summary="Get plan")
def get_plan(
    plan_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("membership_plans.read")
    ),
) -> PlanOut:
    assert ctx.business is not None
    try:
        plan = membership_service.get_plan(
            db, business_id=ctx.business.id, plan_id=plan_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return PlanOut.model_validate(plan)


@router.patch(
    "/membership-plans/{plan_id}", response_model=PlanOut, summary="Update plan"
)
def update_plan(
    plan_id: str,
    payload: PlanUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("membership_plans.manage")
    ),
) -> PlanOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        plan = membership_service.update_plan(
            db,
            business_id=ctx.business.id,
            plan_id=plan_id,
            fields=payload.model_dump(exclude_unset=True),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(plan)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="membership_plan.updated",
        actor_user_id=ctx.user.id,
        entity_type="membership_plan",
        entity_id=plan.id,
        request_id=request_id(request),
    )
    return PlanOut.model_validate(plan)


# -- memberships ------------------------------------------------------------------


@router.get(
    "/memberships", response_model=Page[MembershipOut], summary="List memberships"
)
def list_memberships(
    member_id: str | None = Query(default=None, max_length=64),
    plan_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    payment_state: str | None = Query(default=None, max_length=32),
    ending_before: str | None = Query(default=None, max_length=16),
    ending_after: str | None = Query(default=None, max_length=16),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("memberships.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = membership_service.list_memberships(
            db,
            business_id=ctx.business.id,
            member_id=member_id,
            plan_id=plan_id,
            status=status,
            payment_state=payment_state,
            ending_before=ending_before,
            ending_after=ending_after,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([MembershipOut.model_validate(i) for i in items], total, paging)


@router.post(
    "/memberships",
    response_model=MembershipOut,
    summary="Create membership",
    status_code=201,
)
def create_membership(
    payload: MembershipCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("memberships.create")),
) -> MembershipOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        membership, _ = membership_service.create_membership(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(membership)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="membership.created",
        actor_user_id=ctx.user.id,
        entity_type="membership",
        entity_id=membership.id,
        request_id=request_id(request),
    )
    return MembershipOut.model_validate(membership)


@router.get(
    "/memberships/{membership_id}",
    response_model=MembershipOut,
    summary="Get membership",
)
def get_membership(
    membership_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("memberships.read")),
) -> MembershipOut:
    assert ctx.business is not None
    try:
        membership = membership_service.get_membership(
            db, business_id=ctx.business.id, membership_id=membership_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return MembershipOut.model_validate(membership)


@router.post(
    "/memberships/{membership_id}/status",
    response_model=MembershipOut,
    summary="Change membership status",
)
def change_membership_status(
    membership_id: str,
    payload: MembershipStatusIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("memberships.update")),
) -> MembershipOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        membership = membership_service.set_status(
            db,
            business_id=ctx.business.id,
            membership_id=membership_id,
            to_status=payload.status,
            actor_user_id=ctx.user.id,
            cancel_reason=payload.cancel_reason,
        )
        db.commit()
        db.refresh(membership)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    action = (
        "membership.cancelled"
        if str(membership.status).lower() == "cancelled"
        else "membership.updated"
    )
    record_audit(
        db,
        business_id=ctx.business.id,
        action=action,
        actor_user_id=ctx.user.id,
        entity_type="membership",
        entity_id=membership.id,
        request_id=request_id(request),
        meta={"status": str(membership.status)},
    )
    return MembershipOut.model_validate(membership)


@router.post(
    "/memberships/{membership_id}/renew",
    response_model=MembershipOut,
    summary="Renew membership (new row + renewal link)",
)
def renew_membership(
    membership_id: str,
    payload: MembershipRenewIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("memberships.update")),
) -> MembershipOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        renewed = membership_service.renew_membership(
            db,
            business_id=ctx.business.id,
            membership_id=membership_id,
            data=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
            settings=get_settings(),
        )
        db.commit()
        db.refresh(renewed)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="membership.renewed",
        actor_user_id=ctx.user.id,
        entity_type="membership",
        entity_id=renewed.id,
        request_id=request_id(request),
    )
    return MembershipOut.model_validate(renewed)


# -- renewals -------------------------------------------------------------------------


@router.get("/renewals", response_model=Page[RenewalOut], summary="List renewals")
def list_renewals(
    member_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    due_before: str | None = Query(default=None, max_length=16),
    due_after: str | None = Query(default=None, max_length=16),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("renewals.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = membership_service.list_renewals(
            db,
            business_id=ctx.business.id,
            member_id=member_id,
            status=status,
            due_before=due_before,
            due_after=due_after,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([RenewalOut.model_validate(i) for i in items], total, paging)


@router.post(
    "/renewals",
    response_model=RenewalOut,
    summary="Create renewal pipeline record",
    status_code=201,
)
def create_renewal(
    payload: RenewalCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("renewals.create")),
) -> RenewalOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        renewal = membership_service.create_renewal_record(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(renewal)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="renewal.created",
        actor_user_id=ctx.user.id,
        entity_type="renewal",
        entity_id=renewal.id,
        request_id=request_id(request),
    )
    return RenewalOut.model_validate(renewal)


@router.get("/renewals/{renewal_id}", response_model=RenewalOut, summary="Get renewal")
def get_renewal(
    renewal_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("renewals.read")),
) -> RenewalOut:
    assert ctx.business is not None
    try:
        renewal = membership_service.get_renewal(
            db, business_id=ctx.business.id, renewal_id=renewal_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return RenewalOut.model_validate(renewal)


@router.post(
    "/renewals/{renewal_id}/status",
    response_model=RenewalOut,
    summary="Transition renewal (pending -> confirmed/cancelled/expired)",
)
def change_renewal_status(
    renewal_id: str,
    payload: RenewalStatusIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("renewals.create")),
) -> RenewalOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        renewal = membership_service.set_renewal_status(
            db,
            business_id=ctx.business.id,
            renewal_id=renewal_id,
            to_status=payload.status,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(renewal)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    action = (
        "renewal.confirmed"
        if str(renewal.status).lower() == "confirmed"
        else "renewal.updated"
    )
    record_audit(
        db,
        business_id=ctx.business.id,
        action=action,
        actor_user_id=ctx.user.id,
        entity_type="renewal",
        entity_id=renewal.id,
        request_id=request_id(request),
        meta={"status": str(renewal.status)},
    )
    return RenewalOut.model_validate(renewal)
