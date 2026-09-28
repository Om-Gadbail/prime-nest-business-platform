"""Staff task model — business-scoped operational work items (Block 4).

Tasks link staff to follow-ups: lead follow-ups, booking confirmations,
or free-form operational work. Optional ``related_entity_*`` deep-links a
task to a lead/booking/contact/customer IN THE SAME BUSINESS (validated
server-side; foreign rows behave as nonexistent).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class Task(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_business_status", "business_id", "status"),
        Index("ix_tasks_business_assignee", "business_id", "assigned_to_user_id"),
        Index("ix_tasks_business_due", "business_id", "due_at"),
        Index("ix_tasks_business_created", "business_id", "created_at"),
        Index("ix_tasks_business_creator", "business_id", "created_by_user_id"),
    )

    id = uuid_pk()
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="set null"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="set null"),
        nullable=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    related_entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
