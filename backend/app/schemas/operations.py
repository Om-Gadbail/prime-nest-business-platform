"""Blocks 5-7 API contracts: operational domain schemas.

Money is Decimal (string-serialized); the backend is authoritative for all
financial math. IDs are UUIDs. Partial updates forbid unknown fields.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# -- members ---------------------------------------------------------------


class MemberCreate(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: str = Field(default="", max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    customer_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    status: str = Field(default="active", max_length=32)
    source: str = Field(default="other", max_length=32)
    emergency_contact_name: str = Field(default="", max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    seat_preference: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)


class MemberUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    status: str | None = Field(default=None, max_length=32)
    source: str | None = Field(default=None, max_length=32)
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    seat_preference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class MemberOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    customer_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    display_name: str
    phone: str | None = None
    email: str | None = None
    status: str
    source: str
    emergency_contact_name: str
    emergency_contact_phone: str | None = None
    seat_preference: str
    notes: str
    created_at: datetime
    updated_at: datetime


# -- plans -------------------------------------------------------------------


class PlanCreate(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)
    category: str = Field(default="custom", max_length=32)
    duration_months: int = Field(default=1, ge=1, le=60)
    price: Decimal = Field(default=Decimal("0"))
    currency: str = Field(default="INR", max_length=8)
    is_best_value: bool = False
    is_active: bool = True
    features: dict = Field(default_factory=dict)


class PlanUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=32)
    duration_months: int | None = Field(default=None, ge=1, le=60)
    price: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)
    is_best_value: bool | None = None
    is_active: bool | None = None
    features: dict | None = None


class PlanOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    name: str
    category: str
    duration_months: int
    price: Decimal
    currency: str
    is_best_value: bool
    is_active: bool
    features: dict
    version: int
    created_at: datetime
    updated_at: datetime


# -- memberships ---------------------------------------------------------------


class MembershipCreate(BaseModel):
    model_config = {"extra": "forbid"}

    member_id: uuid.UUID
    plan_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    price: Decimal | None = None
    discount: Decimal | None = None
    currency: str = Field(default="INR", max_length=8)
    status: str = Field(default="pending", max_length=32)
    payment_state: str = Field(default="unpaid", max_length=32)
    notes: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(default="", max_length=64)


class MembershipStatusIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(min_length=1, max_length=32)
    cancel_reason: str = Field(default="", max_length=500)


class MembershipOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    member_id: uuid.UUID
    plan_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    status: str
    payment_state: str
    start_date: date
    end_date: date
    price: Decimal
    discount: Decimal
    final_amount: Decimal
    currency: str
    plan_name_snapshot: str
    plan_version_snapshot: int
    notes: str
    cancel_reason: str
    cancelled_at: datetime | None = None
    renewed_from_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class MembershipRenewIn(BaseModel):
    model_config = {"extra": "forbid"}

    new_plan_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    price: Decimal | None = None
    discount: Decimal | None = None
    currency: str = Field(default="INR", max_length=8)
    notes: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(default="", max_length=64)


# -- payments --------------------------------------------------------------------


class PaymentCreate(BaseModel):
    model_config = {"extra": "forbid"}

    amount: Decimal
    currency: str = Field(default="INR", max_length=8)
    method: str = Field(default="manual", max_length=32)
    member_id: uuid.UUID | None = None
    membership_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    provider_ref: str = Field(default="", max_length=200)
    invoice_no: str = Field(default="", max_length=64)
    due_at: datetime | None = None
    notes: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(default="", max_length=64)


class PaymentStatusIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(min_length=1, max_length=32)


class PaymentRefundIn(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=5, max_length=500)


class PaymentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    member_id: uuid.UUID | None = None
    membership_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    amount: Decimal
    currency: str
    method: str
    provider: str
    status: str
    paid_at: datetime | None = None
    due_at: datetime | None = None
    invoice_no: str
    notes: str
    created_at: datetime
    updated_at: datetime


# -- attendance ---------------------------------------------------------------------


class CheckInIn(BaseModel):
    model_config = {"extra": "forbid"}

    member_id: uuid.UUID
    attendance_date: date | None = None
    membership_id: uuid.UUID | None = None
    seat_id: uuid.UUID | None = None
    source: str = Field(default="manual", max_length=16)
    notes: str = Field(default="", max_length=500)


class AttendanceCorrectIn(BaseModel):
    model_config = {"extra": "forbid"}

    notes: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=16)
    seat_id: uuid.UUID | None = None


class AttendanceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    member_id: uuid.UUID
    membership_id: uuid.UUID | None = None
    seat_id: uuid.UUID | None = None
    attendance_date: date
    checked_in_at: datetime
    checked_out_at: datetime | None = None
    source: str
    notes: str
    created_at: datetime


# -- renewals --------------------------------------------------------------------------


class RenewalCreate(BaseModel):
    model_config = {"extra": "forbid"}

    membership_id: uuid.UUID
    due_date: date | None = None
    renewal_amount: Decimal | None = None
    currency: str = Field(default="INR", max_length=8)
    new_plan_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=2000)


class RenewalOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    member_id: uuid.UUID
    membership_id: uuid.UUID
    new_membership_id: uuid.UUID | None = None
    previous_plan_id: uuid.UUID | None = None
    new_plan_id: uuid.UUID | None = None
    renewal_amount: Decimal
    currency: str
    status: str
    due_date: date
    renewed_at: datetime | None = None
    notes: str
    created_at: datetime
    updated_at: datetime


class RenewalStatusIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(min_length=1, max_length=32)


class PaymentWebhookIn(BaseModel):
    model_config = {"extra": "forbid"}

    idempotency_key: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    amount: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)
    provider: str = Field(default="mock", max_length=64)


# -- seats -------------------------------------------------------------------------------


class SeatAreaCreate(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)
    floor: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=500)


class SeatAreaOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    name: str
    floor: str
    description: str
    created_at: datetime


class SeatCreate(BaseModel):
    model_config = {"extra": "forbid"}

    seat_number: str = Field(min_length=1, max_length=64)
    area_id: uuid.UUID | None = None
    seat_type: str = Field(default="regular", max_length=32)
    status: str = Field(default="available", max_length=32)
    notes: str = Field(default="", max_length=500)


class SeatUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    seat_type: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=500)
    area_id: uuid.UUID | None = None


class SeatOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    area_id: uuid.UUID | None = None
    seat_number: str
    seat_type: str
    status: str
    notes: str
    created_at: datetime
    updated_at: datetime


class SeatAllocateIn(BaseModel):
    model_config = {"extra": "forbid"}

    seat_id: uuid.UUID
    member_id: uuid.UUID
    membership_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=500)


class SeatTransferIn(BaseModel):
    model_config = {"extra": "forbid"}

    to_member_id: uuid.UUID


class SeatAllocationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    seat_id: uuid.UUID
    member_id: uuid.UUID
    membership_id: uuid.UUID | None = None
    status: str
    allocated_at: datetime
    released_at: datetime | None = None
    notes: str
    created_at: datetime


class SeatAvailabilityOut(BaseModel):
    total: int
    available: int
    allocated_active: int
    by_status: dict


# -- approvals ----------------------------------------------------------------------------------


class ApprovalRequestIn(BaseModel):
    model_config = {"extra": "forbid"}

    entity_type: str = Field(min_length=1, max_length=48)
    entity_id: uuid.UUID | None = None
    action: str = Field(default="approve", max_length=32)
    title: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=2000)
    meta: dict = Field(default_factory=dict)


class ApprovalDecideIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(min_length=1, max_length=32)
    decision_note: str = Field(default="", max_length=2000)


class ApprovalOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID | None = None
    action: str
    status: str
    title: str
    reason: str
    decision_note: str
    requested_by_user_id: uuid.UUID | None = None
    decided_by_user_id: uuid.UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
