"""5: invalid configuration fails fast with a clear message."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_missing_database_url_fails_clearly() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="testing",
            database_url="",
            secret_key="test-secret",
        )
    assert "DATABASE_URL is not set" in str(exc_info.value)


def test_non_postgres_url_fails_clearly() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="testing",
            database_url="sqlite:///local.db",
            secret_key="test-secret",
        )
    assert "must be a PostgreSQL URL" in str(exc_info.value)


def test_default_secret_rejected_in_production() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://u:p@db:5432/app_db",
            secret_key="change-me-in-production",
        )
    assert "SECRET_KEY" in str(exc_info.value)


def test_cors_parses_comma_separated_string() -> None:
    s = Settings(
        app_env="testing",
        database_url="postgresql+psycopg://u:p@db:5432/app_db",
        secret_key="test-secret",
        backend_cors_origins="http://a.test, http://b.test",  # type: ignore[arg-type]
    )
    assert s.backend_cors_origins == ["http://a.test", "http://b.test"]
