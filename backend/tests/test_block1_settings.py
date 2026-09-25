"""Block 1 — settings authorization matrix + validation tests."""

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
        for role in ("OWNER", "ADMIN", "MANAGER", "STAFF", "VIEWER"):
            email = f"s-{role.lower()}@example.com"
            user = create_test_user(db, email=email)
            add_test_membership(db, user_id=user.id, business_slug="prime",
                                role_name=role, is_default=True)
        client = make_auth_client(db)
        for role in ("OWNER", "ADMIN", "MANAGER", "STAFF", "VIEWER"):
            email = f"s-{role.lower()}@example.com"
            tokens[role] = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": TEST_PASSWORD},
            ).json()["access_token"]
        yield {"db": db, "client": client, "tokens": tokens}
    finally:
        db.close()
        engine.dispose()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_settings_rejected(env) -> None:
    assert env["client"].get("/api/v1/business/settings").status_code == 401
    assert (
        env["client"]
        .patch("/api/v1/business/settings", json={"branding": {}})
        .status_code
        == 401
    )


def test_viewer_cannot_update_settings(env) -> None:
    r = env["client"].patch(
        "/api/v1/business/settings",
        json={"branding": {"tagline": "nope"}},
        headers=_h(env["tokens"]["VIEWER"]),
    )
    assert r.status_code == 403


def test_staff_cannot_update_restricted_settings(env) -> None:
    r = env["client"].patch(
        "/api/v1/business/settings",
        json={"operational": {"booking_enabled": True}},
        headers=_h(env["tokens"]["STAFF"]),
    )
    assert r.status_code == 403


def test_manager_cannot_update_settings(env) -> None:
    r = env["client"].patch(
        "/api/v1/business/settings",
        json={"branding": {"tagline": "nope"}},
        headers=_h(env["tokens"]["MANAGER"]),
    )
    assert r.status_code == 403


def test_admin_can_update_settings(env) -> None:
    r = env["client"].patch(
        "/api/v1/business/settings",
        json={"branding": {"tagline": "admin-ok"}},
        headers=_h(env["tokens"]["ADMIN"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["branding"]["tagline"] == "admin-ok"


def test_owner_can_update_settings(env) -> None:
    r = env["client"].patch(
        "/api/v1/business/settings",
        json={"operational": {"booking_enabled": True, "lead_capture_enabled": False}},
        headers=_h(env["tokens"]["OWNER"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["operational"]["booking_enabled"] is True


def test_settings_validation_cases(env) -> None:
    client = env["client"]
    h = _h(env["tokens"]["OWNER"])
    bad_cases = [
        {"branding": {"primary_color": "red"}},
        {"contact": {"email": "not-an-email"}},
        {"contact": {"website_url": "ftp://x"}},
        {"localization": {"timezone": "Mars/Olympus"}},
        {"localization": {"currency": "US"}},
        {"hours": {"weekly": {"monday": {"open": "25:00"}}}},
        {"operational": {"booking_enabled": "yes"}},
        {"unknown_section": {}},
    ]
    for payload in bad_cases:
        r = client.patch("/api/v1/business/settings", json=payload, headers=h)
        assert r.status_code == 422, payload


def test_settings_good_cases(env) -> None:
    client = env["client"]
    h = _h(env["tokens"]["OWNER"])
    r = client.patch(
        "/api/v1/business/settings",
        json={
            "branding": {"display_name": "Prime", "primary_color": "#0ea5e9"},
            "contact": {"email": "info@example.com", "phone": "+1 555 123 4567"},
            "localization": {"timezone": "UTC", "currency": "usd", "locale": "en-US"},
            "hours": {"weekly": {"monday": {"open": "09:00", "close": "18:00"}}},
            "operational": {"booking_enabled": True},
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["localization"]["currency"] == "USD"
