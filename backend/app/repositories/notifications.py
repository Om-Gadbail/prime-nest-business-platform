"""Notification repository: SQL only, business + recipient scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.membership import BusinessMembership
from app.models.notification import Notification, NotificationPreference
from app.models.rbac import Role
from app.repositories.pagination import clamp_page


def create(
    db: Session,
    *,
    business_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str = "",
    severity: str = "info",
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    data: dict | None = None,
    dedupe_key: str | None = None,
    expires_at: datetime | None = None,
) -> Notification:
    notification = Notification(
        business_id=business_id,
        recipient_user_id=recipient_user_id,
        notification_type=notification_type,
        title=title,
        body=body,
        severity=severity,
        source_type=source_type,
        source_id=source_id,
        data=dict(data or {}),
        dedupe_key=dedupe_key,
        expires_at=expires_at,
    )
    db.add(notification)
    db.flush()
    return notification


def get_for_recipient(
    db: Session,
    *,
    notification_id: object,
    business_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
) -> Notification | None:
    try:
        wanted = (
            notification_id
            if isinstance(notification_id, uuid.UUID)
            else uuid.UUID(str(notification_id))
        )
    except (ValueError, AttributeError, TypeError):
        return None
    stmt = select(Notification).where(
        Notification.id == wanted,
        Notification.business_id == business_id,
        Notification.recipient_user_id == recipient_user_id,
    )
    return db.execute(stmt).scalars().first()


def list_for_recipient(
    db: Session,
    *,
    business_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    unread_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[Notification], int]:
    stmt = (
        select(Notification)
        .where(
            Notification.business_id == business_id,
            Notification.recipient_user_id == recipient_user_id,
        )
        .order_by(Notification.created_at.desc())
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    stmt = stmt.offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def count_unread(
    db: Session, *, business_id: uuid.UUID, recipient_user_id: uuid.UUID
) -> int:
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.business_id == business_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )
    )
    return int(db.execute(stmt).scalar() or 0)


def mark_all_read(
    db: Session,
    *,
    business_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    now: datetime,
) -> int:
    items, _ = list_for_recipient(
        db,
        business_id=business_id,
        recipient_user_id=recipient_user_id,
        unread_only=True,
        limit=100,
        offset=0,
    )
    # Bounded batches; repeat the call if more remain (keeps UPDATEs small).
    for item in items:
        item.read_at = now
    db.flush()
    return len(items)


def list_staff_recipients(
    db: Session,
    *,
    business_id: uuid.UUID,
    role_names: tuple[str, ...],
    limit: int = 100,
) -> list[uuid.UUID]:
    """Active membership user IDs holding one of the given system roles."""
    stmt = (
        select(BusinessMembership.user_id)
        .join(Role, Role.id == BusinessMembership.role_id)
        .where(
            BusinessMembership.business_id == business_id,
            BusinessMembership.status == "active",
            Role.name.in_(role_names),
            Role.business_id.is_(None),
        )
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get_preference(
    db: Session,
    *,
    user_id: uuid.UUID,
    business_id: uuid.UUID,
    notification_type: str,
) -> NotificationPreference | None:
    return db.get(NotificationPreference, (user_id, business_id, notification_type))


def is_enabled(
    db: Session,
    *,
    user_id: uuid.UUID,
    business_id: uuid.UUID,
    notification_type: str,
) -> bool:
    pref = get_preference(
        db,
        user_id=user_id,
        business_id=business_id,
        notification_type=notification_type,
    )
    return pref.enabled if pref is not None else True


def set_preference(
    db: Session,
    *,
    user_id: uuid.UUID,
    business_id: uuid.UUID,
    notification_type: str,
    enabled: bool,
) -> NotificationPreference:
    pref = get_preference(
        db,
        user_id=user_id,
        business_id=business_id,
        notification_type=notification_type,
    )
    if pref is None:
        pref = NotificationPreference(
            user_id=user_id,
            business_id=business_id,
            notification_type=notification_type,
            enabled=enabled,
        )
        db.add(pref)
    else:
        pref.enabled = enabled
    db.flush()
    return pref
