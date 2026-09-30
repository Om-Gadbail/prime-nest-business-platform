"""Blocks 5-7 — adversarial isolation/RBAC tests (every entity, both ways)."""

from __future__ import annotations


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


def _prime_setup(b57):  # noqa: F811
    """Create one of every operational entity in prime; return id map."""
    c = b57["client"]
    m = api_member(b57, "prime", phone="+911111110001")
    ms = api_membership(b57, "prime", m["id"], api_plan_id(b57, "prime", "monthly"),
                        start_date="2026-01-01", end_date="2026-12-31")
    pay = api_payment(b57, "prime", "1500.00", member_id=m["id"],
                      membership_id=ms["id"])
    att = c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]},
                 headers=H(b57, "prime")).json()
    ren = c.post("/api/v1/renewals", json={"membership_id": ms["id"]},
                 headers=H(b57, "prime")).json()
    plan_id = api_plan_id(b57, "prime", "monthly")
    appr = c.post("/api/v1/approvals",
                  json={"entity_type": "payment", "entity_id": pay["id"],
                        "title": "refund review", "reason": "verify"},
                  headers=H(b57, "prime")).json()
    return {
        "member": m["id"], "membership": ms["id"], "payment": pay["id"],
        "attendance": att["id"], "renewal": ren["id"], "plan": plan_id,
        "approval": appr["id"],
    }


def test_cross_business_reads_are_404(b57) -> None:  # noqa: F811
    ids = _prime_setup(b57)
    c = b57["client"]
    nest = H(b57, "nest")  # nest OWNER: valid auth, wrong business
    assert c.get(f"/api/v1/members/{ids['member']}", headers=nest).status_code == 404
    assert c.get(f"/api/v1/memberships/{ids['membership']}", headers=nest).status_code == 404
    assert c.get(f"/api/v1/payments/{ids['payment']}", headers=nest).status_code == 404
    assert c.get(f"/api/v1/membership-plans/{ids['plan']}", headers=nest).status_code == 404
    assert c.get(f"/api/v1/renewals/{ids['renewal']}", headers=nest).status_code == 404
    assert c.get(f"/api/v1/approvals/{ids['approval']}", headers=nest).status_code == 404
    # Lists never leak across businesses either.
    assert c.get("/api/v1/members", headers=nest).json()["total"] == 0
    assert c.get("/api/v1/payments", headers=nest).json()["total"] == 0
    assert c.get("/api/v1/memberships", headers=nest).json()["total"] == 0


def test_forged_links_rejected(b57) -> None:  # noqa: F811
    """Foreign member/membership/customer IDs behave as nonexistent."""
    ids = _prime_setup(b57)
    c = b57["client"]
    nest = H(b57, "nest")
    # Membership for a prime member from nest: member 404.
    r = c.post("/api/v1/memberships",
               json={"member_id": ids["member"], "start_date": "2026-01-01",
                     "end_date": "2026-02-01", "price": "100.00"},
               headers=nest)
    assert r.status_code == 404, r.text
    # Payment pointing at a prime membership from nest: 404.
    r = c.post("/api/v1/payments",
               json={"amount": "100.00", "membership_id": ids["membership"]},
               headers=nest)
    assert r.status_code == 404, r.text
    # Check-in for a prime member from nest: 404.
    r = c.post("/api/v1/attendance/check-in",
               json={"member_id": ids["member"]}, headers=nest)
    assert r.status_code == 404, r.text
    # Seat allocation for a prime member from nest: member 404
    # (seats.manage held by nest owner; the member link fails first).
    seat = api_seat(b57, "nest", "X-01")
    r = api_allocate(b57, seat["id"], ids["member"], slug="nest")
    assert r.status_code == 404, r.text
    # Status/mutation endpoints on foreign rows: 404, not 403 (no oracle).
    r = c.post(f"/api/v1/memberships/{ids['membership']}/status",
               json={"status": "cancelled", "cancel_reason": "x"}, headers=nest)
    assert r.status_code == 404, r.text
    r = c.post(f"/api/v1/payments/{ids['payment']}/refund",
               json={"reason": "forged refund attempt here"}, headers=nest)
    assert r.status_code == 404, r.text


