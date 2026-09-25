"""Shared test support for Block 1 (SQLite-backed integration tests).

Uses an isolated in-memory SQLite database per test so tenant isolation,
RBAC, and auth flows are exercised without a live Postgres. Production
migrations still target Postgres via Docker (see README).
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_PASSWORD = "StrongPass-1234!"


def make_test_session() -> tuple[object, Session]:
    """Create fresh SQLite engine + seeded session. Caller must close/dispose."""
    from app.models import Base
    from app.services import seed

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db: Session = factory()
    seed.seed_development(db)
    return engine, db


def create_test_user(
    db: Session,
    *,
    email: str,
    password: str = TEST_PASSWORD,
    full_name: str = "Test User",
    is_active: bool = True,
    is_verified: bool = True,
):  # type: ignore[no-untyped-def]
    from app.core import security
    from app.repositories import users as user_repo

    user = user_repo.create(
        db,
        email=email,
        password_hash=security.hash_password(password),
        full_name=full_name,
        is_active=is_active,
        is_verified=is_verified,
    )
    db.commit()
    db.refresh(user)
    return user


def add_test_membership(
    db: Session,
    *,
    user_id: object,
    business_slug: str,
    role_name: str = "STAFF",
    status: str = "active",
    is_default: bool = False,
):  # type: ignore[no-untyped-def]
    from app.models.business import Business
    from app.repositories import memberships as membership_repo

    business = db.execute(select(Business).where(Business.slug == business_slug)).scalars().first()
    assert business is not None, f"seed missing business {business_slug}"
    role = membership_repo.get_role_by_name(db, name=role_name)
    assert role is not None, f"seed missing role {role_name}"
    membership = membership_repo.create_membership(
        db,
        user_id=user_id,  # type: ignore[arg-type]
        business_id=business.id,
        role_id=role.id,
        status=status,
        is_default=is_default,
    )
    db.commit()
    # Re-fetch with eager loads for role/business access after commit.
    fresh = membership_repo.get_membership(db, user_id=user_id, business_id=business.id)  # type: ignore[arg-type]
    assert fresh is not None
    return fresh


def login_token(
    client, *, email: str, password: str = TEST_PASSWORD, business_slug: str | None = None
) -> dict:
    """Login via API and return parsed body (access/refresh tokens included)."""
    payload: dict = {"email": email, "password": password}
    if business_slug:
        payload["business_slug"] = business_slug
    resp = client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_auth_client(db: Session):  # type: ignore[no-untyped-def]
    """Build a TestClient whose get_db dependency yields the given SQLite session."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import create_app

    app = create_app()

    def _override() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = _override
    return TestClient(app, raise_server_exceptions=False)
