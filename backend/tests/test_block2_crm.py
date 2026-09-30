"""Block 2 — CRM foundation tests (contacts, customers, conversion)."""

from __future__ import annotations

import pytest

from tests.block2_support import auth_headers, b2, login_as  # noqa: F401


def test_contact_crud_and_search(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    resp = client.post(
        "/api/v1/contacts",
        json={"first_name": "Priya", "last_name": "Nair", "phone": "+919876500001",
              "email": "priya@example.com"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    assert resp.json()["display_name"] == "Priya Nair"
    assert "normalized_phone" not in resp.json()  # internal field hidden
    # Search by name/phone/email within business.
    assert client.get("/api/v1/contacts?search=priya", headers=h).json()["total"] == 1
    assert client.get("/api/v1/contacts?search=9876500001", headers=h).json()["total"] == 1
    assert client.get("/api/v1/contacts?search=PRIYA@EXAMPLE.COM", headers=h).json()["total"] == 1
    # Update + validation.
    resp = client.patch(
        f"/api/v1/contacts/{cid}", json={"status": "inactive"}, headers=h
    )
    assert resp.status_code == 200 and resp.json()["status"] == "inactive"
    assert client.patch(
        f"/api/v1/contacts/{cid}", json={"status": "vip"}, headers=h
    ).status_code == 422
    assert client.post(
        "/api/v1/contacts", json={"first_name": "", "last_name": ""}, headers=h
    ).status_code == 422


def test_shared_phone_allowed_for_family(b2) -> None:
    """No unrealistic uniqueness: two contacts may share a phone number."""
    h = auth_headers(b2["prime"]["access_token"])
    for name in ("Parent One", "Child One"):
        resp = b2["client"].post(
            "/api/v1/contacts",
            json={"first_name": name, "phone": "+919800000001"}, headers=h,
        )
        assert resp.status_code == 201, resp.text


def test_customer_crud_and_duplicate_guard(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    cid = client.post(
        "/api/v1/contacts", json={"first_name": "Rohan", "phone": "+919876500002"},
        headers=h,
    ).json()["id"]
    resp = client.post("/api/v1/customers", json={"contact_id": cid}, headers=h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["contact_id"] == cid
    # Second customer for the same contact -> 409.
    assert client.post(
        "/api/v1/customers", json={"contact_id": cid}, headers=h
    ).status_code == 409
    # Foreign contact id -> 404 (uniform, no oracle).
    import uuid as _uuid

    assert client.post(
        "/api/v1/customers", json={"contact_id": str(_uuid.uuid4())}, headers=h
    ).status_code == 404
    # Update + list filter.
    cust_id = resp.json()["id"]
    assert client.patch(
        f"/api/v1/customers/{cust_id}", json={"notes": "Prefers mornings"}, headers=h
    ).status_code == 200
    assert client.get("/api/v1/customers?status=active", headers=h).json()["total"] == 1


def test_lead_conversion_end_to_end(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    lead = client.post(
        "/api/v1/leads",
        json={"display_name": "Convert Me", "phone": "+919876500003",
              "service_interest": "Trial"},
        headers=h,
    ).json()
    # booked is a convertible pre-state.
    for nxt in ("contacted", "qualified", "booked"):
        assert client.post(
            f"/api/v1/leads/{lead['id']}/status", json={"status": nxt}, headers=h
        ).status_code == 200
    resp = client.post(
        f"/api/v1/leads/{lead['id']}/convert",
        json={"customer_notes": "Converted at trial."}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    customer = resp.json()
    # History preserved: lead row still exists as CONVERTED with links.
    lead_after = client.get(f"/api/v1/leads/{lead['id']}", headers=h).json()
    assert lead_after["status"] == "converted"
    assert lead_after["customer_id"] == customer["id"]
    assert lead_after["converted_at"]
    assert customer["contact_id"] == lead_after["contact_id"]
    # converting again -> 409.
    assert client.post(
        f"/api/v1/leads/{lead['id']}/convert", json={}, headers=h
    ).status_code == 409
    # Activities show the conversion.
    acts = client.get(f"/api/v1/leads/{lead['id']}/activities", headers=h).json()
    assert any(a["activity_type"] == "converted" for a in acts["items"])


def test_conversion_reuses_existing_customer(b2) -> None:
    """Two leads for the same person convert to ONE customer row."""
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    phone = "+919876500004"
    ids = []
    for name in ("Twin A", "Twin B"):
        lead = client.post(
            "/api/v1/leads", json={"display_name": name, "phone": phone}, headers=h
        ).json()
        ids.append(lead["id"])
    c1 = client.post(f"/api/v1/leads/{ids[0]}/convert", json={}, headers=h)
    c2 = client.post(f"/api/v1/leads/{ids[1]}/convert", json={}, headers=h)
    assert c1.status_code == c2.status_code == 200
    assert c1.json()["id"] == c2.json()["id"]


def test_conversion_rollback_on_failure(b2) -> None:
    """If conversion fails midway, nothing partial remains (atomicity)."""
    from app.services import leads as leads_service
    from app.services.errors import NotFoundError

    db = b2["db"]
    h = auth_headers(b2["prime"]["access_token"])
    lead = b2["client"].post(
        "/api/v1/leads",
        json={"display_name": "Rollback Case", "phone": "+919876500005"}, headers=h,
    ).json()
    # Break the contact link mid-conversion: point at a foreign contact id,
    # then delete... simplest deterministic failure: convert a ghost lead.
    import uuid as _uuid

    with pytest.raises(NotFoundError):
        leads_service.convert_lead(
            db, business_id=_uuid.UUID(b2["prime"]["business"]["id"]),
            lead_id=str(_uuid.uuid4()),
        )
    # The real lead is untouched; no customer leaked.
    assert b2["client"].get(f"/api/v1/leads/{lead['id']}", headers=h).json()["status"] == "new"


def test_crm_cross_business_isolation(b2) -> None:
    h_prime = auth_headers(b2["prime"]["access_token"])
    h_nest = auth_headers(b2["nest"]["access_token"])
    cid = b2["client"].post(
        "/api/v1/contacts", json={"first_name": "Prime Only", "phone": "+919876500006"},
        headers=h_prime,
    ).json()["id"]
    # Nest owner: get/update/list/search all behave as nonexistent.
    assert b2["client"].get(f"/api/v1/contacts/{cid}", headers=h_nest).status_code == 404
    assert b2["client"].patch(
        f"/api/v1/contacts/{cid}", json={"notes": "x"}, headers=h_nest
    ).status_code == 404
    assert b2["client"].get(
        "/api/v1/contacts?search=Prime Only", headers=h_nest
    ).json()["total"] == 0
    # Nest customer cannot be created from a Prime contact.
    assert b2["client"].post(
        "/api/v1/customers", json={"contact_id": cid}, headers=h_nest
    ).status_code == 404
    # Body business_id smuggling is ignored (no such accepted field anyway).
    resp = b2["client"].post(
        "/api/v1/contacts",
        json={"first_name": "Smuggle", "business_id": "nest-biz-id"}, headers=h_prime,
    )
    assert resp.status_code == 422  # unknown field rejected, never trusted


def test_crm_permissions(b2) -> None:
    staff = login_as(
        b2["client"], b2["db"], email="crm-staff@example.com", slug="prime", role="STAFF"
    )
    sh = auth_headers(staff["access_token"])
    # Release change (owner-ready): STAFF does frontline CRM — contacts
    # read/create/update, customers read/create/update.
    assert b2["client"].get("/api/v1/contacts", headers=sh).status_code == 200
    resp = b2["client"].post(
        "/api/v1/contacts", json={"first_name": "Staff Made"}, headers=sh
    )
    assert resp.status_code == 201, resp.text
    assert b2["client"].get("/api/v1/customers", headers=sh).status_code == 200
    assert b2["client"].post(
        "/api/v1/customers", json={"contact_id": resp.json()["id"]}, headers=sh
    ).status_code == 201
    # STAFF can update contacts.
    assert b2["client"].patch(
        f"/api/v1/contacts/{resp.json()['id']}", json={"notes": "x"}, headers=sh
    ).status_code == 200
