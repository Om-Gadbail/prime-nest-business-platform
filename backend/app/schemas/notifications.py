"""Notification schemas (recipient-scoped; no cross-user reads)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    notification_type: str
    title: str
    body: str
    severity: str
    read_at: datetime | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    data: dict = Field(default_factory=dict)
    created_at: datetime
    expires_at: datetime | None = None


class UnreadCountOut(BaseModel):
    unread: int


class PreferenceIn(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool


class PreferenceOut(BaseModel):
    model_config = {"from_attributes": True}

    notification_type: str
    enabled: bool
