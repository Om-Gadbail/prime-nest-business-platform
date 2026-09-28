"""Block 1 — tenant isolation tests (adversarial).

Proves repository + service + API layers never leak across businesses, and
that client-provided business identifiers are never trusted.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

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
        prime_owner = create_test_user(db, email="p-owner@example.com")
        add_test_membership(db, user_id=prime_owner.id, business_slug="prime",
                            role_name="OWNER", is_default=True)
        nest_owner = create_test_user(db, email="n-owner@example.com")
        add_test_membership(db, user_id=nest_owner.id, business_slug="nest",
                            role_name="OWNER", is_default=True)
        client = make_auth_client(db)
        p_token = client.post(
            "/api/v1/auth/login",
            json={"email": "p-owner@example.com", "password": TEST_PASSWORD},
        ).json()
        n_token = client.post(
            "/api/v1/auth/login",
            json={"email": "n-owner@example.com", "password": TEST_PASSWORD},
        ).json()
        yield {"db": db, "client": client, "p": p_token, "n": n_token}
    finally:
        db.close()
        engine.dispose()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_prime_settings_isolated_from_nest(env) -> None:
    client = env["client"]
    # Prime owner writes prime settings.
    r = client.patch(
        "/api/v1/business/settings",
        json={"branding": {"display_name": "PRIME-ONLY"}},
        headers=_h(env["p"]["access_token"]),
    )
    assert r.status_code == 200
    # Nest owner reads nest settings — must NOT see prime value.
    n = client.get("/api/v1/business/settings", headers=_h(env["n"]["access_token"]))
    assert n.status_code == 200
    assert n.json()["branding"].get("display_name") != "PRIME-ONLY"
    # Prime reads its own value back.
    p = client.get("/api/v1/business/settings", headers=_h(env["p"]["access_token"]))
    assert p.json()["branding"]["display_name"] == "PRIME-ONLY"


def test_nest_settings_isolated_from_prime(env) -> None:
    client = env["client"]
    client.patch(
        "/api/v1/business/settings",
        json={"branding": {"display_name": "NEST-ONLY"}},
        headers=_h(env["n"]["access_token"]),
    )
    p = client.get("/api/v1/business/settings", headers=_h(env["p"]["access_token"]))
    assert p.json()["branding"].get("display_name") != "NEST-ONLY"


def test_business_endpoint_returns_own_tenant_only(env) -> None:
    client = env["client"]
    p = client.get("/api/v1/business", headers=_h(env["p"]["access_token"])).json()
    n = client.get("/api/v1/business", headers=_h(env["n"]["access_token"])).json()
    assert p["slug"] == "prime" and n["slug"] == "nest"
    assert p["id"] != n["id"]


def test_url_business_id_cannot_bypass_context(env) -> None:
    """There is no /business/{id} route; unknown paths must 404, not leak."""
    client = env["client"]
    nest_id = str(env["n"]["business"]["id"])
    # Attempt to guess a tenant-scoped URL — must not resolve to nest data.
    resp = client.get(
        f"/api/v1/business/{nest_id}", headers=_h(env["p"]["access_token"])
    )
    assert resp.status_code == 404


def test_query_param_business_id_cannot_bypass(env) -> None:
    client = env["client"]
    nest_id = env["n"]["business"]["id"]
    # Settings endpoint ignores query params; context still decides tenant.
    resp = client.get(
        f"/api/v1/business/settings?business_id={nest_id}",
        headers=_h(env["p"]["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["business_id"] == env["p"]["business"]["id"]


def test_body_business_id_cannot_bypass(env) -> None:
    client = env["client"]
    nest_id = env["n"]["business"]["id"]
    # Smuggled business_id in PATCH body is ignored (not an updatable field).
    resp = client.patch(
        "/api/v1/business/settings",
        json={"branding": {"display_name": "Prime2"}, "business_id": nest_id},  # type: ignore
        headers=_h(env["p"]["access_token"]),
    )
    assert resp.status_code in (200, 422)
    # Nest settings must be untouched.
    n = client.get("/api/v1/business/settings", headers=_h(env["n"]["access_token"])).json()
    assert n["branding"].get("display_name") != "Prime2"


def test_relationship_traversal_cannot_bypass(env) -> None:
    """Membership queries are always (user_id, business_id) scoped."""
    from app.repositories import memberships as membership_repo

    db = env["db"]
    from app.models.user import User

    prime_user = db.execute(
        select(User).where(User.email == "p-owner@example.com")
    ).scalars().first()
    assert prime_user is not None
    from app.models.business import Business

    nest = db.execute(select(Business).where(Business.slug == "nest")).scalars().first()
    assert nest is not None
    assert (
        membership_repo.get_membership(db, user_id=prime_user.id, business_id=nest.id)
        is None
    )


def test_repository_scope_helpers(env) -> None:
    from app.models.business_settings import BusinessSettings
    from app.models.business import Business
    from app.repositories import base as base_repo

    db = env["db"]
    prime = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    nest = db.execute(select(Business).where(Business.slug == "nest")).scalars().first()
    assert prime is not None and nest is not None
    # Wrong-business single fetch returns None.
    assert base_repo.get_scoped(db, BusinessSettings, nest.id, prime.id) is None
    assert base_repo.get_scoped(db, BusinessSettings, prime.id, prime.id) is not None
    # Unscoped model raises fail-closed.
    with pytest.raises(TypeError):
        base_repo.apply_business_scope(select(Business), Business, prime.id)


def test_forged_jwt_business_id_without_membership_rejected(env) -> None:
    import jwt as pyjwt

    from app.core.config import get_settings

    settings = get_settings()
    # Forge a token claiming nest business for the prime user (valid signature
    # requires the real secret — simulate by decoding prime token payload and
    # re-encoding with the real secret but swapped business_id).
    payload = pyjwt.decode(
        env["p"]["access_token"], options={"verify_signature": False}
    )
    payload["business_id"] = env["n"]["business"]["id"]
    forged = pyjwt.encode(payload, settings.effective_jwt_secret, algorithm="HS256")
    resp = env["client"].get("/api/v1/business", headers=_h(forged))
    # Prime user has no nest membership -> must be forbidden even with signature.
    assert resp.status_code == 403
