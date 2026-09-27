"""Blocks 5-7 — end-to-end flows through the real API + DB stack.

Prime:  lead -> booking -> customer -> member -> membership -> payment
        -> attendance -> renewal -> owner analytics.
Nest:   lead -> enquiry -> customer -> member -> plan -> payment -> seat
        -> check-in -> renewal -> owner analytics.
Owner:  prime + nest -> combined dashboard.
"""

from __future__ import annotations


from tests.block57_support import (  # noqa: F811
    H,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    api_seat,
    b57,  # noqa: F401
)


def test_prime_e2e(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = H(b57, "prime")
    # Lead -> booking -> conversion.
    lead = c.post("/api/v1/leads",
                  json={"display_name": "E2E Prime", "phone": "+919000000001",
                        "source": "website", "service_interest": "Gym Membership"},
                  headers=h).json()
    booking = c.post("/api/v1/bookings",
                     json={"title": "Trial visit", "booking_type": "trial",
                           "lead_id": lead["id"], "contact_id": lead["contact_id"]},
                     headers=h)
    assert booking.status_code in (200, 201), booking.text
    # Lifecycle may pass through contacted/qualified/booked only.
    for status in ("contacted", "qualified", "booked"):
        assert c.post(f"/api/v1/leads/{lead['id']}/status",
                      json={"status": status}, headers=h).status_code == 200
    assert c.post(f"/api/v1/bookings/{booking.json()['id']}/confirm",
                  headers=h).status_code == 200
    customer = c.post(f"/api/v1/leads/{lead['id']}/convert", json={},
                      headers=h).json()
    # Customer -> member -> membership -> paid -> attendance.
    member = c.post("/api/v1/members",
                    json={"display_name": "E2E Prime", "phone": "+919000000001",
                          "customer_id": customer["id"], "lead_id": lead["id"]},
                    headers=h).json()
    ms = api_membership(b57, "prime", member["id"],
                        api_plan_id(b57, "prime", "quarterly"),
                        start_date="2026-06-01", end_date="2026-08-31")
    pay = api_payment(b57, "prime", "3500.00", member_id=member["id"],
                      membership_id=ms["id"], method="upi")
    assert c.post(f"/api/v1/payments/{pay['id']}/status",
                  json={"status": "paid"}, headers=h).status_code == 200
    assert c.post("/api/v1/attendance/check-in",
                  json={"member_id": member["id"]}, headers=h).status_code == 201
    # Follow-up task linked to the member (workflow navigation).
    task = c.post("/api/v1/tasks",
                  json={"title": "Call about renewal",
                        "related_entity_type": "member",
                        "related_entity_id": member["id"]},
                  headers=h)
    assert task.status_code == 201, task.text
    # Renewal -> owner sees the business truthfully.
    renewed = c.post(f"/api/v1/memberships/{ms['id']}/renew", json={},
                     headers=h).json()
    assert renewed["renewed_from_id"] == ms["id"]
    overview = c.get("/api/v1/owner/overview", headers=h).json()
    assert overview["membership"]["active_memberships"] >= 1
    assert overview["revenue"]["collected"] == "3500.00"
    assert overview["leads"]["converted"] >= 1


def test_nest_e2e(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = H(b57, "nest")
    lead = c.post("/api/v1/leads",
                  json={"display_name": "E2E Nest", "phone": "+919000000002",
                        "source": "walk_in"}, headers=h).json()
    for status in ("contacted", "qualified", "booked"):
        assert c.post(f"/api/v1/leads/{lead['id']}/status",
                      json={"status": status}, headers=h).status_code == 200
    customer = c.post(f"/api/v1/leads/{lead['id']}/convert", json={},
                      headers=h).json()
    member = c.post("/api/v1/members",
                    json={"display_name": "E2E Nest", "phone": "+919000000002",
                          "customer_id": customer["id"],
                          "seat_preference": "confirmed, first floor"},
                    headers=h).json()
    plan_id = api_plan_id(b57, "nest", "nest-confirmed-3m")
    ms = api_membership(b57, "nest", member["id"], plan_id,
                        start_date="2026-06-01", end_date="2026-08-31")
    assert ms["price"] == "3000.00"
    pay = api_payment(b57, "nest", "3000.00", member_id=member["id"],
                      membership_id=ms["id"], method="cash")
    assert c.post(f"/api/v1/payments/{pay['id']}/status",
                  json={"status": "paid"}, headers=h).status_code == 200
    seat = api_seat(b57, "nest", "E2E-01", seat_type="confirmed")
    alloc = c.post("/api/v1/seat-allocations",
                   json={"seat_id": seat["id"], "member_id": member["id"],
                         "membership_id": ms["id"]}, headers=h)
    assert alloc.status_code == 201, alloc.text
    assert c.post("/api/v1/attendance/check-in",
                  json={"member_id": member["id"], "seat_id": seat["id"]},
                  headers=h).status_code == 201
    renewed = c.post(f"/api/v1/memberships/{ms['id']}/renew",
                     json={"new_plan_id": plan_id}, headers=h).json()
    assert renewed["status"] == "active"
    overview = c.get("/api/v1/owner/overview", headers=h).json()
    assert overview["membership"]["active_memberships"] >= 1
    assert overview["seats"]["allocated_active"] >= 1
    assert overview["revenue"]["collected"] == "3000.00"


def test_combined_owner_e2e(b57) -> None:  # noqa: F811
    c = b57["client"]
    # Seed both sides.
    m1 = api_member(b57, "prime", phone="+919000000011")
    ms1 = api_membership(b57, "prime", m1["id"],
                         api_plan_id(b57, "prime", "monthly"),
                         start_date="2026-07-01", end_date="2026-07-31")
    p1 = api_payment(b57, "prime", "1500.00", member_id=m1["id"],
                     membership_id=ms1["id"])
    c.post(f"/api/v1/payments/{p1['id']}/status", json={"status": "paid"},
           headers=H(b57, "prime"))
    m2 = api_member(b57, "nest", phone="+919000000012")
    ms2 = api_membership(b57, "nest", m2["id"],
                         api_plan_id(b57, "nest", "nest-regular-1m"),
                         start_date="2026-07-01", end_date="2026-07-31")
    p2 = api_payment(b57, "nest", "800.00", member_id=m2["id"],
                     membership_id=ms2["id"])
    c.post(f"/api/v1/payments/{p2['id']}/status", json={"status": "paid"},
           headers=H(b57, "nest"))
    body = c.get("/api/v1/owner/combined", headers=H(b57, "prime")).json()
    # Prompt 2: the prime-only OWNER aggregates only their granted business.
    assert body["totals"]["collected"] == "1500.00"
    assert body["totals"]["payments"] == 1
    by_slug = {b["business"]["slug"]: b for b in body["businesses"]}
    assert set(by_slug) == {"prime"}
    assert by_slug["prime"]["revenue"]["collected"] == "1500.00"
    # A dual-membership owner (the Prompt 2 unified-owner pattern) sees both.
    dual_headers = _dual_owner_headers(b57)
    body = c.get("/api/v1/owner/combined", headers=dual_headers).json()
    assert body["totals"]["collected"] == "2300.00"
    assert body["totals"]["payments"] == 2
    by_slug = {b["business"]["slug"]: b for b in body["businesses"]}
    assert by_slug["prime"]["revenue"]["collected"] == "1500.00"
    assert by_slug["nest"]["revenue"]["collected"] == "800.00"


def _dual_owner_headers(b57) -> dict:  # noqa: F811
    """Login headers for a fresh OWNER member of BOTH prime and nest."""
    from tests.block1_support import (
        TEST_PASSWORD,
        add_test_membership,
        create_test_user,
    )

    user = create_test_user(b57["db"], email="dual-owner@example.com")
    add_test_membership(
        b57["db"], user_id=user.id, business_slug="prime",
        role_name="OWNER", is_default=True,
    )
    add_test_membership(
        b57["db"], user_id=user.id, business_slug="nest", role_name="OWNER",
    )
    resp = b57["client"].post(
        "/api/v1/auth/login",
        json={"email": "dual-owner@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
