"""Operational membership / plan / renewal repositories: SQL only, scoped.

NOTE: staff business-membership (RBAC) helpers live in
``app.repositories.memberships`` — this module is the OPERATIONAL
membership catalogue (members <-> plans enrolments). The split keeps the
Block 1 RBAC surface untouched.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.operations import Membership, MembershipPlan, Renewal
from app.repositories.base import apply_business_scope, get_scoped
from app.repositories.pagination import apply_sort, clamp_page

SORTABLE_PLANS = {
    "created_at": MembershipPlan.created_at,
    "updated_at": MembershipPlan.updated_at,
    "price": MembershipPlan.price,
    "name": MembershipPlan.name,
    "duration_months": MembershipPlan.duration_months,
}

SORTABLE_MEMBERSHIPS = {
    "created_at": Membership.created_at,
    "updated_at": Membership.updated_at,
    "start_date": Membership.start_date,
    "end_date": Membership.end_date,
    "final_amount": Membership.final_amount,
}

SORTABLE_RENEWALS = {
    "created_at": Renewal.created_at,
    "due_date": Renewal.due_date,
    "status": Renewal.status,
}


# -- plans ---------------------------------------------------------------


def create_plan(db: Session, *, business_id: uuid.UUID, fields: dict) -> MembershipPlan:
    plan = MembershipPlan(business_id=business_id, **fields)
    db.add(plan)
    db.flush()
    return plan


def get_plan(
    db: Session, *, plan_id: object, business_id: uuid.UUID
) -> MembershipPlan | None:
    return get_scoped(db, MembershipPlan, plan_id, business_id)


def get_plan_by_code(
    db: Session, *, business_id: uuid.UUID, code: str
) -> MembershipPlan | None:
    stmt = select(MembershipPlan).where(
        MembershipPlan.business_id == business_id,
        MembershipPlan.code == code,
    )
    return db.execute(stmt).scalars().first()


def list_plans(
    db: Session,
    *,
    business_id: uuid.UUID,
    category: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[MembershipPlan], int]:
    stmt = apply_business_scope(select(MembershipPlan), MembershipPlan, business_id)
    if category:
        stmt = stmt.where(MembershipPlan.category == category)
    if is_active is not None:
        stmt = stmt.where(MembershipPlan.is_active == is_active)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                MembershipPlan.name.ilike(like),
                MembershipPlan.code.ilike(like),
            )
        )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_PLANS,
        default=MembershipPlan.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


# -- memberships ----------------------------------------------------------


def create_membership(
    db: Session, *, business_id: uuid.UUID, fields: dict
) -> Membership:
    membership = Membership(business_id=business_id, **fields)
    db.add(membership)
    db.flush()
    return membership


def get_membership(
    db: Session, *, membership_id: object, business_id: uuid.UUID
) -> Membership | None:
    return get_scoped(db, Membership, membership_id, business_id)


def get_membership_by_idem(
    db: Session, *, business_id: uuid.UUID, idempotency_key: str
) -> Membership | None:
    if not idempotency_key:
        return None
    stmt = select(Membership).where(
        Membership.business_id == business_id,
        Membership.idempotency_key == idempotency_key,
    )
    return db.execute(stmt).scalars().first()


def list_memberships(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    status: str | None = None,
    payment_state: str | None = None,
    ending_before: date | None = None,
    ending_after: date | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Membership], int]:
    stmt = apply_business_scope(select(Membership), Membership, business_id)
    if member_id is not None:
        stmt = stmt.where(Membership.member_id == member_id)
    if plan_id is not None:
        stmt = stmt.where(Membership.plan_id == plan_id)
    if status:
        stmt = stmt.where(Membership.status == status)
    if payment_state:
        stmt = stmt.where(Membership.payment_state == payment_state)
    if ending_before is not None:
        stmt = stmt.where(Membership.end_date <= ending_before)
    if ending_after is not None:
        stmt = stmt.where(Membership.end_date >= ending_after)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_MEMBERSHIPS,
        default=Membership.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def active_for_member(
    db: Session, *, business_id: uuid.UUID, member_id: uuid.UUID
) -> Membership | None:
    """Current ACTIVE membership for a member (at most one expected)."""
    stmt = (
        select(Membership)
        .where(
            Membership.business_id == business_id,
            Membership.member_id == member_id,
            Membership.status == "active",
        )
        .order_by(Membership.end_date.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


# -- renewals --------------------------------------------------------------


def create_renewal(db: Session, *, business_id: uuid.UUID, fields: dict) -> Renewal:
    renewal = Renewal(business_id=business_id, **fields)
    db.add(renewal)
    db.flush()
    return renewal


def get_renewal(
    db: Session, *, renewal_id: object, business_id: uuid.UUID
) -> Renewal | None:
    return get_scoped(db, Renewal, renewal_id, business_id)


def list_renewals(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id: uuid.UUID | None = None,
    status: str | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Renewal], int]:
    stmt = apply_business_scope(select(Renewal), Renewal, business_id)
    if member_id is not None:
        stmt = stmt.where(Renewal.member_id == member_id)
    if status:
        stmt = stmt.where(Renewal.status == status)
    if due_before is not None:
        stmt = stmt.where(Renewal.due_date <= due_before)
    if due_after is not None:
        stmt = stmt.where(Renewal.due_date >= due_after)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_RENEWALS,
        default=Renewal.due_date,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total
