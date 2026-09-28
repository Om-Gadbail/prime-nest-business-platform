"""Block 2 service-layer errors (mapped to HTTP status by routers)."""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for expected service failures (safe messages only)."""


class NotFoundError(ServiceError):
    """Record not found within the authorized scope (maps to 404)."""


class ForbiddenError(ServiceError):
    """Authenticated but not allowed (maps to 403)."""


class ConflictError(ServiceError):
    """State/idempotency/duplicate conflict (maps to 409)."""


class PayloadTooLargeError(ServiceError):
    """Request body exceeds the configured limit (maps to 413)."""


class RateLimitedError(ServiceError):
    """Rate limit exceeded (maps to 429)."""

    def __init__(self, message: str = "Rate limit exceeded.", retry_after: int = 60):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class AIDisabledError(ServiceError):
    """AI is disabled (maps to 503 — dependency not configured)."""


class AIProviderError(ServiceError):
    """AI provider failure or misconfiguration (maps to 502)."""
