"""Business settings service: validation + updates.

Core identity fields live on businesses; flexible presentation/operational
configuration lives here in JSONB sections.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.business_settings import BusinessSettings
from app.repositories import settings as settings_repo

SECTIONS = ("branding", "contact", "address", "hours", "localization", "operational")

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_PHONE_RE = re.compile(r"^[+\d][\d\s\-().]{5,30}$")
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:[-_][A-Z]{2})?$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _validate_timezone(value: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {value}") from exc


def _validate_url(value: str, *, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{field} must be a valid http(s) URL.")


def validate_settings_payload(payload: dict) -> dict[str, dict]:
    """Validate partial settings update. Returns cleaned {section: dict}."""
    if not isinstance(payload, dict):
        raise ValueError("Settings payload must be an object.")
    unknown = set(payload.keys()) - set(SECTIONS)
    if unknown:
        raise ValueError(f"Unknown settings section(s): {sorted(unknown)}.")
    cleaned: dict[str, dict] = {}
    for section, value in payload.items():
        if not isinstance(value, dict):
            raise ValueError(f"Section '{section}' must be an object.")
        validator = globals().get(f"_validate_{section}", None)
        if validator is not None:
            cleaned[section] = validator(value)
        else:
            cleaned[section] = dict(value)
    return cleaned


def _validate_branding(value: dict) -> dict:
    allowed = {
        "display_name",
        "tagline",
        "logo_url",
        "primary_color",
        "secondary_color",
    }
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"Unknown branding field(s): {sorted(unknown)}.")
    out = dict(value)
    for color_field in ("primary_color", "secondary_color"):
        if out.get(color_field) not in (None, ""):
            if not _HEX_COLOR_RE.match(str(out[color_field])):
                raise ValueError(
                    f"branding.{color_field} must be a hex color like '#1a2b3c'."
                )
    if out.get("logo_url"):
        _validate_url(str(out["logo_url"]), field="branding.logo_url")
    return out


def _validate_contact(value: dict) -> dict:
    allowed = {"phone", "whatsapp", "email", "website_url"}
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"Unknown contact field(s): {sorted(unknown)}.")
    out = dict(value)
    for phone_field in ("phone", "whatsapp"):
        if out.get(phone_field) not in (None, ""):
            if not _PHONE_RE.match(str(out[phone_field]).strip()):
                raise ValueError(f"contact.{phone_field} has an invalid phone shape.")
    if out.get("email") not in (None, ""):
        from email_validator import EmailNotValidError, validate_email

        try:
            validate_email(str(out["email"]), check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError(f"contact.email is invalid: {exc}") from exc
    if out.get("website_url") not in (None, ""):
        _validate_url(str(out["website_url"]), field="contact.website_url")
    return out


def _validate_address(value: dict) -> dict:
    allowed = {
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "postal_code",
        "country",
    }
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"Unknown address field(s): {sorted(unknown)}.")
    return dict(value)


def _validate_hours(value: dict) -> dict:
    allowed = {"weekly", "closed_days", "notes"}
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"Unknown hours field(s): {sorted(unknown)}.")
    out = dict(value)
    if "weekly" in out and out["weekly"] is not None:
        weekly = out["weekly"]
        if not isinstance(weekly, dict):
            raise ValueError("hours.weekly must be an object keyed by weekday.")
        for day, entry in weekly.items():
            if day not in _DAYS:
                raise ValueError(f"hours.weekly has unknown day: {day}.")
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise ValueError(f"hours.weekly.{day} must be an object.")
            if entry.get("closed") is True:
                continue
            for bound in ("open", "close"):
                if bound in entry and entry[bound] not in (None, ""):
                    if not _TIME_RE.match(str(entry[bound])):
                        raise ValueError(
                            f"hours.weekly.{day}.{bound} must be HH:MM (24h)."
                        )
    if "closed_days" in out and out["closed_days"] is not None:
        if not isinstance(out["closed_days"], list):
            raise ValueError("hours.closed_days must be a list.")
    return out


def _validate_localization(value: dict) -> dict:
    allowed = {"timezone", "locale", "currency"}
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"Unknown localization field(s): {sorted(unknown)}.")
    out = dict(value)
    if out.get("timezone") not in (None, ""):
        _validate_timezone(str(out["timezone"]))
    if out.get("locale") not in (None, ""):
        if not _LOCALE_RE.match(str(out["locale"])):
            raise ValueError("localization.locale must look like 'en' or 'en-US'.")
    if out.get("currency") not in (None, ""):
        if not _CURRENCY_RE.match(str(out["currency"]).upper()):
            raise ValueError(
                "localization.currency must be a 3-letter ISO code like 'USD'."
            )
        out["currency"] = str(out["currency"]).upper()
    return out


def _validate_operational(value: dict) -> dict:
    # Flat feature flags plus nested Blocks 5-7 configuration sections.
    # Capability/module behavior is data (never `if business.name == …`).
    allowed = {
        "booking_enabled",
        "lead_capture_enabled",
        "notifications_enabled",
        "capabilities",
        "membership",
        "payments",
        "attendance",
        "renewals",
        "seats",
        "dashboard",
    }
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"Unknown operational field(s): {sorted(unknown)}.")
    out = dict(value)
    for flag in ("booking_enabled", "lead_capture_enabled", "notifications_enabled"):
        if flag in out and not isinstance(out[flag], bool):
            raise ValueError(f"operational.{flag} must be a boolean.")
    if "capabilities" in out and out["capabilities"] is not None:
        out["capabilities"] = _validate_capabilities(out["capabilities"])
    for section in (
        "membership",
        "payments",
        "attendance",
        "renewals",
        "seats",
        "dashboard",
    ):
        if section in out and out[section] is not None:
            if not isinstance(out[section], dict):
                raise ValueError(f"operational.{section} must be an object.")
            out[section] = dict(out[section])
    return out


# Capability flags recognised by the Blocks 5-7 operational modules.
# Unknown flags are rejected so typos fail loudly instead of silently
# disabling features.
KNOWN_CAPABILITIES = frozenset(
    {
        "crm",
        "leads",
        "bookings",
        "memberships",
        "members",
        "payments",
        "attendance",
        "renewals",
        "plans",
        "seat_management",
        "fitness_tracking",
        "approvals",
        "analytics",
        "owner_dashboard",
        # Blocks 8-12 modules (configurable per business, template-defaulted).
        "automation",
        "whatsapp",
        "ai_assistant",
        "ai_public_chat",
        "growth",
        "reviews",
        "referrals",
    }
)


def _validate_capabilities(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("operational.capabilities must be an object.")
    unknown = set(value.keys()) - set(KNOWN_CAPABILITIES)
    if unknown:
        raise ValueError(f"Unknown capability flag(s): {sorted(unknown)}.")
    out: dict[str, bool] = {}
    for key, flag in value.items():
        if not isinstance(flag, bool):
            raise ValueError(f"operational.capabilities.{key} must be a boolean.")
        out[key] = flag
    return out


def get_settings(db: Session, *, business_id: object) -> BusinessSettings:
    import uuid as _uuid

    bid = (
        business_id
        if isinstance(business_id, _uuid.UUID)
        else _uuid.UUID(str(business_id))
    )
    row = settings_repo.get_by_business(db, bid)
    if row is None:
        row = settings_repo.ensure_for_business(db, bid)
        db.commit()
        db.refresh(row)
    return row


def update_settings(
    db: Session, *, business_id: object, payload: dict
) -> BusinessSettings:
    cleaned = validate_settings_payload(payload)
    row = get_settings(db, business_id=business_id)
    # Merge per section (partial update semantics).
    merged: dict[str, dict] = {}
    for section in SECTIONS:
        current = dict(getattr(row, section) or {})
        if section in cleaned:
            current.update(cleaned[section])
        merged[section] = current
    # Re-validate merged result to catch cross-field issues.
    for section in SECTIONS:
        validator = globals().get(f"_validate_{section}")
        if validator is not None:
            merged[section] = validator(merged[section])
    updated = settings_repo.update_sections(db, row, merged)
    db.commit()
    db.refresh(updated)
    return updated
