"""Notification service (Block 2 foundation).

Only in-app delivery is REAL in this block (rows in ``notifications``).
Email/WhatsApp exist as explicit adapter interfaces whose ``send`` raises
``ChannelNotConfiguredError`` — no fake "sent" statuses anywhere.

Block 8 will replace the direct fan-out calls below with durable events;
all creation goes through this service so the swap is mechanical.
"""

from __future__ import annotations

import abc
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.crm_vocab import NOTIFICATION_SEVERITIES, NOTIFICATION_TYPES
from app.repositories import notifications as notif_repo
from app.services.errors import ConflictError, NotFoundError

# Roles that receive operational fan-out (new lead/booking): managers and up.
OPERATIONAL_ROLES = ("OWNER", "ADMIN", "MANAGER")


class ChannelNotConfiguredError(ConflictError):
    """Raised when a future channel (email/WhatsApp) is invoked in Block 2."""


class NotificationProvider(abc.ABC):
    """Future channel adapter interface (email/WhatsApp plug in here)."""

    channel: str = "abstract"

    @abc.abstractmethod
    def send(
        self, *, recipient: str, title: str, body: str, data: dict | None = None
    ) -> dict:
        """Deliver one message. Returns provider receipt. Raises on failure."""


class InAppNotificationProvider(NotificationProvider):
    """The only working Block 2 provider: persists to PostgreSQL."""

    channel = "inapp"

    def __init__(self, db: Session) -> None:
        self._db = db

    def send(
        self, *, recipient: str, title: str, body: str, data: dict | None = None
    ) -> dict:
        raise NotImplementedError(
            "Use notification_service.create_notification() (business + user "
            "scoping is mandatory; raw sends are not allowed)."
        )


class EmailNotificationProvider(NotificationProvider):
    """Future SMTP/API adapter — NOT implemented in Block 2."""

    channel = "email"

    def send(
        self, *, recipient: str, title: str, body: str, data: dict | None = None
    ) -> dict:
        raise ChannelNotConfiguredError(
            "Email delivery is not configured in this release."
        )


