"""Task schemas (staff APIs; business scope enforced server-side)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    priority: str = Field(default="medium", max_length=16)
    assigned_to_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    related_entity_type: str | None = Field(default=None, max_length=48)
    related_entity_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: str | None = Field(default=None, max_length=16)
    due_at: datetime | None = None
    assigned_to_user_id: uuid.UUID | None = None


class TaskAssignIn(BaseModel):
    model_config = {"extra": "forbid"}

    assigned_to_user_id: uuid.UUID


class TaskStatusIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(max_length=32)


class TaskOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    description: str
    status: str
    priority: str
    assigned_to_user_id: uuid.UUID | None = None
    created_by_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
