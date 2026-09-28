"""Audit event model — append-only business-scoped activity log (Block 4).

This is NOT debug logging. One row per important business/security
operation (lead assigned, booking confirmed, task completed, login,
permission denial, cross-business access attempt, ...).

Rules:
- Rows are NEVER updated or deleted through application APIs (no PUT/
  DELETE endpoints; services only INSERT + SELECT).
- ``business_id`` scopes visibility: staff only see their own business's
  events (permission ``audit.read``).
- ``meta`` carries before/after summaries, reasons, request IDs — NEVER
  secrets (passwords, tokens, API keys) or unnecessary PII. The audit
  service strips sensitive keys before persisting.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_business_created", "business_id", "created_at"),
        Index("ix_audit_events_business_actor", "business_id", "actor_user_id"),
        Index(
            "ix_audit_events_business_entity",
            "business_id",
            "entity_type",
            "entity_id",
        ),
        Index("ix_audit_events_business_action", "business_id", "action"),
    )

    id = uuid_pk()
    # Nullable ONLY for pre-authentication security events (failed login
    # with no resolvable business). Every authenticated event carries the
    # actor's business. Queries always filter by business (fail closed).
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="restrict"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="set null"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="-")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Small structured context (before/after summaries, reason, source).
    # Never secrets; service-layer sanitized.
    meta: Mapped[dict] = mapped_column(SA_JSON(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
