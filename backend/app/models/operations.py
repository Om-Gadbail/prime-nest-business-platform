"""Blocks 5-7 operational domain models.

Reusable Business Operations Platform tables shared by Prime Fitness,
Nest Library, and future businesses:

- ``Member`` (BUSINESS_SCOPED) — operational member profile linked to the
  existing CRM identity (``customers``/``contacts``). Never a duplicate
  identity: ``customer_id`` is unique per business when set.
- ``MembershipPlan`` (BUSINESS_SCOPED) — data-driven plan catalogue
  (Nest pricing lives here, not in UI code). Historical pricing is
  snapshotted onto ``Membership`` rows so plan edits never rewrite history.
- ``Membership`` (BUSINESS_SCOPED) — one member <-> plan enrolment with
  explicit lifecycle. ``status`` (lifecycle) and ``payment_state`` are
  separate concepts by design.
- ``Payment`` (BUSINESS_SCOPED) — provider-neutral fee records with
  idempotency keys. No provider secrets live here.
- ``Attendance`` (BUSINESS_SCOPED) — one row per member per day
  (unique constraint = duplicate-submit safety).
- ``Renewal`` (BUSINESS_SCOPED) — renewal pipeline records linking the
  expiring membership to its replacement.
- ``SeatArea`` / ``Seat`` (BUSINESS_SCOPED) — seat inventory for
  seat-based businesses (Nest). Generic: floors/zones/sections via areas.
- ``SeatAllocation`` (BUSINESS_SCOPED) — exclusive seat assignments.
  Partial unique indexes guarantee at most one ACTIVE allocation per
  seat AND per member (race-safe at the DB layer, not just in Python).
- ``Approval`` (BUSINESS_SCOPED) — owner approval/control foundation.
- ``DomainEvent`` (BUSINESS_SCOPED) — durable hook log for future Block 8
  automation (services emit; nothing consumes yet).

Table classification (isolation model):
- GLOBAL: Person (existing), Business, Role/Permission (existing).
- BUSINESS_SCOPED: every table in this module.
- USER_SCOPED: none here (AuthSession covers sessions).
- SYSTEM: Alembic revisions, idempotency handled per-business here.

Money: NUMERIC(12, 2) major units + explicit currency. Never floats.
Time: timezone-aware timestamps; membership/attendance dates are plain
DATEs interpreted in the business timezone by services.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON as SA_JSON,
)
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))


class Member(Base, BusinessScopedMixin, TimestampMixin):
    """Operational member profile (Block 6 step 28 / Block 7 step 33).

    Integrates with the CRM identity: ``customer_id`` (and ``contact_id``)
    reference the existing per-business CRM rows. ``customer_id`` is unique
    per business when set — one operational profile per customer.
    """

    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "customer_id", name="uq_members_business_customer"
        ),
        Index("ix_members_business_status", "business_id", "status"),
        Index("ix_members_business_created", "business_id", "created_at"),
        Index("ix_members_business_phone", "business_id", "normalized_phone"),
        Index("ix_members_business_email", "business_id", "normalized_email"),
        Index("ix_members_business_contact", "business_id", "contact_id"),
    )

    id = uuid_pk()
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("customers.id", ondelete="restrict"),
        nullable=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("contacts.id", ondelete="set null"),
        nullable=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("leads.id", ondelete="set null"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    normalized_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    emergency_contact_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    seat_preference: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )

    memberships: Mapped[list["Membership"]] = relationship(
        "Membership", back_populates="member", passive_deletes=True
    )


class MembershipPlan(Base, BusinessScopedMixin, TimestampMixin):
    """Data-driven membership plan catalogue (Block 7 step 34).

    Nest pricing lives in rows of this table (seeded), never in UI code.
    Edits create no side effects on history: ``Membership`` snapshots the
    price actually charged.
    """

    __tablename__ = "membership_plans"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "code", name="uq_membership_plans_business_code"
        ),
        Index("ix_membership_plans_business_active", "business_id", "is_active"),
        Index("ix_membership_plans_business_category", "business_id", "category"),
    )

    id = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price: Mapped[Decimal] = _money()
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    is_best_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    features: Mapped[dict] = mapped_column(SA_JSON(), nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )

    memberships: Mapped[list["Membership"]] = relationship(
        "Membership", back_populates="plan", passive_deletes=True
    )


class Membership(Base, BusinessScopedMixin, TimestampMixin):
    """Operational membership enrolment (Block 6 step 27).

    ``status`` = lifecycle state; ``payment_state`` = money state. The two
    are deliberately independent columns.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "idempotency_key",
            name="uq_memberships_business_idem",
        ),
        Index("ix_memberships_business_member", "business_id", "member_id"),
        Index("ix_memberships_business_status", "business_id", "status"),
        Index("ix_memberships_business_end", "business_id", "end_date"),
        Index("ix_memberships_business_plan", "business_id", "plan_id"),
        Index("ix_memberships_business_payment", "business_id", "payment_state"),
    )

    id = uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("members.id", ondelete="restrict"),
        nullable=False,
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("membership_plans.id", ondelete="set null"),
        nullable=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="set null"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payment_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unpaid"
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Historical price snapshot (NUMERIC major units + currency).
    price: Mapped[Decimal] = _money()
    discount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    final_amount: Mapped[Decimal] = _money()
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    plan_name_snapshot: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    plan_version_snapshot: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    cancel_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    renewed_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="set null"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )

    member: Mapped["Member"] = relationship("Member", back_populates="memberships")
    plan: Mapped["MembershipPlan | None"] = relationship(
        "MembershipPlan", back_populates="memberships"
    )


