"""User repository: SQL only."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == normalize_email(email))
    return db.execute(stmt).scalars().first()


def create(
    db: Session,
    *,
    email: str,
    password_hash: str,
    full_name: str = "",
    phone: str | None = None,
    is_active: bool = True,
    is_verified: bool = False,
) -> User:
    user = User(
        email=normalize_email(email),
        password_hash=password_hash,
        full_name=full_name,
        phone=phone,
        is_active=is_active,
        is_verified=is_verified,
    )
    db.add(user)
    db.flush()
    return user


def set_last_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    db.flush()
