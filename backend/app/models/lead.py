"""Lead + LeadActivity models (Block 2 CRM foundation)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class Lead(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_business_status", "business_id", "status"),
        Index("ix_leads_business_created", "business_id", "created_at"),
        Index("ix_leads_business_assigned", "business_id", "assigned_user_id"),
        Index("ix_leads_business_phone", "business_id", "normalized_phone"),
        Index("ix_leads_business_email", "business_id", "normalized_email"),
        Index("ix_leads_business_follow_up", "business_id", "follow_up_at"),
    )

    id = uuid_pk()
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("contacts.id", ondelete="set null"),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("customers.id", ondelete="set null"),
        nullable=True,
        index=True,
    )
    # Snapshot of the name as given (contact may be unresolved at intake).
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    normalized_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="website")
    source_detail: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="set null"),
        nullable=True,
    )
    service_interest: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    message: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    follow_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lost_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    consent_marketing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    landing_page: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    referrer: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    utm_source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    utm_medium: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    utm_campaign: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    utm_term: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    utm_content: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Lead routing metadata (Block 3): how this lead reached its owning
    # business. Set at intake (slug/intent/default) or on explicit staff
    # transfer. Auditable; never silently rewritten.
    routed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    routing_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    routed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    contact: Mapped["Contact | None"] = relationship("Contact", back_populates="leads")
    activities: Mapped[list["LeadActivity"]] = relationship(
        "LeadActivity",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="LeadActivity.created_at",
    )
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking", back_populates="lead", passive_deletes=True
    )


class LeadActivity(Base, BusinessScopedMixin, TimestampMixin):
    """Append-only CRM history (notes, status/assignment changes, conversions)."""

    __tablename__ = "lead_activities"
    __table_args__ = (
        Index("ix_lead_activities_lead_created", "lead_id", "created_at"),
        Index("ix_lead_activities_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("leads.id", ondelete="cascade"),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="set null"),
        nullable=True,
    )
    activity_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default="note"
    )
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")

    lead: Mapped["Lead"] = relationship("Lead", back_populates="activities")
