"""Block 1 — authentication tests (login / tokens / refresh / logout / me)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

from tests.block1_support import (
    TEST_PASSWORD,
    add_test_membership,
    create_test_user,
    make_auth_client,
    make_test_session,
)


@pytest.fixture
def setup():
    engine, db = make_test_session()
    try:
        user = create_test_user(db, email="auth@example.com")
        add_test_membership(
            db, user_id=user.id, business_slug="prime", role_name="OWNER", is_default=True
        )
        client = make_auth_client(db)
        yield {"db": db, "client": client, "user": user}
    finally:
        db.close()
        engine.dispose()


def test_valid_login_returns_tokens_and_context(setup) -> None:
    client = setup["client"]
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["business"]["slug"] == "prime"
    assert "business.read" in body["permissions"]
    assert resp.cookies.get("refresh_token")


def test_invalid_password_generic_failure(setup) -> None:
    client = setup["client"]
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": "wrong-password-123"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Invalid email or password."


def test_unknown_email_generic_failure(setup) -> None:
    client = setup["client"]
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password-123"},
    )
    good_bad = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": "wrong-password-123"},
    )
    # Must not leak account existence: identical status + message.
    assert bad.status_code == good_bad.status_code == 401
    assert bad.json() == good_bad.json()


def test_me_returns_context(setup) -> None:
    client = setup["client"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    ).json()
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == "auth@example.com"
    assert me.json()["business"]["slug"] == "prime"


def test_me_rejects_missing_token(setup) -> None:
    assert setup["client"].get("/api/v1/auth/me").status_code == 401


def test_malformed_token_rejected(setup) -> None:
    client = setup["client"]
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401


def test_invalid_signature_rejected(setup) -> None:
    from app.core.config import get_settings

    client = setup["client"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    ).json()
    # Re-sign with a different secret.
    payload = pyjwt.decode(login["access_token"], options={"verify_signature": False})
    forged = pyjwt.encode(payload, "wrong-secret-xyz-12345678901234567890", algorithm="HS256")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
    assert get_settings() is not None


def test_expired_access_token_rejected(setup) -> None:
    import uuid
    from datetime import datetime, timezone

    client = setup["client"]
    user = setup["user"]
    from app.core.config import get_settings

    settings = get_settings()
    # Craft an already-expired token with valid signature.
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "jti": uuid.uuid4().hex,
        "iat": int((now - timedelta(hours=2)).timestamp()),
        "exp": int((now - timedelta(hours=1)).timestamp()),
        "type": "access",
        "business_id": None,
    }
    expired = pyjwt.encode(payload, settings.effective_jwt_secret, algorithm=settings.jwt_algorithm)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_refresh_token_works_and_rotates(setup) -> None:
    client = setup["client"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    ).json()
    old_refresh = login["refresh_token"]
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r1.status_code == 200, r1.text
    new_refresh = r1.json()["refresh_token"]
    assert new_refresh != old_refresh
    # Old (rotated) refresh token must now fail.
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401


def test_reused_revoked_refresh_token_rejected_and_family_revoked(setup) -> None:
    client = setup["client"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    ).json()
    r1 = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    ).json()
    # Use the rotated-out original again -> reuse detection revokes family.
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )
    # Even the latest refresh token is now revoked after reuse detection.
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": r1["refresh_token"]}
        ).status_code
        == 401
    )


def test_logout_revokes_session(setup) -> None:
    client = setup["client"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    ).json()
    out = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": login["refresh_token"]},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert out.status_code == 200
    # Refresh after logout must fail.
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )


def test_expired_session_rejected(setup) -> None:
    from app.core import security

    db = setup["db"]
    client = setup["client"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    ).json()
    # Force-expire the session row in the DB.
    token_hash = security.hash_refresh_token(login["refresh_token"])
    from app.repositories import sessions as session_repo

    sess = session_repo.get_by_hash(db, token_hash)
    assert sess is not None
    sess.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )


def test_refresh_token_only_hash_stored(setup) -> None:
    from app.core import security

    db = setup["db"]
    client = setup["client"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auth@example.com", "password": TEST_PASSWORD},
    ).json()
    from app.models.auth_session import AuthSession
    from sqlalchemy import select

    hashes = db.execute(select(AuthSession.refresh_token_hash)).scalars().all()
    assert login["refresh_token"] not in hashes
    assert security.hash_refresh_token(login["refresh_token"]) in hashes
