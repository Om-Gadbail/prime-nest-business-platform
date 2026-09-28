"""Prompt 6 — Owner Command Center & Portfolio Intelligence tests.

Scope-aware owner analytics: alerts, growth (prev-period), renewals
buckets, payment health, attendance signals, automation health, plus
authorization (single-business, combined, forged scope, staff denial)
and audit behavior for sensitive combined views.
"""

from __future__ import annotations

from datetime import date, timedelta

from tests.block57_support import (  # noqa: F811
    H,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    auth_headers,
    b57,  # noqa: F401
)


def _prime_owner_headers(b57):  # noqa: F811
    return H(b57, "prime", "OWNER")


def _paid(b57, slug="prime", amount="1000.00", **kw):  # noqa: F811
    c = b57["client"]
    m = api_member(b57, slug)
    plan = api_plan_id(b57, slug, "monthly" if slug == "prime" else "1m")
    ms = api_membership(b57, slug, m["id"], plan)
    pay = api_payment(b57, slug, amount, member_id=m["id"],
                      membership_id=ms["id"], method="upi", **kw)
    r = c.post(f"/api/v1/payments/{pay['id']}/status", json={"status": "paid"},
               headers=H(b57, slug))
    assert r.status_code == 200, r.text
    return pay


# -- A/B: owner login + /auth/me ----------------------------------------------


