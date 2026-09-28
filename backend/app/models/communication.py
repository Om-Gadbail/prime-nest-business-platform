"""Blocks 8-12 communication models (provider-neutral, business-scoped).

Business Service -> CommunicationService -> ProviderAdapter -> WhatsApp/Email/SMS.
Vendor specifics stay in adapters; these tables are channel-generic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_business_status", "business_id", "status"),
        Index("ix_conversations_business_channel", "business_id", "channel"),
        Index("ix_conversations_business_lead", "business_id", "lead_id"),
        Index("ix_conversations_business_contact", "business_id", "contact_id"),
        Index("ix_conversations_business_updated", "business_id", "updated_at"),
        # Dedupe concurrent get_or_create: one row per (business, channel,
        # external_id) when external_id is set. Partial so rows with "" (no
        # external id) never collide. Mirrors 0007 migration index.
        Index(
            "uq_conversations_business_channel_external",
            "business_id",
            "channel",
            "external_id",
            unique=True,
            sqlite_where=text("external_id <> ''"),
            postgresql_where=text("external_id <> ''"),
        ),
    )

    id = uuid_pk()
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    external_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="set null"), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contacts.id", ondelete="set null"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="set null"), nullable=True
    )
    subject_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subject_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_marketing: Mapped[bool] = mapped_column(nullable=False, default=False)


class Message(Base, BusinessScopedMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "provider_message_id",
            name="uq_messages_business_provider",
        ),
        Index("ix_messages_business_conv", "business_id", "conversation_id"),
        Index("ix_messages_business_status", "business_id", "status"),
        Index("ix_messages_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="set null"), nullable=True
    )
    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, default="outbound"
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="whatsapp")
    sender: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    recipient: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    template_code: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="log")
    # Provider-supplied id (WhatsApp wamid, etc.). NULL = not yet assigned
    # (e.g. queued/failed before provider responded). NULLs never collide in
    # the (business_id, provider_message_id) unique constraint on Postgres
    # (or SQLite), unlike the old "" default which violated it on 2nd row.
    provider_message_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, default=None
    )
    automation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    meta: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class MessageTemplate(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("business_id", "code", name="uq_msg_templates_business_code"),
        Index("ix_msg_templates_business_channel", "business_id", "channel"),
    )

    id = uuid_pk()
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="whatsapp")
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    variables: Mapped[list] = mapped_column(SA_JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class CommunicationPreference(Base, BusinessScopedMixin, TimestampMixin):
    """Customer-facing opt-in / channel preference (not staff prefs)."""

    __tablename__ = "communication_preferences"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "channel",
            "address",
            name="uq_comm_prefs_business_channel_address",
        ),
        Index("ix_comm_prefs_business_channel", "business_id", "channel"),
    )

    id = uuid_pk()
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str] = mapped_column(String(320), nullable=False)  # phone/email
    opt_in: Mapped[bool] = mapped_column(nullable=False, default=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="set null"), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contacts.id", ondelete="set null"), nullable=True
    )


class MessageDeliveryEvent(Base, BusinessScopedMixin):
    __tablename__ = "message_delivery_events"
    __table_args__ = (
        Index("ix_msg_delivery_business_msg", "business_id", "message_id"),
        Index("ix_msg_delivery_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="set null"), nullable=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    raw: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
