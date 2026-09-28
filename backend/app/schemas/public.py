"""Public (anonymous) intake schemas.

Minimal by design: only what a website visitor submits, plus attribution.
Honeypot field ``website_url`` must be empty from real users; bots that
fill it receive a fake success WITHOUT any record being created (handled
in the router, not as a validation error — never signal the trap).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

_PHONE_RE = r"^[+\d][\d\s\-().]{5,30}$"


class PublicLeadIn(BaseModel):
    # NOTE: no extra="forbid" here — browsers/proxies may add harmless
    # fields; unknown fields are ignored, never trusted.
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=32, pattern=_PHONE_RE)
    email: EmailStr | None = None
    message: str = Field(default="", max_length=2000)
    service_interest: str = Field(default="", max_length=200)
    source_detail: str = Field(default="", max_length=200)
    preferred_time: str = Field(default="", max_length=120)
    consent_marketing: bool = False
    landing_page: str = Field(default="", max_length=500)
    referrer: str = Field(default="", max_length=500)
    utm_source: str = Field(default="", max_length=200)
    utm_medium: str = Field(default="", max_length=200)
    utm_campaign: str = Field(default="", max_length=200)
    utm_term: str = Field(default="", max_length=200)
    utm_content: str = Field(default="", max_length=200)
    # Honeypot — must stay empty. Checked server-side, never validated here.
    website_url: str = Field(default="", max_length=500)


class PublicBookingIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=32, pattern=_PHONE_RE)
    email: EmailStr | None = None
    booking_type: str = Field(default="enquiry", max_length=32)
    title: str = Field(default="", max_length=200)
    requested_start_at: datetime | None = None
    preferred_time_label: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=2000)
    source_detail: str = Field(default="", max_length=200)
    landing_page: str = Field(default="", max_length=500)
    referrer: str = Field(default="", max_length=500)
    utm_source: str = Field(default="", max_length=200)
    utm_medium: str = Field(default="", max_length=200)
    utm_campaign: str = Field(default="", max_length=200)
    # Honeypot — must stay empty (see above).
    website_url: str = Field(default="", max_length=500)


class PublicLeadOut(BaseModel):
    success: bool = True
    status: str = "received"
    lead_id: str
    message: str = "Your enquiry has been received. We will contact you shortly."


class PublicBookingOut(BaseModel):
    success: bool = True
    status: str = "received"
    booking_id: str
    message: str = "Your request has been received. We will confirm with you shortly."


class PublicConfigOut(BaseModel):
    slug: str
    name: str
    business_type: str
    timezone: str
    lead_capture_enabled: bool
    booking_enabled: bool
