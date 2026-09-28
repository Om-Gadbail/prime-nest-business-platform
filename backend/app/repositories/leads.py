"""Lead + LeadActivity repository: SQL only, always business-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.lead import Lead, LeadActivity
from app.repositories.base import apply_business_scope
from app.repositories.pagination import apply_sort, clamp_page


SORTABLE_LEADS = {
    "created_at": Lead.created_at,
    "updated_at": Lead.updated_at,
    "follow_up_at": Lead.follow_up_at,
    "display_name": Lead.display_name,
    "status": Lead.status,
}


def create(db: Session, *, business_id: uuid.UUID, fields: dict) -> Lead:
    lead = Lead(business_id=business_id, **fields)
    db.add(lead)
    db.flush()
    return lead


def get_scoped(
    db: Session,
    *,
    lead_id: object,
    business_id: uuid.UUID,
    with_relations: bool = False,
) -> Lead | None:
    from app.repositories.base import get_scoped as _get

    lead = _get(db, Lead, lead_id, business_id)
    if lead is not None and with_relations:
        db.refresh(lead, attribute_names=["contact", "activities"])
    return lead


def list_scoped(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    source: str | None = None,
    assigned_user_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    follow_up_from: datetime | None = None,
    follow_up_to: datetime | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> tuple[list[Lead], int]:
    stmt = apply_business_scope(select(Lead), Lead, business_id)
    if status:
        stmt = stmt.where(Lead.status == status)
    if source:
        stmt = stmt.where(Lead.source == source)
    if assigned_user_id is not None:
        stmt = stmt.where(Lead.assigned_user_id == assigned_user_id)
    if created_from is not None:
        stmt = stmt.where(Lead.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Lead.created_at <= created_to)
    if follow_up_from is not None:
        stmt = stmt.where(Lead.follow_up_at >= follow_up_from)
    if follow_up_to is not None:
        stmt = stmt.where(Lead.follow_up_at <= follow_up_to)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Lead.display_name.ilike(like),
                Lead.phone.ilike(like),
                Lead.email.ilike(like),
                Lead.normalized_phone.ilike(like),
                Lead.normalized_email.ilike(like),
                Lead.service_interest.ilike(like),
            )
        )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    stmt = apply_sort(
        stmt,
        sort=sort,
        direction=direction,
        allowed=SORTABLE_LEADS,
        default=Lead.created_at,
    )
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def set_fields(lead: Lead, fields: dict) -> Lead:
    for key, value in fields.items():
        if hasattr(lead, key):
            setattr(lead, key, value)
    return lead


def add_activity(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: uuid.UUID,
    activity_type: str,
    note: str = "",
    actor_user_id: uuid.UUID | None = None,
) -> LeadActivity:
    activity = LeadActivity(
        business_id=business_id,
        lead_id=lead_id,
        activity_type=activity_type,
        note=note,
        actor_user_id=actor_user_id,
    )
    db.add(activity)
    db.flush()
    return activity


def list_activities(
    db: Session,
    *,
    business_id: uuid.UUID,
    lead_id: uuid.UUID,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[LeadActivity], int]:
    stmt = (
        select(LeadActivity)
        .where(
            LeadActivity.business_id == business_id,
            LeadActivity.lead_id == lead_id,
        )
        .order_by(LeadActivity.created_at.asc())
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def get_with_activities(
    db: Session, *, lead_id: object, business_id: uuid.UUID
) -> Lead | None:
    stmt = select(Lead).where(Lead.business_id == business_id)
    try:
        wanted = lead_id if isinstance(lead_id, uuid.UUID) else uuid.UUID(str(lead_id))
    except (ValueError, AttributeError, TypeError):
        return None
    stmt = stmt.where(Lead.id == wanted).options(selectinload(Lead.activities))
    return db.execute(stmt).scalars().first()
