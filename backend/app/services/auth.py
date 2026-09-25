"""Authentication service: login / refresh / logout / switch-business.

Orchestrates repositories + security primitives. No SQL here (repos own it),
no HTTP here (routers own it).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from sqlalchemy.orm import Session

from app.core import security
from app.core.config import Settings
from app.models.business import Business
from app.models.membership import BusinessMembership
from app.models.user import User
from app.repositories import businesses as business_repo
from app.repositories import memberships as membership_repo
from app.repositories import sessions as session_repo
from app.repositories import users as user_repo
from app.services import authorization as authz

GENERIC_FAILURE = "Invalid email or password."


class AuthError(Exception):
    """Generic authentication failure (message must stay generic to callers)."""


class ForbiddenError(PermissionError):
    """Authenticated but not allowed (maps to 403)."""


def _pick_default_membership(
    memberships: list[BusinessMembership],
) -> BusinessMembership | None:
    """Prefer is_default active membership whose business is active, else first active."""
    active = [m for m in memberships if m.status == "active"]
    # Filter to active businesses only.
    usable = [
        m for m in active
        if m.business is not None and m.business.is_active and m.business.status == "active"
    ]
    if not usable:
        return None
    for m in usable:
        if m.is_default:
            return m
    return usable[0]


def _issue_session(
    db: Session,
    settings: Settings,
    *,
    user: User,
    business: Business | None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str, datetime]:
    """Create access token + rotated refresh session. Returns (access, refresh_raw, exp)."""
    access, _jti, _exp = security.create_access_token(
        user_id=user.id,
        business_id=business.id if business else None,
        secret=settings.effective_jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.access_token_expire_minutes,
    )
    refresh_raw = security.generate_refresh_token()
    refresh_hash = security.hash_refresh_token(refresh_raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    session_repo.create(
        db,
        user_id=user.id,
        business_id=business.id if business else None,
        refresh_token_hash=refresh_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    return access, refresh_raw, expires_at


def login(
    db: Session,
    settings: Settings,
    *,
    email: str,
    password: str,
    business_slug: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Validate credentials, resolve business context, issue tokens."""
    user = user_repo.get_by_email(db, email)
    # Generic failure: do not leak whether the email exists.
    if user is None or not user.is_active:
        # Run a dummy verify to keep timing roughly constant.
        security.verify_password(password, security.hash_password("dummy-password-value"))
        raise AuthError(GENERIC_FAILURE)
    if not security.verify_password(password, user.password_hash):
        raise AuthError(GENERIC_FAILURE)

    memberships = membership_repo.list_user_memberships(db, user_id=user.id)

    target: BusinessMembership | None = None
    if business_slug:
        slug = business_slug.strip().lower()
        for m in memberships:
            if (
                m.business is not None
                and m.business.slug == slug
                and m.status == "active"
                and m.business.is_active
                and m.business.status == "active"
            ):
                target = m
                break
        if target is None:
            raise ForbiddenError("No access to the requested business.")
    else:
        target = _pick_default_membership(memberships)

    business = target.business if target else None
    access, refresh_raw, _exp = _issue_session(
        db, settings, user=user, business=business,
        user_agent=user_agent, ip_address=ip_address,
    )
    user_repo.set_last_login(db, user)
    db.commit()
    # Re-read membership to ensure fresh role eager-load after commit.
    fresh_membership = None
    if target is not None:
        fresh_membership = membership_repo.get_membership(
            db, user_id=user.id, business_id=target.business_id
        )
    ctx = authz.build_context(db, user=user, business=business, membership=fresh_membership)
    return {
        "user": user,
        "business": business,
        "membership": fresh_membership,
        "permissions": sorted(ctx.permissions),
        "access_token": access,
        "refresh_token": refresh_raw,
        "token_type": "bearer",
    }


