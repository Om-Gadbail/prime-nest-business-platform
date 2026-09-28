"""Shared test support for Block 2 (SQLite-backed integration tests).

Same strategy as Block 1: isolated in-memory SQLite per test, production
migrations target Postgres via Docker. Adds Block 2 conveniences: role
users, login tokens, public payload factories, rate-limiter isolation.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.block1_support import (
    TEST_PASSWORD,
    add_test_membership,
    create_test_user,
    make_test_session,
)

STAFF_ROLES = ("OWNER", "ADMIN", "MANAGER", "STAFF", "VIEWER")


@pytest.fixture
def b2():
    """Fresh DB + client + prime/nest owner users with tokens."""
    engine, db = make_test_session()
    try:
        from app.api.deps import get_db
        from app.main import create_app

        prime_owner = create_test_user(db, email="prime-owner@example.com")
        add_test_membership(
            db, user_id=prime_owner.id, business_slug="prime",
            role_name="OWNER", is_default=True,
        )
        nest_owner = create_test_user(db, email="nest-owner@example.com")
        add_test_membership(
            db, user_id=nest_owner.id, business_slug="nest",
            role_name="OWNER", is_default=True,
        )
        app = create_app()

        def _override() -> Generator[Session, None, None]:
            yield db

        app.dependency_overrides[get_db] = _override
        client = TestClient(app, raise_server_exceptions=False)
        prime_tokens = _login(client, "prime-owner@example.com")
        nest_tokens = _login(client, "nest-owner@example.com")
        yield {
            "engine": engine,
            "db": db,
            "client": client,
            "prime_owner": prime_owner,
            "nest_owner": nest_owner,
            "prime": prime_tokens,
            "nest": nest_tokens,
        }
    finally:
        db.close()
        engine.dispose()


def enable_rate_limit(
    monkeypatch: pytest.MonkeyPatch, *, public_requests: int = 2,
    public_window: int = 600, auth_requests: int = 30, auth_window: int = 300,
) -> None:
    """Turn the limiter on with tiny budgets for abuse-protection tests."""
    from app.core.config import get_settings

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_REQUESTS", str(public_requests))
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_WINDOW_SECONDS", str(public_window))
    monkeypatch.setenv("RATE_LIMIT_AUTH_REQUESTS", str(auth_requests))
    monkeypatch.setenv("RATE_LIMIT_AUTH_WINDOW_SECONDS", str(auth_window))
    get_settings.cache_clear()


def _login(client: TestClient, email: str, **kw) -> dict:
    payload: dict = {"email": email, "password": TEST_PASSWORD}
    payload.update(kw)
    resp = client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def login_as(
    client: TestClient, db: Session, *, email: str, slug: str, role: str = "STAFF"
) -> dict:
    """Create (or reuse) a user with the given role and return login tokens."""
    from sqlalchemy import select

    from app.models.user import User

    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if user is None:
        user = create_test_user(db, email=email)
        add_test_membership(
            db, user_id=user.id, business_slug=slug, role_name=role,
            is_default=True,
        )
    return _login(client, email)


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_user(db: Session, *, email: str, slug: str, role: str):
    user = create_test_user(db, email=email)
    add_test_membership(
        db, user_id=user.id, business_slug=slug, role_name=role, is_default=True
    )
    return user


def public_lead_payload(**overrides) -> dict:
    payload = {
        "name": "Aarav Sharma",
        "phone": "+919876543210",
        "email": "aarav@example.com",
        "message": "I want to know about memberships.",
        "service_interest": "Gym Membership",
    }
    payload.update(overrides)
    return payload


def public_booking_payload(**overrides) -> dict:
    payload = {
        "name": "Aarav Sharma",
        "phone": "+919876543210",
        "booking_type": "trial",
        "title": "Free trial visit",
        "message": "Saturday morning please.",
    }
    payload.update(overrides)
    return payload


def new_idem_key() -> str:
    return f"test-{uuid.uuid4().hex[:20]}"
