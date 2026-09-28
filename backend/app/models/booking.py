"""Booking model — generic business-scoped request (Block 2).

Public intake always creates REQUESTED. Staff confirm explicitly in later
workflows. There is NO availability engine here: a REQUESTED row is a
request, never a guarantee of a slot/seat.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class Booking(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_business_start", "business_id", "requested_start_at"),
        Index("ix_bookings_business_status", "business_id", "status"),
        Index("ix_bookings_business_assigned", "business_id", "assigned_user_id"),
        Index("ix_bookings_contact", "contact_id"),
        Index("ix_bookings_lead", "lead_id"),
    )

    id = uuid_pk()
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("contacts.id", ondelete="set null"),
        nullable=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("customers.id", ondelete="set null"),
        nullable=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("leads.id", ondelete="set null"),
        nullable=True,
    )
    booking_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="enquiry"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    requested_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="set null"),
        nullable=True,
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="website")
    cancellation_reason: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )

    contact: Mapped["Contact | None"] = relationship(
        "Contact", back_populates="bookings"
    )
    lead: Mapped["Lead | None"] = relationship("Lead", back_populates="bookings")
