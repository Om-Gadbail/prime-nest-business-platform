"""Shared Block 2 endpoint helpers: error mapping + request ID."""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.services.errors import (
    AIDisabledError,
    AIProviderError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    ServiceError,
)


def request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


def record_audit(
    db,  # type: ignore[no-untyped-def]
    *,
    business_id,
    action: str,
    actor_user_id=None,
    entity_type: str | None = None,
    entity_id=None,
    result: str = "success",
    request_id: str = "-",
    ip_address: str | None = None,
    user_agent: str | None = None,
    meta: dict | None = None,
) -> None:
    """Persist one audit event after the business commit (never raises).

    Called AFTER the endpoint's main commit so an audit-write failure can
    never roll back business data. Failures are swallowed deliberately —
    the business operation already succeeded.
    """
    from app.services import audit as audit_service

    try:
        audit_service.log_event(
            db,
            business_id=business_id,
            action=action,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            result=result,
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta=meta,
        )
        db.commit()
    except Exception:  # noqa: BLE001 - audit must never break responses
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def map_service_error(exc: Exception) -> HTTPException:
    """Map service errors to safe HTTP responses (no internals leak)."""
    # Messaging provider failures surface as 502, never a 500.
    if exc.__class__.__name__ == "MessagingError":
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Messaging provider is unavailable. The message was logged for retry.",
        )
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, IntegrityError):
        # Unique-constraint (and similar) races surface here when optimistic
        # handling already rolled back: safe generic 409, never SQL internals.
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request conflicts with existing data. Please retry.",
        )
    if isinstance(exc, PayloadTooLargeError):
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        )
    if isinstance(exc, RateLimitedError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, AIDisabledError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    if isinstance(exc, AIProviderError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    if isinstance(exc, ServiceError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc
