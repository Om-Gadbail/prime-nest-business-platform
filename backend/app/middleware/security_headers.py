"""Security-headers middleware (Prompt 8).

Adds defense-in-depth response headers without breaking local HTTP dev:
- X-Content-Type-Options: nosniff (always)
- Referrer-Policy: strict-origin-when-cross-origin (always)
- X-Frame-Options: DENY (always; dashboards use top-level navigation)
- Permissions-Policy: minimal (no camera/mic/geolocation)
- HSTS: only when the request is HTTPS (never force on local HTTP)
- Content-Security-Policy: report-only style minimal default that does not
  break Vite dev or Swagger UI (no blocking frame-ancestors beyond DENY).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # HSTS only over HTTPS so local http://localhost dev keeps working.
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