def test_viewer_cannot_mutate(b57) -> None:  # noqa: F811
    ids = _prime_setup(b57)
    c = b57["client"]
    v = H(b57, "prime", "VIEWER")
    assert c.post("/api/v1/members", json={"display_name": "No"},
                  headers=v).status_code == 403
    assert c.post("/api/v1/memberships",
                  json={"member_id": ids["member"]},
                  headers=v).status_code == 403
    assert c.post("/api/v1/payments", json={"amount": "10"},
                  headers=v).status_code == 403
    assert c.post("/api/v1/attendance/check-in",
                  json={"member_id": ids["member"]},
                  headers=v).status_code == 403
    assert c.post("/api/v1/seats", json={"seat_number": "ZZ-9"},
                  headers=v).status_code == 403
    assert c.post("/api/v1/renewals", json={"membership_id": ids["membership"]},
                  headers=v).status_code == 403
    # Viewer CAN request an approval (read-level intent) but never decide it.
    assert c.post("/api/v1/approvals",
                  json={"entity_type": "x", "title": "t", "reason": "r"},
                  headers=v).status_code == 201
    assert c.post(f"/api/v1/approvals/{ids['approval']}/decide",
                  json={"status": "approved"}, headers=v).status_code == 403
    # Reads stay allowed (read-only role keeps working).
    assert c.get("/api/v1/members", headers=v).status_code == 200
    assert c.get("/api/v1/owner/overview", headers=v).status_code == 200


def test_staff_mutation_boundaries(b57) -> None:  # noqa: F811
    ids = _prime_setup(b57)
    c = b57["client"]
    s = H(b57, "prime", "STAFF")
    # Allowed: register members/memberships/payments/check-ins.
    assert c.post("/api/v1/members", json={"display_name": "Desk"},
                  headers=s).status_code == 201
    # Release change (owner-ready): frontline STAFF progresses operational
    # work — member/membership/payment updates, seat allocation, renewals.
    assert c.patch(f"/api/v1/members/{ids['member']}", json={"notes": "x"},
                   headers=s).status_code == 200
    assert c.post(f"/api/v1/memberships/{ids['membership']}/status",
                  json={"status": "cancelled", "cancel_reason": "x"},
                  headers=s).status_code == 200
    assert c.post(f"/api/v1/payments/{ids['payment']}/status",
                  json={"status": "paid"}, headers=s).status_code == 200
    assert c.post("/api/v1/seats", json={"seat_number": "ZZ-8"},
                  headers=s).status_code == 201
    assert c.post("/api/v1/renewals", json={"membership_id": ids["membership"]},
                  headers=s).status_code == 201
    # Still denied: refunds, plan management, approvals-decide, owner views.
    assert c.post(f"/api/v1/payments/{ids['payment']}/refund",
                  json={"reason": "x"}, headers=s).status_code == 403
    assert c.post("/api/v1/membership-plans", json={"code": "x", "name": "x"},
                  headers=s).status_code in (403, 404, 405)
    assert c.post(f"/api/v1/approvals/{ids['approval']}/decide",
                  json={"status": "approved"}, headers=s).status_code == 403
    assert c.get("/api/v1/owner/combined", headers=s).status_code == 403


def test_approval_self_decision_rejected(b57) -> None:  # noqa: F811
    c = b57["client"]
    appr = c.post("/api/v1/approvals",
                  json={"entity_type": "refund", "title": "self",
                        "reason": "requesting approval"},
                  headers=H(b57, "prime")).json()
    # Requester (same owner user) cannot approve their own request.
    r = c.post(f"/api/v1/approvals/{appr['id']}/decide",
               json={"status": "approved"}, headers=H(b57, "prime"))
    assert r.status_code == 409, r.text


def test_garbage_uuids_are_404_not_500(b57) -> None:  # noqa: F811
    c = b57["client"]
    o = H(b57, "prime")
    for path in ("/api/v1/members/not-a-uuid",
                 "/api/v1/memberships/not-a-uuid",
                 "/api/v1/payments/not-a-uuid",
                 "/api/v1/renewals/not-a-uuid",
                 "/api/v1/seats/not-a-uuid",
                 "/api/v1/approvals/not-a-uuid"):
        assert c.get(path, headers=o).status_code == 404, path
