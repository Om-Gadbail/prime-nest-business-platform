"""Authorization service: server-side permission resolution.

Rules:
- Database membership/role state is authoritative (JWT is identity/context only).
- Deny by default; permissions come from role_permissions join, never from
  role-name string comparisons scattered through the codebase.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.membership import BusinessMembership
from app.models.user import User
from app.repositories import memberships as membership_repo


@dataclass(frozen=True)
class AuthenticatedContext:
    user: User
    business: Business | None
    membership: BusinessMembership | None
    role_name: str | None
    permissions: frozenset[str]


def resolve_permissions(db: Session, *, role_id: uuid.UUID) -> frozenset[str]:
    return frozenset(membership_repo.list_role_permission_keys(db, role_id=role_id))


def build_context(
    db: Session, *, user: User, business: Business | None,
    membership: BusinessMembership | None,
) -> AuthenticatedContext:
    if membership is None:
        return AuthenticatedContext(
            user=user, business=business, membership=None,
            role_name=None, permissions=frozenset(),
        )
    # Ensure role is loaded (membership query eager-loads it, but be safe).
    role = membership.role
    role_name = role.name if role is not None else None
    permissions = resolve_permissions(db, role_id=membership.role_id)
    return AuthenticatedContext(
        user=user, business=business, membership=membership,
        role_name=role_name, permissions=permissions,
    )


def has_permission(ctx: AuthenticatedContext, permission: str) -> bool:
    return permission in ctx.permissions


def require_active_context(ctx: AuthenticatedContext) -> None:
    """Raise PermissionError if the context is not usable (fail closed)."""
    if ctx.business is None or ctx.membership is None:
        raise PermissionError("No active business context.")
    if not ctx.user.is_active:
        raise PermissionError("User is inactive.")
    if ctx.membership.status != "active":
        raise PermissionError("Membership is not active.")
    if not ctx.business.is_active or ctx.business.status != "active":
        raise PermissionError("Business is not active.")
