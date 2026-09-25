"""Authentication endpoints (/api/v1/auth).

Token storage note (browser Staff Dashboard):
- Access token: short-lived Bearer token, keep in memory only.
- Refresh token: opaque long-lived credential. Prefer a Secure HttpOnly
  SameSite cookie (set by login/refresh below); NEVER persist it in
  localStorage. The JSON copy in responses exists for non-browser clients
  and tests. No BFF is introduced in this block.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import get_settings
from app.repositories import memberships as membership_repo
from app.schemas.auth import (
    AuthResponse,
    AvailableBusiness,
    BusinessSummary,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    MembershipOut,
    RefreshRequest,
    SwitchBusinessRequest,
    UserOut,
)
from app.services import auth as auth_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
_GENERIC_AUTH_FAILURE = "Invalid email or password."


def _cookie_kwargs() -> dict:
    settings = get_settings()
    kwargs: dict = {
        "httponly": True,
        "samesite": settings.auth_cookie_samesite,
        "secure": settings.auth_cookie_secure,
        "path": "/api/v1/auth",
        "max_age": settings.refresh_token_expire_days * 24 * 3600,
    }
    return kwargs


def _user_out(user: object) -> UserOut:
    return UserOut.model_validate(
        {
            "id": getattr(user, "id"),
            "email": getattr(user, "email"),
            "full_name": getattr(user, "full_name") or "",
            "phone": getattr(user, "phone"),
            "is_active": getattr(user, "is_active"),
            "is_verified": getattr(user, "is_verified"),
            "last_login_at": (
                getattr(user, "last_login_at").isoformat()
                if getattr(user, "last_login_at", None)
                else None
            ),
        }
    )


def _to_auth_response(result: dict) -> AuthResponse:
    user = result["user"]
    business = result.get("business")
    membership = result.get("membership")
    return AuthResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result.get("token_type", "bearer"),
        user=_user_out(user),
        business=BusinessSummary.model_validate(business) if business else None,
        membership=(
            MembershipOut(
                business_id=membership.business_id,
                role=membership.role.name if getattr(membership, "role", None) else None,
                status=membership.status,
                is_default=membership.is_default,
            )
            if membership
            else None
        ),
        permissions=list(result.get("permissions") or []),
    )


def _client_ip(request: Request) -> str | None:
    try:
        if request.client:
            return request.client.host
    except Exception:
        return None
    return None


@router.post("/login", response_model=AuthResponse, summary="Login")
def login(
    payload: LoginRequest, request: Request, response: Response,
    db: Session = Depends(deps.get_db),
) -> AuthResponse:
    settings = get_settings()
    try:
        result = auth_service.login(
            db, settings,
            email=str(payload.email),
            password=payload.password,
            business_slug=payload.business_slug,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except auth_service.ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except auth_service.AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_GENERIC_AUTH_FAILURE
        ) from None
    response.set_cookie(REFRESH_COOKIE, result["refresh_token"], **_cookie_kwargs())
    return _to_auth_response(result)


@router.get("/me", response_model=MeResponse, summary="Current user + business context")
def me(ctx: AuthenticatedContext = Depends(deps.get_current_context)) -> MeResponse:
    membership = ctx.membership
    return MeResponse(
        user=_user_out(ctx.user),
        business=BusinessSummary.model_validate(ctx.business) if ctx.business else None,
        membership=(
            MembershipOut(
                business_id=membership.business_id,
                role=ctx.role_name,
                status=membership.status,
                is_default=membership.is_default,
            )
            if membership
            else None
        ),
        permissions=sorted(ctx.permissions),
    )


@router.post("/refresh", response_model=AuthResponse, summary="Rotate refresh token")
def refresh(
    payload: RefreshRequest, request: Request, response: Response,
    db: Session = Depends(deps.get_db),
) -> AuthResponse:
    settings = get_settings()
    raw = payload.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")
    try:
        result = auth_service.refresh(
            db, settings, refresh_token=raw,
            user_agent=request.headers.get("user-agent"), ip_address=_client_ip(request),
        )
    except auth_service.ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except auth_service.AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token."
        ) from None
    response.set_cookie(REFRESH_COOKIE, result["refresh_token"], **_cookie_kwargs())
    return _to_auth_response(result)


@router.post("/logout", status_code=200, summary="Logout (revoke session)")
def logout(
    payload: LogoutRequest, request: Request, response: Response,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.get_current_context),
) -> dict:
    raw = payload.refresh_token or request.cookies.get(REFRESH_COOKIE)
    auth_service.logout(db, refresh_token=raw)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return {"status": "logged_out"}


@router.get(
    "/businesses", response_model=list[AvailableBusiness], summary="Businesses I belong to"
)
def my_businesses(
    ctx: AuthenticatedContext = Depends(deps.get_current_context),
    db: Session = Depends(deps.get_db),
) -> list[AvailableBusiness]:
    memberships = membership_repo.list_user_memberships(db, user_id=ctx.user.id)
    out: list[AvailableBusiness] = []
    for m in memberships:
        if m.business is None or m.status != "active":
            continue
        if not m.business.is_active or m.business.status != "active":
            continue
        out.append(
            AvailableBusiness(
                business=BusinessSummary.model_validate(m.business),
                role=m.role.name if getattr(m, "role", None) else None,
                status=m.status,
                is_default=m.is_default,
            )
        )
    return out


@router.post("/switch-business", response_model=AuthResponse, summary="Switch business")
def switch_business(
    payload: SwitchBusinessRequest, request: Request, response: Response,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.get_current_context),
) -> AuthResponse:
    settings = get_settings()
    try:
        result = auth_service.switch_business(
            db, settings, user=ctx.user, business_id_or_slug=payload.business_id,
            user_agent=request.headers.get("user-agent"), ip_address=_client_ip(request),
        )
    except auth_service.ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    response.set_cookie(REFRESH_COOKIE, result["refresh_token"], **_cookie_kwargs())
    return _to_auth_response(result)