class Payment(Base, BusinessScopedMixin, TimestampMixin):
    """Provider-neutral fee/payment record (Block 6 step 29).

    Adapters (cash/UPI/gateway…) plug in behind ``method``/``provider``;
    core business logic never branches on a provider name. ``provider_ref``
    and webhook secrets are NEVER exposed to the frontend.
    """

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "idempotency_key", name="uq_payments_business_idem"
        ),
        Index("ix_payments_business_member", "business_id", "member_id"),
        Index("ix_payments_business_membership", "business_id", "membership_id"),
        Index("ix_payments_business_status", "business_id", "status"),
        Index("ix_payments_business_created", "business_id", "created_at"),
        Index("ix_payments_business_due", "business_id", "due_at"),
    )

    id = uuid_pk()
    member_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("members.id", ondelete="set null"), nullable=True
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="set null"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="set null"), nullable=True
    )
    amount: Mapped[Decimal] = _money()
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    provider_ref: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    invoice_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )


class Attendance(Base, BusinessScopedMixin, TimestampMixin):
    """Daily attendance / check-in record (Block 6 step 30, Block 7 step 37).

    One row per member per day — the unique constraint makes duplicate
    submissions (double-tap, retry, kiosk bounce) collapse safely.
    """

    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "member_id",
            "attendance_date",
            name="uq_attendance_business_member_day",
        ),
        Index("ix_attendance_business_day", "business_id", "attendance_date"),
        Index("ix_attendance_business_member", "business_id", "member_id"),
        Index("ix_attendance_business_seat", "business_id", "seat_id"),
    )

    id = uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("members.id", ondelete="restrict"), nullable=False
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="set null"), nullable=True
    )
    seat_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("seats.id", ondelete="set null"), nullable=True
    )
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    checked_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    notes: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )


class Renewal(Base, BusinessScopedMixin, TimestampMixin):
    """Renewal pipeline record (Block 6 step 31, Block 7 step 38).

    A renewal links the expiring ``membership`` to its replacement
    (``new_membership``). Expiry never deletes history — including seat
    history for confirmed-seat memberships.
    """

    __tablename__ = "renewals"
    __table_args__ = (
        Index("ix_renewals_business_member", "business_id", "member_id"),
        Index("ix_renewals_business_status", "business_id", "status"),
        Index("ix_renewals_business_due", "business_id", "due_date"),
        Index("ix_renewals_business_membership", "business_id", "membership_id"),
    )

    id = uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("members.id", ondelete="restrict"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="restrict"), nullable=False
    )
    new_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="set null"), nullable=True
    )
    previous_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("membership_plans.id", ondelete="set null"), nullable=True
    )
    new_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("membership_plans.id", ondelete="set null"), nullable=True
    )
    renewal_amount: Mapped[Decimal] = _money()
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    renewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )


