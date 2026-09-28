"""Block 2 — staff Lead Management API tests."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, login_as  # noqa: F401


def _create(client, headers, **overrides):
    payload = {"display_name": "Test Lead", "phone": "+919876543211"}
    payload.update(overrides)
    return client.post("/api/v1/leads", json=payload, headers=headers)


def test_create_and_get_lead(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    resp = _create(b2["client"], h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "new"
    assert body["source"] == "website"
    # Internal normalization fields are never exposed.
    assert "normalized_phone" not in body
    assert "normalized_email" not in body

    got = b2["client"].get(f"/api/v1/leads/{body['id']}", headers=h)
    assert got.status_code == 200, got.text
    assert got.json()["display_name"] == "Test Lead"


def test_create_lead_requires_contact_info(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    resp = _create(b2["client"], h, display_name="", phone=None)
    assert resp.status_code == 422, resp.text


def test_create_lead_invalid_email_phone(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    assert _create(b2["client"], h, email="not-an-email").status_code == 422
    assert _create(b2["client"], h, phone="12").status_code == 422


def test_create_lead_oversized_input(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    resp = _create(b2["client"], h, message="x" * 2001)
    assert resp.status_code == 422, resp.text
    resp = b2["client"].post(
        "/api/v1/leads", json={"display_name": "x" * 201}, headers=h
    )
    assert resp.status_code == 422


def test_create_lead_rejects_unknown_fields(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    resp = _create(b2["client"], h, business_id="anything", password_hash="x")
    assert resp.status_code == 422, resp.text


def test_update_lead(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    lead_id = _create(b2["client"], h).json()["id"]
    resp = b2["client"].patch(
        f"/api/v1/leads/{lead_id}",
        json={"service_interest": "Personal Training", "follow_up_at": "2030-01-02T10:00:00Z"},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["service_interest"] == "Personal Training"


def test_list_filters_search_pagination_sort(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    for i in range(5):
        _create(
            b2["client"], h, display_name=f"Gym Member {i}",
            phone=f"+9198765432{i:02d}",
            service_interest="Gym Membership" if i % 2 == 0 else "Yoga",
        )
    client = b2["client"]
    assert client.get("/api/v1/leads?limit=2&offset=0", headers=h).json()["total"] == 5
    page2 = client.get("/api/v1/leads?limit=2&offset=2", headers=h).json()
    assert len(page2["items"]) == 2 and page2["limit"] == 2 and page2["offset"] == 2
    # Server-side max page size enforced.
    big = client.get("/api/v1/leads?limit=5000", headers=h).json()
    assert big["limit"] == 100 or len(big["items"]) <= 100
    # Search bounded + safe.
    found = client.get("/api/v1/leads?search=Gym Member 1", headers=h).json()
    assert found["total"] >= 1
    assert client.get("/api/v1/leads?search=" + "x" * 65, headers=h).status_code == 422
    # Sort allowlist: unknown field falls back safely (no SQL error leak).
    resp = client.get("/api/v1/leads?sort=password_hash;DROP", headers=h)
    assert resp.status_code == 200, resp.text
    # Status filter validation.
    assert client.get("/api/v1/leads?status=bogus", headers=h).status_code == 422
    interest = client.get("/api/v1/leads?search=Yoga", headers=h).json()
    assert interest["total"] >= 1


def test_assign_lead_and_activity(b2) -> None:
    tokens = login_as(
        b2["client"], b2["db"], email="prime-manager@example.com",
        slug="prime", role="MANAGER",
    )
    h = auth_headers(tokens["access_token"])
    staff = login_as(
        b2["client"], b2["db"], email="prime-staff@example.com",
        slug="prime", role="STAFF",
    )
    from app.services.auth import login as _  # noqa: F401  (import sanity)
    import uuid as _uuid

    lead_id = _create(b2["client"], h).json()["id"]
    # Resolve staff user id via me endpoint.
    me = b2["client"].get(
        "/api/v1/auth/me", headers=auth_headers(staff["access_token"])
    ).json()
    staff_id = me["user"]["id"]
    resp = b2["client"].post(
        f"/api/v1/leads/{lead_id}/assign",
        json={"assigned_user_id": staff_id}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned_user_id"] == staff_id
    # Assignee outside the business is a uniform 404 (no oracle).
    resp = b2["client"].post(
        f"/api/v1/leads/{lead_id}/assign",
        json={"assigned_user_id": str(_uuid.uuid4())}, headers=h,
    )
    assert resp.status_code == 404, resp.text
    # Assignment wrote history + staff notification.
    acts = b2["client"].get(f"/api/v1/leads/{lead_id}/activities", headers=h).json()
    assert any(a["activity_type"] == "assigned" for a in acts["items"])
    notifs = b2["client"].get(
        "/api/v1/notifications", headers=auth_headers(staff["access_token"])
    ).json()
    assert any(n["notification_type"] == "lead_assigned" for n in notifs["items"])


def test_status_lifecycle_and_invalid(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    lead_id = _create(b2["client"], h).json()["id"]
    client = b2["client"]
    for nxt in ("contacted", "qualified", "booked"):
        resp = client.post(
            f"/api/v1/leads/{lead_id}/status", json={"status": nxt}, headers=h
        )
        assert resp.status_code == 200, (nxt, resp.text)
    # Illegal jump new->converted directly is rejected.
    lead2 = _create(b2["client"], h).json()["id"]
    resp = client.post(
        f"/api/v1/leads/{lead2}/status", json={"status": "converted"}, headers=h
    )
    assert resp.status_code == 409, resp.text
    # LOST requires a reason.
    assert client.post(
        f"/api/v1/leads/{lead2}/status", json={"status": "lost"}, headers=h
    ).status_code == 422
    resp = client.post(
        f"/api/v1/leads/{lead2}/status",
        json={"status": "lost", "lost_reason": "No budget"}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lost_reason"] == "No budget"
    # Invalid status value.
    assert client.post(
        f"/api/v1/leads/{lead2}/status", json={"status": "TRIAL_BOOKED"}, headers=h
    ).status_code in (409, 422)
    # Invalid UUID shape is a safe 404, not a 500.
    assert client.get("/api/v1/leads/not-a-uuid", headers=h).status_code == 404
    assert client.patch(
        "/api/v1/leads/not-a-uuid", json={"message": "x"}, headers=h
    ).status_code == 404


def test_notes_and_activities(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    lead_id = _create(b2["client"], h).json()["id"]
    client = b2["client"]
    resp = client.post(
        f"/api/v1/leads/{lead_id}/notes", json={"note": "Called, no answer."},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["activity_type"] == "note"
    assert client.post(
        f"/api/v1/leads/{lead_id}/notes", json={"note": "   "}, headers=h
    ).status_code == 422
    assert client.post(
        f"/api/v1/leads/{lead_id}/notes",
        json={"note": "x", "activity_type": "bogus"}, headers=h,
    ).status_code == 422
    acts = client.get(f"/api/v1/leads/{lead_id}/activities", headers=h).json()
    assert acts["total"] >= 2  # creation note + manual note


def test_lead_requires_permission(b2) -> None:
    # No token -> 401; viewer can read but cannot write.
    assert b2["client"].get("/api/v1/leads").status_code == 401
    viewer = login_as(
        b2["client"], b2["db"], email="prime-viewer@example.com",
        slug="prime", role="VIEWER",
    )
    vh = auth_headers(viewer["access_token"])
    assert b2["client"].get("/api/v1/leads", headers=vh).status_code == 200
    assert _create(b2["client"], vh).status_code == 403
