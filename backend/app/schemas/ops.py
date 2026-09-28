"""Dashboard + unified-identity schemas (read contracts for the staff UI)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OverviewLeads(BaseModel):
    new: int
    follow_ups_due: int
    created_today: int


class OverviewBookings(BaseModel):
    requested: int
    created_today: int


class OverviewNotifications(BaseModel):
    unread: int


class OverviewTasks(BaseModel):
    mine_open: int
    mine_overdue: int
    open_total: int


class RecentLeadItem(BaseModel):
    id: uuid.UUID
    display_name: str
    status: str
    source: str
    created_at: datetime


class RecentActivityItem(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    activity_type: str
    note: str
    actor_user_id: uuid.UUID | None = None
    created_at: datetime


class DashboardOverviewOut(BaseModel):
    business_id: uuid.UUID
    generated_at: datetime
    leads: OverviewLeads
    bookings: OverviewBookings
    notifications: OverviewNotifications
    tasks: OverviewTasks
    recent_leads: list[RecentLeadItem] = Field(default_factory=list)
    recent_activity: list[RecentActivityItem] = Field(default_factory=list)


class StatusSummaryOut(BaseModel):
    by_status: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class PersonLinkOut(BaseModel):
    link_id: uuid.UUID
    contact_id: uuid.UUID
    link_type: str
    confidence: str
    created_at: datetime


class PersonOut(BaseModel):
    person_id: uuid.UUID
    phone_masked: str
    email_masked: str
    links: list[PersonLinkOut] = Field(default_factory=list)


class CrossBusinessPersonOut(BaseModel):
    person_id: uuid.UUID
    phone_masked: str
    email_masked: str
    businesses: dict[str, int] = Field(default_factory=dict)
    total_links: int = 0


class IdentityLinkCreate(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: uuid.UUID
    person_id: uuid.UUID
    note: str = Field(default="", max_length=500)


class IdentityLinkOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    person_id: uuid.UUID
    contact_id: uuid.UUID
    link_type: str
    confidence: str
    created_at: datetime


class LeadTransferIn(BaseModel):
    model_config = {"extra": "forbid"}

    target_business_slug: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=10, max_length=500)
