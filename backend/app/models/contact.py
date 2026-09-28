"""Contact model — reusable business-scoped contact identity.

One row per real-world person per business. Uniqueness is deliberately NOT
enforced on phone/email (families share numbers); matching/dedup happens in
services via normalized fields + explicit staff merge later.
"""

from __future__ import annotations

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class Contact(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_business_created", "business_id", "created_at"),
        Index("ix_contacts_business_phone", "business_id", "normalized_phone"),
        Index("ix_contacts_business_email", "business_id", "normalized_email"),
    )

    id = uuid_pk()
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    normalized_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    preferred_contact_channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="other"
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    customers: Mapped[list["Customer"]] = relationship(
        "Customer", back_populates="contact", passive_deletes=True
    )
    leads: Mapped[list["Lead"]] = relationship(
        "Lead", back_populates="contact", passive_deletes=True
    )
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking", back_populates="contact", passive_deletes=True
    )

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
