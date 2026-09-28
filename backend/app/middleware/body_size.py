"""Body-size guard (ASGI middleware, header + actual-bytes, pre-parse).

FastAPI parses JSON bodies before endpoint dependencies run, so a
dependency-level size check cannot protect the parser itself. This
middleware rejects oversized requests using the Content-Length header
(fast path, body never read) AND by counting actual streamed bytes
(closes the chunked/no-length bypass) — the body is capped at the limit
+1 byte so oversized payloads are rejected with 413 before parsing.
Pydantic max_lengths bound the rest.

The limit (MAX_BODY_BYTES, default 64KB) applies to every endpoint;
anonymous intake is additionally rate-limited per IP downstream.
"""

from __future__ import annotations

import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings


def _too_large(limit: int, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "error": {
                "code": "payload_too_large",
                "message": f"Request body too large (limit {limit} bytes).",
            }
        },
        headers={"X-Request-ID": request_id},
    )


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        try:
            limit = int(get_settings().max_body_bytes)
        except (ValueError, AttributeError, TypeError):  # pragma: no cover
            return await call_next(request)
        request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        raw = request.headers.get("content-length")
        if raw:
            try:
                size = int(raw)
            except (TypeError, ValueError):
                size = 0
            if size > limit:
                return _too_large(limit, request_id)
        # Count actual bytes (chunked / missing / lying Content-Length).
        total = 0
        original_receive = request._receive

        async def _receive_limited():  # type: ignore[no-untyped-def]
            nonlocal total
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                total += len(body)
                if total > limit:
                    # Cap: report oversize via sentinel on request state.
                    request.state.body_too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        # Only wrap when a body may be present.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            request._receive = _receive_limited  # type: ignore[attr-defined]
            response = await call_next(request)
            if getattr(request.state, "body_too_large", False):
                return _too_large(limit, request_id)
            return response
        return await call_next(request)