def refresh(
    db: Session,
    settings: Settings,
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Rotate a refresh token. Reuse of revoked tokens revokes the family."""
    token_hash = security.hash_refresh_token(refresh_token)
    sess = session_repo.get_by_hash(db, token_hash)
    now = datetime.now(timezone.utc)
    if sess is None:
        raise AuthError("Invalid refresh token.")

    # Ensure timezone-aware comparison (SQLite returns naive datetimes).
    expires_at = sess.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if sess.revoked_at is not None:
        # Reuse detected: revoke all sessions for this user (session-family protection).
        session_repo.revoke_all_for_user(db, user_id=sess.user_id)
        db.commit()
        raise AuthError("Invalid refresh token.")
    if expires_at is not None and expires_at <= now:
        raise AuthError("Invalid refresh token.")

    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise AuthError("Invalid refresh token.")

    business = None
    membership = None
    if sess.business_id is not None:
        business = business_repo.get_by_id(db, sess.business_id)
        membership = membership_repo.get_membership(
            db, user_id=user.id, business_id=sess.business_id
        )
        if (
            business is None
            or not business.is_active
            or business.status != "active"
            or membership is None
            or membership.status != "active"
        ):
            raise ForbiddenError("Business access is no longer active.")

    # Rotate: revoke old, issue new.
    session_repo.revoke(db, sess)
    new_business = business
    access, new_refresh_raw, _exp = _issue_session(
        db, settings, user=user, business=new_business,
        user_agent=user_agent or sess.user_agent, ip_address=ip_address or sess.ip_address,
    )
    session_repo.touch(db, sess)
    db.commit()
    ctx = authz.build_context(db, user=user, business=new_business, membership=membership)
    return {
        "user": user,
        "business": new_business,
        "membership": membership,
        "permissions": sorted(ctx.permissions),
        "access_token": access,
        "refresh_token": new_refresh_raw,
        "token_type": "bearer",
    }


def logout(db: Session, *, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    sess = session_repo.get_by_hash(db, security.hash_refresh_token(refresh_token))
    if sess is not None and sess.revoked_at is None:
        session_repo.revoke(db, sess)
        db.commit()


def switch_business(
    db: Session,
    settings: Settings,
    *,
    user: User,
    business_id_or_slug: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Issue fresh tokens for another business the user belongs to."""
    if not user.is_active:
        raise AuthError("Invalid session.")

    business: Business | None = None
    # Accept UUID or slug (both untrusted input — verified against membership).
    try:
        bid = uuid.UUID(str(business_id_or_slug))
        business = business_repo.get_by_id(db, bid)
    except (ValueError, AttributeError):
        business = business_repo.get_by_slug(db, str(business_id_or_slug))

    if business is None or not business.is_active or business.status != "active":
        raise ForbiddenError("No access to the requested business.")
    membership = membership_repo.get_membership(
        db, user_id=user.id, business_id=business.id
    )
    if membership is None or membership.status != "active":
        raise ForbiddenError("No access to the requested business.")

    access, refresh_raw, _exp = _issue_session(
        db, settings, user=user, business=business,
        user_agent=user_agent, ip_address=ip_address,
    )
    db.commit()
    ctx = authz.build_context(db, user=user, business=business, membership=membership)
    return {
        "user": user,
        "business": business,
        "membership": membership,
        "permissions": sorted(ctx.permissions),
        "access_token": access,
        "refresh_token": refresh_raw,
        "token_type": "bearer",
    }


def authenticate_request(db: Session, settings: Settings, *, token: str) -> authz.AuthenticatedContext:
    """Validate Bearer token against DB state (membership/role are authoritative)."""
    try:
        payload = security.decode_access_token(
            token=token,
            secret=settings.effective_jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except pyjwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token.") from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as exc:
        raise AuthError("Invalid or expired token.") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("Invalid or expired token.")

    raw_business = payload.get("business_id")
    if raw_business is None:
        return authz.build_context(db, user=user, business=None, membership=None)
    try:
        business_id = uuid.UUID(str(raw_business))
    except (ValueError, TypeError) as exc:
        raise AuthError("Invalid or expired token.") from exc

    business = business_repo.get_by_id(db, business_id)
    if business is None or not business.is_active or business.status != "active":
        raise ForbiddenError("Business access is no longer active.")
    membership = membership_repo.get_membership(db, user_id=user.id, business_id=business_id)
    if membership is None or membership.status != "active":
        raise ForbiddenError("Business access is no longer active.")
    return authz.build_context(db, user=user, business=business, membership=membership)
