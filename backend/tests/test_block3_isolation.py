"""Block 3 — adversarial business-isolation verification (Prime <-> Nest).

Every protected resource must deny cross-business access with a uniform
404 (no existence oracle) or a safe 403 (permission gates). Frontend
hiding is never trusted; all enforcement is server-side.
"""

from __future__ import annotations

import uuid

from tests.block2_support import auth_headers, b2, login_as, public_lead_payload  # noqa: F401


def _prime_seed(b2) -> dict:
    prime = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    lead_id = client.post(
        "/api/v1/leads",
        json={"display_name": "Iso Lead", "phone": "+919777700001"},
        headers=prime,
    ).json()["id"]
    booking_id = client.post(
        "/api/v1/bookings", json={"title": "Iso booking"}, headers=prime
    ).json()["id"]
    contact_id = client.post(
        "/api/v1/contacts", json={"first_name": "Iso", "phone": "+919777700002"},
        headers=prime,
    ).json()["id"]
    customer_id = client.post(
        "/api/v1/customers", json={"contact_id": contact_id}, headers=prime
    ).json()["id"]
    task_id = client.post(
        "/api/v1/tasks", json={"title": "Iso task"}, headers=prime
    ).json()["id"]
    activity_id = client.post(
        f"/api/v1/leads/{lead_id}/notes", json={"note": "iso note"}, headers=prime
    ).json()["id"]
    event_id = client.get(
        "/api/v1/audit-events?limit=1", headers=prime
    ).json()["items"][0]["id"]
    notif_id = client.get("/api/v1/notifications", headers=prime).json()["items"][0]["id"]
    person_id = client.get("/api/v1/identity/links", headers=prime).json()["items"][0]["person_id"]
    return {
        "lead": lead_id, "booking": booking_id, "contact": contact_id,
        "customer": customer_id, "task": task_id, "activity": activity_id,
        "event": event_id, "notification": notif_id, "person": person_id,
    }


def test_cross_business_resource_ids_denied(b2) -> None:
    ids = _prime_seed(b2)
    nest = auth_headers(b2["nest"]["access_token"])
    client = b2["client"]

    assert client.get(f"/api/v1/leads/{ids['lead']}", headers=nest).status_code == 404
    assert client.get(f"/api/v1/bookings/{ids['booking']}", headers=nest).status_code == 404
    assert client.get(f"/api/v1/contacts/{ids['contact']}", headers=nest).status_code == 404
    assert client.get(f"/api/v1/customers/{ids['customer']}", headers=nest).status_code == 404
    assert client.get(f"/api/v1/tasks/{ids['task']}", headers=nest).status_code == 404
    assert client.get(
        f"/api/v1/leads/{ids['lead']}/activities", headers=nest
    ).status_code == 404
    assert client.get(
        f"/api/v1/audit-events/{ids['event']}", headers=nest
    ).status_code == 404
    assert client.post(
        f"/api/v1/notifications/{ids['notification']}/read", headers=nest
    ).status_code == 404
    assert client.get(
        f"/api/v1/identity/persons/{ids['person']}", headers=nest
    ).status_code == 404
    # Mutations on foreign IDs also 404 (never 403-with-oracle, never success).
    assert client.patch(
        f"/api/v1/leads/{ids['lead']}", json={"message": "hijack"}, headers=nest
    ).status_code == 404
    assert client.post(
        f"/api/v1/bookings/{ids['booking']}/confirm", headers=nest
    ).status_code == 404
    assert client.post(
        f"/api/v1/tasks/{ids['task']}/status", json={"status": "completed"},
        headers=nest,
    ).status_code == 404
    assert client.post(
        f"/api/v1/leads/{ids['lead']}/convert", json={}, headers=nest
    ).status_code == 404


def test_query_param_and_search_isolation(b2) -> None:
    ids = _prime_seed(b2)
    nest = auth_headers(b2["nest"]["access_token"])
    client = b2["client"]

    # Search terms matching Prime data return nothing under Nest scope.
    for path in (
        "/api/v1/leads?search=Iso",
        "/api/v1/contacts?search=919777700002",
        "/api/v1/tasks?search=Iso",
        "/api/v1/bookings?limit=100&offset=0",
    ):
        resp = client.get(path, headers=nest)
        assert resp.status_code == 200, (path, resp.text)
        body = resp.json()
        assert body["total"] == 0, (path, body)
        assert body["items"] == []

    # Pagination never crosses the boundary (large pages, offsets).
    prime = auth_headers(b2["prime"]["access_token"])
    assert client.get("/api/v1/leads?limit=100&offset=50", headers=nest).json()["total"] == 0
    assert client.get("/api/v1/leads?limit=100&offset=0", headers=prime).json()["total"] >= 1

    # Sorting by any field stays scoped.
    assert client.get(
        "/api/v1/leads?sort=created_at&direction=asc", headers=nest
    ).json()["total"] == 0

    # Filtering by Prime's assignee UUID under Nest scope -> empty, not error/leak.
    assert client.get(
        f"/api/v1/tasks?assigned_to_user_id={b2['prime_owner'].id}", headers=nest
    ).json()["total"] == 0
    _ = ids


