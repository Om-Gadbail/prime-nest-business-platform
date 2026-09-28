"""Security-relevant event logging (no secrets, no full payloads, minimal PII)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# Keys that must never appear in logs (matched case-insensitively, substring).
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
)

_MAX_VALUE_CHARS = 200


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_SUBSTRINGS)


def sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop sensitive keys, truncate the rest (safe for logging)."""
    clean: dict[str, Any] = {}
    for key, value in fields.items():
        if _is_sensitive(str(key)):
            continue
        text = str(value) if not isinstance(value, str) else value
        clean[str(key)] = text[:_MAX_VALUE_CHARS]
    return clean


def security_event(
    event: str,
    *,
    request_id: str | None = None,
    business_slug: str | None = None,
    user_id: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log one security-relevant event line (rate limits, honeypots, ...)."""
    parts = [f"security event={event}"]
    if request_id:
        parts.append(f"request_id={request_id}")
    if business_slug:
        parts.append(f"business={business_slug}")
    if user_id is not None:
        parts.append(f"user_id={user_id}")
    if extra:
        for key, value in sanitize_fields(extra).items():
            parts.append(f"{key}={value}")
    logger.warning(" ".join(parts))
