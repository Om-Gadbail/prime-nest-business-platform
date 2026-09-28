"""Blocks 8-12 automation models (event-driven, business-scoped).

- ``AutomationRule`` — configurable event -> conditions -> actions.
- ``AutomationExecution`` — durable, idempotent, retry-safe run record.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutomationRule(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "automation_rules"
    __table_args__ = (
        Index("ix_automation_rules_business_active", "business_id", "is_active"),
        Index("ix_automation_rules_business_event", "business_id", "event_type"),
    )

    id = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    priority: Mapped[int] = mapped_column(nullable=False, default=100)
    # Conditions: e.g. {"lead_status": "new", "source": "website"} — all must match.
    conditions: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    # Actions: list of {"type": "send_message"|"create_task"|..., "params": {...}}.
    actions: Mapped[list] = mapped_column(SA_JSON, nullable=False, default=list)
    # Config: {"cooldown_hours": 24, "max_retries": 3, "template_code": ...}.
    config: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )


class AutomationExecution(Base, BusinessScopedMixin):
    __tablename__ = "automation_executions"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "idempotency_key", name="uq_auto_exec_business_idem"
        ),
        Index("ix_auto_exec_business_status", "business_id", "status"),
        Index("ix_auto_exec_business_rule", "business_id", "rule_id"),
        Index("ix_auto_exec_business_created", "business_id", "created_at"),
        Index("ix_auto_exec_business_event", "business_id", "event_type"),
    )

    id = uuid_pk()
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("automation_rules.id", ondelete="set null"), nullable=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=5)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_payload: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    output_payload: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class DailyReport(Base, BusinessScopedMixin):
    """Cached daily owner brief payload (reproducible, auditable)."""

    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "report_date", name="uq_daily_reports_business_date"
        ),
        Index("ix_daily_reports_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    report_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    payload: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
