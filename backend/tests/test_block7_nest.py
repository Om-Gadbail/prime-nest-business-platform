"""Block 7 — Nest Library operations tests (plans, seats, check-in, renewals)."""

from __future__ import annotations

from decimal import Decimal

from tests.block57_support import (  # noqa: F811
    H,
    api_allocate,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    api_seat,
    b57,  # noqa: F401
)

# Spec ``STEP 34`` catalogue (exact values; no free trial, no invented offers).
EXPECTED_NEST_PRICES = {
    "nest-regular-1m": "800",
    "nest-regular-3m": "2400",
    "nest-regular-6m": "4800",
    "nest-regular-8m": "6400",
    "nest-regular-12m": "9600",
    "nest-confirmed-1m": "1000",
    "nest-confirmed-3m": "3000",
    "nest-confirmed-6m": "6000",
    "nest-confirmed-8m": "8000",
    "nest-confirmed-12m": "12000",
    "nest-offer-regular-1m": "699",
    "nest-offer-regular-3m": "1999",
    "nest-offer-regular-6m": "3999",
    "nest-offer-regular-8m": "4999",
    "nest-offer-regular-12m": "7999",
    "nest-offer-confirmed-1m": "899",
    "nest-offer-confirmed-3m": "2599",
    "nest-offer-confirmed-6m": "4999",
    "nest-offer-confirmed-8m": "5999",
    "nest-offer-confirmed-12m": "9999",
}


def test_nest_plan_catalogue_exact(b57) -> None:  # noqa: F811
    c = b57["client"]
    r = c.get("/api/v1/membership-plans", params={"limit": 100},
              headers=H(b57, "nest"))
    assert r.status_code == 200, r.text
    by_code = {p["code"]: p for p in r.json()["items"]}
    assert set(EXPECTED_NEST_PRICES) <= set(by_code), (
        "catalogue missing codes: "
        f"{set(EXPECTED_NEST_PRICES) - set(by_code)}"
    )
    for code, price in EXPECTED_NEST_PRICES.items():
        assert Decimal(by_code[code]["price"]) == Decimal(price), code
    # 12-month tiers flagged Best Value; opening offers categorized.
    for code in ("nest-regular-12m", "nest-confirmed-12m",
                 "nest-offer-regular-12m", "nest-offer-confirmed-12m"):
        assert by_code[code]["is_best_value"] is True, code
    assert by_code["nest-offer-regular-1m"]["category"] == "opening_regular"
    assert by_code["nest-confirmed-1m"]["category"] == "confirmed"
    # Category filter works (website plan-selection contract).
    r = c.get("/api/v1/membership-plans",
              params={"category": "confirmed", "limit": 100},
              headers=H(b57, "nest"))
    assert r.json()["total"] == 5


def test_seat_inventory_and_availability(b57) -> None:  # noqa: F811
    c = b57["client"]
    # Seeded areas exist (template data, not hardcoded layout).
    r = c.get("/api/v1/seat-areas", headers=H(b57, "nest"))
    assert r.status_code == 200 and r.json()["total"] >= 2, r.text
    s1 = api_seat(b57, "nest", "R-01", seat_type="regular")
    api_seat(b57, "nest", "C-01", seat_type="confirmed")
    # Duplicate seat number rejected.
    r = c.post("/api/v1/seats", json={"seat_number": "R-01"},
               headers=H(b57, "nest"))
    assert r.status_code == 409, r.text
    # Server-computed availability (never frontend input).
    avail = c.get("/api/v1/seats/availability", headers=H(b57, "nest")).json()
    assert avail["total"] >= 2 and avail["available"] >= 2
    assert avail["allocated_active"] == 0
    # Free-seat search respects type filter.
    free = c.get("/api/v1/seats/available",
                 params={"seat_type": "confirmed"}, headers=H(b57, "nest")).json()
    assert {s["seat_number"] for s in free["items"]} >= {"C-01"}
    # Blocking an occupied seat is rejected (release first).
    m = api_member(b57, "nest")
    alloc = api_allocate(b57, s1["id"], m["id"])
    assert alloc.status_code == 201, alloc.text
    r = c.patch(f"/api/v1/seats/{s1['id']}", json={"status": "maintenance"},
                headers=H(b57, "nest"))
    assert r.status_code == 409, r.text


