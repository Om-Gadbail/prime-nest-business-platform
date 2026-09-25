"""Versioned system endpoints (proves /api/v1 wiring works)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.health import VersionResponse
from app.services import health as health_service

router = APIRouter(tags=["system"])


@router.get("/version", response_model=VersionResponse, summary="API version")
def get_version() -> dict:
    return health_service.get_api_version()
