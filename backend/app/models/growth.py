"""Blocks 8-12 growth + intelligence models (business-scoped, configurable).

No hardcoded Prime<->Nest branches: BusinessRelationship rows configure
cross-business links; sources are data rows, not enums in code.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from decimal import Decimal

from app.models.base import Base, BusinessScopedMixin, TimestampMixin, uuid_pk


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GrowthSource(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "growth_sources"
    __table_args__ = (
        UniqueConstraint("business_id", "code", name="uq_growth_sources_business_code"),
    )

    id = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Attribution(Base, BusinessScopedMixin):
    __tablename__ = "attributions"
    __table_args__ = (
        Index("ix_attr_business_source", "business_id", "source_code"),
        Index("ix_attr_business_subject", "business_id", "subject_type", "subject_id"),
        Index("ix_attr_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default="other"
    )
    campaign: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    landing_page: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    referrer: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    utm: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    converted: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Monetary attribution revenue in major units (same NUMERIC(12,2) standard
    # as payments/memberships). Never floats, never lexical strings.
    revenue: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Referral(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "referrals"
    __table_args__ = (
        Index("ix_referrals_business_status", "business_id", "status"),
        Index("ix_referrals_business_created", "business_id", "created_at"),
    )

    id = uuid_pk()
    referrer_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    referrer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    referrer_member_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    referred_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    referred_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    referred_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="set null"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    consent: Mapped[bool] = mapped_column(nullable=False, default=False)
    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")


class CrossSellOpportunity(Base, BusinessScopedMixin, TimestampMixin):
    __tablename__ = "cross_sell_opportunities"
    __table_args__ = (
        Index("ix_xsell_business_status", "business_id", "status"),
        Index("ix_xsell_business_target", "business_id", "target_business_id"),
    )

    id = uuid_pk()
    # Owning business = source business; target = business being offered.
    target_business_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="set null"), nullable=True
    )
    member_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    eligibility_reason: Mapped[str] = mapped_column(
        String(1000), nullable=False, default=""
    )
    offer: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="eligible")
    consent: Mapped[bool] = mapped_column(nullable=False, default=False)
    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BusinessRelationship(Base, TimestampMixin):
    """Global (not business-scoped): configured link between two businesses."""

    __tablename__ = "business_relationships"
    __table_args__ = (
        UniqueConstraint(
            "from_business_id",
            "to_business_id",
            name="uq_business_rel_from_to",
        ),
    )

    id = uuid_pk()
    from_business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="cascade"), nullable=False
    )
    to_business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="cascade"), nullable=False
    )
    rel_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="cross_sell"
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    config: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)


class AnalyticsSnapshot(Base, BusinessScopedMixin):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "period",
            "metric_key",
            name="uq_analytics_business_period_metric",
        ),
        Index("ix_analytics_business_period", "business_id", "period"),
    )

    id = uuid_pk()
    period: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # e.g. 2026-09-26:30d
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Numeric metric value (counts stored as e.g. 42.00, money as 1234.50).
    # NUMERIC keeps SQL SUM/AVG/ordering correct; API serialization stays
    # backwards-compatible (ints for counts, "%.2f" strings for revenue).
    value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00")
    )
    dimensions: Mapped[dict] = mapped_column(SA_JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
