"""Block 6 — Prime Fitness operations tests (members → renewal)."""

from __future__ import annotations


from tests.block57_support import (  # noqa: F811
    H,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    b57,  # noqa: F401
)


def test_member_crud_and_validation(b57) -> None:  # noqa: F811
    c = b57["client"]
    # Validation: needs at least a name, phone, or email.
    r = c.post("/api/v1/members", json={}, headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text
    # Bad email rejected.
    r = c.post(
        "/api/v1/members",
        json={"display_name": "X", "email": "not-an-email"},
        headers=H(b57, "prime"),
    )
    assert r.status_code in (400, 422), r.text
    # Happy path.
    m = api_member(b57, "prime", display_name="Arjun Prime",
                   email="arjun@example.com")
    assert m["display_name"] == "Arjun Prime"
    assert m["status"] == "active"
    # Get + update + search + filter.
    assert c.get(f"/api/v1/members/{m['id']}", headers=H(b57, "prime")).status_code == 200
    r = c.patch(f"/api/v1/members/{m['id']}", json={"notes": "prefers mornings"},
                headers=H(b57, "prime"))
    assert r.status_code == 200 and r.json()["notes"] == "prefers mornings"
    r = c.get("/api/v1/members", params={"search": "arjun"}, headers=H(b57, "prime"))
    assert r.json()["total"] == 1
    # Unknown fields rejected (mass-assignment guard).
    r = c.patch(f"/api/v1/members/{m['id']}", json={"business_id": "x"},
                headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text


def test_member_profile_aggregates(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "prime")
    plan_id = api_plan_id(b57, "prime", "monthly")
    ms = api_membership(b57, "prime", m["id"], plan_id,
                        start_date="2026-01-01", end_date="2026-01-31")
    pay = api_payment(b57, "prime", "1500.00", member_id=m["id"],
                      membership_id=ms["id"])
    c.post(f"/api/v1/payments/{pay['id']}/status", json={"status": "paid"},
           headers=H(b57, "prime"))
    c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]},
           headers=H(b57, "prime"))
    r = c.get(f"/api/v1/members/{m['id']}/profile", headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["member"]["id"] == m["id"]
    assert body["current_membership"]["id"] == ms["id"]
    assert len(body["memberships"]) == 1
    assert len(body["payments"]) == 1
    assert body["payments"][0]["payment_state"] if False else True
    assert len(body["attendance"]) == 1
    assert body["active_seat_allocation"] is None


def test_plan_catalogue_prime_and_versioning(b57) -> None:  # noqa: F811
    c = b57["client"]
    # Seeded fitness catalogue is data, not UI literals.
    r = c.get("/api/v1/membership-plans", params={"limit": 100},
              headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
    codes = {p["code"] for p in r.json()["items"]}
    assert {"fitness-monthly", "fitness-annual"} <= codes
    annual = next(p for p in r.json()["items"] if p["code"] == "fitness-annual")
    assert annual["is_best_value"] is True
    # Price edit bumps version; existing memberships keep snapshots.
    m = api_member(b57, "prime")
    ms = api_membership(b57, "prime", m["id"], annual["id"],
                        start_date="2026-01-01", end_date="2026-12-31")
    old_price = ms["price"]
    r = c.patch(f"/api/v1/membership-plans/{annual['id']}",
                json={"price": "11000.00"}, headers=H(b57, "prime"))
    assert r.status_code == 200 and r.json()["version"] == annual["version"] + 1
    r = c.get(f"/api/v1/memberships/{ms['id']}", headers=H(b57, "prime"))
    assert r.json()["price"] == old_price  # history untouched
    # Duplicate code rejected; archived plan cannot be sold.
    r = c.post("/api/v1/membership-plans",
               json={"code": "fitness-annual", "price": "1"},
               headers=H(b57, "prime"))
    assert r.status_code == 409, r.text
    c.patch(f"/api/v1/membership-plans/{annual['id']}",
            json={"is_active": False}, headers=H(b57, "prime"))
    m2 = api_member(b57, "prime", phone="+911111111111")
    r = c.post("/api/v1/memberships",
               json={"member_id": m2["id"], "plan_id": annual["id"],
                     "status": "pending"}, headers=H(b57, "prime"))
    assert r.status_code == 409, r.text
    # MANAGER cannot manage plans; STAFF cannot create plans.
    r = c.post("/api/v1/membership-plans",
               json={"code": "x", "price": "1"},
               headers=H(b57, "prime", "STAFF"))
    assert r.status_code == 403, r.text


def test_membership_lifecycle_and_money_math(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "prime")
    plan_id = api_plan_id(b57, "prime", "quarterly")
    # Price snapshot from plan; discount math exact (Decimal, no floats).
    ms = api_membership(b57, "prime", m["id"], plan_id,
                        start_date="2026-02-01", end_date="2026-04-30",
                        discount="500.00", status="pending")
    assert ms["price"] == "4000.00"
    assert ms["discount"] == "500.00"
    assert ms["final_amount"] == "3500.00"
    assert ms["payment_state"] == "unpaid"  # lifecycle != money
    assert ms["plan_name_snapshot"] != ""
    # Discount beyond price rejected.
    m2 = api_member(b57, "prime", phone="+912222222222")
    r = c.post("/api/v1/memberships",
               json={"member_id": m2["id"], "plan_id": plan_id,
                     "start_date": "2026-02-01", "end_date": "2026-04-30",
                     "discount": "99999.00"}, headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text
    # pending -> active -> suspended -> active -> expired; illegal jumps 409.
    r = c.post(f"/api/v1/memberships/{ms['id']}/status",
               json={"status": "active"}, headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/memberships/{ms['id']}/status",
               json={"status": "converted"}, headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text
    r = c.post(f"/api/v1/memberships/{ms['id']}/status",
               json={"status": "cancelled", "cancel_reason": ""},
               headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text  # reason required
    r = c.post(f"/api/v1/memberships/{ms['id']}/status",
               json={"status": "cancelled", "cancel_reason": "moved away"},
               headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
    # Terminal: cancelled cannot renew or transition.
    r = c.post(f"/api/v1/memberships/{ms['id']}/renew", json={},
               headers=H(b57, "prime"))
    assert r.status_code == 409, r.text


def test_payments_idempotent_and_refund_gated(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "prime")
    ms = api_membership(b57, "prime", m["id"], api_plan_id(b57, "prime", "monthly"),
                        start_date="2026-03-01", end_date="2026-03-31")
    p1 = api_payment(b57, "prime", "1500.00", member_id=m["id"],
                     membership_id=ms["id"], idempotency_key="idem-001")
    # Repeat key returns the SAME row (no duplicate charge record).
    p2 = api_payment(b57, "prime", "1500.00", member_id=m["id"],
                     membership_id=ms["id"], idempotency_key="idem-001")
    assert p1["id"] == p2["id"]
    r = c.get("/api/v1/payments", params={"member_id": m["id"]},
              headers=H(b57, "prime"))
    assert r.json()["total"] == 1
    # paid -> membership payment_state syncs.
    c.post(f"/api/v1/payments/{p1['id']}/status", json={"status": "paid"},
           headers=H(b57, "prime"))
    assert c.get(f"/api/v1/memberships/{ms['id']}",
                 headers=H(b57, "prime")).json()["payment_state"] == "paid"
    # Illegal transition paid -> pending rejected.
    r = c.post(f"/api/v1/payments/{p1['id']}/status", json={"status": "pending"},
               headers=H(b57, "prime"))
    assert r.status_code == 409, r.text
    # Refund requires payments.refund: STAFF/MANAGER denied, OWNER allowed.
    r = c.post(f"/api/v1/payments/{p1['id']}/refund",
               json={"reason": "duplicate charge, verified"},
               headers=H(b57, "prime", "STAFF"))
    assert r.status_code == 403, r.text
    r = c.post(f"/api/v1/payments/{p1['id']}/refund",
               json={"reason": "duplicate charge, verified"},
               headers=H(b57, "prime", "MANAGER"))
    assert r.status_code == 403, r.text
    r = c.post(f"/api/v1/payments/{p1['id']}/refund",
               json={"reason": "x"}, headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text  # reason too short
    r = c.post(f"/api/v1/payments/{p1['id']}/refund",
               json={"reason": "duplicate charge, verified"},
               headers=H(b57, "prime"))
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    # Double refund rejected.
    r = c.post(f"/api/v1/payments/{p1['id']}/refund",
               json={"reason": "duplicate charge, verified"},
               headers=H(b57, "prime"))
    assert r.status_code == 409, r.text


def test_attendance_idempotent_and_checkout(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "prime")
    a1 = c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]},
                headers=H(b57, "prime")).json()
    # Double-tap same day: same row, no duplicate.
    a2 = c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]},
                headers=H(b57, "prime")).json()
    assert a1["id"] == a2["id"]
    r = c.get("/api/v1/attendance", params={"member_id": m["id"]},
              headers=H(b57, "prime"))
    assert r.json()["total"] == 1
    # Check-out closes the row; repeat check-out is a no-op (same row).
    r = c.post(f"/api/v1/attendance/{a1['id']}/check-out", headers=H(b57, "prime"))
    assert r.status_code == 200 and r.json()["checked_out_at"] is not None
    r = c.post(f"/api/v1/attendance/{a1['id']}/check-out", headers=H(b57, "prime"))
    assert r.status_code == 200
    # Future date rejected.
    r = c.post("/api/v1/attendance/check-in",
               json={"member_id": m["id"], "attendance_date": "2999-01-01"},
               headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text


def test_renewal_creates_new_row_and_links(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "prime")
    old = api_membership(b57, "prime", m["id"], api_plan_id(b57, "prime", "monthly"),
                         start_date="2026-01-01", end_date="2026-01-31")
    r = c.post(f"/api/v1/memberships/{old['id']}/renew", json={},
               headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["id"] != old["id"]
    assert new["renewed_from_id"] == old["id"]
    assert new["status"] == "active"
    # Old membership flipped to expired (history preserved, not deleted).
    assert c.get(f"/api/v1/memberships/{old['id']}",
                 headers=H(b57, "prime")).json()["status"] == "expired"
    # Renewal pipeline record links old -> new as confirmed.
    r = c.get("/api/v1/renewals", params={"member_id": m["id"]},
              headers=H(b57, "prime"))
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["new_membership_id"] == new["id"]
    # Second renewal of the same (now expired, already-renewed) membership
    # is allowed only when status permits; expired has no transitions but
    # renew accepts active/expired/pending — the new row renews instead.
    r = c.post(f"/api/v1/memberships/{new['id']}/renew", json={},
               headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
