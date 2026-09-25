"""Consistent error responses; never leak internals in production."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope("http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Return a safe summary, not raw internals.
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )[:500]
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", details or "Invalid request."),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        logger.exception("unhandled error request_id=%s: %s", request_id, type(exc).__name__)
        try:
            debug = not get_settings().is_production
        except Exception:  # noqa: BLE001
            debug = False
        message = f"{type(exc).__name__}: {exc}" if debug else "Internal server error."
        return JSONResponse(status_code=500, content=_envelope("internal_error", message))
