"""Block 1 — user model tests."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from tests.block1_support import TEST_PASSWORD, make_test_session


@pytest.fixture
def tdb():
    engine, db = make_test_session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_user_creation_and_email_normalized(tdb) -> None:
    from tests.block1_support import create_test_user

    user = create_test_user(tdb, email="  Mixed@Example.COM  ")
    assert user.email == "mixed@example.com"
    assert user.is_active is True


def test_email_uniqueness_case_insensitive(tdb) -> None:
    from tests.block1_support import create_test_user

    create_test_user(tdb, email="dup@example.com")
    with pytest.raises(IntegrityError):
        create_test_user(tdb, email="DUP@example.com")
    tdb.rollback()


def test_password_is_hashed_not_plaintext(tdb) -> None:
    from app.core import security
    from tests.block1_support import create_test_user

    user = create_test_user(tdb, email="hash@example.com", password="supersecure-999")
    assert user.password_hash != "supersecure-999"
    assert "supersecure-999" not in user.password_hash
    assert security.verify_password("supersecure-999", user.password_hash) is True
    assert security.verify_password("wrong-password-x", user.password_hash) is False


def test_password_policy_enforced() -> None:
    from app.core import security

    with pytest.raises(ValueError):
        security.validate_password_policy("short")
    with pytest.raises(ValueError):
        security.validate_password_policy("x" * 129)
    security.validate_password_policy("long-enough-123")


def test_password_hash_uses_argon2id(tdb) -> None:
    from tests.block1_support import create_test_user

    user = create_test_user(tdb, email="argon@example.com")
    assert user.password_hash.startswith("$argon2")


def test_inactive_user_rejected_at_login(tdb) -> None:
    from app.core.config import get_settings
    from app.services import auth as auth_service
    from tests.block1_support import create_test_user

    get_settings.cache_clear()
    from app.core.config import get_settings as gs

    settings = gs()
    create_test_user(tdb, email="inactive@example.com", is_active=False)
    with pytest.raises(auth_service.AuthError):
        auth_service.login(
            tdb, settings, email="inactive@example.com", password=TEST_PASSWORD
        )


def test_user_response_never_contains_password_hash(tdb) -> None:
    from tests.block1_support import create_test_user, make_auth_client

    user = create_test_user(tdb, email="safe@example.com")
    from tests.block1_support import add_test_membership

    add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="OWNER",
                        is_default=True)
    client = make_auth_client(tdb)
    body = client.post(
        "/api/v1/auth/login", json={"email": "safe@example.com", "password": TEST_PASSWORD}
    ).json()
    dumped = str(body)
    assert "password_hash" not in dumped
    assert "$argon2" not in dumped
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    ).json()
    assert "password_hash" not in str(me)
