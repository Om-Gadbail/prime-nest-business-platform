"""Business settings model (one row per business, JSONB sections)."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def _json_column(default: dict | None = None):  # type: ignore[no-untyped-def]
    """Portable JSON column (JSONB on Postgres via migration, JSON on SQLite)."""
    if default is None:
        default = {}
    return mapped_column(
        SA_JSON(),
        nullable=False,
        default=dict,
        server_default="{}",
    )


class BusinessSettings(Base, TimestampMixin):
    __tablename__ = "business_settings"

    # One-to-one: business_id is both PK and FK.
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="cascade"),
        primary_key=True,
    )

    branding: Mapped[dict] = _json_column()
    contact: Mapped[dict] = _json_column()
    address: Mapped[dict] = _json_column()
    hours: Mapped[dict] = _json_column()
    localization: Mapped[dict] = _json_column()
    operational: Mapped[dict] = _json_column()

    business: Mapped["Business"] = relationship("Business", back_populates="settings")
