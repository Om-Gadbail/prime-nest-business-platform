"""User model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = uuid_pk()
    # Always stored normalized (lowercased + stripped) — enforced in services.
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    # Argon2id hash via pwdlib. NEVER exposed via API.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list["BusinessMembership"]] = relationship(
        "BusinessMembership", back_populates="user", passive_deletes=True
    )
    auth_sessions: Mapped[list["AuthSession"]] = relationship(
        "AuthSession", back_populates="user", passive_deletes=True
    )
