"""Block 5 — Owner Command Center tests (overview, revenue, funnel, combined)."""

from __future__ import annotations


from tests.block57_support import (  # noqa: F811
    H,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    b57,  # noqa: F401
)


def _seed_prime_revenue(b57) -> None:  # noqa: F811
    m = api_member(b57, "prime", phone="+911000000001")
    plan = api_plan_id(b57, "prime", "monthly")
    ms = api_membership(b57, "prime", m["id"], plan,
                        start_date="2026-01-01", end_date="2026-01-31")
    for amount, method in (("1500.00", "upi"), ("1500.00", "cash")):
        pay = api_payment(b57, "prime", amount, member_id=m["id"],
                          membership_id=ms["id"], method=method)
        r = b57["client"].post(f"/api/v1/payments/{pay['id']}/status",
                               json={"status": "paid"}, headers=H(b57, "prime"))
        assert r.status_code == 200, r.text


def test_owner_overview_empty_is_truthful(b57) -> None:  # noqa: F811
    """No data -> zeros, never invented metrics."""
    r = b57["client"].get("/api/v1/owner/overview", headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["business"]["slug"] == "prime"
    assert body["membership"]["active_memberships"] == 0
    assert body["membership"]["total"] == 0
    assert body["revenue"]["collected"] == "0.00"
    assert body["revenue"]["payment_count"] == 0
    assert body["leads"]["total"] == 0
    assert body["leads"]["lead_conversion_rate"] == 0.0
    assert body["attendance_today"]["total"] == 0
    assert body["renewals"]["total"] == 0
    assert "generated_at" in body


def test_owner_overview_reflects_real_data(b57) -> None:  # noqa: F811
    _seed_prime_revenue(b57)
    body = b57["client"].get("/api/v1/owner/overview",
                             headers=H(b57, "prime")).json()
    assert body["membership"]["active_memberships"] == 1
    assert body["membership"]["active_members"] == 1
    assert body["revenue"]["collected"] == "3000.00"
    assert body["revenue"]["payment_count"] == 2
    assert body["revenue"]["average_transaction"] == "1500.00"
    assert body["revenue"]["by_method"]["upi"]["count"] == 1
    assert body["revenue"]["by_method"]["cash"]["count"] == 1


def test_revenue_presets_and_daily_trend(b57) -> None:  # noqa: F811
    _seed_prime_revenue(b57)
    c = b57["client"]
    for preset in ("today", "7d", "30d", "month", "quarter", "all"):
        r = c.get("/api/v1/owner/revenue", params={"preset": preset},
                  headers=H(b57, "prime"))
        assert r.status_code == 200, (preset, r.text)
        assert r.json()["summary"]["collected"] == "3000.00"
    r = c.get("/api/v1/owner/revenue", params={"preset": "30d"},
              headers=H(b57, "prime"))
    assert isinstance(r.json()["daily_trend"], list)
    r = c.get("/api/v1/owner/revenue", params={"preset": "bogus"},
              headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text
    r = c.get("/api/v1/owner/revenue",
              params={"date_from": "2026-01-02", "date_to": "2026-01-01"},
              headers=H(b57, "prime"))
    assert r.status_code in (400, 422), r.text


def test_lead_funnel_formulas_documented(b57) -> None:  # noqa: F811
    c = b57["client"]
    # 2 converted, 1 lost, 1 spam -> eligible excludes spam.
    for name, phone in (
        ("A", "+911000000011"), ("B", "+911000000012"),
        ("C", "+911000000013"), ("D", "+911000000014"),
    ):
        lead = c.post("/api/v1/leads",
                      json={"display_name": name, "phone": phone},
                      headers=H(b57, "prime")).json()
        if name in ("A", "B"):
            for s in ("contacted", "qualified", "booked"):
                c.post(f"/api/v1/leads/{lead['id']}/status", json={"status": s},
                       headers=H(b57, "prime"))
            c.post(f"/api/v1/leads/{lead['id']}/convert", json={},
                   headers=H(b57, "prime"))
        elif name == "C":
            c.post(f"/api/v1/leads/{lead['id']}/status",
                   json={"status": "lost", "lost_reason": "moved away", "note": "x"},
                   headers=H(b57, "prime"))
        else:
            c.post(f"/api/v1/leads/{lead['id']}/status", json={"status": "spam"},
                   headers=H(b57, "prime"))
    body = c.get("/api/v1/owner/leads", headers=H(b57, "prime")).json()
    funnel = body["funnel"]
    assert funnel["total"] == 4
    assert funnel["converted"] == 2
    assert funnel["eligible"] == 3  # spam excluded, documented
    assert funnel["lead_conversion_rate"] == round(2 / 3, 4)
    assert "lead_conversion_rate" in body["formulas"]
    assert "booking_conversion_rate" in body["formulas"]
    # Zero-denominator safety on a fresh business.
    empty = c.get("/api/v1/owner/leads", headers=H(b57, "nest")).json()
    assert empty["funnel"]["lead_conversion_rate"] == 0.0


def test_combined_gating_and_content(b57) -> None:  # noqa: F811
    c = b57["client"]
    _seed_prime_revenue(b57)
    # STAFF and VIEWER cannot use the combined view.
    assert c.get("/api/v1/owner/combined",
                 headers=H(b57, "prime", "STAFF")).status_code == 403
    assert c.get("/api/v1/owner/combined",
                 headers=H(b57, "prime", "VIEWER")).status_code == 403
    # MANAGER lacks owner.combined.read.
    assert c.get("/api/v1/owner/combined",
                 headers=H(b57, "prime", "MANAGER")).status_code == 403
    # Prompt 2 (Attack #15 fix): combined aggregates ONLY the caller's
    # explicitly granted businesses. The prime-only OWNER sees Prime alone.
    r = c.get("/api/v1/owner/combined", headers=H(b57, "prime"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "all"
    assert body["totals"]["collected"] == "3000.00"
    assert body["totals"]["leads"] >= 0
    assert [b["business"]["slug"] for b in body["businesses"]] == ["prime"]
    # Single-scope to the granted business still flows through the gate.
    r = c.get("/api/v1/owner/combined", params={"scope": "prime"},
              headers=H(b57, "prime"))
    assert r.status_code == 200
    assert [b["business"]["slug"] for b in r.json()["businesses"]] == ["prime"]
    # Single-scope to an UNASSIGNED business is denied (403, not leakage).
    assert c.get("/api/v1/owner/combined", params={"scope": "nest"},
                 headers=H(b57, "prime")).status_code == 403
    # Unknown scope is 404 (no oracle beyond that).
    assert c.get("/api/v1/owner/combined", params={"scope": "nope"},
                 headers=H(b57, "prime")).status_code == 404
    # Prompt 2 (Attack #15 fix): combined aggregates ONLY explicitly granted
    # businesses. The nest-only OWNER sees Nest alone — NOT Prime.
    r = c.get("/api/v1/owner/combined", headers=H(b57, "nest"))
    assert r.status_code == 200, r.text
    assert [b["business"]["slug"] for b in r.json()["businesses"]] == ["nest"]
    # ... and the nest-only OWNER is denied Prime scope explicitly.
    assert c.get("/api/v1/owner/combined", params={"scope": "prime"},
                 headers=H(b57, "nest")).status_code == 403


def test_owner_endpoints_require_auth_and_permission(b57) -> None:  # noqa: F811
    c = b57["client"]
    assert c.get("/api/v1/owner/overview").status_code == 401
    assert c.get("/api/v1/owner/combined").status_code == 401
    # STAFF lacks owner.dashboard.read entirely.
    assert c.get("/api/v1/owner/overview",
                 headers=H(b57, "prime", "STAFF")).status_code == 403
    assert c.get("/api/v1/owner/revenue",
                 headers=H(b57, "prime", "STAFF")).status_code == 403
