"""Business + settings schemas."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class BusinessOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    business_type: str
    status: str
    timezone: str | None = None
    currency: str | None = None
    locale: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    website_url: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    whatsapp: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    website_url: str | None = Field(default=None, max_length=500)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=128)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, max_length=8)
    locale: str | None = Field(default=None, max_length=16)


class SettingsOut(BaseModel):
    business_id: uuid.UUID
    branding: dict[str, Any] = Field(default_factory=dict)
    contact: dict[str, Any] = Field(default_factory=dict)
    address: dict[str, Any] = Field(default_factory=dict)
    hours: dict[str, Any] = Field(default_factory=dict)
    localization: dict[str, Any] = Field(default_factory=dict)
    operational: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    branding: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    address: dict[str, Any] | None = None
    hours: dict[str, Any] | None = None
    localization: dict[str, Any] | None = None
    operational: dict[str, Any] | None = None
