"""Block 3 — Nest public intake (slug=nest) + shared-entry routing."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, new_idem_key, public_booking_payload, public_lead_payload  # noqa: F401


def test_nest_lead_booking_config(b2) -> None:
    client = b2["client"]
    config = client.get("/api/v1/public/nest/config")
    assert config.status_code == 200, config.text
    assert config.json()["slug"] == "nest"
    assert config.json()["lead_capture_enabled"] is True
    assert config.json()["booking_enabled"] is True

    lead = client.post(
        "/api/v1/public/nest/leads", json=public_lead_payload(),
        headers={"Idempotency-Key": new_idem_key()},
    )
    assert lead.status_code == 201, lead.text
    assert lead.json()["status"] == "received"

    booking = client.post(
        "/api/v1/public/nest/bookings", json=public_booking_payload(),
        headers={"Idempotency-Key": new_idem_key()},
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["status"] == "received"

    # Staff sees both in Nest scope with slug routing lineage.
    nest = auth_headers(b2["nest"]["access_token"])
    leads = client.get("/api/v1/leads", headers=nest).json()
    assert leads["total"] >= 1
    assert leads["items"][0]["routed_by"] == "slug"
    bookings = client.get("/api/v1/bookings", headers=nest).json()
    assert bookings["total"] >= 1


def test_nest_visit_request_honest_copy(b2) -> None:
    """A Nest 'book visit' form creates REQUESTED — never confirmed."""
    client = b2["client"]
    resp = client.post(
        "/api/v1/public/nest/bookings",
        json=public_booking_payload(
            booking_type="visit", title="Evening study visit",
            message="Need a quiet seat tomorrow evening.",
        ),
    )
    assert resp.status_code == 201, resp.text
    nest = auth_headers(b2["nest"]["access_token"])
    booking_id = resp.json()["booking_id"]
    got = client.get(f"/api/v1/bookings/{booking_id}", headers=nest).json()
    assert got["status"] == "requested"
    assert got["booking_type"] == "visit"


def test_unknown_slug_uniform_404(b2) -> None:
    client = b2["client"]
    assert client.get("/api/v1/public/nope/config").status_code == 404
    assert client.post(
        "/api/v1/public/nope/leads", json=public_lead_payload()
    ).status_code == 404
    assert client.post(
        "/api/v1/public/nope/bookings", json=public_booking_payload()
    ).status_code == 404
