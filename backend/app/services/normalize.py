"""PII normalization helpers (phone/email/name).

Normalization outputs are used for matching/search only and are not
exposed unnecessarily through public APIs.
"""

from __future__ import annotations

import re

_NON_DIGIT_RE = re.compile(r"[^\d]")
_PHONE_KEEP_RE = re.compile(r"[^\d+]")
_WS_RE = re.compile(r"\s+")


def normalize_phone(raw: str | None) -> str | None:
    """Canonical phone form: optional leading '+', then digits only.

    Returns None for empty input. Keeps country trunk digits (no E.164
    assumption — lenient international, 7..15 digits).
    """
    if raw is None:
        return None
    text = _WS_RE.sub("", str(raw).strip())
    if not text:
        return None
    cleaned = _PHONE_KEEP_RE.sub("", text)
    # Collapse duplicate '+' and keep it only as a prefix.
    digits = _NON_DIGIT_RE.sub("", cleaned)
    if not digits:
        return None
    if len(digits) < 7 or len(digits) > 15:
        return None
    return f"+{digits}" if cleaned.startswith("+") else digits


def normalize_email(raw: str | None) -> str | None:
    """Canonical email form: stripped + lowercased. Shape checked elsewhere."""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text or "@" not in text or len(text) > 320:
        return None
    return text


def split_name(display: str) -> tuple[str, str]:
    """Split a free-form display name into (first_name, last_name)."""
    parts = _WS_RE.sub(" ", str(display or "").strip()).split(" ")
    parts = [p for p in parts if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def mask_phone_last4(normalized: str | None) -> str:
    """Privacy-preserving contact reference (last 4 digits only)."""
    digits = _NON_DIGIT_RE.sub("", normalized or "")
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def mask_email(normalized: str | None) -> str:
    """Privacy-preserving email reference (domain + first letter only)."""
    if not normalized or "@" not in normalized:
        return "***"
    local, _, domain = normalized.partition("@")
    prefix = local[:1] if local else "*"
    return f"{prefix}***@{domain}" if domain else "***"
