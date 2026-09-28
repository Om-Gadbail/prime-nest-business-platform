"""Blocks 8-12 AI business-layer models (conversations, tool calls, recommendations).

Website Chat and WhatsApp share ONE conversation/agent runtime; only the
channel adapter differs. AI never gets raw DB access — only narrow tools.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIConversation(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        Index("ix_ai_conv_business_channel", "business_id", "channel"),
        Index("ix_ai_conv_business_status", "business_id", "status"),
        Index("ix_ai_conv_business_visitor", "business_id", "visitor_key"),
    )

    id = uuid_pk()
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    visitor_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    # public | staff | owner
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="set null"), nullable=True
    )
    escalated: Mapped[bool] = mapped_column(nullable=False, default=False)
    consent: Mapped[bool] = mapped_column(nullable=False, default=False)


class AIMessage(Base, BusinessScopedMixin):
    __tablename__ = "ai_messages"
    __table_args__ = (
        Index("ix_ai_msg_business_conv", "business_id", "conversation_id"),
        Index("ix_ai_msg_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_conversations.id", ondelete="cascade"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(String(8000), nullable=False, default="")
    tool_calls: Mapped[list] = mapped_column(SA_JSON, nullable=False, default=list)
    tool_results: Mapped[list] = mapped_column(SA_JSON, nullable=False, default=list)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AIToolCall(Base, BusinessScopedMixin):
    __tablename__ = "ai_tool_calls"
    __table_args__ = (
        Index("ix_ai_tool_business_conv", "business_id", "conversation_id"),
        Index("ix_ai_tool_business_tool", "business_id", "tool_name"),
        Index("ix_ai_tool_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_conversations.id", ondelete="set null"), nullable=True
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    caller: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AIRecommendation(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "ai_recommendations"
    __table_args__ = (
        Index("ix_ai_rec_business_status", "business_id", "status"),
        Index("ix_ai_rec_business_type", "business_id", "rec_type"),
        Index("ix_ai_rec_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    rec_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    reason: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    supporting_data: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    suggested_action: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="ai")
