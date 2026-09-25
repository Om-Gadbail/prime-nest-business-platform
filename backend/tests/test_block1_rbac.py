"""Block 1 — RBAC enforcement tests."""

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
        tokens = {}
        client_holder: dict = {}
        for role in ("OWNER", "ADMIN", "MANAGER", "STAFF", "VIEWER"):
            email = f"{role.lower()}@example.com"
            user = create_test_user(db, email=email)
            add_test_membership(db, user_id=user.id, business_slug="prime",
                                role_name=role, is_default=True)
        from tests.block1_support import make_auth_client as _mk

        client = _mk(db)
        for role in ("OWNER", "ADMIN", "MANAGER", "STAFF", "VIEWER"):
            email = f"{role.lower()}@example.com"
            body = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": TEST_PASSWORD},
            ).json()
            tokens[role] = body["access_token"]
        yield {"db": db, "client": client, "tokens": tokens}
    finally:
        db.close()
        engine.dispose()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_owner_has_all_permissions(env) -> None:
    client = env["client"]
    me = client.get("/api/v1/auth/me", headers=_h(env["tokens"]["OWNER"])).json()
    for perm in (
        "business.read", "business.update", "settings.read", "settings.update",
        "users.read", "members.read",
    ):
        assert perm in me["permissions"]


def test_admin_operational_permissions(env) -> None:
    client = env["client"]
    me = client.get("/api/v1/auth/me", headers=_h(env["tokens"]["ADMIN"])).json()
    assert "settings.update" in me["permissions"]
    assert "business.update" in me["permissions"]
    # ADMIN deliberately lacks users.disable (OWNER-only in this matrix).
    assert "users.disable" not in me["permissions"]


def test_manager_permissions(env) -> None:
    me = env["client"].get(
        "/api/v1/auth/me", headers=_h(env["tokens"]["MANAGER"])
    ).json()
    assert "members.create" in me["permissions"]
    assert "settings.update" not in me["permissions"]
    assert "business.update" not in me["permissions"]


def test_staff_limited_permissions(env) -> None:
    me = env["client"].get("/api/v1/auth/me", headers=_h(env["tokens"]["STAFF"])).json()
    assert "leads.create" in me["permissions"]
    assert "settings.update" not in me["permissions"]
    assert "members.create" not in me["permissions"]


def test_viewer_read_only(env) -> None:
    client = env["client"]
    me = client.get("/api/v1/auth/me", headers=_h(env["tokens"]["VIEWER"])).json()
    assert "business.read" in me["permissions"]
    assert "settings.read" in me["permissions"]
    assert "settings.update" not in me["permissions"]
    # Viewer cannot write settings.
    resp = client.patch(
        "/api/v1/business/settings",
        json={"branding": {"tagline": "x"}},
        headers=_h(env["tokens"]["VIEWER"]),
    )
    assert resp.status_code == 403


def test_unauthorized_write_rejected(env) -> None:
    client = env["client"]
    for role in ("MANAGER", "STAFF", "VIEWER"):
        resp = client.patch(
            "/api/v1/business/settings",
            json={"branding": {"tagline": "x"}},
            headers=_h(env["tokens"][role]),
        )
        assert resp.status_code == 403, role


def test_unauthorized_read_rejected_for_no_context(env) -> None:
    engine2, db2 = make_test_session()
    try:
        from tests.block1_support import create_test_user as _cu
        from tests.block1_support import make_auth_client as _mk

        _cu(db2, email="loner@example.com")
        c2 = _mk(db2)
        token = c2.post(
            "/api/v1/auth/login",
            json={"email": "loner@example.com", "password": TEST_PASSWORD},
        ).json()["access_token"]
        resp = c2.get("/api/v1/business", headers=_h(token))
        assert resp.status_code == 403
    finally:
        db2.close()
        engine2.dispose()


def test_role_escalation_rejected(env) -> None:
    """Clients cannot assign themselves OWNER via any API payload."""
    client = env["client"]
    # No endpoint accepts role assignment; attempt to smuggle role fields.
    resp = client.patch(
        "/api/v1/business",
        json={"name": "Hacked", "role": "OWNER", "role_id": "OWNER"},  # type: ignore
        headers=_h(env["tokens"]["STAFF"]),
    )
    # STAFF lacks business.update -> 403 regardless of smuggled fields.
    assert resp.status_code == 403
    me = client.get("/api/v1/auth/me", headers=_h(env["tokens"]["STAFF"])).json()
    assert me["membership"]["role"] == "STAFF"


def test_changed_role_takes_effect_immediately(env) -> None:
    from app.repositories import memberships as membership_repo
    from app.models.user import User
    from sqlalchemy import select

    db = env["db"]
    client = env["client"]
    staff_user = db.execute(select(User).where(User.email == "staff@example.com")).scalars().first()
    assert staff_user is not None
    from app.models.business import Business

    prime = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    assert prime is not None
    membership = membership_repo.get_membership(db, user_id=staff_user.id, business_id=prime.id)
    assert membership is not None
    viewer_role = membership_repo.get_role_by_name(db, name="VIEWER")
    assert viewer_role is not None
    membership.role_id = viewer_role.id
    db.commit()
    # Shared test session caches relationships (expire_on_commit=False);
    # expire so the next request re-reads role state like a fresh prod session.
    db.expire_all()
    # Same token (still valid) must now reflect VIEWER permissions from DB.
    me = client.get("/api/v1/auth/me", headers=_h(env["tokens"]["STAFF"])).json()
    assert me["membership"]["role"] == "VIEWER"
    assert "leads.create" not in me["permissions"]


def test_revoked_membership_stops_working_immediately(env) -> None:
    from app.models.user import User
    from sqlalchemy import select

    db = env["db"]
    client = env["client"]
    staff_user = db.execute(select(User).where(User.email == "staff@example.com")).scalars().first()
    assert staff_user is not None
    from app.models.business import Business

    prime = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    assert prime is not None
    from app.repositories import memberships as membership_repo

    membership = membership_repo.get_membership(db, user_id=staff_user.id, business_id=prime.id)
    assert membership is not None
    membership.status = "revoked"
    db.commit()
    db.expire_all()
    resp = client.get("/api/v1/business", headers=_h(env["tokens"]["STAFF"]))
    assert resp.status_code == 403
