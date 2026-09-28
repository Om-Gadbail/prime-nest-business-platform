"""Audit-event schemas (read-only; no create/update/delete contracts)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    action: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    result: str
    request_id: str
    meta: dict = {}
    created_at: datetime
