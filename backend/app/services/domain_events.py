"""Domain-event hooks for future Block 8 automation.

Services EMIT events here after successful state changes; nothing in
Blocks 5-7 consumes them. Each emit persists one ``domain_events`` row
(append-only, business-scoped) with IDs + safe metadata only.

Payload hygiene: IDs, timestamps, event/entity types, and small scalar
metadata. NEVER secrets, tokens, full PII, or payment credentials.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ops_vocab import DOMAIN_EVENTS
from app.repositories import approvals as approvals_repo


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_event_type(event_type: str) -> str:
    value = str(event_type or "").strip()
    if value not in DOMAIN_EVENTS:
        raise ValueError(
            f"Unknown domain event: {event_type!r}. Allowed: {sorted(DOMAIN_EVENTS)}."
        )
    return value


def _safe_payload(payload: dict | None) -> dict:
    """Keep only JSON-safe scalars; drop anything sensitive-looking."""
    _SENSITIVE = (
        "password",
        "secret",
        "token",
        "jwt",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "session",
        "credential",
        "refresh",
        "card",
        "cvv",
        "pin",
    )
    clean: dict = {}
    for key, value in dict(payload or {}).items():
        lowered = str(key).lower()
        if any(part in lowered for part in _SENSITIVE):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[str(key)[:64]] = value
        else:
            try:
                clean[str(key)[:64]] = str(value)[:500]
            except Exception:  # noqa: BLE001 - events must never raise
                continue
    return clean


def emit(
    db: Session,
    *,
    business_id: uuid.UUID,
    event_type: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> object:
    """Persist one domain event (caller's transaction; flush only)."""
    event = approvals_repo.record_event(
        db,
        business_id=business_id,
        event_type=validate_event_type(event_type),
        entity_type=(str(entity_type)[:48] if entity_type else None),
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        payload=_safe_payload(payload),
        created_at=_utcnow(),
    )
    db.flush()
    return event
