"""Owner command-center + staff analytics read contracts (Block 5).

All values are server-computed aggregates. Money serializes as strings
(Decimal-safe); rates are floats in [0, 1] with documented formulas.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BusinessRef(BaseModel):
    id: str
    slug: str
    name: str
    business_type: str


class MembershipStats(BaseModel):
    active_memberships: int = 0
    active_members: int = 0
    new_members_today: int = 0
    expiring_soon: int = 0
    expired: int = 0
    by_status: dict = Field(default_factory=dict)
    total: int = 0


class RevenueStats(BaseModel):
    collected: str = "0.00"
    pending: str = "0.00"
    overdue: str = "0.00"
    refunded: str = "0.00"
    payment_count: int = 0
    average_transaction: str = "0.00"
    by_status: dict = Field(default_factory=dict)
    by_method: dict = Field(default_factory=dict)


class LeadFunnel(BaseModel):
    total: int = 0
    by_status: dict = Field(default_factory=dict)
    by_source: dict = Field(default_factory=dict)
    converted: int = 0
    eligible: int = 0
    lead_conversion_rate: float = 0.0
    booked: int = 0
    booking_conversion_rate: float = 0.0


class BookingStats(BaseModel):
    by_status: dict = Field(default_factory=dict)
    total: int = 0


class AttendanceStats(BaseModel):
    total: int = 0
    currently_checked_in: int | None = None
    by_source: dict = Field(default_factory=dict)


class RenewalStats(BaseModel):
    by_status: dict = Field(default_factory=dict)
    total: int = 0
    due_soon: int = 0
    overdue: int = 0
    pending_amount: str = "0.00"


class SeatStats(BaseModel):
    total: int = 0
    available: int = 0
    allocated_active: int = 0
    by_status: dict = Field(default_factory=dict)


class OwnerBusinessOverview(BaseModel):
    business: BusinessRef
    generated_at: datetime
    membership: MembershipStats
    revenue: RevenueStats
    leads: LeadFunnel
    bookings: BookingStats
    attendance_today: AttendanceStats
    renewals: RenewalStats
    seats: SeatStats | None = None


class OwnerRevenueReport(BaseModel):
    business_id: str
    generated_at: datetime
    window: dict = Field(default_factory=dict)
    summary: RevenueStats
    daily_trend: list = Field(default_factory=list)


class OwnerLeadsReport(BaseModel):
    business_id: str
    generated_at: datetime
    formulas: dict = Field(default_factory=dict)
    funnel: LeadFunnel
    daily_trend: list = Field(default_factory=list)


class CombinedBusinessItem(BaseModel):
    business: BusinessRef
    revenue: RevenueStats
    leads: LeadFunnel
    membership: MembershipStats
    attendance_today: AttendanceStats
    renewals: RenewalStats
    seats: SeatStats | None = None


class CombinedOverview(BaseModel):
    generated_at: datetime
    scope: str
    totals: dict = Field(default_factory=dict)
    businesses: list[CombinedBusinessItem] = Field(default_factory=list)


class OwnerAlertItem(BaseModel):
    severity: str = Field(description="critical | warning | info")
    business: dict = Field(default_factory=dict)
    category: str = Field(
        description="finance | membership | leads | attendance | automation"
    )
    title: str
    detail: str = ""
    count: int = 0
    observed_at: datetime
    drill: str = Field(
        description="Owner UI section hint: payments | renewals | members | leads | automation"
    )


class OwnerAlertsReport(BaseModel):
    generated_at: datetime
    scope: str
    combined: bool = False
    window: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)
    total: int = 0
    alerts: list[OwnerAlertItem] = Field(default_factory=list)


class OwnerScopeBusiness(BaseModel):
    business: BusinessRef
    metrics: dict = Field(default_factory=dict)


class OwnerGrowthReport(BaseModel):
    generated_at: datetime
    scope: str
    combined: bool = False
    window: dict = Field(default_factory=dict)
    businesses: list[OwnerScopeBusiness] = Field(default_factory=list)


class OwnerRenewalsItem(BaseModel):
    business: BusinessRef
    buckets: dict = Field(default_factory=dict)


class OwnerRenewalsReport(BaseModel):
    generated_at: datetime
    scope: str
    combined: bool = False
    businesses: list[OwnerRenewalsItem] = Field(default_factory=list)


class OwnerPaymentsItem(BaseModel):
    business: BusinessRef
    health: dict = Field(default_factory=dict)


class OwnerPaymentsReport(BaseModel):
    generated_at: datetime
    scope: str
    combined: bool = False
    window: dict = Field(default_factory=dict)
    businesses: list[OwnerPaymentsItem] = Field(default_factory=list)


class OwnerAttendanceItem(BaseModel):
    business: BusinessRef
    attendance: dict = Field(default_factory=dict)


class OwnerAttendanceReport(BaseModel):
    generated_at: datetime
    scope: str
    combined: bool = False
    window: dict = Field(default_factory=dict)
    businesses: list[OwnerAttendanceItem] = Field(default_factory=list)


class OwnerAutomationItem(BaseModel):
    business: BusinessRef
    health: dict = Field(default_factory=dict)


class OwnerAutomationReport(BaseModel):
    generated_at: datetime
    scope: str
    combined: bool = False
    businesses: list[OwnerAutomationItem] = Field(default_factory=list)
