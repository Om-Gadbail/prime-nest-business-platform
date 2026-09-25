"""Business (tenant root) model."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

# Allowed values (validated at service/schema layer; stored as plain strings
# for SQLite/Postgres portability — no PG ENUM so tests run on SQLite).
BUSINESS_TYPES = {"fitness", "library", "other"}
BUSINESS_STATUSES = {"active", "inactive"}


class Business(Base, TimestampMixin):
    __tablename__ = "businesses"

    id = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True, default="UTC")
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    locale: Mapped[str | None] = mapped_column(String(16), nullable=True)

    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships (no cascade delete of tenant data — restrict).
    memberships: Mapped[list["BusinessMembership"]] = relationship(
        "BusinessMembership", back_populates="business", passive_deletes=True
    )
    settings: Mapped["BusinessSettings | None"] = relationship(
        "BusinessSettings", back_populates="business", uselist=False, passive_deletes=True
    )
    auth_sessions: Mapped[list["AuthSession"]] = relationship(
        "AuthSession", back_populates="business", passive_deletes=True
    )
