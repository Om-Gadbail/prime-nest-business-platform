"""Booking schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

_PHONE_RE = r"^[+\d][\d\s\-().]{5,30}$"


class BookingCreate(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: str = Field(default="", max_length=200)
    phone: str | None = Field(default=None, max_length=32, pattern=_PHONE_RE)
    email: EmailStr | None = None
    booking_type: str = Field(default="enquiry", max_length=32)
    title: str = Field(default="", max_length=200)
    requested_start_at: datetime | None = None
    requested_end_at: datetime | None = None
    notes: str = Field(default="", max_length=2000)
    source: str = Field(default="website", max_length=32)
    contact_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    assigned_user_id: uuid.UUID | None = None


class BookingUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=200)
    booking_type: str | None = Field(default=None, max_length=32)
    requested_start_at: datetime | None = None
    requested_end_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    assigned_user_id: uuid.UUID | None = None


class BookingTransitionIn(BaseModel):
    model_config = {"extra": "forbid"}

    cancellation_reason: str = Field(default="", max_length=500)


class TrialOutcomeIn(BaseModel):
    """Staff-recorded trial/visit outcome (Prompt 7 growth engine)."""

    model_config = {"extra": "forbid"}

    outcome: str = Field(max_length=32)  # attended | no_show


class BookingOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    contact_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    booking_type: str
    status: str
    title: str
    requested_start_at: datetime | None = None
    requested_end_at: datetime | None = None
    assigned_user_id: uuid.UUID | None = None
    notes: str
    source: str
    cancellation_reason: str
    created_at: datetime
    updated_at: datetime
