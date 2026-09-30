"""Block 2 — staff Booking API tests (lifecycle + validation + isolation)."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, login_as  # noqa: F401


def _create(client, headers, **overrides):
    payload = {"title": "Trial visit", "booking_type": "trial"}
    payload.update(overrides)
    return client.post("/api/v1/bookings", json=payload, headers=headers)


def test_create_and_get_booking(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    resp = _create(b2["client"], h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "requested"
    got = b2["client"].get(f"/api/v1/bookings/{resp.json()['id']}", headers=h)
    assert got.status_code == 200


def test_create_booking_validation(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    assert _create(b2["client"], h, booking_type="vip").status_code == 422
    # end before start.
    resp = _create(
        b2["client"], h,
        requested_start_at="2030-05-02T10:00:00Z",
        requested_end_at="2030-05-01T10:00:00Z",
    )
    assert resp.status_code == 422, resp.text
    # absurd range.
    resp = _create(b2["client"], h, requested_start_at="1990-01-01T00:00:00Z")
    assert resp.status_code == 422
    # unknown fields rejected.
    assert _create(b2["client"], h, status="confirmed").status_code == 422


def test_booking_lifecycle(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    bid = _create(client, h).json()["id"]
    assert client.post(f"/api/v1/bookings/{bid}/confirm", headers=h).status_code == 200
    # Double confirm is idempotent-safe (same state returns 200).
    assert client.post(f"/api/v1/bookings/{bid}/confirm", headers=h).status_code == 200
    resp = client.post(f"/api/v1/bookings/{bid}/complete", headers=h)
    assert resp.status_code == 200 and resp.json()["status"] == "completed"
    # Terminal: completed -> cancelled forbidden.
    resp = client.post(
        f"/api/v1/bookings/{bid}/cancel",
        json={"cancellation_reason": "x"}, headers=h,
    )
    assert resp.status_code == 409, resp.text


def test_cancel_requires_reason_and_no_show_flow(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    bid = _create(client, h).json()["id"]
    assert client.post(
        f"/api/v1/bookings/{bid}/cancel", json={}, headers=h
    ).status_code == 422
    resp = client.post(
        f"/api/v1/bookings/{bid}/cancel",
        json={"cancellation_reason": "Member sick"}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cancellation_reason"] == "Member sick"
    # cancelled -> completed is illegal.
    assert client.post(f"/api/v1/bookings/{bid}/complete", headers=h).status_code == 409
    # cancelled -> requested re-open allowed for staff.
    resp = client.post(f"/api/v1/bookings/{bid}/confirm", headers=h)
    assert resp.status_code == 409  # confirm is not the re-open path
    # no-show path from requested.
    bid2 = _create(client, h).json()["id"]
    resp = client.post(f"/api/v1/bookings/{bid2}/no-show", headers=h)
    assert resp.status_code == 200 and resp.json()["status"] == "no_show"


def test_booking_filters_and_update(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    bid = _create(client, h, title="Physio consult", booking_type="consultation").json()["id"]
    assert client.get("/api/v1/bookings?booking_type=consultation", headers=h).json()["total"] == 1
    resp = client.patch(
        f"/api/v1/bookings/{bid}", json={"title": "Physio consult (rescheduled)"},
        headers=h,
    )
    assert resp.status_code == 200 and "rescheduled" in resp.json()["title"]
    assert client.get("/api/v1/bookings?status=bogus", headers=h).status_code == 422


def test_booking_isolation_and_permissions(b2) -> None:
    h_prime = auth_headers(b2["prime"]["access_token"])
    h_nest = auth_headers(b2["nest"]["access_token"])
    bid = _create(b2["client"], h_prime).json()["id"]
    assert b2["client"].get(f"/api/v1/bookings/{bid}", headers=h_nest).status_code == 404
    assert b2["client"].patch(
        f"/api/v1/bookings/{bid}", json={"title": "hijack"}, headers=h_nest
    ).status_code == 404
    assert b2["client"].post(f"/api/v1/bookings/{bid}/confirm", headers=h_nest).status_code == 404
    # Release change (owner-ready): STAFF confirms trials (bookings.update);
    # viewer cannot create.
    staff = login_as(
        b2["client"], b2["db"], email="bk-staff@example.com", slug="prime", role="STAFF"
    )
    sh = auth_headers(staff["access_token"])
    assert _create(b2["client"], sh).status_code == 201  # STAFF can create
    assert b2["client"].post(f"/api/v1/bookings/{bid}/confirm", headers=sh).status_code == 200
    viewer = login_as(
        b2["client"], b2["db"], email="bk-viewer@example.com", slug="prime", role="VIEWER"
    )
    assert _create(b2["client"], auth_headers(viewer["access_token"])).status_code == 403
