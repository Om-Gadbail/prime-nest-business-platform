"""Business membership model (user <-> business <-> role)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

MEMBERSHIP_STATUSES = {"active", "suspended", "revoked"}


class BusinessMembership(Base, TimestampMixin):
    __tablename__ = "business_memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "business_id", name="uq_business_memberships_user_business"
        ),
        Index("ix_business_memberships_user_id", "user_id"),
        Index("ix_business_memberships_business_id", "business_id"),
        Index("ix_business_memberships_role_id", "role_id"),
    )

    id = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="cascade"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("roles.id", ondelete="restrict"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship("User", back_populates="memberships")
    business: Mapped["Business"] = relationship(
        "Business", back_populates="memberships"
    )
    role: Mapped["Role"] = relationship("Role", back_populates="memberships")
