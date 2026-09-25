"""Versioned API router: all /api/v1 routes are assembled here."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import auth, business, system

router = APIRouter()
router.include_router(system.router)
router.include_router(auth.router)
router.include_router(business.router)
