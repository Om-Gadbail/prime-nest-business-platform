"""Member endpoints (staff, business-scoped, RBAC-enforced)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.operations import MemberCreate, MemberOut, MemberUpdate
from app.services import members as members_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/members", tags=["members"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("", response_model=Page[MemberOut], summary="List members")
def list_members(
    status: str | None = Query(default=None, max_length=32),
    source: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=64),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("members.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = members_service.list_members(
            db,
            business_id=ctx.business.id,
            status=status,
            source=source,
            search=search,
            created_from=created_from,
            created_to=created_to,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([MemberOut.model_validate(i) for i in items], total, paging)


@router.post("", response_model=MemberOut, summary="Create member", status_code=201)
def create_member(
    payload: MemberCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("members.create")),
) -> MemberOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        member = members_service.create_member(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(member)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="member.created",
        actor_user_id=ctx.user.id,
        entity_type="member",
        entity_id=member.id,
        request_id=request_id(request),
    )
    return MemberOut.model_validate(member)


@router.get("/{member_id}", response_model=MemberOut, summary="Get member")
def get_member(
    member_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("members.read")),
) -> MemberOut:
    assert ctx.business is not None
    try:
        member = members_service.get_member(
            db, business_id=ctx.business.id, member_id=member_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return MemberOut.model_validate(member)


@router.get("/{member_id}/profile", summary="Full member operational profile")
def member_profile(
    member_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("members.read")),
) -> dict:
    """Member + current membership + history + payments + visits + seat."""
    from app.schemas.operations import (
        AttendanceOut,
        MembershipOut,
        PaymentOut,
        RenewalOut,
        SeatAllocationOut,
    )

    assert ctx.business is not None
    try:
        profile = members_service.member_profile(
            db, business_id=ctx.business.id, member_id=member_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    current = profile["current_membership"]
    return {
        "member": MemberOut.model_validate(profile["member"]).model_dump(mode="json"),
        "current_membership": (
            MembershipOut.model_validate(current).model_dump(mode="json")
            if current is not None
            else None
        ),
        "memberships": [
            MembershipOut.model_validate(m).model_dump(mode="json")
            for m in profile["memberships"]
        ],
        "payments": [
            PaymentOut.model_validate(p).model_dump(mode="json")
            for p in profile["payments"]
        ],
        "attendance": [
            AttendanceOut.model_validate(a).model_dump(mode="json")
            for a in profile["attendance"]
        ],
        "renewals": [
            RenewalOut.model_validate(r).model_dump(mode="json")
            for r in profile["renewals"]
        ],
        "active_seat_allocation": (
            SeatAllocationOut.model_validate(
                profile["active_seat_allocation"]
            ).model_dump(mode="json")
            if profile["active_seat_allocation"] is not None
            else None
        ),
    }


@router.patch("/{member_id}", response_model=MemberOut, summary="Update member")
def update_member(
    member_id: str,
    payload: MemberUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("members.update")),
) -> MemberOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        member = members_service.update_member(
            db,
            business_id=ctx.business.id,
            member_id=member_id,
            fields=payload.model_dump(exclude_unset=True),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(member)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="member.updated",
        actor_user_id=ctx.user.id,
        entity_type="member",
        entity_id=member.id,
        request_id=request_id(request),
    )
    return MemberOut.model_validate(member)


@router.get("/{member_id}/timeline", summary="Unified member timeline (360 view)")
def member_timeline(
    member_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("members.read")),
) -> dict:
    """Chronological member story: audit + domain events + lead activity.

    Joins the three existing trails (no duplicate audit system) and sorts
    by timestamp descending. All rows are pre-scoped to the caller's
    business; cross-tenant member IDs return 404.
    """
    from sqlalchemy import select

    from app.models.audit_event import AuditEvent
    from app.models.lead import LeadActivity
    from app.models.operations import DomainEvent

    assert ctx.business is not None
    try:
        member = members_service.get_member(
            db, business_id=ctx.business.id, member_id=member_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    mid = str(member.id)
    items: list[dict] = []
    audit_rows = (
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.business_id == ctx.business.id,
                AuditEvent.entity_id == member.id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    for row in audit_rows:
        items.append(
            {
                "kind": "audit",
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id) if row.entity_id else None,
                "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    event_rows = (
        db.execute(
            select(DomainEvent)
            .where(
                DomainEvent.business_id == ctx.business.id,
                DomainEvent.entity_id == member.id,
            )
            .order_by(DomainEvent.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    for row in event_rows:
        items.append(
            {
                "kind": "event",
                "action": row.event_type,
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id) if row.entity_id else None,
                "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    # Lead history linked via member.lead_id (conversion provenance).
    if member.lead_id is not None:
        lead_rows = (
            db.execute(
                select(LeadActivity)
                .where(LeadActivity.lead_id == member.lead_id)
                .order_by(LeadActivity.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        for row in lead_rows:
            items.append(
                {
                    "kind": "lead_activity",
                    "action": f"lead.{row.activity_type}",
                    "entity_type": "lead",
                    "entity_id": str(row.lead_id),
                    "actor_user_id": (
                        str(row.actor_user_id) if row.actor_user_id else None
                    ),
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                }
            )
    # Member-linked domain events (membership/payment/seat/renewal rows carry
    # their own entity_id, so also surface events that reference this member
    # in payload-free membership listings via a second pass on memberships).
    from app.repositories import op_memberships as _op_repo

    memberships, _ = _op_repo.list_memberships(
        db, business_id=ctx.business.id, member_id=member.id, limit=20, offset=0
    )
    membership_ids = {str(m.id) for m in memberships}
    if membership_ids:
        from sqlalchemy import or_ as _or

        extra = (
            db.execute(
                select(DomainEvent)
                .where(
                    DomainEvent.business_id == ctx.business.id,
                    _or(
                        DomainEvent.entity_id.in_([m.id for m in memberships]),
                    ),
                )
                .order_by(DomainEvent.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        for row in extra:
            items.append(
                {
                    "kind": "event",
                    "action": row.event_type,
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id) if row.entity_id else None,
                    "actor_user_id": (
                        str(row.actor_user_id) if row.actor_user_id else None
                    ),
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                }
            )
    items.sort(key=lambda e: str(e.get("created_at") or ""), reverse=True)
    return {"member_id": mid, "items": items[:limit], "total": len(items[:limit])}
