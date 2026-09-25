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

    # Drop cached singletons so the new env takes effect per test.
    from app.core import database
    from app.core.config import get_settings

    get_settings.cache_clear()
    database.reset_engine_cache()
    yield
    get_settings.cache_clear()
    database.reset_engine_cache()


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
