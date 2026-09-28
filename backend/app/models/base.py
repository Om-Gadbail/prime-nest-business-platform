"""SQLAlchemy declarative base + shared mixins.

MULTI-TENANCY (Block 1):
  - `businesses` table is the tenant root.
  - Tenant-owned tables carry `business_id -> businesses.id` via
    `BusinessScopedMixin`. Repositories MUST filter by `business_id`
    derived from the authenticated context (never from client input).

Nothing here is hardcoded to any single business. Keep it that way.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Consistent constraint/index naming so Alembic autogenerate diffs are stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Reusable created/updated timestamps for future models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary key column factory (native UUID on Postgres, CHAR on SQLite)."""
    return mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )


class BusinessScopedMixin:
    """Mixin for tenant-owned tables.

    Adds a non-nullable ``business_id`` FK to ``businesses.id``.

    IMPORTANT: every query against a model using this mixin MUST be scoped
    with ``business_id`` from the authenticated context. Use the helpers in
    ``app.repositories.base`` (``apply_business_scope`` / ``get_scoped`` /
    ``list_scoped``) — never trust client-provided business identifiers.
    """

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="restrict"),
        nullable=False,
        index=True,
    )
