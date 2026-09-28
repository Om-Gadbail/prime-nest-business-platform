"""Block 4 — dashboard APIs (overview, summaries, activity, snapshots)."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, login_as, public_lead_payload  # noqa: F401


def _seed_prime(client, prime_headers) -> None:
    client.post(
        "/api/v1/leads",
        json={"display_name": "Dash Lead", "phone": "+919666600001"},
        headers=prime_headers,
    )
    client.post("/api/v1/public/prime/bookings", json={
        "name": "Dash Visitor", "phone": "+919666600002",
        "booking_type": "trial", "title": "Trial visit",
    })
    client.post("/api/v1/tasks", json={"title": "Dash task"}, headers=prime_headers)


def test_overview_shape_and_counts(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    _seed_prime(b2["client"], prime)

    resp = b2["client"].get("/api/v1/dashboard/overview", headers=prime)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["leads"]["new"] >= 1
    assert body["leads"]["created_today"] >= 1
    assert body["bookings"]["requested"] >= 1
    assert body["bookings"]["created_today"] >= 1
    assert body["tasks"]["open_total"] >= 1
    assert body["notifications"]["unread"] >= 1  # new-lead fan-out
    assert len(body["recent_leads"]) >= 1
    assert isinstance(body["recent_activity"], list)
    # No internal normalization fields leak.
    assert "normalized_phone" not in resp.text


def test_overview_is_business_scoped(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    nest = auth_headers(b2["nest"]["access_token"])
    _seed_prime(b2["client"], prime)

    nest_overview = b2["client"].get("/api/v1/dashboard/overview", headers=nest).json()
    assert nest_overview["leads"]["new"] == 0
    assert nest_overview["bookings"]["requested"] == 0
    assert nest_overview["tasks"]["open_total"] == 0
    assert nest_overview["recent_leads"] == []


def test_summaries_and_activity(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    _seed_prime(b2["client"], prime)

    leads = b2["client"].get("/api/v1/dashboard/leads/summary", headers=prime)
    assert leads.status_code == 200, leads.text
    assert leads.json()["by_status"].get("new", 0) >= 1

    bookings = b2["client"].get("/api/v1/dashboard/bookings/summary", headers=prime)
    assert bookings.json()["by_status"].get("requested", 0) >= 1

    activity = b2["client"].get("/api/v1/dashboard/activity", headers=prime)
    assert activity.status_code == 200, activity.text
    assert activity.json()["total"] >= 1


def test_dashboard_snapshots(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    staff = login_as(
        b2["client"], b2["db"], email="dash-staff@example.com",
        slug="prime", role="STAFF",
    )
    staff_h = auth_headers(staff["access_token"])
    # Assign the staff user a task so workload counters are non-trivial.
    task_id = b2["client"].post(
        "/api/v1/tasks", json={"title": "Staff workload"}, headers=prime
    ).json()["id"]
    b2["client"].post(
        f"/api/v1/tasks/{task_id}/assign",
        json={"assigned_to_user_id": staff["user"]["id"]},
        headers=prime,
    )

    workload = b2["client"].get("/api/v1/dashboard/tasks", headers=staff_h)
    assert workload.status_code == 200, workload.text
    assert workload.json()["mine_open"] >= 1

    snapshot = b2["client"].get("/api/v1/dashboard/notifications", headers=staff_h)
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["unread"] >= 1


def test_dashboard_requires_auth_and_permissions(b2) -> None:
    # No token -> 401.
    assert b2["client"].get("/api/v1/dashboard/overview").status_code == 401
    # VIEWER can read overview (dashboard.read) but not the audit activity.
    viewer = login_as(
        b2["client"], b2["db"], email="dash-viewer@example.com",
        slug="prime", role="VIEWER",
    )
    vh = auth_headers(viewer["access_token"])
    assert b2["client"].get("/api/v1/dashboard/overview", headers=vh).status_code == 200
    assert b2["client"].get("/api/v1/dashboard/activity", headers=vh).status_code == 403


def test_booking_reopen_flow(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    booking_id = b2["client"].post(
        "/api/v1/bookings", json={"title": "Reopen me"}, headers=prime
    ).json()["id"]
    assert b2["client"].post(
        f"/api/v1/bookings/{booking_id}/cancel",
        json={"cancellation_reason": "Visitor asked to reschedule."},
        headers=prime,
    ).status_code == 200
    reopened = b2["client"].post(f"/api/v1/bookings/{booking_id}/reopen", headers=prime)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "requested"
    # Nest cannot reopen Prime's booking.
    nest = auth_headers(b2["nest"]["access_token"])
    assert b2["client"].post(
        f"/api/v1/bookings/{booking_id}/reopen", headers=nest
    ).status_code == 404
