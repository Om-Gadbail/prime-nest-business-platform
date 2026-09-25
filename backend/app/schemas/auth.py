"""Auth schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    # Optional explicit business selection (slug). Verified server-side.
    business_slug: str | None = Field(default=None, max_length=64)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=512)


class SwitchBusinessRequest(BaseModel):
    # Accepts business UUID or slug; verified against membership server-side.
    business_id: str = Field(min_length=1, max_length=64)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str = ""
    phone: str | None = None
    is_active: bool
    is_verified: bool
    last_login_at: str | None = None

    model_config = {"from_attributes": True}


class BusinessSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    business_type: str
    status: str

    model_config = {"from_attributes": True}


class MembershipOut(BaseModel):
    business_id: uuid.UUID
    role: str | None = None
    status: str
    is_default: bool


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
    business: BusinessSummary | None = None
    membership: MembershipOut | None = None
    permissions: list[str] = Field(default_factory=list)


class MeResponse(BaseModel):
    user: UserOut
    business: BusinessSummary | None = None
    membership: MembershipOut | None = None
    permissions: list[str] = Field(default_factory=list)


class AvailableBusiness(BaseModel):
    business: BusinessSummary
    role: str | None = None
    status: str
    is_default: bool
