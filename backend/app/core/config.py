"""Application settings (pydantic-settings).

Single source of truth for environment-driven configuration.
Fails fast with a clear message when required values are missing/invalid.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _sibling_field(info: object, key: str) -> str:
    """Best-effort read of a sibling settings field inside a validator.

    During normal pydantic validation ``info.data`` is a dict of already
    validated fields; in any other situation the field is unavailable and we
    return "" (this helper never raises — config inspection must be total).
    """
    data = getattr(info, "data", None)
    if not isinstance(data, dict):
        return ""
    value = data.get(key, "")
    if isinstance(value, str):
        return value
    return str(value) if value else ""


def _split_origins(value: object, *, env_name: str) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [o.strip() for o in value.split(",") if o.strip()]
    if isinstance(value, list):
        return [str(o).strip() for o in value if str(o).strip()]
    raise ValueError(f"{env_name} must be a comma-separated string or list")


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Prime Nest Business Platform")
    app_env: Literal["development", "testing", "production"] = Field(
        default="development"
    )
    app_version: str = Field(default="0.1.0")
    api_v1_prefix: str = Field(default="/api/v1")
    log_level: str = Field(default="INFO")

    # Example: postgresql+psycopg://user:password@db:5432/app_db
    database_url: str = Field(default="")

    # --- Prompt 2: multi-business database targets ---
    # Each key may point at its own PostgreSQL database (platform_db /
    # prime_db / nest_db). Empty (default) = co-located mode: the key falls
    # back to DATABASE_URL and all tenants share one physical database with
    # row-level isolation (the pre-split posture). Set distinct URLs to cut
    # over to physically separate databases — no code changes required, only
    # config + the data-migration runbook (docs/database-migration-report.md).
    # These URLs are SERVER configuration. No request, job payload, header,
    # or query param may ever select a database (see app/core/db_routing.py).
    platform_database_url: str = Field(default="", max_length=1024)
    prime_database_url: str = Field(default="", max_length=1024)
    nest_database_url: str = Field(default="", max_length=1024)

    # --- Prompt 2: unified platform owner seed ---
    # Development/demo bootstrap for the single canonical owner identity.
    # The password default below is a DEMO credential for non-production
    # only; production refuses to seed the demo password (see seed service).
    owner_seed_email: str = Field(
        default="owner@prime-nest-dashboard.com", max_length=320
    )
    owner_seed_password: str = Field(default="OwnerDemo123!", max_length=128)
    seed_platform_owner: bool = Field(default=True)

    # --- Development staff seed (non-production only) ---
    # Restricted single-business STAFF identities for local dashboard
    # verification (Prime Staff :5175, Nest Staff :5176). Same demo-password
    # convention as the owner seed. NEVER seeded when APP_ENV=production
    # (see seed service) — production staff are invited, never seeded.
    staff_seed_password: str = Field(default="StaffDemo123!", max_length=128)
    seed_dev_staff: bool = Field(default=True)

    # NoDecode: accept comma-separated "http://a,http://b" from env as-is;
    # the validator below splits it (otherwise pydantic-settings tries JSON).
    # Exact origins only — never "*". Dev fallback (localhost) is applied in
    # main.py when nothing is configured outside production.
    backend_cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Public website origins (e.g. the Prime site on Vite dev / its domain).
    # Unioned with BACKEND_CORS_ORIGINS for CORS; also used for public-endpoint
    # Origin documentation. Owner-configurable; no production default invented.
    public_site_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Placeholder for future auth/session signing. Required in production.
    secret_key: str = Field(default="change-me-in-production")

    # --- Block 1: authentication / token configuration ---
    # JWT_SECRET_KEY overrides SECRET_KEY when set (both supported).
    jwt_secret_key: str = Field(default="")
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=14, ge=1, le=90)
    auth_cookie_secure: bool = Field(default=False)
    auth_cookie_samesite: Literal["lax", "strict", "none"] = Field(default="lax")

    # --- Block 2: rate limiting (abuse protection) ---
    # In-process fixed-window limiter. Safe for development / single worker.
    # PRODUCTION REQUIREMENT: with multiple workers/replicas, replace the
    # in-memory backend with Redis (see app/services/rate_limit.py) — the
    # endpoint/service API does not change.
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_requests: int = Field(default=120, ge=1, le=100000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=86400)
    # Stricter bucket for anonymous public intake (per IP + business + endpoint).
    rate_limit_public_requests: int = Field(default=20, ge=1, le=100000)
    rate_limit_public_window_seconds: int = Field(default=600, ge=1, le=86400)
    # Generous bucket for auth endpoints (login/refresh) — abuse extension point.
    rate_limit_auth_requests: int = Field(default=30, ge=1, le=100000)
    rate_limit_auth_window_seconds: int = Field(default=300, ge=1, le=86400)
    # Prompt 8: per-surface buckets (all configurable, Redis-backed in prod).
    # Owner aggregates are expensive (multi-business); webhooks face vendor
    # retries; automation trigger/scheduler-run are privileged ops.
    rate_limit_owner_requests: int = Field(default=60, ge=1, le=100000)
    rate_limit_owner_window_seconds: int = Field(default=60, ge=1, le=86400)
    rate_limit_webhook_requests: int = Field(default=120, ge=1, le=100000)
    rate_limit_webhook_window_seconds: int = Field(default=60, ge=1, le=86400)
    rate_limit_automation_requests: int = Field(default=60, ge=1, le=100000)
    rate_limit_automation_window_seconds: int = Field(default=60, ge=1, le=86400)
    # Prompt 8: per-account login throttle (stacked on the per-IP bucket).
    rate_limit_login_account_requests: int = Field(default=10, ge=1, le=100000)
    rate_limit_login_account_window_seconds: int = Field(default=300, ge=1, le=86400)

    # --- Block 2: API payload limits ---
    # Hard pre-parse cap enforced by middleware on Content-Length for ALL
    # endpoints (Pydantic max_lengths bound the rest after parsing).
    max_body_bytes: int = Field(default=65536, ge=1024, le=1048576)

    # --- Block 2: AI foundation (provider-neutral, disabled by default) ---
    # The app must work completely with AI_ENABLED=false (Noop path).
    # Credentials for future providers live ONLY here (backend env), never in
    # frontend variables. .env.example carries placeholders only.
    ai_enabled: bool = Field(default=False)
    ai_provider: str = Field(default="noop", max_length=64)
    ai_model: str = Field(default="", max_length=128)
    ai_timeout_seconds: int = Field(default=20, ge=1, le=300)
    ai_max_input_chars: int = Field(default=8000, ge=500, le=100000)

    # --- Blocks 8-12: Gemini AI gateway (provider-neutral, Block 10) ---
    # GEMINI_API_KEY lives ONLY in backend env; never exposed to frontend.
    # GEMINI_MODEL is configurable; prefer a current stable Flash-class model.
    # NOTE (Prompt 7, verified live Sep 2026): `gemini-2.5-flash` returns 404
    # "no longer available to new users" for recently provisioned keys (and
    # `gemini-2.0-flash` was shut down Jun 2026). The default is now
    # `gemini-3.6-flash` (live-verified 200 with the gateway's v1beta
    # generateContent shape incl. temperature 0.4 + functionDeclarations).
    # Override via GEMINI_MODEL env for newer Flash models.
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-3.6-flash", max_length=128)
    ai_max_output_tokens: int = Field(default=1024, ge=64, le=8192)
    ai_max_tool_calls: int = Field(default=6, ge=1, le=20)
    ai_public_chat_enabled: bool = Field(default=True)
    ai_public_rate_requests: int = Field(default=10, ge=1, le=1000)
    ai_public_rate_window_seconds: int = Field(default=600, ge=60, le=86400)

    # --- Blocks 8-12: WhatsApp / messaging (provider-neutral, Block 9) ---
    # LEGACY global single-number set (backwards compat only; new code MUST
    # use the business-scoped PRIME_*/NEST_* sets below). A global credential
    # architecture is NOT acceptable for Prime/Nest isolation — the legacy
    # fields are only a demo fallback and never win over a business config.
    whatsapp_enabled: bool = Field(default=False)
    whatsapp_access_token: str = Field(default="")
    whatsapp_phone_number_id: str = Field(default="")
    whatsapp_business_account_id: str = Field(default="")
    whatsapp_verify_token: str = Field(default="")
    whatsapp_app_secret: str = Field(default="")

    # --- Pre-Prompt-7: business-scoped WhatsApp Cloud API credentials ---
    # TWO independent credential sets (one Meta app per business). The
    # provider implementation is shared; ONLY the credentials differ and are
    # resolved server-side from the authenticated BusinessContext (never from
    # client input). Future businesses follow the same pattern (<SLUG>_ prefix).
    # All values live ONLY in backend env (never VITE_*, never committed).
    prime_whatsapp_enabled: bool = Field(default=False)
    prime_whatsapp_access_token: str = Field(default="")
    prime_whatsapp_phone_number_id: str = Field(default="")
    prime_whatsapp_business_account_id: str = Field(default="")
    prime_whatsapp_verify_token: str = Field(default="")
    prime_whatsapp_app_secret: str = Field(default="")
    nest_whatsapp_enabled: bool = Field(default=False)
    nest_whatsapp_access_token: str = Field(default="")
    nest_whatsapp_phone_number_id: str = Field(default="")
    nest_whatsapp_business_account_id: str = Field(default="")
    nest_whatsapp_verify_token: str = Field(default="")
    nest_whatsapp_app_secret: str = Field(default="")
    # Production multi-number routing: "prime:12345,nest:67890" (slug:phone_id pairs).
    # Per-business operational config (business_settings.operational.whatsapp.phone_number_id)
    # wins over this map; the map wins over the single WHATSAPP_PHONE_NUMBER_ID fallback.
    whatsapp_phone_number_map: str = Field(default="", max_length=1024)
    # Meta Graph API version for WhatsApp Cloud API (configurable, no code
    # change needed to move to newer versions, e.g. WHATSAPP_API_VERSION=v22.0).
    # Provider modes: MOCK ("log": demo-safe, no external send) vs META_CLOUD
    # ("whatsapp": real Graph API credential bound). Both names are accepted
    # as provider aliases (see app/services/messaging.py).
    whatsapp_api_version: str = Field(default="v21.0", max_length=16)
    whatsapp_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    whatsapp_max_attempts: int = Field(default=3, ge=1, le=5)

    # --- Full-platform integration: Redis / scheduler / worker ---
    # Empty (default) = single-process safe fallback (in-memory limiter, DB polling).
    # Set REDIS_URL=redis://redis:6379/0 in Docker to enable distributed rate
    # limiting + scheduler leader locking. Never commit real credentials.
    redis_url: str = Field(default="", max_length=512)
    # --- Phase 2: Worker-compatible Redis transport (Upstash REST via httpx) ---
    # Raw redis-py TCP cannot run inside Workers isolates. When these are set
    # (Worker secrets, never frontend vars), the rate limiter + scheduler
    # lease use the REST transport; Docker keeps using REDIS_URL unchanged.
    redis_rest_url: str = Field(default="", max_length=512)
    redis_rest_token: str = Field(default="", max_length=512)
    scheduler_enabled: bool = Field(default=True)
    scheduler_interval_seconds: int = Field(default=60, ge=10, le=3600)
    scheduler_lease_seconds: int = Field(default=120, ge=30, le=3600)
    worker_enabled: bool = Field(default=True)
    worker_interval_seconds: int = Field(default=15, ge=5, le=600)
    worker_batch_size: int = Field(default=50, ge=1, le=500)

    # --- Blocks 8-12: automation scheduler (Block 8) ---
    automation_enabled: bool = Field(default=True)
    automation_max_attempts: int = Field(default=5, ge=1, le=10)

    # --- Prompt 5: payment provider webhook verification ---
    # HMAC secret for provider callbacks. Empty = webhooks rejected with
    # 503 (never accept unverified money movement). Test/simulated
    # webhooks use PAYMENT_WEBHOOK_SECRET=test-secret in local/dev only.
    payment_webhook_secret: str = Field(default="")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "DATABASE_URL is not set. Copy .env.example to .env and set "
                "DATABASE_URL, e.g. "
                "postgresql+psycopg://postgres:postgres@db:5432/app_db"
            )
        vv = v.strip()
        if not vv.startswith(
            (
                "postgresql://",
                "postgresql+psycopg://",
                "postgresql+psycopg2://",
                # Worker edge driver (Hyperdrive, sync SQLAlchemy only).
                # Docker keeps using +psycopg; this only widens accepted input.
                "postgresql+pg8000://",
            )
        ):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL starting with "
                "'postgresql://', 'postgresql+psycopg://' or "
                "'postgresql+pg8000://'. "
                f"Got: '{vv[:24]}...'"
            )
        return vv

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, v: object) -> list[str]:
        return _split_origins(v, env_name="BACKEND_CORS_ORIGINS")

    @field_validator("public_site_origins", mode="before")
    @classmethod
    def split_public_origins(cls, v: object) -> list[str]:
        return _split_origins(v, env_name="PUBLIC_SITE_ORIGINS")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str, info: object) -> str:
        # Enforce a real secret in production; allow the dev default otherwise.
        env = _sibling_field(info, "app_env")
        if env == "production" and v in ("", "change-me-in-production"):
            # Allow production when JWT_SECRET_KEY carries a strong value instead.
            jwt_val = _sibling_field(info, "jwt_secret_key")
            if jwt_val in ("", "change-me-in-production"):
                raise ValueError(
                    "SECRET_KEY (or JWT_SECRET_KEY) must be set to a strong random value "
                    "when APP_ENV=production."
                )
        return v

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, v: str, info: object) -> str:
        env = _sibling_field(info, "app_env")
        if env == "production" and v != "" and v == "change-me-in-production":
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong random value when APP_ENV=production."
            )
        return v

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, v: str) -> str:
        allowed = {"HS256", "HS384", "HS512"}
        if v not in allowed:
            raise ValueError(f"JWT_ALGORITHM must be one of {sorted(allowed)}.")
        return v

    @field_validator("auth_cookie_samesite")
    @classmethod
    def validate_cookie_samesite(cls, v: str, info: object) -> str:
        # SameSite=None requires Secure cookies (browsers reject otherwise);
        # fail fast so a misconfigured production never ships lax security.
        env = _sibling_field(info, "app_env")
        secure_raw = ""
        data = getattr(info, "data", None)
        if isinstance(data, dict):
            secure_raw = str(data.get("auth_cookie_secure", ""))
        if v == "none" and secure_raw.lower() not in ("true", "1", "yes"):
            if env == "production":
                raise ValueError(
                    "AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true."
                )
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"

    @property
    def effective_jwt_secret(self) -> str:
        """Signing key for JWTs: JWT_SECRET_KEY wins, else SECRET_KEY."""
        if self.jwt_secret_key and self.jwt_secret_key.strip():
            return self.jwt_secret_key
        return self.secret_key

    @property
    def effective_cors_origins(self) -> list[str]:
        """Union of configured exact origins (no wildcards, deduped, ordered)."""
        seen: list[str] = []
        for origin in (*self.backend_cors_origins, *self.public_site_origins):
            if origin and origin not in seen:
                seen.append(origin)
        return seen

    @property
    def whatsapp_phone_map(self) -> dict[str, str]:
        """Parse WHATSAPP_PHONE_NUMBER_MAP ("slug:phone_id,slug:phone_id").

        Returns {phone_number_id: slug}. Malformed pairs are ignored (fail safe).
        """
        out: dict[str, str] = {}
        for pair in (self.whatsapp_phone_number_map or "").split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            slug, phone_id = pair.split(":", 1)
            slug, phone_id = slug.strip().lower(), phone_id.strip()
            if slug and phone_id:
                out[phone_id] = slug
        return out

    def database_url_for_key(self, database_key: str) -> str:
        """Resolve the SQLAlchemy URL for a trusted database key.

        Per-key URL wins when configured; otherwise falls back to the shared
        DATABASE_URL (co-located mode). Unknown keys fall back too — the
        allowlist gate lives in app/core/db_routing.py, never here.
        """
        key = (database_key or "").strip()
        if key == "platform_db" and (self.platform_database_url or "").strip():
            return self.platform_database_url.strip()
        if key == "prime_db" and (self.prime_database_url or "").strip():
            return self.prime_database_url.strip()
        if key == "nest_db" and (self.nest_database_url or "").strip():
            return self.nest_database_url.strip()
        return self.database_url

    @property
    def is_split_mode(self) -> bool:
        """True when any business database has its own URL (physical split)."""
        return bool(
            (self.platform_database_url or "").strip()
            or (self.prime_database_url or "").strip()
            or (self.nest_database_url or "").strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Call get_settings.cache_clear() in tests."""
    return Settings()  # type: ignore[call-arg]
