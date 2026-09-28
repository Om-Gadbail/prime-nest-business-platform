"""Lead + LeadActivity schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

_PHONE_RE = r"^[+\d][\d\s\-().]{5,30}$"
_UTM_MAX = 200


class LeadCreate(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: str = Field(default="", max_length=200)
    phone: str | None = Field(default=None, max_length=32, pattern=_PHONE_RE)
    email: EmailStr | None = None
    source: str = Field(default="website", max_length=32)
    source_detail: str = Field(default="", max_length=200)
    service_interest: str = Field(default="", max_length=200)
    message: str = Field(default="", max_length=2000)
    follow_up_at: datetime | None = None
    consent_marketing: bool = False
    landing_page: str = Field(default="", max_length=500)
    referrer: str = Field(default="", max_length=500)
    utm_source: str = Field(default="", max_length=_UTM_MAX)
    utm_medium: str = Field(default="", max_length=_UTM_MAX)
    utm_campaign: str = Field(default="", max_length=_UTM_MAX)
    utm_term: str = Field(default="", max_length=_UTM_MAX)
    utm_content: str = Field(default="", max_length=_UTM_MAX)
    contact_id: uuid.UUID | None = None
    assigned_user_id: uuid.UUID | None = None


class LeadUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32, pattern=_PHONE_RE)
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=32)
    source_detail: str | None = Field(default=None, max_length=200)
    service_interest: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=2000)
    follow_up_at: datetime | None = None
    consent_marketing: bool | None = None
    landing_page: str | None = Field(default=None, max_length=500)
    referrer: str | None = Field(default=None, max_length=500)
    utm_source: str | None = Field(default=None, max_length=_UTM_MAX)
    utm_medium: str | None = Field(default=None, max_length=_UTM_MAX)
    utm_campaign: str | None = Field(default=None, max_length=_UTM_MAX)
    utm_term: str | None = Field(default=None, max_length=_UTM_MAX)
    utm_content: str | None = Field(default=None, max_length=_UTM_MAX)


class LeadAssignIn(BaseModel):
    model_config = {"extra": "forbid"}

    assigned_user_id: uuid.UUID


class LeadStatusIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(max_length=32)
    lost_reason: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=2000)


class LeadNoteIn(BaseModel):
    model_config = {"extra": "forbid"}

    note: str = Field(min_length=1, max_length=2000)
    activity_type: str = Field(default="note", max_length=48)


class LeadConvertIn(BaseModel):
    model_config = {"extra": "forbid"}

    customer_notes: str = Field(default="", max_length=2000)


class LeadOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    contact_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    display_name: str
    phone: str | None = None
    email: str | None = None
    source: str
    source_detail: str
    status: str
    assigned_user_id: uuid.UUID | None = None
    service_interest: str
    message: str
    follow_up_at: datetime | None = None
    last_contacted_at: datetime | None = None
    converted_at: datetime | None = None
    lost_reason: str
    consent_marketing: bool
    routed_by: str = "system"
    routing_reason: str = ""
    routed_at: datetime | None = None
    landing_page: str
    referrer: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_term: str
    utm_content: str
    created_at: datetime
    updated_at: datetime


class LeadActivityOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    lead_id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    activity_type: str
    note: str
    created_at: datetime