def test_owner_login_and_me(b57) -> None:  # noqa: F811
    c = b57["client"]
    r = c.post("/api/v1/auth/login",
               json={"email": "prime-owner@example.com", "password": "StrongPass-1234!"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert "owner.dashboard.read" in body["permissions"]
    assert "owner.combined.read" in body["permissions"]
    me = c.get("/api/v1/auth/me",
               headers=auth_headers(body["access_token"])).json()
    assert me["membership"]["role"] == "OWNER"
    assert me["business"]["slug"] == "prime"


# -- empty states are truthful -------------------------------------------------


def test_new_endpoints_empty_are_truthful(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    for path in ("alerts", "growth", "renewals", "payments", "attendance",
                 "automation-health"):
        r = c.get(f"/api/v1/owner/{path}", headers=h)
        assert r.status_code == 200, (path, r.text)
        assert "generated_at" in r.json(), path
    alerts = c.get("/api/v1/owner/alerts", headers=h).json()
    assert alerts["total"] == 0 and alerts["alerts"] == []
    growth = c.get("/api/v1/owner/growth?preset=30d", headers=h).json()
    assert growth["businesses"][0]["metrics"]["revenue"]["current"] == "0.00"
    assert growth["businesses"][0]["metrics"]["revenue"]["delta_pct"] is None
    renewals = c.get("/api/v1/owner/renewals", headers=h).json()
    assert renewals["businesses"][0]["buckets"]["total"] == 0
    assert renewals["businesses"][0]["buckets"]["renewal_rate"] == 0.0
    payments = c.get("/api/v1/owner/payments?preset=30d", headers=h).json()
    assert payments["businesses"][0]["health"]["attention"] == []
    attendance = c.get("/api/v1/owner/attendance?preset=30d", headers=h).json()
    assert attendance["businesses"][0]["attendance"]["total"] == 0
    auto = c.get("/api/v1/owner/automation-health", headers=h).json()
    health = auto["businesses"][0]["health"]
    # Seed provisions default rules, so the engine inventory is visible
    # even with zero executions; timestamps stay null (honest, not invented).
    assert health["rules_total"] >= 1
    assert health["executions_total"] == 0
    assert health["last_success_at"] is None


# -- payments: failed + overdue surface in health + alerts ---------------------


def test_payment_health_and_alerts(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    m = api_member(b57, "prime")
    plan = api_plan_id(b57, "prime", "monthly")
    ms = api_membership(b57, "prime", m["id"], plan)
    failed = api_payment(b57, "prime", "500.00", member_id=m["id"],
                         membership_id=ms["id"])
    r = c.post(f"/api/v1/payments/{failed['id']}/status", json={"status": "failed"},
               headers=h)
    assert r.status_code == 200, r.text
    overdue = api_payment(b57, "prime", "700.00", member_id=m["id"],
                          membership_id=ms["id"])
    r = c.post(f"/api/v1/payments/{overdue['id']}/status", json={"status": "overdue"},
               headers=h)
    assert r.status_code == 200, r.text

    health = c.get("/api/v1/owner/payments?preset=all", headers=h).json()
    row = health["businesses"][0]["health"]
    assert row["failed_count"] == 1
    assert row["overdue_count"] == 1
    assert row["outstanding"] == "700.00"
    ids = {a["id"] for a in row["attention"]}
    assert {failed["id"], overdue["id"]} <= ids
    # No provider refs or secrets leak through the attention queue.
    assert all("provider_ref" not in a and "secret" not in str(a).lower()
               for a in row["attention"])

    alerts = c.get("/api/v1/owner/alerts?preset=all", headers=h).json()
    cats = {(a["category"], a["severity"]) for a in alerts["alerts"]}
    assert ("finance", "warning") in cats
    assert all(a["observed_at"] for a in alerts["alerts"])


def test_failed_payment_spike_is_critical(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    m = api_member(b57, "prime")
    plan = api_plan_id(b57, "prime", "monthly")
    ms = api_membership(b57, "prime", m["id"], plan)
    for _ in range(5):
        pay = api_payment(b57, "prime", "100.00", member_id=m["id"],
                          membership_id=ms["id"])
        r = c.post(f"/api/v1/payments/{pay['id']}/status", json={"status": "failed"},
                   headers=h)
        assert r.status_code == 200, r.text
    alerts = c.get("/api/v1/owner/alerts?preset=all", headers=h).json()
    assert any(a["severity"] == "critical" and a["category"] == "finance"
               for a in alerts["alerts"])


# -- renewals: buckets + overdue + completion -----------------------------------


def test_renewal_buckets(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    m = api_member(b57, "prime")
    plan = api_plan_id(b57, "prime", "monthly")
    today = date.today()
    due_dates = [today + timedelta(days=3), today + timedelta(days=10),
                 today + timedelta(days=25), today - timedelta(days=2)]
    for i, due in enumerate(due_dates):
        ms = api_membership(b57, "prime", m["id"], plan,
                            start_date="2026-01-01", end_date=str(due))
        r = c.post("/api/v1/renewals",
                   json={"membership_id": ms["id"], "due_date": due.isoformat()},
                   headers=h)
        assert r.status_code == 201, r.text
        if i == 0:
            r = c.post(f"/api/v1/renewals/{r.json()['id']}/status",
                       json={"status": "confirmed"}, headers=h)
            assert r.status_code == 200, r.text
    body = c.get("/api/v1/owner/renewals", headers=h).json()
    buckets = body["businesses"][0]["buckets"]
    # 1 confirmed + 3 pending (10d, 25d, overdue).
    assert buckets["due_7d"]["count"] == 0
    assert buckets["due_14d"]["count"] == 1
    assert buckets["due_30d"]["count"] == 2
    assert buckets["overdue"]["count"] == 1
    assert buckets["completed"] == 1
    assert buckets["renewal_rate"] == round(1 / 4, 4)
    alerts = c.get("/api/v1/owner/alerts?preset=all", headers=h).json()
    assert any(a["category"] == "membership" and "overdue" in a["title"].lower()
               for a in alerts["alerts"])


# -- growth: prev-period deltas + zero-denominator honesty -----------------------


def test_growth_reports_revenue_delta(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    _paid(b57, "prime", "2000.00")
    body = c.get("/api/v1/owner/growth?preset=30d", headers=h).json()
    rev = body["businesses"][0]["metrics"]["revenue"]
    assert rev["current"] == "2000.00"
    # Previous 30d window is empty in a fresh DB: no baseline, no pct.
    assert rev["previous"] == "0.00"
    assert rev["delta"] == "2000.00"
    assert rev["delta_pct"] is None
    assert body["window"]["previous_start"] is not None


def test_growth_open_window_has_no_previous(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    _paid(b57, "prime", "2000.00")
    body = c.get("/api/v1/owner/growth?preset=all", headers=h).json()
    rev = body["businesses"][0]["metrics"]["revenue"]
    assert rev["current"] == "2000.00"
    assert rev["previous"] is None and rev["delta_pct"] is None


# -- attendance: trend + inactive honesty -----------------------------------------


def test_attendance_trend_and_inactive(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    m = api_member(b57, "prime")
    plan = api_plan_id(b57, "prime", "monthly")
    api_membership(b57, "prime", m["id"], plan)
    r = c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]}, headers=h)
    assert r.status_code in (200, 201), r.text
    body = c.get("/api/v1/owner/attendance?preset=30d", headers=h).json()
    att = body["businesses"][0]["attendance"]
    assert att["total"] >= 1
    assert att["active_members"] >= 1
    assert len(att["daily_trend"]) >= 1
    # 30d window < default 14d? No: 30 >= 14, inactivity is evaluated.
    assert att["inactive"]["evaluated"] is True
    short = c.get("/api/v1/owner/attendance?preset=today", headers=h).json()
    assert short["businesses"][0]["attendance"]["inactive"]["evaluated"] is False


# -- lead exceptions feed alerts ---------------------------------------------------


def test_stale_and_uncontacted_leads_alert(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    r = c.post("/api/v1/leads", json={"display_name": "Stale Lead"}, headers=h)
    assert r.status_code == 201, r.text
    lead_id = r.json()["id"]
    # Backdate deterministically: a 10-day-old untouched lead.
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.models.lead import Lead

    db = b57["db"]
    row = db.get(Lead, _uuid.UUID(lead_id))
    row.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    db.commit()
    alerts = c.get("/api/v1/owner/alerts?preset=all", headers=h).json()
    assert any(a["category"] == "leads" and a["severity"] == "warning"
               for a in alerts["alerts"])


# -- automation health ---------------------------------------------------------------


def test_automation_health_reports_rules(b57) -> None:  # noqa: F811
    c = b57["client"]
    h = _prime_owner_headers(b57)
    n_before = c.get("/api/v1/owner/automation-health", headers=h).json(
    )["businesses"][0]["health"]["rules_total"]
    r = c.post("/api/v1/automation/rules",
               json={"name": "Welcome", "event_type": "lead.created",
                     "is_active": True, "priority": 100,
                     "conditions": {}, "actions": [], "config": {}},
               headers=h)
    assert r.status_code == 201, r.text
    body = c.get("/api/v1/owner/automation-health", headers=h).json()
    health = body["businesses"][0]["health"]
    assert health["rules_total"] == n_before + 1
    assert health["rules_active"] >= 1


# -- scope authorization ---------------------------------------------------------------


def test_scope_all_requires_combined_role(b57) -> None:  # noqa: F811
    c = b57["client"]
    # Prime STAFF lacks owner.dashboard.read entirely.
    r = c.get("/api/v1/owner/alerts", headers=H(b57, "prime", "STAFF"))
    assert r.status_code == 403, r.text
    # Prime MANAGER has dashboard.read but not combined.read: single OK, scope denied.
    assert c.get("/api/v1/owner/alerts", headers=H(b57, "prime", "MANAGER")).status_code == 200
    r = c.get("/api/v1/owner/alerts?scope=all", headers=H(b57, "prime", "MANAGER"))
    assert r.status_code == 403, r.text


def _dual_owner_headers(b57):  # noqa: F811
    """An OWNER with active memberships in BOTH prime and nest."""
    from tests.block1_support import (
        TEST_PASSWORD,
        add_test_membership,
        create_test_user,
    )

    user = create_test_user(b57["db"], email="dual-owner@example.com")
    add_test_membership(b57["db"], user_id=user.id, business_slug="prime",
                        role_name="OWNER", is_default=True)
    add_test_membership(b57["db"], user_id=user.id, business_slug="nest",
                        role_name="OWNER")
    r = b57["client"].post("/api/v1/auth/login",
                           json={"email": "dual-owner@example.com",
                                 "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    return auth_headers(r.json()["access_token"])


def test_combined_scope_isolation(b57) -> None:  # noqa: F811
    c = b57["client"]
    _paid(b57, "prime", "2000.00")
    # b57 per-business owners see only their own grant via scope=all.
    owner = _prime_owner_headers(b57)
    own = c.get("/api/v1/owner/growth?preset=all&scope=all", headers=owner).json()
    assert [b["business"]["slug"] for b in own["businesses"]] == ["prime"]
    assert own["businesses"][0]["metrics"]["revenue"]["current"] == "2000.00"
    # Dual-business owner sees both; slug scope narrows honestly.
    dual = _dual_owner_headers(b57)
    body = c.get("/api/v1/owner/growth?preset=all&scope=all", headers=dual).json()
    assert body["combined"] is True
    slugs = {b["business"]["slug"] for b in body["businesses"]}
    assert slugs == {"prime", "nest"}
    prime_only = c.get("/api/v1/owner/growth?preset=all&scope=prime", headers=dual).json()
    assert [b["business"]["slug"] for b in prime_only["businesses"]] == ["prime"]
    assert prime_only["businesses"][0]["metrics"]["revenue"]["current"] == "2000.00"
    nest_only = c.get("/api/v1/owner/growth?preset=all&scope=nest", headers=dual).json()
    assert nest_only["businesses"][0]["metrics"]["revenue"]["current"] == "0.00"
    # Forged slug -> 404, no oracle beyond that.
    assert c.get("/api/v1/owner/growth?scope=nope", headers=dual).status_code == 404
    # Single-business owner cannot reach the other business.
    nest_owner = H(b57, "nest", "OWNER")
    r = c.get("/api/v1/owner/growth?scope=prime", headers=nest_owner)
    assert r.status_code == 403, r.text
    nest_all = c.get("/api/v1/owner/combined?scope=all", headers=nest_owner).json()
    assert [b["business"]["slug"] for b in nest_all["businesses"]] == ["nest"]


def test_unauthenticated_denied(b57) -> None:  # noqa: F811
    c = b57["client"]
    for path in ("alerts", "growth", "renewals", "payments", "attendance",
                 "automation-health"):
        assert c.get(f"/api/v1/owner/{path}").status_code == 401


def test_combined_totals_extended(b57) -> None:  # noqa: F811
    c = b57["client"]
    _paid(b57, "prime", "2000.00")
    body = c.get("/api/v1/owner/combined?scope=all&preset=all",
                 headers=_prime_owner_headers(b57)).json()
    totals = body["totals"]
    for key in ("active_memberships", "active_members", "bookings",
                "attendance_today", "renewals_due_soon", "renewals_overdue",
                "outstanding"):
        assert key in totals, key
    assert totals["collected"] == "2000.00"


def test_single_endpoints_accept_slug_scope(b57) -> None:  # noqa: F811
    c = b57["client"]
    _paid(b57, "prime", "2000.00")
    dual = _dual_owner_headers(b57)
    body = c.get("/api/v1/owner/overview?scope=nest", headers=dual).json()
    assert body["business"]["slug"] == "nest"
    rev = c.get("/api/v1/owner/revenue?preset=all&scope=prime", headers=dual).json()
    assert rev["summary"]["collected"] == "2000.00"
    leads = c.get("/api/v1/owner/leads?scope=nest", headers=dual).json()
    assert leads["funnel"]["total"] == 0
    # scope=all is multi-business: these single-shape endpoints refuse it.
    r = c.get("/api/v1/owner/overview?scope=all", headers=dual)
    assert r.status_code == 422, r.text
    # Unknown slug -> 404; unassigned slug -> 403.
    assert c.get("/api/v1/owner/overview?scope=nope", headers=dual).status_code == 404
    nest_owner = H(b57, "nest", "OWNER")
    assert c.get("/api/v1/owner/overview?scope=prime", headers=nest_owner).status_code == 403


def test_combined_access_is_audited(b57) -> None:  # noqa: F811
    c = b57["client"]
    owner = _prime_owner_headers(b57)
    r = c.get("/api/v1/owner/alerts?preset=all&scope=all", headers=owner)
    assert r.status_code == 200, r.text
    rows = c.get("/api/v1/audit-events", headers=owner)
    assert rows.status_code == 200, rows.text
    actions = {(e.get("action"), e.get("entity_type")) for e in rows.json()["items"]}
    assert ("report.generated", "owner_alerts") in actions


def test_checkin_defaults_to_business_today(b57) -> None:  # noqa: F811
    """Dateless check-ins land on the business-local day (Asia/Kolkata seed).

    Regression: UTC dating pushed near-midnight IST visits onto the wrong
    day in owner "today" views.
    """
    from zoneinfo import ZoneInfo

    from datetime import datetime, timezone

    from app.repositories import businesses as business_repo

    c = b57["client"]
    h = _prime_owner_headers(b57)
    m = api_member(b57, "prime")
    plan = api_plan_id(b57, "prime", "monthly")
    api_membership(b57, "prime", m["id"], plan)
    r = c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]}, headers=h)
    assert r.status_code in (200, 201), r.text
    biz = business_repo.get_by_slug(b57["db"], "prime")
    expected = datetime.now(ZoneInfo(biz.timezone or "UTC")).date().isoformat()
    assert r.json()["attendance_date"] == expected
    assert datetime.now(timezone.utc).date().isoformat() in {
        expected,
        (datetime.now(timezone.utc) - timedelta(hours=6)).date().isoformat(),
    }
    body = c.get("/api/v1/owner/overview?scope=prime&preset=all", headers=h).json()
    assert body["attendance_today"]["total"] == 1
