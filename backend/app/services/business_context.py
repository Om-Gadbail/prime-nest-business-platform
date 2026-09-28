"""Shared business API layer (Block 3, step 12).

One reusable business-aware foundation for Prime, Nest, and future
businesses — no copy-pasted business-specific backend logic.

Concepts:
- ``BusinessContext`` — deterministic per-request business scope
  (business + membership + user + permissions), built server-side from
  the authenticated token. Client-supplied business IDs are never used.
- ``BusinessResolver`` — resolves staff (Bearer) and public (slug)
  contexts through the single verified paths.
- ``BusinessAccessPolicy`` — explicit permission/role gates used by
  routers (deny by default, least privilege).
- ``BusinessScopedService`` — small helpers for consistent pagination,
  sorting allowlists, and search validation across resources.

Every business-scoped request follows:
  Authenticate -> user -> membership -> business context -> permission
  -> resource scoped to business -> operation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.membership import BusinessMembership
from app.models.user import User
from app.core import db_routing as routing
from app.services import public as public_service
from app.services.authorization import AuthenticatedContext
from app.services.errors import ForbiddenError, NotFoundError


@dataclass(frozen=True)
class BusinessContext:
    """Deterministic server-side business scope for one request.

    Built ONLY after authentication + user-active check + membership
    verification + business-active check + role/permission resolution +
    trusted database mapping. A frontend ``business_id`` is merely a
    REQUESTED context selector — it is never authorization proof and never
    selects a database. The ``database_key`` below comes exclusively from
    the platform registry (``Business.database_key`` via
    ``app.core.db_routing``); unknown/empty mappings fail closed.
    """

    business: Business
    membership: BusinessMembership
    user: User
    role_name: str | None
    permissions: frozenset[str]
    database_key: str = ""
    access_scope: str = "business"
    request_id: str = "-"

    @property
    def business_id(self) -> uuid.UUID:
        return self.business.id

    @property
    def business_slug(self) -> str:
        return self.business.slug

    @property
    def external_business_id(self) -> str | None:
        return getattr(self.business, "external_id", None)

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def has(self, permission: str) -> bool:
        return permission in self.permissions


class BusinessResolver:
    """Single verified resolution paths (staff + public). No alternatives."""

    @staticmethod
    def for_staff(
        ctx: AuthenticatedContext, *, request_id: str = "-"
    ) -> BusinessContext:
        """Build the staff context. Fail closed on any missing/inactive part."""
        if ctx.business is None or ctx.membership is None:
            raise ForbiddenError("No active business context.")
        if not ctx.user.is_active:
            raise ForbiddenError("User is inactive.")
        if ctx.membership.status != "active":
            raise ForbiddenError("Membership is not active.")
        if not ctx.business.is_active or ctx.business.status != "active":
            raise ForbiddenError("Business is not active.")
        try:
            database_key = routing.resolve_database_key(ctx.business)
        except routing.DatabaseRoutingError as exc:
            # No dangerous default tenant: a business without a trusted
            # database mapping cannot serve traffic.
            raise ForbiddenError(
                "Business database mapping is not configured."
            ) from exc
        return BusinessContext(
            business=ctx.business,
            membership=ctx.membership,
            user=ctx.user,
            role_name=ctx.role_name,
            permissions=ctx.permissions,
            database_key=database_key,
            access_scope="business",
            request_id=request_id,
        )

    @staticmethod
    def for_public(db: Session, *, slug: object) -> Business:
        """Resolve an anonymous business by public slug (server-verified)."""
        business = public_service.resolve_public_business(db, slug=slug)
        try:
            routing.resolve_database_key(business)
        except routing.DatabaseRoutingError as exc:
            # Slug is valid but the business has no trusted database mapping:
            # safe failure (same 404 surface as unknown/inactive slug).
            raise NotFoundError("Business not found.") from exc
        return business


class BusinessAccessPolicy:
    """Explicit deny-by-default gates (backend enforcement; frontend hides UX only)."""

    @staticmethod
    def require(ctx: BusinessContext, permission: str) -> None:
        if permission not in ctx.permissions:
            raise ForbiddenError(f"Missing permission: {permission}.")

    @staticmethod
    def require_any(ctx: BusinessContext, *permissions: str) -> None:
        if not any(p in ctx.permissions for p in permissions):
            raise ForbiddenError(f"Missing one of: {', '.join(permissions)}.")

    @staticmethod
    def require_role(ctx: BusinessContext, *role_names: str) -> None:
        """Role gate for exceptional cross-business ops (transfers)."""
        if ctx.role_name not in role_names:
            raise ForbiddenError(
                f"Requires role {role_names[0] if len(role_names) == 1 else role_names}."
            )

    @staticmethod
    def assert_same_business(
        resource_business_id: uuid.UUID, ctx: BusinessContext
    ) -> None:
        """Uniform 404 when a resource belongs to another business (no oracle)."""
        if resource_business_id != ctx.business_id:
            raise NotFoundError("Resource not found.")


class BusinessScopedService:
    """Shared list-parameter helpers (pagination/sort/search discipline)."""

    SEARCH_MAX_CHARS = 64

    @staticmethod
    def validate_search(search: str | None) -> str | None:
        if search is None:
            return None
        text = str(search).strip()
        if not text:
            return None
        if len(text) > BusinessScopedService.SEARCH_MAX_CHARS:
            raise ValueError(
                f"Search must be at most {BusinessScopedService.SEARCH_MAX_CHARS} characters."
            )
        return text

    @staticmethod
    def clamp_page(limit: int | None, offset: int | None) -> tuple[int, int]:
        from app.repositories.pagination import clamp_page

        return clamp_page(limit, offset)
