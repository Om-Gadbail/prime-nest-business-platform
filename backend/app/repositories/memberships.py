"""Membership / role / permission repositories: SQL only."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.membership import BusinessMembership
from app.models.rbac import Permission, Role, RolePermission


def get_membership(
    db: Session, *, user_id: uuid.UUID, business_id: uuid.UUID
) -> BusinessMembership | None:
    stmt = (
        select(BusinessMembership)
        .where(
            BusinessMembership.user_id == user_id,
            BusinessMembership.business_id == business_id,
        )
        .options(
            selectinload(BusinessMembership.role),
            selectinload(BusinessMembership.business),
        )
    )
    return db.execute(stmt).scalars().first()


def list_user_memberships(
    db: Session, *, user_id: uuid.UUID
) -> list[BusinessMembership]:
    stmt = (
        select(BusinessMembership)
        .where(BusinessMembership.user_id == user_id)
        .options(
            selectinload(BusinessMembership.business),
            selectinload(BusinessMembership.role),
        )
        .order_by(BusinessMembership.created_at)
    )
    return list(db.execute(stmt).scalars().all())


def create_membership(
    db: Session,
    *,
    user_id: uuid.UUID,
    business_id: uuid.UUID,
    role_id: uuid.UUID,
    status: str = "active",
    is_default: bool = False,
) -> BusinessMembership:
    membership = BusinessMembership(
        user_id=user_id,
        business_id=business_id,
        role_id=role_id,
        status=status,
        is_default=is_default,
    )
    db.add(membership)
    db.flush()
    return membership


def get_role_by_name(
    db: Session, *, name: str, business_id: uuid.UUID | None = None
) -> Role | None:
    stmt = select(Role).where(Role.name == name, Role.business_id == business_id)
    return db.execute(stmt).scalars().first()


def get_role_by_id(db: Session, role_id: uuid.UUID) -> Role | None:
    return db.get(Role, role_id)


def get_permission_by_key(db: Session, key: str) -> Permission | None:
    stmt = select(Permission).where(Permission.key == key)
    return db.execute(stmt).scalars().first()


def list_role_permission_keys(db: Session, *, role_id: uuid.UUID) -> set[str]:
    stmt = (
        select(Permission.key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return set(db.execute(stmt).scalars().all())


def ensure_role(
    db: Session,
    *,
    name: str,
    display_name: str = "",
    description: str = "",
    business_id: uuid.UUID | None = None,
    is_system: bool = True,
) -> Role:
    existing = get_role_by_name(db, name=name, business_id=business_id)
    if existing is not None:
        return existing
    role = Role(
        name=name,
        display_name=display_name or name.title(),
        description=description,
        business_id=business_id,
        is_system=is_system,
    )
    db.add(role)
    db.flush()
    return role


def ensure_permission(db: Session, *, key: str, description: str = "") -> Permission:
    existing = get_permission_by_key(db, key=key)
    if existing is not None:
        return existing
    perm = Permission(key=key, description=description)
    db.add(perm)
    db.flush()
    return perm


def grant_permission(
    db: Session, *, role_id: uuid.UUID, permission_id: uuid.UUID
) -> None:
    existing = db.get(RolePermission, (role_id, permission_id))
    if existing is None:
        db.add(RolePermission(role_id=role_id, permission_id=permission_id))
        db.flush()