def test_seat_allocation_exclusivity(b57) -> None:  # noqa: F811
    c = b57["client"]
    s1 = api_seat(b57, "nest", "R-10")
    m1 = api_member(b57, "nest", phone="+913333333333")
    m2 = api_member(b57, "nest", phone="+914444444444")
    # First allocation wins.
    assert api_allocate(b57, s1["id"], m1["id"]).status_code == 201
    # Same seat to another member: 409.
    r = api_allocate(b57, s1["id"], m2["id"])
    assert r.status_code == 409, r.text
    # Same member to another seat: 409 (one active seat per member).
    s2 = api_seat(b57, "nest", "R-11")
    r = api_allocate(b57, s2["id"], m1["id"])
    assert r.status_code == 409, r.text
    # Non-available seat cannot be allocated.
    c.patch(f"/api/v1/seats/{s2['id']}", json={"status": "blocked"},
            headers=H(b57, "nest"))
    r = api_allocate(b57, s2["id"], m2["id"])
    assert r.status_code == 409, r.text
    # Release frees both seat and member; history preserved.
    alloc_id = c.get("/api/v1/seat-allocations",
                     params={"seat_id": s1["id"], "status": "active"},
                     headers=H(b57, "nest")).json()["items"][0]["id"]
    r = c.post(f"/api/v1/seat-allocations/{alloc_id}/release",
               headers=H(b57, "nest"))
    assert r.status_code == 200 and r.json()["status"] == "released"
    assert api_allocate(b57, s1["id"], m2["id"]).status_code == 201
    # Full history (released + active) retained for the seat.
    hist = c.get("/api/v1/seat-allocations", params={"seat_id": s1["id"]},
                 headers=H(b57, "nest")).json()
    assert hist["total"] == 2
    # Transfer is atomic: old -> transferred, replacement active.
    m3 = api_member(b57, "nest", phone="+915555555555")
    active_id = next(
        a["id"] for a in hist["items"] if a["status"] == "active"
    )
    r = c.post(f"/api/v1/seat-allocations/{active_id}/transfer",
               json={"to_member_id": m3["id"]}, headers=H(b57, "nest"))
    assert r.status_code == 200, r.text
    assert r.json()["member_id"] == m3["id"]
    avail = c.get("/api/v1/seats/availability", headers=H(b57, "nest")).json()
    assert avail["allocated_active"] == 1


def test_nest_checkin_with_seat_and_renewal_preserves_seat(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "nest", phone="+916666666666",
                   seat_preference="window, ground floor")
    plan_id = api_plan_id(b57, "nest", "nest-confirmed-1m")
    ms = api_membership(b57, "nest", m["id"], plan_id,
                        start_date="2026-01-01", end_date="2026-01-31")
    seat = api_seat(b57, "nest", "C-10", seat_type="confirmed")
    api_allocate(b57, seat["id"], m["id"], membership_id=ms["id"])
    # Check-in associated with the seat.
    r = c.post("/api/v1/attendance/check-in",
               json={"member_id": m["id"], "seat_id": seat["id"]},
               headers=H(b57, "nest"))
    assert r.status_code == 201 and r.json()["seat_id"] == seat["id"], r.text
    # Renew with the confirmed plan; allocation history survives expiry.
    r = c.post(f"/api/v1/memberships/{ms['id']}/renew",
               json={"new_plan_id": plan_id}, headers=H(b57, "nest"))
    assert r.status_code == 200, r.text
    hist = c.get("/api/v1/seat-allocations",
                 params={"member_id": m["id"]}, headers=H(b57, "nest")).json()
    assert hist["total"] == 1  # historical assignment preserved, not deleted
    # Member profile shows seat continuity data.
    profile = c.get(f"/api/v1/members/{m['id']}/profile",
                    headers=H(b57, "nest")).json()
    assert profile["active_seat_allocation"] is not None
    assert len(profile["memberships"]) == 2


def test_nest_full_operational_flow(b57) -> None:  # noqa: F811
    """Lead -> customer -> member -> plan -> payment -> seat -> check-in."""
    c = b57["client"]
    lead = c.post("/api/v1/leads",
                  json={"display_name": "Nest Prospect",
                        "phone": "+917777777777", "source": "walk_in"},
                  headers=H(b57, "nest")).json()
    # booked -> converted path (valid lifecycle: new/contacted/qualified/booked).
    for status in ("contacted", "qualified", "booked"):
        r = c.post(f"/api/v1/leads/{lead['id']}/status", json={"status": status},
                   headers=H(b57, "nest"))
        assert r.status_code == 200, (status, r.text)
    customer = c.post(f"/api/v1/leads/{lead['id']}/convert", json={},
                      headers=H(b57, "nest")).json()
    member = c.post("/api/v1/members",
                    json={"display_name": "Nest Prospect",
                          "phone": "+917777777777",
                          "customer_id": customer["id"],
                          "lead_id": lead["id"]},
                    headers=H(b57, "nest")).json()
    assert member["customer_id"] == customer["id"]
    plan_id = api_plan_id(b57, "nest", "nest-offer-regular-3m")
    ms = api_membership(b57, "nest", member["id"], plan_id,
                        start_date="2026-04-01", end_date="2026-06-30")
    assert ms["price"] == "1999.00"
    pay = api_payment(b57, "nest", "1999.00", member_id=member["id"],
                      membership_id=ms["id"], method="cash")
    c.post(f"/api/v1/payments/{pay['id']}/status", json={"status": "paid"},
           headers=H(b57, "nest"))
    seat = api_seat(b57, "nest", "R-20")
    assert api_allocate(b57, seat["id"], member["id"],
                        membership_id=ms["id"]).status_code == 201
    assert c.post("/api/v1/attendance/check-in",
                  json={"member_id": member["id"], "seat_id": seat["id"]},
                  headers=H(b57, "nest")).status_code == 201
    # Renewal pipeline record + confirmed renewal.
    assert c.post("/api/v1/renewals", json={"membership_id": ms["id"]},
                  headers=H(b57, "nest")).status_code == 201
    renewed = c.post(f"/api/v1/memberships/{ms['id']}/renew", json={},
                     headers=H(b57, "nest")).json()
    assert renewed["status"] == "active"
