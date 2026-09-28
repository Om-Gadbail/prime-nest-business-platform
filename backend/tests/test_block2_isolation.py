"""Block 2 — adversarial tenant-isolation tests (Prime <-> Nest)."""

from __future__ import annotations

import uuid

from tests.block2_support import (  # noqa: F401
    auth_headers,
    b2,
    public_booking_payload,
    public_lead_payload,
)


def _seed_prime_records(client, h_prime):
    lead = client.post(
        "/api/v1/leads",
        json={"display_name": "Prime Secret", "phone": "+919876501001",
              "email": "prime-secret@example.com"},
        headers=h_prime,
    ).json()
    contact = client.post(
        "/api/v1/contacts",
        json={"first_name": "Prime", "last_name": "Secret",
              "phone": "+919876501002", "email": "prime-contact@example.com"},
        headers=h_prime,
    ).json()
    customer = client.post(
        "/api/v1/customers", json={"contact_id": contact["id"]}, headers=h_prime
    ).json()
    booking = client.post(
        "/api/v1/bookings", json={"title": "Prime Session"}, headers=h_prime
    ).json()
    return {"lead": lead, "contact": contact, "customer": customer, "booking": booking}


def test_cross_business_object_access_denied(b2) -> None:
    h_prime = auth_headers(b2["prime"]["access_token"])
    h_nest = auth_headers(b2["nest"]["access_token"])
    recs = _seed_prime_records(b2["client"], h_prime)
    client = b2["client"]
    # Every direct-ID access from Nest behaves as nonexistent.
    assert client.get(f"/api/v1/leads/{recs['lead']['id']}", headers=h_nest).status_code == 404
    assert client.get(f"/api/v1/contacts/{recs['contact']['id']}", headers=h_nest).status_code == 404
    assert client.get(f"/api/v1/customers/{recs['customer']['id']}", headers=h_nest).status_code == 404
    assert client.get(f"/api/v1/bookings/{recs['booking']['id']}", headers=h_nest).status_code == 404
    # Mutations too.
    assert client.patch(
        f"/api/v1/leads/{recs['lead']['id']}", json={"message": "hijack"}, headers=h_nest
    ).status_code == 404
    assert client.post(
        f"/api/v1/leads/{recs['lead']['id']}/notes", json={"note": "x"}, headers=h_nest
    ).status_code == 404
    assert client.post(
        f"/api/v1/leads/{recs['lead']['id']}/convert", json={}, headers=h_nest
    ).status_code == 404
    assert client.post(
        f"/api/v1/bookings/{recs['booking']['id']}/confirm", headers=h_nest
    ).status_code == 404
    # Mirror direction: Nest records invisible to Prime.
    nest_lead = client.post(
        "/api/v1/leads", json={"display_name": "Nest Secret"}, headers=h_nest
    ).json()
    assert client.get(f"/api/v1/leads/{nest_lead['id']}", headers=h_prime).status_code == 404


def test_no_count_or_search_leakage(b2) -> None:
    h_prime = auth_headers(b2["prime"]["access_token"])
    h_nest = auth_headers(b2["nest"]["access_token"])
    _seed_prime_records(b2["client"], h_prime)
    client = b2["client"]
    # Nest list/search totals reveal nothing about Prime rows.
    assert client.get("/api/v1/leads", headers=h_nest).json()["total"] == 0
    assert client.get("/api/v1/leads?search=Prime Secret", headers=h_nest).json()["total"] == 0
    assert client.get("/api/v1/contacts?search=Prime Secret", headers=h_nest).json()["total"] == 0
    assert client.get("/api/v1/contacts?search=prime-secret@example.com", headers=h_nest).json()["total"] == 0
    assert client.get("/api/v1/bookings", headers=h_nest).json()["total"] == 0
    assert client.get("/api/v1/customers", headers=h_nest).json()["total"] == 0
    # Activities of a foreign lead are unreachable.
    prime_lead_id = client.get("/api/v1/leads", headers=h_prime).json()["items"][0]["id"]
    assert client.get(
        f"/api/v1/leads/{prime_lead_id}/activities", headers=h_nest
    ).status_code == 404


def test_query_body_and_forged_context_attacks(b2) -> None:
    h_prime = auth_headers(b2["prime"]["access_token"])
    recs = _seed_prime_records(b2["client"], h_prime)
    client = b2["client"]
    nest_id = b2["nest"]["business"]["id"]
    # Query-string business_id is not a thing (ignored, never trusted).
    resp = client.get(
        f"/api/v1/leads/{recs['lead']['id']}?business_id={nest_id}", headers=h_prime
    )
    assert resp.status_code == 200  # own record still resolves via token context
    # Forged business claim in body is rejected (unknown field), never honored.
    resp = client.post(
        "/api/v1/leads",
        json={"display_name": "Forge", "business_id": nest_id}, headers=h_prime,
    )
    assert resp.status_code == 422
    # Forged JWT business_id for a business the user lacks -> 403, no data.
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    from app.core.config import get_settings

    settings = get_settings()
    payload = {
        "sub": str(b2["prime_owner"].id),
        "jti": uuid.uuid4().hex,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()),
        "type": "access",
        "business_id": nest_id,  # prime owner has no Nest membership
    }
    forged = pyjwt.encode(payload, settings.effective_jwt_secret, algorithm="HS256")
    resp = client.get("/api/v1/leads", headers=auth_headers(forged))
    assert resp.status_code == 403, resp.text


def test_relationship_traversal_blocked(b2) -> None:
    """Contact/customer links cannot be followed across the tenant boundary."""
    h_prime = auth_headers(b2["prime"]["access_token"])
    h_nest = auth_headers(b2["nest"]["access_token"])
    recs = _seed_prime_records(b2["client"], h_prime)
    client = b2["client"]
    # Nest creates a lead pointing at Prime's contact id -> 404 (no link).
    resp = client.post(
        "/api/v1/leads",
        json={"display_name": "Traversal", "contact_id": recs["contact"]["id"]},
        headers=h_nest,
    )
    assert resp.status_code == 404, resp.text
    # Nest booking pointing at Prime's lead -> 404.
    resp = client.post(
        "/api/v1/bookings",
        json={"title": "Traversal", "lead_id": recs["lead"]["id"]}, headers=h_nest,
    )
    assert resp.status_code == 404, resp.text


def test_duplicate_detection_does_not_leak(b2) -> None:
    """Same phone in both businesses: intake succeeds in each, links stay local."""
    phone = "+919876502001"
    for slug in ("prime", "nest"):
        resp = b2["client"].post(
            f"/api/v1/public/{slug}/leads",
            json=public_lead_payload(phone=phone, email=f"dup-{slug}@example.com"),
        )
        assert resp.status_code == 201, resp.text
    h_prime = auth_headers(b2["prime"]["access_token"])
    h_nest = auth_headers(b2["nest"]["access_token"])
    prime_lead = b2["client"].get("/api/v1/leads", headers=h_prime).json()["items"][0]
    nest_lead = b2["client"].get("/api/v1/leads", headers=h_nest).json()["items"][0]
    assert prime_lead["contact_id"] != nest_lead["contact_id"]