class WhatsAppNotificationProvider(NotificationProvider):
    """Future WhatsApp Business API adapter — NOT implemented in Block 2."""

    channel = "whatsapp"

    def send(
        self, *, recipient: str, title: str, body: str, data: dict | None = None
    ) -> dict:
        raise ChannelNotConfiguredError(
            "WhatsApp delivery is not configured in this release."
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_type(notification_type: str) -> str:
    value = str(notification_type or "").strip().lower()
    if value not in NOTIFICATION_TYPES:
        raise ValueError(
            f"Unknown notification type: {notification_type!r}. "
            f"Allowed: {sorted(NOTIFICATION_TYPES)}."
        )
    return value


def _validate_severity(severity: str) -> str:
    value = str(severity or "info").strip().lower()
    if value not in NOTIFICATION_SEVERITIES:
        raise ValueError(
            f"Unknown severity: {severity!r}. "
            f"Allowed: {sorted(NOTIFICATION_SEVERITIES)}."
        )
    return value


def create_notification(
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
    respect_preferences: bool = True,
) -> object | None:
    """Persist one in-app notification (None when the user opted out)."""
    ntype = _validate_type(notification_type)
    if respect_preferences and not notif_repo.is_enabled(
        db,
        user_id=recipient_user_id,
        business_id=business_id,
        notification_type=ntype,
    ):
        return None
    title_clean = str(title or "").strip()[:200]
    if not title_clean:
        raise ValueError("Notification title is required.")
    notification = notif_repo.create(
        db,
        business_id=business_id,
        recipient_user_id=recipient_user_id,
        notification_type=ntype,
        title=title_clean,
        body=str(body or "")[:2000],
        severity=_validate_severity(severity),
        source_type=(str(source_type)[:48] if source_type else None),
        source_id=source_id,
        data=dict(data or {}),
        dedupe_key=(str(dedupe_key)[:128] if dedupe_key else None),
    )
    return notification


def notify_staff(
    db: Session,
    *,
    business_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str = "",
    severity: str = "info",
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    data: dict | None = None,
    dedupe_prefix: str | None = None,
    exclude_user_id: uuid.UUID | None = None,
) -> int:
    """Fan out to OWNER/ADMIN/MANAGER recipients (preference-aware)."""
    recipients = notif_repo.list_staff_recipients(
        db, business_id=business_id, role_names=OPERATIONAL_ROLES
    )
    created = 0
    for recipient in recipients:
        if exclude_user_id is not None and recipient == exclude_user_id:
            continue
        dedupe = f"{dedupe_prefix}:{recipient}" if dedupe_prefix else None
        result = create_notification(
            db,
            business_id=business_id,
            recipient_user_id=recipient,
            notification_type=notification_type,
            title=title,
            body=body,
            severity=severity,
            source_type=source_type,
            source_id=source_id,
            data=data,
            dedupe_key=dedupe,
        )
        if result is not None:
            created += 1
    return created


def notify_new_lead(
    db: Session, *, business_id: uuid.UUID, lead_id: uuid.UUID, lead_name: str
) -> int:
    name = (lead_name or "A new lead").strip()[:120] or "A new lead"
    return notify_staff(
        db,
        business_id=business_id,
        notification_type="new_lead",
        title=f"New lead: {name}",
        body="A new enquiry was received. Review and assign it.",
        source_type="lead",
        source_id=lead_id,
        data={"lead_id": str(lead_id)},
        dedupe_prefix=f"new-lead:{lead_id}",
    )


def notify_new_booking(
    db: Session, *, business_id: uuid.UUID, booking_id: uuid.UUID, title: str
) -> int:
    label = (title or "A new booking request").strip()[:120] or "A new booking request"
    return notify_staff(
        db,
        business_id=business_id,
        notification_type="new_booking",
        title=f"New booking request: {label}",
        body="A new booking request is awaiting confirmation.",
        source_type="booking",
        source_id=booking_id,
        data={"booking_id": str(booking_id)},
        dedupe_prefix=f"new-booking:{booking_id}",
    )


def notify_assignment(
    db: Session,
    *,
    business_id: uuid.UUID,
    assignee_user_id: uuid.UUID,
    kind: str,
    record_id: uuid.UUID,
    title: str,
) -> bool:
    ntype = "lead_assigned" if kind == "lead" else "system"
    result = create_notification(
        db,
        business_id=business_id,
        recipient_user_id=assignee_user_id,
        notification_type=ntype,
        title=title[:200],
        body=f"A {kind} was assigned to you. Please follow up.",
        source_type=kind,
        source_id=record_id,
        data={f"{kind}_id": str(record_id)},
        dedupe_key=f"assigned:{kind}:{record_id}:{assignee_user_id}",
    )
    return result is not None


def notify_task_assigned(
    db: Session,
    *,
    business_id: uuid.UUID,
    assignee_user_id: uuid.UUID,
    task_id: uuid.UUID,
    title: str,
) -> bool:
    label = (title or "A task").strip()[:120] or "A task"
    result = create_notification(
        db,
        business_id=business_id,
        recipient_user_id=assignee_user_id,
        notification_type="task_assigned",
        title=f"Task assigned: {label}",
        body="A task was assigned to you. Please review it before the due date.",
        source_type="task",
        source_id=task_id,
        data={"task_id": str(task_id)},
        dedupe_key=f"assigned:task:{task_id}:{assignee_user_id}",
    )
    return result is not None


def notify_task_completed(
    db: Session,
    *,
    business_id: uuid.UUID,
    task_id: uuid.UUID,
    title: str,
    actor_user_id: uuid.UUID | None = None,
) -> int:
    label = (title or "A task").strip()[:120] or "A task"
    return notify_staff(
        db,
        business_id=business_id,
        notification_type="task_completed",
        title=f"Task completed: {label}",
        body="A staff task was marked complete.",
        source_type="task",
        source_id=task_id,
        data={"task_id": str(task_id)},
        dedupe_prefix=f"task-completed:{task_id}",
        exclude_user_id=actor_user_id,
    )


def list_mine(
    db: Session,
    *,
    business_id: uuid.UUID,
    user_id: uuid.UUID,
    unread_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
):
    return notif_repo.list_for_recipient(
        db,
        business_id=business_id,
        recipient_user_id=user_id,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


def unread_count(db: Session, *, business_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return notif_repo.count_unread(
        db, business_id=business_id, recipient_user_id=user_id
    )


def mark_read(
    db: Session, *, business_id: uuid.UUID, user_id: uuid.UUID, notification_id: object
):
    notification = notif_repo.get_for_recipient(
        db,
        notification_id=notification_id,
        business_id=business_id,
        recipient_user_id=user_id,
    )
    # Uniform 404: foreign/other-user rows behave as nonexistent (no oracle).
    if notification is None:
        raise NotFoundError("Notification not found.")
    if notification.read_at is None:
        notification.read_at = _utcnow()
        db.flush()
    return notification


def mark_all_read(db: Session, *, business_id: uuid.UUID, user_id: uuid.UUID) -> int:
    marked = notif_repo.mark_all_read(
        db, business_id=business_id, recipient_user_id=user_id, now=_utcnow()
    )
    db.flush()
    return marked


def set_preference(
    db: Session,
    *,
    business_id: uuid.UUID,
    user_id: uuid.UUID,
    notification_type: str,
    enabled: bool,
):
    pref = notif_repo.set_preference(
        db,
        user_id=user_id,
        business_id=business_id,
        notification_type=_validate_type(notification_type),
        enabled=bool(enabled),
    )
    db.flush()
    return pref