class SeatArea(Base, BusinessScopedMixin, TimestampMixin):
    """Seat zone/floor/section container (Block 7 step 35).

    Physical layout stays configurable: areas carry floor/zone labels, seats
    hang off areas. No hardcoded floor plans anywhere.
    """

    __tablename__ = "seat_areas"
    __table_args__ = (
        UniqueConstraint("business_id", "code", name="uq_seat_areas_business_code"),
        Index("ix_seat_areas_business_floor", "business_id", "floor"),
    )

    id = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    floor: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    seats: Mapped[list["Seat"]] = relationship(
        "Seat", back_populates="area", passive_deletes=True
    )


class Seat(Base, BusinessScopedMixin, TimestampMixin):
    """Seat inventory record (Block 7 step 35)."""

    __tablename__ = "seats"
    __table_args__ = (
        UniqueConstraint("business_id", "seat_number", name="uq_seats_business_number"),
        Index("ix_seats_business_status", "business_id", "status"),
        Index("ix_seats_business_area", "business_id", "area_id"),
        Index("ix_seats_business_type", "business_id", "seat_type"),
    )

    id = uuid_pk()
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("seat_areas.id", ondelete="set null"), nullable=True
    )
    seat_number: Mapped[str] = mapped_column(String(64), nullable=False)
    seat_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="regular"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    notes: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )

    area: Mapped["SeatArea | None"] = relationship("SeatArea", back_populates="seats")


class SeatAllocation(Base, BusinessScopedMixin, TimestampMixin):
    """Exclusive seat assignment (Block 7 step 36).

    CONCURRENCY CONTRACT: at most one ACTIVE allocation per seat and at
    most one ACTIVE allocation per member. Enforced by partial unique
    indexes (Postgres + SQLite both support them) so concurrent requests
    cannot double-assign even if both pass the Python check.
    """

    __tablename__ = "seat_allocations"
    __table_args__ = (
        Index("ix_seat_alloc_business_seat", "business_id", "seat_id"),
        Index("ix_seat_alloc_business_member", "business_id", "member_id"),
        Index("ix_seat_alloc_business_status", "business_id", "status"),
        # Partial unique indexes: only rows with status='active' participate,
        # so history (released/transferred) never collides. Both Postgres
        # and SQLite enforce these at the DB layer (race-safe).
        Index(
            "uq_seat_alloc_active_seat",
            "seat_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_seat_alloc_active_member",
            "member_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = uuid_pk()
    seat_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("seats.id", ondelete="restrict"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("members.id", ondelete="restrict"), nullable=False
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="set null"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    allocated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )
    released_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )


class Approval(Base, BusinessScopedMixin, TimestampMixin):
    """Owner approval/control request (Block 5 step: approval foundation).

    Polymorphic: ``entity_type``/``entity_id`` reference any operational
    record (membership, payment, refund, seat transfer…). Sensitive
    operations stay PENDING until an authorized owner/admin decides.
    """

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_business_status", "business_id", "status"),
        Index("ix_approvals_business_entity", "business_id", "entity_type"),
        Index("ix_approvals_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="approve")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    reason: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    meta: Mapped[dict] = mapped_column(SA_JSON(), nullable=False, default=dict)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")


class DomainEvent(Base, BusinessScopedMixin):
    """Durable domain-event hook log (future Block 8 automation).

    Services emit events here (and mirror key ones to audit). Nothing in
    Blocks 5-7 consumes them — they are extension points. Payloads carry
    IDs + safe metadata only: no secrets, no unnecessary PII.
    Append-only: no update/delete paths exist.
    """

    __tablename__ = "domain_events"
    __table_args__ = (
        Index("ix_domain_events_business_type", "business_id", "event_type"),
        Index("ix_domain_events_business_created", "business_id", "created_at"),
        Index(
            "ix_domain_events_business_entity",
            "business_id",
            "entity_type",
            "entity_id",
        ),
    )

    id = uuid_pk()
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="set null"), nullable=True
    )
    payload: Mapped[dict] = mapped_column(SA_JSON(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


__all__ = [
    "Approval",
    "Attendance",
    "DomainEvent",
    "Member",
    "Membership",
    "MembershipPlan",
    "Payment",
    "Renewal",
    "Seat",
    "SeatAllocation",
    "SeatArea",
]
