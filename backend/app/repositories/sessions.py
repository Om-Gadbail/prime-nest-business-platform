"""Auth session repository: SQL only. Only hashes are stored/compared."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth_session import AuthSession


def get_by_hash(db: Session, refresh_token_hash: str) -> AuthSession | None:
    stmt = select(AuthSession).where(
        AuthSession.refresh_token_hash == refresh_token_hash
    )
    return db.execute(stmt).scalars().first()


def create(
    db: Session,
    *,
    user_id: uuid.UUID,
    business_id: uuid.UUID | None,
    refresh_token_hash: str,
    expires_at: datetime,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> AuthSession:
    session = AuthSession(
        user_id=user_id,
        business_id=business_id,
        refresh_token_hash=refresh_token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(session)
    db.flush()
    return session


def revoke(db: Session, session: AuthSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.flush()


def revoke_all_for_user_business(
    db: Session, *, user_id: uuid.UUID, business_id: uuid.UUID | None
) -> int:
    stmt = select(AuthSession).where(
        AuthSession.user_id == user_id,
        AuthSession.business_id == business_id,
        AuthSession.revoked_at.is_(None),
    )
    sessions = list(db.execute(stmt).scalars().all())
    now = datetime.now(timezone.utc)
    for s in sessions:
        s.revoked_at = now
    db.flush()
    return len(sessions)


def revoke_all_for_user(db: Session, *, user_id: uuid.UUID) -> int:
    stmt = select(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    sessions = list(db.execute(stmt).scalars().all())
    now = datetime.now(timezone.utc)
    for s in sessions:
        s.revoked_at = now
    db.flush()
    return len(sessions)


def touch(db: Session, session: AuthSession) -> None:
    session.last_used_at = datetime.now(timezone.utc)
    db.flush()
