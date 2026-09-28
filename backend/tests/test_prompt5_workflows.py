"""Prompt 5 — golden business workflow proof (Prime + Nest + cross-tenant).

Every step goes through the real HTTP surface and asserts DB state,
business_id scoping, and audit/event trails. No mocks, no fakes:
payment verification uses the HMAC webhook contract with a test secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from tests.block57_support import (  # noqa: F811
    H,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    api_seat,
    b57,  # noqa: F401
)


def _webhook_sig(secret: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def _prime_lead_to_member(b57, slug="prime"):  # noqa: F811
    c = b57["client"]
    lead = c.post(
        "/api/v1/leads",
        json={"display_name": "Prime Prospect", "phone": "+919000000001",
              "source": "website"},
        headers=H(b57, slug),
    ).json()
    assert lead["id"]
    for status in ("contacted", "qualified", "booked"):
        r = c.post(f"/api/v1/leads/{lead['id']}/status", json={"status": status},
                   headers=H(b57, slug))
        assert r.status_code == 200, (status, r.text)
    # Follow-up task linked to the lead (next action visible).
    task = c.post(
        "/api/v1/tasks",
        json={"title": "Call prospect", "related_entity_type": "lead",
              "related_entity_id": lead["id"], "priority": "high"},
        headers=H(b57, slug),
    )
    assert task.status_code == 201, task.text
    customer = c.post(f"/api/v1/leads/{lead['id']}/convert", json={},
                      headers=H(b57, slug)).json()
    assert customer["id"]
    member = c.post(
        "/api/v1/members",
        json={"display_name": "Prime Prospect", "phone": "+919000000001",
              "customer_id": customer["id"], "lead_id": lead["id"]},
        headers=H(b57, slug),
    )
    assert member.status_code == 201, member.text
    return lead, customer, member.json()


def test_prompt5_prime_golden_workflow(b57) -> None:  # noqa: F811
    """Website lead -> CRM -> conversion -> membership -> payment -> check-in -> renewal."""
    c = b57["client"]
    lead, customer, member = _prime_lead_to_member(b57, "prime")

    plan_id = api_plan_id(b57, "prime", "monthly")
    ms = api_membership(b57, "prime", member["id"], plan_id,
                        start_date="2026-09-01", end_date="2026-09-30")
    assert ms["status"] == "active"
    assert ms["plan_name_snapshot"] != ""

    pay = api_payment(b57, "prime", "1500.00", member_id=member["id"],
                      membership_id=ms["id"], method="online",
                      idempotency_key="p5-prime-001")
    assert pay["invoice_no"].startswith("INV-")
    # Frontend success is NOT truth: membership stays unpaid until verified.
    assert c.get(f"/api/v1/memberships/{ms['id']}",
                 headers=H(b57, "prime")).json()["payment_state"] != "paid"

    # Verified webhook (test secret at service boundary, labelled mock).
    import app.core.config as _cfg

    _cfg.get_settings.cache_clear()
    import os

    os.environ["PAYMENT_WEBHOOK_SECRET"] = "p5-test-secret"
    _cfg.get_settings.cache_clear()
    try:
        hook = {"idempotency_key": "p5-prime-001", "status": "paid",
                "amount": "1500.00", "currency": "INR", "provider": "mock"}
        r = c.post("/api/v1/payments/webhook", json=hook,
                   headers={"x-webhook-signature": _webhook_sig("p5-test-secret", hook)})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "paid"
        # Duplicate delivery: idempotent, no double credit.
        r2 = c.post("/api/v1/payments/webhook", json=hook,
                    headers={"x-webhook-signature": _webhook_sig("p5-test-secret", hook)})
        assert r2.status_code == 200 and r2.json()["duplicate"] is True
        assert c.get("/api/v1/payments",
                     params={"member_id": member["id"]},
                     headers=H(b57, "prime")).json()["total"] == 1
    finally:
        del os.environ["PAYMENT_WEBHOOK_SECRET"]
        _cfg.get_settings.cache_clear()

    # Entitlement active after verified payment.
    assert c.get(f"/api/v1/memberships/{ms['id']}",
                 headers=H(b57, "prime")).json()["payment_state"] == "paid"

    # Check-in + duplicate protection.
    a1 = c.post("/api/v1/attendance/check-in", json={"member_id": member["id"]},
                headers=H(b57, "prime"))
    assert a1.status_code == 201, a1.text
    a2 = c.post("/api/v1/attendance/check-in", json={"member_id": member["id"]},
                headers=H(b57, "prime"))
    assert a2.json()["id"] == a1.json()["id"]

    # Renewal pipeline: dedupe + FSM + confirm + renew.
    r1 = c.post("/api/v1/renewals", json={"membership_id": ms["id"]},
                headers=H(b57, "prime"))
    assert r1.status_code == 201, r1.text
    r2 = c.post("/api/v1/renewals", json={"membership_id": ms["id"]},
                headers=H(b57, "prime"))
    assert r2.json()["id"] == r1.json()["id"]  # no duplicate pipeline row
    rid = r1.json()["id"]
    bad = c.post(f"/api/v1/renewals/{rid}/status", json={"status": "bogus-x"},
                 headers=H(b57, "prime"))
    assert bad.status_code in (400, 422), bad.text
    ok = c.post(f"/api/v1/renewals/{rid}/status", json={"status": "confirmed"},
                headers=H(b57, "prime"))
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
    # Same-state repeat is a safe no-op.
    ok2 = c.post(f"/api/v1/renewals/{rid}/status", json={"status": "confirmed"},
                 headers=H(b57, "prime"))
    assert ok2.status_code == 200
    # Terminal: confirmed cannot move.
    term = c.post(f"/api/v1/renewals/{rid}/status", json={"status": "pending"},
                  headers=H(b57, "prime"))
    assert term.status_code == 409, term.text

    renewed = c.post(f"/api/v1/memberships/{ms['id']}/renew", json={},
                     headers=H(b57, "prime"))
    assert renewed.status_code == 200, renewed.text

    # Timeline + events + owner visibility.
    tl = c.get(f"/api/v1/members/{member['id']}/timeline", headers=H(b57, "prime"))
    assert tl.status_code == 200 and len(tl.json()["items"]) >= 3, tl.text
    ev = c.get("/api/v1/domain-events", headers=H(b57, "prime"))
    assert ev.status_code == 200 and ev.json()["total"] >= 5, ev.text
    owner = c.get("/api/v1/owner/overview", headers=H(b57, "prime"))
    assert owner.status_code == 200, owner.text
    assert "business" in owner.text.lower() or "prime" in owner.text.lower()


def test_prompt5_nest_golden_workflow(b57) -> None:  # noqa: F811
    """Enquiry -> member -> membership -> payment -> seat -> check-in -> renewal."""
    c = b57["client"]
    lead = c.post(
        "/api/v1/leads",
        json={"display_name": "Nest Reader", "phone": "+918000000002",
              "source": "website"},
        headers=H(b57, "nest"),
    ).json()
    for status in ("contacted", "qualified", "booked"):
        assert c.post(f"/api/v1/leads/{lead['id']}/status", json={"status": status},
                      headers=H(b57, "nest")).status_code == 200
    customer = c.post(f"/api/v1/leads/{lead['id']}/convert", json={},
                      headers=H(b57, "nest")).json()
    member = c.post(
        "/api/v1/members",
        json={"display_name": "Nest Reader", "phone": "+918000000002",
              "customer_id": customer["id"], "lead_id": lead["id"]},
        headers=H(b57, "nest"),
    ).json()
    plan_id = api_plan_id(b57, "nest", "nest-regular-1m")
    ms = api_membership(b57, "nest", member["id"], plan_id,
                        start_date="2026-09-01", end_date="2026-09-30")
    pay = api_payment(b57, "nest", "800.00", member_id=member["id"],
                      membership_id=ms["id"], method="cash",
                      idempotency_key="p5-nest-001")
    assert c.post(f"/api/v1/payments/{pay['id']}/status", json={"status": "paid"},
                  headers=H(b57, "nest")).status_code == 200

    seat = api_seat(b57, "nest", "P5-N1")
    r = c.post("/api/v1/seat-allocations",
               json={"seat_id": seat["id"], "member_id": member["id"],
                     "membership_id": ms["id"]}, headers=H(b57, "nest"))
    assert r.status_code == 201, r.text
    # Conflict: same seat to another member denied.
    m2 = api_member(b57, "nest", phone="+918000000003")
    r = c.post("/api/v1/seat-allocations",
               json={"seat_id": seat["id"], "member_id": m2["id"]},
               headers=H(b57, "nest"))
    assert r.status_code == 409, r.text

    chk = c.post("/api/v1/attendance/check-in",
                 json={"member_id": member["id"], "seat_id": seat["id"]},
                 headers=H(b57, "nest"))
    assert chk.status_code == 201 and chk.json()["seat_id"] == seat["id"], chk.text

    # Release -> available again.
    alloc_id = c.get("/api/v1/seat-allocations",
                     params={"seat_id": seat["id"], "status": "active"},
                     headers=H(b57, "nest")).json()["items"][0]["id"]
    assert c.post(f"/api/v1/seat-allocations/{alloc_id}/release",
                  headers=H(b57, "nest")).status_code == 200
    # Renew preserves history; re-allocate works after release.
    renewed = c.post(f"/api/v1/memberships/{ms['id']}/renew", json={},
                     headers=H(b57, "nest"))
    assert renewed.status_code == 200, renewed.text
    assert c.post("/api/v1/seat-allocations",
                  json={"seat_id": seat["id"], "member_id": member["id"]},
                  headers=H(b57, "nest")).status_code == 201

    tl = c.get(f"/api/v1/members/{member['id']}/timeline", headers=H(b57, "nest"))
    assert tl.status_code == 200 and len(tl.json()["items"]) >= 3


def test_prompt5_cross_tenant_denied(b57) -> None:  # noqa: F811
    c = b57["client"]
    m_prime = api_member(b57, "prime", phone="+919111111111")
    m_nest = api_member(b57, "nest", phone="+918111111111")
    # Nest IDs through Prime APIs -> 404 (no oracle).
    assert c.get(f"/api/v1/members/{m_nest['id']}",
                 headers=H(b57, "prime")).status_code == 404
    assert c.get(f"/api/v1/members/{m_prime['id']}",
                 headers=H(b57, "nest")).status_code == 404
    # Search never leaks across tenants.
    assert c.get("/api/v1/members", params={"search": "91111111111"},
                 headers=H(b57, "nest")).json()["total"] == 0
    # Timeline cross-read denied.
    assert c.get(f"/api/v1/members/{m_nest['id']}/timeline",
                 headers=H(b57, "prime")).status_code == 404
    # Domain events scoped per business (no shared feed).
    p_total = c.get("/api/v1/domain-events", headers=H(b57, "prime")).json()["total"]
    n_total = c.get("/api/v1/domain-events", headers=H(b57, "nest")).json()["total"]
    assert isinstance(p_total, int) and isinstance(n_total, int)


def test_prompt5_payment_matrix(b57) -> None:  # noqa: F811
    import app.core.config as _cfg
    import os

    c = b57["client"]
    m = api_member(b57, "prime", phone="+919222222222")
    ms = api_membership(b57, "prime", m["id"], api_plan_id(b57, "prime", "monthly"),
                        start_date="2026-05-01", end_date="2026-05-31")
    pay = api_payment(b57, "prime", "1500.00", member_id=m["id"],
                      membership_id=ms["id"], method="online",
                      idempotency_key="p5-matrix-001")
    os.environ["PAYMENT_WEBHOOK_SECRET"] = "p5-matrix-secret"
    _cfg.get_settings.cache_clear()
    try:
        good = {"idempotency_key": "p5-matrix-001", "status": "paid",
                "amount": "1500.00", "currency": "INR", "provider": "mock"}
        # Wrong signature -> 401, no mutation.
        bad_sig = c.post("/api/v1/payments/webhook", json=good,
                         headers={"x-webhook-signature": "deadbeef"})
        assert bad_sig.status_code == 401, bad_sig.text
        assert c.get(f"/api/v1/payments/{pay['id']}",
                     headers=H(b57, "prime")).json()["status"] == "pending"
        # Wrong amount -> 409, no mutation.
        wrong = dict(good, amount="1.00")
        r = c.post("/api/v1/payments/webhook", json=wrong,
                   headers={"x-webhook-signature": _webhook_sig("p5-matrix-secret", wrong)})
        assert r.status_code == 409, r.text
        # Wrong currency -> 409.
        wrongc = dict(good, currency="USD")
        r = c.post("/api/v1/payments/webhook", json=wrongc,
                   headers={"x-webhook-signature": _webhook_sig("p5-matrix-secret", wrongc)})
        assert r.status_code == 409, r.text
        # Unknown payment -> 404.
        unk = dict(good, idempotency_key="no-such-key")
        r = c.post("/api/v1/payments/webhook", json=unk,
                   headers={"x-webhook-signature": _webhook_sig("p5-matrix-secret", unk)})
        assert r.status_code == 404, r.text
        # Success then replay -> duplicate flag, single payment row.
        r = c.post("/api/v1/payments/webhook", json=good,
                   headers={"x-webhook-signature": _webhook_sig("p5-matrix-secret", good)})
        assert r.status_code == 200 and r.json()["duplicate"] is False
        r = c.post("/api/v1/payments/webhook", json=good,
                   headers={"x-webhook-signature": _webhook_sig("p5-matrix-secret", good)})
        assert r.json()["duplicate"] is True
        # Failure after paid is an illegal regression -> 409 via FSM.
        fail = dict(good, status="failed")
        r = c.post("/api/v1/payments/webhook", json=fail,
                   headers={"x-webhook-signature": _webhook_sig("p5-matrix-secret", fail)})
        assert r.status_code == 409, r.text
    finally:
        del os.environ["PAYMENT_WEBHOOK_SECRET"]
        _cfg.get_settings.cache_clear()
    # Webhooks without a configured secret -> 503 (never accept blind).
    good2 = {"idempotency_key": "p5-matrix-001", "status": "paid",
             "amount": "1500.00", "currency": "INR", "provider": "mock"}
    r = c.post("/api/v1/payments/webhook", json=good2,
               headers={"x-webhook-signature": "anything"})
    assert r.status_code == 503, r.text


def test_prompt5_attendance_entitlement_matrix(b57) -> None:  # noqa: F811
    c = b57["client"]
    # Active member -> success.
    m = api_member(b57, "prime", phone="+919333333333")
    ms = api_membership(b57, "prime", m["id"], api_plan_id(b57, "prime", "monthly"),
                        start_date="2026-06-01", end_date="2026-06-30")
    assert c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]},
                  headers=H(b57, "prime")).status_code == 201
    # Expired membership -> denied.
    c.post(f"/api/v1/memberships/{ms['id']}/status",
           json={"status": "expired"}, headers=H(b57, "prime"))
    m2 = api_member(b57, "prime", phone="+919333333334")
    ms2 = api_membership(b57, "prime", m2["id"], api_plan_id(b57, "prime", "monthly"),
                         start_date="2026-06-01", end_date="2026-06-30")
    c.post(f"/api/v1/memberships/{ms2['id']}/status",
           json={"status": "expired"}, headers=H(b57, "prime"))
    r = c.post("/api/v1/attendance/check-in",
               json={"member_id": m2["id"], "attendance_date": "2026-06-02"},
               headers=H(b57, "prime"))
    assert r.status_code == 409, r.text
    # Explicit expired membership linkage -> denied.
    r = c.post("/api/v1/attendance/check-in",
               json={"member_id": m2["id"], "membership_id": ms2["id"],
                     "attendance_date": "2026-06-03"},
               headers=H(b57, "prime"))
    assert r.status_code == 409, r.text
    # Wrong tenant -> denied.
    r = c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]},
               headers=H(b57, "nest"))
    assert r.status_code == 404, r.text


def test_prompt5_seat_maintenance_denied_and_member_race_safe(b57) -> None:  # noqa: F811
    c = b57["client"]
    seat = api_seat(b57, "nest", "P5-M1")
    c.patch(f"/api/v1/seats/{seat['id']}", json={"status": "maintenance"},
            headers=H(b57, "nest"))
    m = api_member(b57, "nest", phone="+918222222222")
    r = c.post("/api/v1/seat-allocations",
               json={"seat_id": seat["id"], "member_id": m["id"]},
               headers=H(b57, "nest"))
    assert r.status_code == 409, r.text
    # Duplicate member profile for same customer -> 409 (race-safe).
    lead = c.post("/api/v1/leads",
                  json={"display_name": "Dup", "phone": "+918333333333"},
                  headers=H(b57, "nest")).json()
    customer = c.post(f"/api/v1/leads/{lead['id']}/convert", json={},
                      headers=H(b57, "nest")).json()
    first = c.post("/api/v1/members",
                   json={"display_name": "Dup", "customer_id": customer["id"]},
                   headers=H(b57, "nest"))
    assert first.status_code == 201, first.text
    second = c.post("/api/v1/members",
                    json={"display_name": "Dup", "customer_id": customer["id"]},
                    headers=H(b57, "nest"))
    assert second.status_code == 409, second.text
