"""Unified identity models — global person + per-business links (Block 3).

Goal: the same real-world person may interact with Prime Fitness AND
Nest Library. The platform links those per-business relationships to one
global ``Person`` WITHOUT breaking business isolation:

- ``persons`` holds ONLY normalized matching signals (phone/email) +
  timestamps — no names, no messages, no business data.
- ``identity_links`` joins one person to one contact within one business.
- Matching is strict equality on normalized phone/email only. Ambiguous
  or weak signals NEVER auto-merge — identities stay separate.
- Cross-business visibility requires the ``identity.read`` permission
  (OWNER/ADMIN only). Normal STAFF users can never enumerate another
  business's relationships through this table.

Phone/email are NOT globally unique on contacts/customers (family
sharing stays allowed); ``persons`` uniqueness is on the normalized
signal with NULLs permitted, so concurrent creation collapses via the
unique constraint + retry instead of duplicating.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


class Person(Base, TimestampMixin):
    __tablename__ = "persons"
    __table_args__ = (
        # NULLs are distinct in Postgres + SQLite: only real signals dedupe.
        UniqueConstraint("normalized_phone", name="uq_persons_normalized_phone"),
        UniqueConstraint("normalized_email", name="uq_persons_normalized_email"),
        Index("ix_persons_phone", "normalized_phone"),
        Index("ix_persons_email", "normalized_email"),
    )

    id = uuid_pk()
    normalized_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    normalized_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    links: Mapped[list["IdentityLink"]] = relationship(
        "IdentityLink", back_populates="person", passive_deletes=True
    )


class IdentityLink(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "identity_links"
    __table_args__ = (
        # One link per contact per business (concurrency safety relies on
        # this constraint + transactional service logic).
        UniqueConstraint(
            "business_id", "contact_id", name="uq_identity_links_business_contact"
        ),
        Index("ix_identity_links_person", "person_id"),
        Index("ix_identity_links_business_person", "business_id", "person_id"),
    )

    id = uuid_pk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("persons.id", ondelete="restrict"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("contacts.id", ondelete="cascade"),
        nullable=False,
    )
    # auto (strict normalized match at intake) | manual (explicit staff link)
    link_type: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    # phone | email | both | manual — which signal justified the link.
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="set null"),
        nullable=True,
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    person: Mapped["Person"] = relationship("Person", back_populates="links")
