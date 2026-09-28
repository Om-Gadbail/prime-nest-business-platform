"""Contact + Customer schemas (staff APIs; no internal fields exposed)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

_PHONE_RE = r"^[+\d][\d\s\-().]{5,30}$"


class ContactCreate(BaseModel):
    model_config = {"extra": "forbid"}

    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    phone: str | None = Field(default=None, max_length=32, pattern=_PHONE_RE)
    email: EmailStr | None = None
    preferred_contact_channel: str = Field(default="other", max_length=16)
    source: str = Field(default="other", max_length=32)
    notes: str = Field(default="", max_length=2000)
    status: str = Field(default="active", max_length=32)


class ContactUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32, pattern=_PHONE_RE)
    email: EmailStr | None = None
    preferred_contact_channel: str | None = Field(default=None, max_length=16)
    source: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=32)


class ContactOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    first_name: str
    last_name: str
    display_name: str = ""
    phone: str | None = None
    email: str | None = None
    preferred_contact_channel: str
    source: str
    notes: str
    status: str
    created_at: datetime
    updated_at: datetime

    @field_validator("display_name", mode="before")
    @classmethod
    def _fallback_name(cls, v: object, info: object) -> str:
        if v:
            return str(v)
        data = getattr(info, "data", None)
        if isinstance(data, dict):
            first = str(data.get("first_name") or "").strip()
            last = str(data.get("last_name") or "").strip()
            return f"{first} {last}".strip()
        return ""


class CustomerCreate(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: uuid.UUID
    status: str = Field(default="active", max_length=32)
    customer_since: datetime | None = None
    notes: str = Field(default="", max_length=2000)


class CustomerUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    status: str | None = Field(default=None, max_length=32)
    customer_since: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CustomerOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    contact_id: uuid.UUID
    status: str
    customer_since: datetime | None = None
    notes: str
    created_at: datetime
    updated_at: datetime
    contact: ContactOut | None = None
