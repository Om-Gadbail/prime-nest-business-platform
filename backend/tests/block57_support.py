"""Shared test support for Blocks 5-7 (SQLite-backed integration tests).

Extends the Block 1/2 strategy: isolated in-memory SQLite per test with
the full seed (RBAC + Prime/Nest + plan catalogues + seat areas).
Adds operational conveniences: role users per business, login tokens,
and entity factories that go through the real HTTP API surface.
"""

from __future__ import annotations

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


@pytest.fixture
def b57():
    """Fresh DB + client + owner/staff/viewer users for prime AND nest."""
    engine, db = make_test_session()
    try:
        from app.api.deps import get_db
        from app.main import create_app

        users = {}
        for slug in ("prime", "nest"):
            for role in ("OWNER", "STAFF", "VIEWER"):
                email = f"{slug}-{role.lower()}@example.com"
                user = create_test_user(db, email=email)
                add_test_membership(
                    db, user_id=user.id, business_slug=slug,
                    role_name=role, is_default=True,
                )
                users[(slug, role)] = user
        # Manager only on prime (plan/seat management permission checks).
        prime_manager = create_test_user(db, email="prime-manager@example.com")
        add_test_membership(
            db, user_id=prime_manager.id, business_slug="prime",
            role_name="MANAGER", is_default=True,
        )
        users[("prime", "MANAGER")] = prime_manager

        app = create_app()

        def _override() -> Generator[Session, None, None]:
            yield db

        app.dependency_overrides[get_db] = _override
        client = TestClient(app, raise_server_exceptions=False)
        tokens = {}
        for (slug, role), user in users.items():
            tokens[(slug, role)] = _login(client, user.email)
        yield {
            "engine": engine, "db": db, "client": client,
            "users": users, "tokens": tokens,
        }
    finally:
        db.close()
        engine.dispose()


def _login(client: TestClient, email: str, **kw) -> dict:
    payload: dict = {"email": email, "password": TEST_PASSWORD}
    payload.update(kw)
    resp = client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def H(env: dict, slug: str, role: str = "OWNER") -> dict:  # noqa: N802
    """Auth headers for a seeded (business, role) user."""
    return auth_headers(env["tokens"][(slug, role)]["access_token"])


# -- API factories (through the real HTTP surface) ---------------------------

def api_member(env: dict, slug: str, role: str = "OWNER", **overrides) -> dict:
    payload = {"display_name": "Test Member", "phone": "+919876543210"}
    payload.update(overrides)
    resp = env["client"].post("/api/v1/members", json=payload, headers=H(env, slug, role))
    assert resp.status_code == 201, resp.text
    return resp.json()


def api_plan_id(env: dict, slug: str, code_contains: str = "1m") -> str:
    """First active plan whose code contains the fragment (Nest seeded)."""
    resp = env["client"].get(
        "/api/v1/membership-plans", params={"limit": 100},
        headers=H(env, slug),
    )
    assert resp.status_code == 200, resp.text
    items = [p for p in resp.json()["items"] if code_contains in p["code"]]
    assert items, f"no seeded plan matches {code_contains!r}"
    return items[0]["id"]


def api_membership(
    env: dict, slug: str, member_id: str, plan_id: str | None = None,
    role: str = "OWNER", **overrides,
) -> dict:
    payload: dict = {"member_id": member_id, "status": "active"}
    if plan_id:
        payload["plan_id"] = plan_id
    else:
        payload.update({"start_date": "2026-01-01", "end_date": "2026-12-31",
                        "price": "1000.00", "currency": "INR"})
    payload.update(overrides)
    resp = env["client"].post(
        "/api/v1/memberships", json=payload, headers=H(env, slug, role)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def api_payment(
    env: dict, slug: str, amount: str = "800.00", role: str = "OWNER",
    **overrides,
) -> dict:
    payload: dict = {"amount": amount, "currency": "INR", "method": "upi"}
    payload.update(overrides)
    resp = env["client"].post(
        "/api/v1/payments", json=payload, headers=H(env, slug, role)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def api_seat(env: dict, slug: str = "nest", number: str = "A-1", **overrides) -> dict:
    payload = {"seat_number": number}
    payload.update(overrides)
    resp = env["client"].post("/api/v1/seats", json=payload, headers=H(env, slug))
    assert resp.status_code == 201, resp.text
    return resp.json()


def api_allocate(
    env: dict, seat_id: str, member_id: str, slug: str = "nest",
    **overrides,
) -> object:
    payload = {"seat_id": seat_id, "member_id": member_id}
    payload.update(overrides)
    return env["client"].post(
        "/api/v1/seat-allocations", json=payload, headers=H(env, slug)
    )
