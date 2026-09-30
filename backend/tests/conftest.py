"""Shared pytest fixtures: env isolation + FastAPI TestClient."""

from __future__ import annotations

import os

# Set safe defaults at IMPORT time (before any `import app...` runs at
# collection). The per-test fixture below re-isolates via monkeypatch.
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_NAME", "Prime Nest Test Platform")
os.environ.setdefault("APP_VERSION", "0.0.0-test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test_db")
os.environ.setdefault("BACKEND_CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test a valid, isolated configuration by default."""
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("APP_NAME", "Prime Nest Test Platform")
    monkeypatch.setenv("APP_VERSION", "0.0.0-test")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test_db"
    )
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    # Hermetic provider defaults: a developer/demo `.env` may carry LIVE
    # Meta WhatsApp test credentials (PRIME_WHATSAPP_*) and a Gemini key.
    # Process env wins over the `.env` file in pydantic-settings, so pin
    # the demo-safe defaults here; tests that need a credential set their
    # own monkeypatched values explicitly.
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.setenv("AI_PROVIDER", "noop")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    for prefix in ("WHATSAPP", "PRIME_WHATSAPP", "NEST_WHATSAPP"):
        monkeypatch.setenv(f"{prefix}_ENABLED", "false")
        for field in ("ACCESS_TOKEN", "PHONE_NUMBER_ID", "BUSINESS_ACCOUNT_ID",
                      "VERIFY_TOKEN", "APP_SECRET"):
            monkeypatch.setenv(f"{prefix}_{field}", "")

    # Drop cached singletons so the new env takes effect per test.
    from app.core import database
    from app.core.config import get_settings
    from app.services.rate_limit import InMemoryRateLimiter, set_limiter

    get_settings.cache_clear()
    database.reset_engine_cache()
    # Fresh rate-limit state per test (the limiter is process-global; without
    # this, one test's logins would consume another test's bucket).
    set_limiter(InMemoryRateLimiter())
    yield
    get_settings.cache_clear()
    database.reset_engine_cache()
    set_limiter(InMemoryRateLimiter())


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def db_session_mock() -> object:
    """A minimal stub session whose execute() succeeds (SELECT 1)."""

    class _Result:
        pass

    class _Session:
        def execute(self, *args: object, **kwargs: object) -> _Result:
            return _Result()

        def close(self) -> None:
            pass

    return _Session()
