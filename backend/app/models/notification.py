"""In-app notification foundation (Block 2).

Only the in-app channel is real in this block. Email/WhatsApp remain
adapter interfaces in the service layer (no fake delivery statuses).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class Notification(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        # Dedupe repeats of the same event for the same recipient; NULL keys
        # stay repeatable (Postgres + SQLite treat NULLs as distinct).
        UniqueConstraint(
            "business_id",
            "recipient_user_id",
            "dedupe_key",
            name="uq_notifications_recipient_dedupe",
        ),
        Index(
            "ix_notifications_recipient_unread",
            "business_id",
            "recipient_user_id",
            "read_at",
        ),
        Index("ix_notifications_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default="system"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Small structured payload for deep-links/counters. Never secrets.
    data: Mapped[dict] = mapped_column(SA_JSON(), nullable=False, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NotificationPreference(Base, TimestampMixin):
    """Per-user, per-business opt-out for notification types (default: enabled)."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="cascade"),
        primary_key=True,
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="cascade"),
        primary_key=True,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(String(48), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
