"""Server-side auth session model (hashed refresh tokens only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk


class AuthSession(Base, TimestampMixin):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_business_id", "business_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
        Index("ix_auth_sessions_revoked_at", "revoked_at"),
    )

    id = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
    )
    # Business context the session was issued for (nullable: user with no memberships).
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="cascade"),
        nullable=True,
    )
    # SHA-256 hex of the opaque refresh token. Raw token is NEVER stored.
    refresh_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="auth_sessions")
    business: Mapped["Business | None"] = relationship(
        "Business", back_populates="auth_sessions"
    )
