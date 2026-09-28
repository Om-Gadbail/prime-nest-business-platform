"""Business-scoped integration configuration (Pre-Prompt-7 foundation).

ONE shared Gemini demo credential + TWO separate WhatsApp business credential
sets + ONE shared provider implementation + SERVER-SIDE business-scoped
credential resolution + STRICT Prime/Nest isolation.

Resolution rule (absolute):

    authenticated identity
        -> server-side BusinessContext (JWT + DB membership, never client input)
        -> authorized business (Business row: slug / external_id)
        -> business-specific integration configuration (this module)
        -> provider credentials (env, backend-only)

Security properties:
- The provider CODE is shared; only the CREDENTIALS are business-specific,
  so future businesses reuse this module with a new env prefix (no forks).
- A Prime context can NEVER resolve Nest credentials and vice versa. Unknown
  or future businesses resolve to DISABLED/NOT_CONFIGURED (fail closed) —
  never to another business's credentials and never to a global fallback
  that mixes tenants.
- Gemini is an intelligence layer, NOT the source of truth: it never decides
  authorization, ownership, membership/payment/attendance status, renewals,
  totals, or permissions (see ``sanitize_context_for_gemini``).
- ``safe_status()`` exposes ONLY booleans/model names — never keys, tokens,
  or secrets — and is the ONLY shape the status endpoint may return.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import Settings

# Canonical stable business identifiers (mirror db_routing.SEED_EXTERNAL_IDS).
PRIME_EXTERNAL_ID = "prime-fitness-001"
NEST_EXTERNAL_ID = "nest-library-001"

# Server-side business keys with dedicated WhatsApp credential sets.
BUSINESS_KEYS: tuple[str, ...] = ("prime", "nest")

ProviderMode = Literal["LIVE", "MOCK", "DISABLED", "NOT_CONFIGURED"]

# Keys that must NEVER be sent to Gemini (or any external AI provider).
GEMINI_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "gemini_api_key",
        "access_token",
        "whatsapp_access_token",
        "prime_whatsapp_access_token",
        "nest_whatsapp_access_token",
        "app_secret",
        "whatsapp_app_secret",
        "prime_whatsapp_app_secret",
        "nest_whatsapp_app_secret",
        "verify_token",
        "whatsapp_verify_token",
        "prime_whatsapp_verify_token",
        "nest_whatsapp_verify_token",
        "password",
        "password_hash",
        "secret",
        "secret_key",
        "jwt_secret_key",
        "refresh_token",
        "auth_token",
        "authorization",
        "payment_webhook_secret",
        "phone_number_id",
        "access",
        "credentials",
    }
)


@dataclass(frozen=True)
class WhatsAppBusinessConfig:
    """Resolved WhatsApp credentials for exactly ONE business."""

    business_key: str  # "prime" | "nest" | "" (unknown/future -> disabled)
    enabled: bool
    access_token: str
    phone_number_id: str
    business_account_id: str
    verify_token: str
    app_secret: str

    @property
    def configured(self) -> bool:
        """True only when token + phone-number-id are both present."""
        return bool(self.access_token.strip() and self.phone_number_id.strip())

    @property
    def live(self) -> bool:
        """True only when explicitly enabled AND fully configured."""
        return bool(self.enabled and self.configured)

    @property
    def mode(self) -> ProviderMode:
        if self.live:
            return "LIVE"
        if self.enabled and not self.configured:
            return "NOT_CONFIGURED"
        if not self.enabled and self.configured:
            return "DISABLED"
        return "NOT_CONFIGURED" if not self.configured else "DISABLED"

    def safe_summary(self) -> dict[str, Any]:
        """Secret-free summary for status endpoints/logs. NEVER add secrets.

        ``provider`` distinguishes MOCK ("log": demo-safe, no external send)
        from LIVE ("whatsapp": real Graph API credential bound).
        """
        return {
            "business_key": self.business_key,
            "configured": self.configured,
            "enabled": self.enabled,
            "mode": self.mode,
            "provider": "whatsapp" if self.live else "log",
        }


@dataclass(frozen=True)
class GeminiConfig:
    """Resolved Gemini configuration (ONE shared demo credential)."""

    api_key: str
    model: str
    timeout_seconds: int
    enabled: bool  # AI_ENABLED kill switch (server-side)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.model.strip())

    @property
    def live(self) -> bool:
        return bool(self.enabled and self.configured)

    @property
    def mode(self) -> ProviderMode:
        if self.live:
            return "LIVE"
        if not self.enabled:
            return "DISABLED"
        return "NOT_CONFIGURED"

    def safe_summary(self) -> dict[str, Any]:
        """Secret-free summary. NEVER include the API key."""
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "model": self.model,
            "mode": self.mode,
            "provider": "gemini" if self.live else "noop",
        }


def resolve_business_key(business: Any) -> str:
    """Map a SERVER-VERIFIED business to its integration key.

    Accepts a Business ORM row, BusinessContext, AuthenticatedContext, or an
    already-verified slug/external_id/database_key string. Returns "prime" or
    "nest", else "" for unknown/future businesses (fail closed).

    NEVER pass raw request input (query/body/header business_id) here — the
    caller must first resolve it through authentication + membership checks
    (BusinessContext) or the public slug path.
    """
    if business is None:
        return ""
    if isinstance(business, str):
        token = business.strip().lower()
        if token in ("prime", PRIME_EXTERNAL_ID, "prime_db", "prime-fitness"):
            return "prime"
        if token in ("nest", NEST_EXTERNAL_ID, "nest_db", "nest-library"):
            return "nest"
        return ""
    # BusinessContext / AuthenticatedContext carry a `.business` row.
    nested = getattr(business, "business", None)
    if nested is not None and nested is not business:
        return resolve_business_key(nested)
    slug = str(getattr(business, "slug", "") or "").strip().lower()
    if slug in ("prime", "nest"):
        return slug
    external_id = str(getattr(business, "external_id", "") or "").strip()
    if external_id == PRIME_EXTERNAL_ID:
        return "prime"
    if external_id == NEST_EXTERNAL_ID:
        return "nest"
    database_key = str(getattr(business, "database_key", "") or "").strip()
    if database_key == "prime_db":
        return "prime"
    if database_key == "nest_db":
        return "nest"
    return ""


def _business_env(settings: Settings, key: str, field: str) -> str:
    """Read ``<KEY>_WHATSAPP_<FIELD>`` from settings (e.g. PRIME_WHATSAPP_*)."""
    attr = f"{key.lower()}_whatsapp_{field}"
    return str(getattr(settings, attr, "") or "")


def resolve_whatsapp_config(
    settings: Settings, business: Any
) -> WhatsAppBusinessConfig:
    """Resolve the WhatsApp credentials for a SERVER-VERIFIED business.

    Prime -> PRIME_WHATSAPP_* only. Nest -> NEST_WHATSAPP_* only. Anything
    else -> disabled/empty (fail closed; never another tenant's creds).
    """
    key = resolve_business_key(business)
    if key not in BUSINESS_KEYS:
        return WhatsAppBusinessConfig(
            business_key="",
            enabled=False,
            access_token="",
            phone_number_id="",
            business_account_id="",
            verify_token="",
            app_secret="",
        )
    enabled_raw = _business_env(settings, key, "enabled")
    if isinstance(enabled_raw, bool):
        enabled = enabled_raw
    else:
        enabled = str(enabled_raw).strip().lower() in ("1", "true", "yes", "on")
    return WhatsAppBusinessConfig(
        business_key=key,
        enabled=enabled,
        access_token=_business_env(settings, key, "access_token"),
        phone_number_id=_business_env(settings, key, "phone_number_id"),
        business_account_id=_business_env(settings, key, "business_account_id"),
        verify_token=_business_env(settings, key, "verify_token"),
        app_secret=_business_env(settings, key, "app_secret"),
    )


def resolve_gemini_config(settings: Settings) -> GeminiConfig:
    """Resolve the shared Gemini demo configuration (business-agnostic creds).

    The CREDENTIAL is shared, but every Gemini request must still carry the
    server-derived business context (business slug/external_id) so the model
    answers for the right business. Gemini never decides authorization.
    """
    return GeminiConfig(
        api_key=(settings.gemini_api_key or ""),
        model=(settings.gemini_model or "gemini-2.5-flash").strip()
        or "gemini-2.5-flash",
        timeout_seconds=int(settings.ai_timeout_seconds or 20),
        enabled=bool(settings.ai_enabled),
    )


def sanitize_context_for_gemini(context: dict[str, Any]) -> dict[str, Any]:
    """Strip forbidden keys before anything reaches Gemini (defence in depth).

    Removes API keys, tokens, secrets, passwords, and credential-adjacent
    fields (case-insensitive, substring match on the forbidden set). Returns
    a NEW dict; the input is never mutated. Non-dict values pass through.
    """
    cleaned: dict[str, Any] = {}
    for key, value in dict(context or {}).items():
        lowered = str(key).strip().lower()
        if not lowered:
            continue
        if lowered in GEMINI_FORBIDDEN_KEYS or any(
            forbidden in lowered for forbidden in GEMINI_FORBIDDEN_KEYS
        ):
            continue
        if isinstance(value, dict):
            cleaned[key] = sanitize_context_for_gemini(value)
        elif isinstance(value, str) and len(value) > 4000:
            cleaned[key] = value[:4000] + "…[truncated]"
        else:
            cleaned[key] = value
    return cleaned


def safe_status(settings: Settings, business: Any) -> dict[str, Any]:
    """Secret-free integration status for exactly ONE server-verified business.

    Shape:
        {"gemini": {...}, "whatsapp": {...}, "business_key": "prime"|"nest"|""}
    NEVER includes keys, tokens, secrets, or verify tokens.
    """
    gemini = resolve_gemini_config(settings)
    whatsapp = resolve_whatsapp_config(settings, business)
    return {
        "gemini": gemini.safe_summary(),
        "whatsapp": whatsapp.safe_summary(),
        "business_key": whatsapp.business_key,
    }


def business_phone_number_ids(settings: Settings) -> dict[str, str]:
    """Map ``{phone_number_id: business_key}`` for the business-scoped sets.

    Used by webhook business resolution (first signal, before any payload
    trust). Legacy global map/phone-id are intentionally EXCLUDED — they
    carry no business scope and must never attribute traffic to a tenant.
    """
    out: dict[str, str] = {}
    for key in BUSINESS_KEYS:
        pid = _business_env(settings, key, "phone_number_id").strip()
        if pid:
            out[pid] = key
    return out


def verify_tokens(settings: Settings) -> dict[str, str]:
    """Map ``{business_key: verify_token}`` for configured businesses only."""
    out: dict[str, str] = {}
    for key in BUSINESS_KEYS:
        token = _business_env(settings, key, "verify_token").strip()
        if token:
            out[key] = token
    return out


def app_secrets(settings: Settings) -> dict[str, str]:
    """Map ``{business_key: app_secret}`` for configured businesses only."""
    out: dict[str, str] = {}
    for key in BUSINESS_KEYS:
        secret = _business_env(settings, key, "app_secret").strip()
        if secret:
            out[key] = secret
    return out
