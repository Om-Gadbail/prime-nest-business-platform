"""Application factory + entrypoint.

Unversioned operational endpoints: /health (liveness), /ready (readiness).
Versioned business API: /api/v1/...
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.middleware.body_size import BodySizeLimitMiddleware
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_id import RequestIDMiddleware
from app.schemas.health import HealthResponse, NotReadyResponse, ReadyResponse
from app.services import health as health_service

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "starting app=%r env=%s version=%s",
        settings.app_name,
        settings.app_env,
        settings.app_version,
    )
    try:
        from app.services import rate_limit as rate_limit_service

        backend = rate_limit_service.configure_redis_limiter(settings)
        logger.info("rate limiter backend=%s", backend)
    except Exception as exc:  # noqa: BLE001 - limiter fallback must never block boot
        logger.warning("rate limiter configuration skipped: %s", type(exc).__name__)
    yield
    logger.info("stopping app")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # --- middleware ---
    # Added first so it runs innermost (after RequestID): 413s carry the
    # request ID and never touch the JSON parser (header-only check).
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)
    # Safe CORS: exact origins only; empty list = same-origin only.
    # In development, allow common local dev servers when nothing is configured.
    cors_origins = list(settings.effective_cors_origins)
    if not cors_origins and not settings.is_production:
        cors_origins = ["http://localhost:3000", "http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "Idempotency-Key",
        ],
    )

    register_exception_handlers(app)

    # --- operational endpoints (unversioned) ---
    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["operations"],
        summary="Liveness",
    )
    def health() -> dict:
        # Liveness: no DB touch, so orchestrators can restart safely.
        return health_service.get_health()

    @app.get(
        "/ready",
        tags=["operations"],
        summary="Readiness",
        responses={200: {"model": ReadyResponse}, 503: {"model": NotReadyResponse}},
    )
    def ready(db: Session = Depends(deps.get_db)) -> dict:
        from fastapi.responses import JSONResponse

        result = health_service.check_readiness(db)
        if result["ready"]:
            payload = {k: v for k, v in result.items() if k != "ready"}
            return payload
        payload = {k: v for k, v in result.items() if k != "ready"}
        return JSONResponse(status_code=503, content=payload)  # type: ignore[return-value]

    # --- versioned API ---
    app.include_router(v1_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
