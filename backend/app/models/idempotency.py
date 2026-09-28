"""Idempotency records for public mutating requests (Block 2).

(``business_id``, ``endpoint``, ``idem_key``) is unique so concurrent
duplicate POSTs collapse to one business mutation. Bounded by design:
rows carry ``created_at`` for retention cleanup (see service docs).
"""

from __future__ import annotations

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class IdempotencyRecord(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "endpoint",
            "idem_key",
            name="uq_idempotency_scope_key",
        ),
        Index("ix_idempotency_created", "created_at"),
    )

    id = uuid_pk()
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    idem_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # SHA-256 hex of the canonical request payload (same key + different
    # payload => 409, never silent overwrite).
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Filled on completion; NULL while the first request is in flight.
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(SA_JSON(), nullable=True)
