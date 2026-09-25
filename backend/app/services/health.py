"""Service layer: readiness/health business logic (no SQL here)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories import health as health_repo


def get_health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
    }


def get_api_version() -> dict:
    settings = get_settings()
    return {
        "api_version": "v1",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
    }


def check_readiness(db: Session) -> dict:
    """Check downstream dependencies (currently: database only)."""
    settings = get_settings()
    db_up = health_repo.ping(db)
    if db_up:
        return {
            "ready": True,
            "status": "ready",
            "database": "up",
            "app": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
        }
    return {
        "ready": False,
        "status": "not_ready",
        "database": "down",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
    }
