"""Shared API dependencies: DB session + authenticated business context.

SECURITY MODEL:
- JWT provides identity/context claims only.
- Database membership/role state is AUTHORITATIVE on every request.
- Client-provided business_id (URL/query/body/header) is NEVER trusted.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.services import auth as auth_service
from app.services.authorization import AuthenticatedContext

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token (Bearer).")


def _unauthorized(detail: str = "Not authenticated.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _forbidden(detail: str = "Forbidden.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _require_database_mapping(ctx: AuthenticatedContext) -> None:
    """Enforce the trusted database mapping on every business-scoped request.

    This is the choke point behind all 140 permission gates: any request
    carrying a business context must resolve to a known database key, or it
    fails closed (403). There is no fallback database. Business-less
    contexts (e.g. /auth/me before a business is selected) skip this check.
    """
    if ctx.business is None:
        return
    from app.core import db_routing as routing

    try:
        routing.resolve_database_key(ctx.business)
    except routing.DatabaseRoutingError as exc:
        raise _forbidden("Business database mapping is not configured.") from exc


def _extract_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials is None or not credentials.credentials:
        return None
    scheme = (credentials.scheme or "").lower()
    if scheme != "bearer":
        return None
    return credentials.credentials


def get_current_context(
    request: Request,
    db: Session = Depends(get_db),
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> AuthenticatedContext:
    settings = get_settings()
    token = _extract_bearer_token(credentials)
    if not token:
        raise _unauthorized("Not authenticated.")
    try:
        ctx = auth_service.authenticate_request(db, settings, token=token)
    except auth_service.ForbiddenError as exc:
        raise _forbidden(str(exc)) from exc
    except auth_service.AuthError as exc:
        raise _unauthorized(str(exc)) from exc
    request.state.auth_context = ctx
    return ctx


def get_current_user(
    ctx: AuthenticatedContext = Depends(get_current_context),
):  # type: ignore[no-untyped-def]
    return ctx.user


def get_current_business(
    ctx: AuthenticatedContext = Depends(get_current_context),
):  # type: ignore[no-untyped-def]
    if ctx.business is None:
        raise _forbidden("No active business context.")
    _require_database_mapping(ctx)
    return ctx.business


def get_current_membership(
    ctx: AuthenticatedContext = Depends(get_current_context),
):  # type: ignore[no-untyped-def]
    if ctx.membership is None:
        raise _forbidden("No active business membership.")
    _require_database_mapping(ctx)
    return ctx.membership


def require_permission(permission: str):  # type: ignore[no-untyped-def]
    """Dependency factory: Depends(require_permission("settings.read"))."""

    def _checker(
        ctx: AuthenticatedContext = Depends(get_current_context),
    ) -> AuthenticatedContext:
        if ctx.business is None or ctx.membership is None:
            raise _forbidden("No active business context.")
        if permission not in ctx.permissions:
            raise _forbidden(f"Missing permission: {permission}.")
        _require_database_mapping(ctx)
        return ctx

    return _checker


def require_business_membership(
    ctx: AuthenticatedContext = Depends(get_current_context),
) -> AuthenticatedContext:
    if ctx.business is None or ctx.membership is None:
        raise _forbidden("No active business membership.")
    _require_database_mapping(ctx)
    return ctx


def get_platform_db(
    db: Session = Depends(get_db),
):  # type: ignore[no-untyped-def]
    """Explicit platform control-plane session (identity/RBAC/registry/audit).

    In co-located mode this is the shared request session; after the physical
    split it resolves to the ``platform_db`` engine for the request scope.
    Prefer this over bare ``get_db`` when the operation is platform-scoped.
    """
    return db


def get_business_db(
    db: Session = Depends(get_db),
    ctx: AuthenticatedContext = Depends(require_business_membership),
):  # type: ignore[no-untyped-def]
    """Explicit business-operational session for the verified context.

    The session serves ``ctx``'s ``database_key`` (prime_db / nest_db) with
    membership + mapping already verified. Prefer this over bare ``get_db``
    in business-scoped routes. Session lifetime stays request-scoped and the
    session is never shared across tasks.
    """
    return db, ctx


__all__ = [
    "bearer_scheme",
    "get_business_db",
    "get_current_business",
    "get_current_context",
    "get_current_membership",
    "get_current_user",
    "get_db",
    "get_platform_db",
    "require_business_membership",
    "require_permission",
]
