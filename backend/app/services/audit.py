"""Audit service: persistent business-scoped activity log (Block 4, step 21).

Conceptually separate from debug logs: one durable row per important
business/security operation. Writes are best-effort wrappers — an audit
failure must NEVER break the business operation it describes.

NEVER logged: passwords, access/refresh tokens, session secrets, API
keys, database credentials, full contact PII beyond operational
minimums. ``meta`` is sanitized (sensitive keys dropped, values
truncated) before persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ops_vocab import AUDIT_ACTIONS, AUDIT_RESULTS
from app.repositories import audit_events as audit_repo
from app.services.errors import NotFoundError

# Keys that must never be persisted in audit metadata (substring match).
_SENSITIVE_SUBSTRINGS = (
    "password",
    "passwd",
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
)

_MAX_META_VALUE_CHARS = 500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_meta(meta: dict | None) -> dict:
    """Drop sensitive keys, truncate values, coerce to JSON-safe scalars."""
    clean: dict = {}
    for key, value in dict(meta or {}).items():
        lowered = str(key).lower()
        if any(part in lowered for part in _SENSITIVE_SUBSTRINGS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            text: object = value
        else:
            try:
                text = str(value)
            except Exception:  # noqa: BLE001 - audit must never raise
                continue
        if isinstance(text, str):
            text = text[:_MAX_META_VALUE_CHARS]
        clean[str(key)[:64]] = text
    return clean


def validate_action(action: str) -> str:
    value = str(action or "").strip()
    if value not in AUDIT_ACTIONS:
        raise ValueError(
            f"Unknown audit action: {action!r}. Allowed: {sorted(AUDIT_ACTIONS)}."
        )
    return value


def log_event(
    db: Session,
    *,
    business_id: uuid.UUID | None,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    result: str = "success",
    request_id: str = "-",
    ip_address: str | None = None,
    user_agent: str | None = None,
    meta: dict | None = None,
) -> object | None:
    """Persist one audit event. Returns None (never raises) on any failure."""
    try:
        action_clean = validate_action(action)
        result_clean = str(result or "success").strip().lower()
        if result_clean not in AUDIT_RESULTS:
            result_clean = "error"
        event = audit_repo.create(
            db,
            business_id=_coerce_uuid(business_id),
            actor_user_id=_coerce_uuid(actor_user_id),
            action=action_clean,
            entity_type=(str(entity_type)[:48] if entity_type else None),
            entity_id=_coerce_uuid(entity_id),
            result=result_clean,
            request_id=(str(request_id or "-")[:64]),
            ip_address=(str(ip_address or "")[:64] or None),
            user_agent=user_agent,
            meta=sanitize_meta(meta),
        )
        db.flush()
        return event
    except Exception:  # noqa: BLE001 - audit must never break business ops
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def _coerce_uuid(value: object) -> uuid.UUID | None:
    """Coerce path-param strings to UUIDs (SQLite needs real UUID binds).

    Unparseable values become None rather than breaking the audit write —
    the raw value stays available in ``meta`` when callers need it.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def list_events(
    db: Session,
    *,
    business_id: uuid.UUID,
    action: str | None = None,
    actor_user_id: object = None,
    entity_type: str | None = None,
    entity_id: object = None,
    result: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    from app.repositories.pagination import parse_uuid

    action_clean = None
    if action:
        action_clean = validate_action(action)
    actor = parse_uuid(actor_user_id) if actor_user_id else None
    if actor_user_id and actor is None:
        raise ValueError("actor_user_id must be a valid UUID.")
    entity = parse_uuid(entity_id) if entity_id else None
    if entity_id and entity is None:
        raise ValueError("entity_id must be a valid UUID.")
    result_clean = None
    if result:
        result_clean = str(result).strip().lower()
        if result_clean not in AUDIT_RESULTS:
            raise ValueError(f"Unknown audit result: {result!r}.")
    search_clean = (str(search or "").strip()[:64]) or None
    return audit_repo.list_scoped(
        db,
        business_id=business_id,
        action=action_clean,
        actor_user_id=actor,
        entity_type=(str(entity_type).strip().lower()[:48] if entity_type else None),
        entity_id=entity,
        result=result_clean,
        created_from=created_from,
        created_to=created_to,
        search=search_clean,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def get_event(db: Session, *, business_id: uuid.UUID, event_id: object):
    event = audit_repo.get_scoped(db, event_id=event_id, business_id=business_id)
    if event is None:
        raise NotFoundError("Audit event not found.")
    return event
