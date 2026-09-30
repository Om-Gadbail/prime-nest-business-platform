"""RBAC models: Role, Permission, RolePermission.

Design:
- roles.business_id NULL  -> system role (OWNER/ADMIN/...) usable by any business.
- roles.business_id NOT NULL -> future business-specific role.
- role assignment always uses role_id FKs; no role-name string checks in services.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

SYSTEM_ROLES = ("OWNER", "ADMIN", "MANAGER", "STAFF", "VIEWER")

# Authorization vocabulary. Only business/settings/users/members/* are enforced
# by Block 1 endpoints; the rest are reserved for future modules.
ALL_PERMISSIONS: tuple[str, ...] = (
    "business.read",
    "business.update",
    "settings.read",
    "settings.update",
    "users.read",
    "users.create",
    "users.update",
    "users.disable",
    "members.read",
    "members.create",
    "members.update",
    "leads.read",
    "leads.create",
    "leads.update",
    "bookings.read",
    "bookings.create",
    "bookings.update",
    "contacts.read",
    "contacts.create",
    "contacts.update",
    "customers.read",
    "customers.create",
    "customers.update",
    "notifications.read",
    "notifications.update",
    "ai.read",
    "leads.transfer",
    "identity.read",
    "tasks.read",
    "tasks.create",
    "tasks.update",
    "audit.read",
    "dashboard.read",
    "payments.read",
    "payments.create",
    "analytics.read",
    # Blocks 5-7 operational permissions (least privilege; deny by default).
    "members.read",
    "members.create",
    "members.update",
    "memberships.read",
    "memberships.create",
    "memberships.update",
    "membership_plans.read",
    "membership_plans.manage",
    "payments.update",
    "payments.refund",
    "attendance.read",
    "attendance.create",
    "attendance.update",
    "renewals.read",
    "renewals.create",
    "renewals.update",
    "seats.read",
    "seats.manage",
    "analytics.owner",
    "owner.dashboard.read",
    "owner.combined.read",
    "approvals.read",
    "approvals.manage",
    # Blocks 8-12: automation / comms / AI / growth / intelligence.
    "automation.read",
    "automation.manage",
    "communications.read",
    "communications.manage",
    "whatsapp.manage",
    "ai.assist",
    "ai.manage",
    "growth.read",
    "growth.manage",
    "reports.read",
)

# Explicit least-privilege matrix (deny by default: anything not listed is denied).
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(ALL_PERMISSIONS),
    "ADMIN": frozenset(p for p in ALL_PERMISSIONS if p != "users.disable"),
    "MANAGER": frozenset(
        {
            "business.read",
            "settings.read",
            "users.read",
            "members.read",
            "members.create",
            "members.update",
            "memberships.read",
            "memberships.create",
            "memberships.update",
            "membership_plans.read",
            "leads.read",
            "leads.create",
            "leads.update",
            "bookings.read",
            "bookings.create",
            "bookings.update",
            "contacts.read",
            "contacts.create",
            "contacts.update",
            "customers.read",
            "customers.create",
            "customers.update",
            "notifications.read",
            "notifications.update",
            "ai.read",
            "tasks.read",
            "tasks.create",
            "tasks.update",
            "audit.read",
            "dashboard.read",
            "payments.read",
            "payments.create",
            "payments.update",
            "attendance.read",
            "attendance.create",
            "attendance.update",
            "renewals.read",
            "renewals.create",
            "renewals.update",
            "seats.read",
            "analytics.read",
            "owner.dashboard.read",
            "approvals.read",
            "automation.read",
            "communications.read",
            "ai.assist",
            "growth.read",
            "reports.read",
        }
    ),
    "STAFF": frozenset(
        {
            "business.read",
            "settings.read",
            "members.read",
            "members.create",
            "members.update",
            "memberships.read",
            "memberships.create",
            "memberships.update",
            "membership_plans.read",
            "leads.read",
            "leads.create",
            "leads.update",
            "bookings.read",
            "bookings.create",
            "bookings.update",
            "contacts.read",
            "contacts.create",
            "contacts.update",
            "customers.read",
            "customers.create",
            "customers.update",
            "notifications.read",
            "notifications.update",
            "tasks.read",
            "tasks.create",
            "tasks.update",
            "audit.read",
            "dashboard.read",
            "payments.read",
            "payments.create",
            "payments.update",
            "attendance.read",
            "attendance.create",
            "attendance.update",
            "renewals.read",
            "renewals.create",
            "renewals.update",
            "seats.read",
            # Nest frontline staff allocate/release seats daily; every
            # mutation is audited and tenant-scoped. Plan pricing
            # (membership_plans.manage) and refunds stay elevated.
            "seats.manage",
            "communications.read",
            "ai.assist",
            "growth.read",
        }
    ),
    "VIEWER": frozenset(
        {
            "business.read",
            "settings.read",
            "users.read",
            "members.read",
            "memberships.read",
            "membership_plans.read",
            "leads.read",
            "bookings.read",
            "contacts.read",
            "customers.read",
            "notifications.read",
            "tasks.read",
            "dashboard.read",
            "payments.read",
            "attendance.read",
            "renewals.read",
            "seats.read",
            "analytics.read",
            "owner.dashboard.read",
            "approvals.read",
            "automation.read",
            "communications.read",
            "growth.read",
            "reports.read",
        }
    ),
}


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_roles_business_id_name"),
        Index("ix_roles_business_id", "business_id"),
        Index("ix_roles_name", "name"),
    )

    id = uuid_pk()
    # NULL = system role; non-NULL = business-specific role (future).
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="cascade"),
        nullable=True,
        default=None,
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["BusinessMembership"]] = relationship(
        "BusinessMembership", back_populates="role", passive_deletes=True
    )


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id = uuid_pk()
    key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="permission", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    """Join table with composite PK (role_id, permission_id)."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("roles.id", ondelete="cascade"),
        primary_key=True,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("permissions.id", ondelete="cascade"),
        primary_key=True,
    )

    role: Mapped[Role] = relationship("Role", back_populates="role_permissions")
    permission: Mapped[Permission] = relationship(
        "Permission", back_populates="role_permissions"
    )
