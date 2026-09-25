"""Application settings (pydantic-settings).

Single source of truth for environment-driven configuration.
Fails fast with a clear message when required values are missing/invalid.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Prime Nest Business Platform")
    app_env: Literal["development", "testing", "production"] = Field(default="development")
    app_version: str = Field(default="0.1.0")
    api_v1_prefix: str = Field(default="/api/v1")
    log_level: str = Field(default="INFO")

    # Example: postgresql+psycopg://user:password@db:5432/app_db
    database_url: str = Field(default="")

    # NoDecode: accept comma-separated "http://a,http://b" from env as-is;
    # the validator below splits it (otherwise pydantic-settings tries JSON).
    backend_cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

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
        if not vv.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL starting with "
                "'postgresql://' or 'postgresql+psycopg://'. "
                f"Got: '{vv[:24]}...'"
            )
        return vv

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, v: object) -> list[str]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        if isinstance(v, list):
            return [str(o).strip() for o in v if str(o).strip()]
        raise ValueError("BACKEND_CORS_ORIGINS must be a comma-separated string or list")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str, info: object) -> str:
        # Enforce a real secret in production; allow the dev default otherwise.
        env = ""
        try:
            env = str(getattr(getattr(info, "data", {}), "get", lambda *a, **k: "")("app_env", "") or "")
        except Exception:
            env = ""
        if env == "production" and v in ("", "change-me-in-production"):
            # Allow production when JWT_SECRET_KEY carries a strong value instead.
            jwt_val = ""
            try:
                jwt_val = str(
                    getattr(getattr(info, "data", {}), "get", lambda *a, **k: "")(
                        "jwt_secret_key", ""
                    )
                    or ""
                )
            except Exception:
                jwt_val = ""
            if jwt_val in ("", "change-me-in-production"):
                raise ValueError(
                    "SECRET_KEY (or JWT_SECRET_KEY) must be set to a strong random value "
                    "when APP_ENV=production."
                )
        return v

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, v: str, info: object) -> str:
        env = ""
        try:
            env = str(getattr(getattr(info, "data", {}), "get", lambda *a, **k: "")("app_env", "") or "")
        except Exception:
            env = ""
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


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Call get_settings.cache_clear() in tests."""
    return Settings()  # type: ignore[call-arg]
