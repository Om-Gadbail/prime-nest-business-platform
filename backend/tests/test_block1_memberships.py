"""Block 1 — membership / business switching / cross-business access tests."""

from __future__ import annotations

import pytest

from tests.block1_support import (
    TEST_PASSWORD,
    add_test_membership,
    create_test_user,
    make_auth_client,
    make_test_session,
)


@pytest.fixture
def env():
    engine, db = make_test_session()
    try:
        prime_user = create_test_user(db, email="prime@example.com")
        add_test_membership(db, user_id=prime_user.id, business_slug="prime",
                            role_name="OWNER", is_default=True)
        nest_user = create_test_user(db, email="nest@example.com")
        add_test_membership(db, user_id=nest_user.id, business_slug="nest",
                            role_name="OWNER", is_default=True)
        both_user = create_test_user(db, email="both@example.com")
        add_test_membership(db, user_id=both_user.id, business_slug="prime",
                            role_name="STAFF", is_default=True)
        add_test_membership(db, user_id=both_user.id, business_slug="nest",
                            role_name="VIEWER")
        loner = create_test_user(db, email="loner@example.com")
        suspended = create_test_user(db, email="suspended@example.com")
        add_test_membership(db, user_id=suspended.id, business_slug="prime",
                            role_name="STAFF", status="suspended", is_default=True)
        revoked = create_test_user(db, email="revoked@example.com")
        add_test_membership(db, user_id=revoked.id, business_slug="prime",
                            role_name="STAFF", status="revoked", is_default=True)
        client = make_auth_client(db)
        yield {"db": db, "client": client}
    finally:
        db.close()
        engine.dispose()


def _login(client, email, **kw):
    payload = {"email": email, "password": TEST_PASSWORD}
    payload.update(kw)
    return client.post("/api/v1/auth/login", json=payload)


def test_user_can_access_own_business(env) -> None:
    resp = _login(env["client"], "prime@example.com")
    assert resp.status_code == 200
    assert resp.json()["business"]["slug"] == "prime"


def test_prime_user_cannot_access_nest(env) -> None:
    client = env["client"]
    prime = _login(client, "prime@example.com").json()
    # Explicit slug selection for a foreign business must be forbidden.
    resp = _login(client, "prime@example.com", business_slug="nest")
    assert resp.status_code == 403
    # Switch-business to foreign tenant must be forbidden.
    sw = client.post(
        "/api/v1/auth/switch-business",
        json={"business_id": "nest"},
        headers={"Authorization": f"Bearer {prime['access_token']}"},
    )
    assert sw.status_code == 403


def test_nest_user_cannot_access_prime(env) -> None:
    client = env["client"]
    nest = _login(client, "nest@example.com").json()
    assert _login(client, "nest@example.com", business_slug="prime").status_code == 403
    sw = client.post(
        "/api/v1/auth/switch-business",
        json={"business_id": "prime"},
        headers={"Authorization": f"Bearer {nest['access_token']}"},
    )
    assert sw.status_code == 403


def test_multi_business_user_can_access_both(env) -> None:
    client = env["client"]
    first = _login(client, "both@example.com").json()
    assert first["business"]["slug"] == "prime"
    # Switch to nest by slug.
    sw = client.post(
        "/api/v1/auth/switch-business",
        json={"business_id": "nest"},
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert sw.status_code == 200, sw.text
    assert sw.json()["business"]["slug"] == "nest"
    # New token is scoped to nest.
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {sw.json()['access_token']}"},
    )
    assert me.json()["business"]["slug"] == "nest"


def test_suspended_membership_denied(env) -> None:
    resp = _login(env["client"], "suspended@example.com")
    # Login with only a suspended membership yields no business context...
    assert resp.status_code == 200
    assert resp.json()["business"] is None
    # ...and switching into the suspended business is forbidden.
    token = resp.json()["access_token"]
    sw = env["client"].post(
        "/api/v1/auth/switch-business",
        json={"business_id": "prime"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sw.status_code == 403


def test_revoked_membership_denied(env) -> None:
    resp = _login(env["client"], "revoked@example.com")
    assert resp.status_code == 200
    assert resp.json()["business"] is None
    token = resp.json()["access_token"]
    sw = env["client"].post(
        "/api/v1/auth/switch-business",
        json={"business_id": "prime"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sw.status_code == 403


def test_inactive_business_denied(env) -> None:
    from app.models.business import Business
    from sqlalchemy import select

    db = env["db"]
    nest = db.execute(select(Business).where(Business.slug == "nest")).scalars().first()
    assert nest is not None
    nest.is_active = False
    nest.status = "inactive"
    db.commit()
    try:
        # Existing nest user can no longer select nest.
        assert _login(env["client"], "nest@example.com").status_code == 200
        body = _login(env["client"], "nest@example.com").json()
        assert body["business"] is None
        assert _login(env["client"], "nest@example.com", business_slug="nest").status_code == 403
    finally:
        nest.is_active = True
        nest.status = "active"
        db.commit()


def test_business_switch_requires_membership(env) -> None:
    client = env["client"]
    loner = _login(client, "loner@example.com").json()
    sw = client.post(
        "/api/v1/auth/switch-business",
        json={"business_id": "prime"},
        headers={"Authorization": f"Bearer {loner['access_token']}"},
    )
    assert sw.status_code == 403


def test_arbitrary_business_id_cannot_bypass(env) -> None:
    import uuid

    client = env["client"]
    prime = _login(client, "prime@example.com").json()
    fake_id = str(uuid.uuid4())
    sw = client.post(
        "/api/v1/auth/switch-business",
        json={"business_id": fake_id},
        headers={"Authorization": f"Bearer {prime['access_token']}"},
    )
    assert sw.status_code == 403


def test_available_businesses_only_lists_mine(env) -> None:
    client = env["client"]
    prime = _login(client, "prime@example.com").json()
    lst = client.get(
        "/api/v1/auth/businesses",
        headers={"Authorization": f"Bearer {prime['access_token']}"},
    )
    assert lst.status_code == 200
    assert [b["business"]["slug"] for b in lst.json()] == ["prime"]
    both = _login(client, "both@example.com").json()
    lst2 = client.get(
        "/api/v1/auth/businesses",
        headers={"Authorization": f"Bearer {both['access_token']}"},
    )
    assert sorted(b["business"]["slug"] for b in lst2.json()) == ["nest", "prime"]
