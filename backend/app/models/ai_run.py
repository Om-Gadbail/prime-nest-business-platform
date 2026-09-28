"""AI run audit metadata (Block 2 AI foundation).

Metadata ONLY: provider, model, capability, status, latency, token usage,
correlation ID. Raw prompts/outputs (which may contain customer PII) are
never persisted here.
"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class AIRun(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "ai_runs"
    __table_args__ = (
        Index("ix_ai_runs_business_created", "business_id", "created_at"),
        Index("ix_ai_runs_business_capability", "business_id", "capability"),
    )

    id = uuid_pk()
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="noop")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error: Mapped[str] = mapped_column(String(500), nullable=False, default="")
