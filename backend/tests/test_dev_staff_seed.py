"""Development staff seed identities (Prime-only / Nest-only STAFF).

Covers the local-dashboard login contract: restricted single-business
STAFF users seeded idempotently outside production, cross-business
denial (403), forged tenant fields on public intake ignored, and Nest
intake idempotency. The unified platform owner authorization is
asserted unchanged.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.block1_support import make_test_session
from tests.block2_support import (
    auth_headers,
    new_idem_key,
    public_lead_payload,
)

PRIME_STAFF_EMAIL = "staff@primefitness.in"
NEST_STAFF_EMAIL = "staff@nestlibrary.in"
STAFF_DEMO_PASSWORD = "StaffDemo123!"


@pytest.fixture
def staff_seed():
    """Fresh DB + client. make_test_session runs the full seed, which now
    includes the restricted development staff identities."""
    engine, db = make_test_session()
    try:
        from app.api.deps import get_db
        from app.main import create_app

        app = create_app()

        def _override() -> Generator[Session, None, None]:
            yield db

        app.dependency_overrides[get_db] = _override
        yield {"client": TestClient(app, raise_server_exceptions=False), "db": db}
    finally:
        db.close()
        engine.dispose()


def _login(client, email: str, password: str = STAFF_DEMO_PASSWORD, **kw) -> dict:
    payload: dict = {"email": email, "password": password}
    payload.update(kw)
    resp = client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _me(client, token: str) -> dict:
    resp = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_dev_staff_seeded_with_restricted_memberships(staff_seed) -> None:
    client = staff_seed["client"]
    prime = _login(client, PRIME_STAFF_EMAIL)
    me = _me(client, prime["access_token"])
    assert me["membership"]["role"] == "STAFF"
    assert me["business"]["slug"] == "prime"

    nest = _login(client, NEST_STAFF_EMAIL)
    me = _me(client, nest["access_token"])
    assert me["membership"]["role"] == "STAFF"
    assert me["business"]["slug"] == "nest"

    # Exactly one business each — never both, never OWNER.
    for tokens in (prime, nest):
        businesses = client.get(
            "/api/v1/auth/businesses",
            headers=auth_headers(tokens["access_token"]),
        )
        assert businesses.status_code == 200, businesses.text
        assert len(businesses.json()) == 1


def test_prime_staff_cannot_reach_nest(staff_seed) -> None:
    client = staff_seed["client"]
    prime = _login(client, PRIME_STAFF_EMAIL)
    headers = auth_headers(prime["access_token"])

    # Business-scoped reads work in the home tenant.
    leads = client.get("/api/v1/leads", headers=headers)
    assert leads.status_code == 200, leads.text

    # Switching into Nest is denied (403, no existence oracle).
    denied = client.post(
        "/api/v1/auth/switch-business", json={"business_id": "nest"}, headers=headers
    )
    assert denied.status_code == 403, denied.text

    # Login directly scoped to Nest is denied as well.
    bad = client.post(
        "/api/v1/auth/login",
        json={
            "email": PRIME_STAFF_EMAIL,
            "password": STAFF_DEMO_PASSWORD,
            "business_slug": "nest",
        },
    )
    assert bad.status_code == 403, bad.text


def test_nest_staff_cannot_reach_prime(staff_seed) -> None:
    client = staff_seed["client"]
    nest = _login(client, NEST_STAFF_EMAIL)
    headers = auth_headers(nest["access_token"])

    leads = client.get("/api/v1/leads", headers=headers)
    assert leads.status_code == 200, leads.text

    denied = client.post(
        "/api/v1/auth/switch-business", json={"business_id": "prime"}, headers=headers
    )
    assert denied.status_code == 403, denied.text

    bad = client.post(
        "/api/v1/auth/login",
        json={
            "email": NEST_STAFF_EMAIL,
            "password": STAFF_DEMO_PASSWORD,
            "business_slug": "prime",
        },
    )
    assert bad.status_code == 403, bad.text


def test_forged_business_id_on_public_intake_is_ignored(staff_seed) -> None:
    client = staff_seed["client"]
    name = "Forged Tenant Probe"
    resp = client.post(
        "/api/v1/public/nest/leads",
        json={
            **public_lead_payload(name=name),
            "business_id": "prime-fitness-001",
            "businessId": "prime-fitness-001",
            "slug": "prime",
        },
        headers={"Idempotency-Key": new_idem_key()},
    )
    assert resp.status_code == 201, resp.text

    nest = _login(client, NEST_STAFF_EMAIL)
    seen = client.get(
        "/api/v1/leads?page_size=100", headers=auth_headers(nest["access_token"])
    ).json()
    assert any(item["display_name"] == name for item in seen["items"])

    prime = _login(client, PRIME_STAFF_EMAIL)
    foreign = client.get(
        "/api/v1/leads?page_size=100", headers=auth_headers(prime["access_token"])
    ).json()
    assert all(item["display_name"] != name for item in foreign["items"])


def test_nest_intake_idempotency_replays_same_lead(staff_seed) -> None:
    client = staff_seed["client"]
    key = new_idem_key()
    first = client.post(
        "/api/v1/public/nest/leads",
        json=public_lead_payload(name="Idempotency Probe"),
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201, first.text
    second = client.post(
        "/api/v1/public/nest/leads",
        json=public_lead_payload(name="Idempotency Probe"),
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 201, second.text
    assert second.json()["lead_id"] == first.json()["lead_id"]

    nest = _login(client, NEST_STAFF_EMAIL)
    seen = client.get(
        "/api/v1/leads?page_size=100", headers=auth_headers(nest["access_token"])
    ).json()
    matches = [
        item for item in seen["items"] if item["display_name"] == "Idempotency Probe"
    ]
    assert len(matches) == 1


def test_owner_authorization_unchanged(staff_seed) -> None:
    client = staff_seed["client"]
    owner = _login(client, "owner@prime-nest-dashboard.com", "OwnerDemo123!")
    businesses = client.get(
        "/api/v1/auth/businesses", headers=auth_headers(owner["access_token"])
    )
    assert businesses.status_code == 200, businesses.text
    roles = {b["business"]["slug"]: b["role"] for b in businesses.json()}
    assert roles == {"prime": "OWNER", "nest": "OWNER"}

    for slug in ("prime", "nest"):
        switched = client.post(
            "/api/v1/auth/switch-business",
            json={"business_id": slug},
            headers=auth_headers(owner["access_token"]),
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["business"]["slug"] == slug