def test_notification_and_task_inbox_isolation(b2) -> None:
    _prime_seed(b2)
    prime = auth_headers(b2["prime"]["access_token"])
    nest = auth_headers(b2["nest"]["access_token"])
    client = b2["client"]

    prime_unread = client.get("/api/v1/notifications/unread-count", headers=prime).json()["unread"]
    nest_unread = client.get("/api/v1/notifications/unread-count", headers=nest).json()["unread"]
    assert prime_unread >= 1
    # Nest's inbox is independent (its own intake events or zero).
    assert isinstance(nest_unread, int)

    prime_tasks = client.get("/api/v1/dashboard/tasks", headers=prime).json()
    nest_tasks = client.get("/api/v1/dashboard/tasks", headers=nest).json()
    assert prime_tasks["mine_open"] >= 0
    assert nest_tasks["mine_open"] == 0


def test_forged_business_id_never_trusted(b2) -> None:
    nest = auth_headers(b2["nest"]["access_token"])
    client = b2["client"]
    # No endpoint accepts business_id to switch scope: unknown fields -> 422.
    resp = client.post(
        "/api/v1/leads",
        json={
            "display_name": "Forge", "phone": "+919777700009",
            "business_id": str(uuid.uuid4()),
        },
        headers=nest,
    )
    assert resp.status_code == 422, resp.text
    # Garbage UUID path segments -> 404, never 500.
    assert client.get(f"/api/v1/leads/{uuid.uuid4()}", headers=nest).status_code == 404
    assert client.get("/api/v1/leads/not-a-uuid", headers=nest).status_code == 404
    assert client.get("/api/v1/tasks/not-a-uuid", headers=nest).status_code == 404
    assert client.get("/api/v1/audit-events/not-a-uuid", headers=nest).status_code == 404


def test_both_business_user_stays_scoped_per_token(b2) -> None:
    client = b2["client"]
    both = login_as(
        client, b2["db"], email="both@example.com", slug="prime", role="OWNER",
    )
    # Grant Nest membership too.
    from tests.block1_support import add_test_membership

    from app.models.user import User

    db = b2["db"]
    user = db.query(User).filter(User.email == "both@example.com").first()
    add_test_membership(db, user_id=user.id, business_slug="nest", role_name="STAFF")

    prime_tokens = client.post(
        "/api/v1/auth/login",
        json={"email": "both@example.com", "password": "StrongPass-1234!", "business_slug": "prime"},
    ).json()
    nest_tokens = client.post(
        "/api/v1/auth/login",
        json={"email": "both@example.com", "password": "StrongPass-1234!", "business_slug": "nest"},
    ).json()
    _ = both

    prime_h = auth_headers(prime_tokens["access_token"])
    nest_h = auth_headers(nest_tokens["access_token"])
    assert "OWNER" in str(client.get("/api/v1/auth/me", headers=prime_h).json())
    # Each token only sees its own business data.
    assert client.get("/api/v1/dashboard/overview", headers=prime_h).status_code == 200
    assert client.get("/api/v1/dashboard/overview", headers=nest_h).status_code == 200

    # Prime-token lead invisible to the same user's Nest token.
    lead_id = client.post(
        "/api/v1/leads",
        json={"display_name": "Dual Lead", "phone": "+919777700010"},
        headers=prime_h,
    ).json()["id"]
    assert client.get(f"/api/v1/leads/{lead_id}", headers=nest_h).status_code == 404


def test_suspended_member_loses_access(b2) -> None:
    client = b2["client"]
    tokens = login_as(
        client, b2["db"], email="suspended@example.com", slug="prime", role="STAFF",
    )
    h = auth_headers(tokens["access_token"])
    assert client.get("/api/v1/dashboard/overview", headers=h).status_code == 200

    # Suspend the existing membership directly (DB is authoritative).
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.business import Business
    from app.models.membership import BusinessMembership

    business = b2["db"].execute(
        select(Business).where(Business.slug == "prime")
    ).scalars().first()
    membership = b2["db"].execute(
        select(BusinessMembership).where(
            BusinessMembership.user_id == _uuid.UUID(tokens["user"]["id"]),
            BusinessMembership.business_id == business.id,
        )
    ).scalars().first()
    assert membership is not None
    membership.status = "suspended"
    b2["db"].commit()
    # Next request re-resolves membership from the DB -> denied.
    assert client.get("/api/v1/dashboard/overview", headers=h).status_code in (401, 403)
