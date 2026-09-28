"""Customer model — business-scoped customer record linked to a contact.

A lead converts into a customer without losing history (lead row stays).
No gym-only or library-only fields here; later blocks extend the
customer/member relationship.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class Customer(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        # One customer record per contact per business (concurrent conversion
        # safety relies on this constraint + transactional service logic).
        UniqueConstraint(
            "business_id", "contact_id", name="uq_customers_business_contact"
        ),
        Index("ix_customers_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    contact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("contacts.id", ondelete="restrict"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    customer_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")

    contact: Mapped["Contact"] = relationship("Contact", back_populates="customers")
