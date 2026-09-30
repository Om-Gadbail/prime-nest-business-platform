"""Prompt 3 — final API/data contract tests (structure, not just status).

Covers: response secrecy, error envelope, pagination bounds, sort allowlist,
tenant-scoped idempotency, money/timestamp serialization, owner shapes, auth
contract, session deps, and OpenAPI validation. Runs on isolated SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from tests.block1_support import (
    TEST_PASSWORD,
    add_test_membership,
    auth_headers,
    create_test_user,
    login_token,
    make_auth_client,
    make_test_session,
)


@pytest.fixture
def tdb():
    engine, db = make_test_session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def api(tdb):
    return make_auth_client(tdb)


def _biz(tdb, slug):
    from app.models.business import Business

    return tdb.execute(select(Business).where(Business.slug == slug)).scalars().one()


def _tok(api, email, password=TEST_PASSWORD, slug=None):
    return login_token(api, email=email, password=password, business_slug=slug)[
        "access_token"
    ]


def _no_secrets(obj) -> list[str]:
    """Collect leaked secret-ish keys/values recursively."""
    leaks: list[str] = []
    needle = (
        "password_hash", "password", "refresh_token", "access_token", "secret",
        "database_url", "api_key", "jwt",
    )
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = str(key).lower()
            if any(n in lowered for n in needle):
                leaks.append(str(key))
            leaks.extend(_no_secrets(value))
    elif isinstance(obj, list):
        for item in obj:
            leaks.extend(_no_secrets(item))
    elif isinstance(obj, str):
        if obj.startswith("$argon2"):
            leaks.append("argon2-hash-value")
    return leaks


@pytest.fixture
def owner_headers(api, tdb):
    return auth_headers(_tok(api, "owner@prime-nest-dashboard.com",
                             password="OwnerDemo123!", slug="prime"))


class TestResponseSecrecy:
    def test_auth_and_staff_responses_carry_no_secrets(self, api, tdb):
        user = create_test_user(tdb, email="sec1@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="OWNER")
        body = login_token(api, email="sec1@example.com", business_slug="prime")
        scrubbed = {k: v for k, v in body.items()
                    if k not in ("access_token", "refresh_token")}
        assert _no_secrets(scrubbed) == []
        headers = auth_headers(body["access_token"])
        for path in ("/api/v1/auth/me", "/api/v1/auth/businesses",
                     "/api/v1/leads", "/api/v1/owner/overview"):
            r = api.get(path, headers=headers)
            assert r.status_code == 200, (path, r.text)
            assert _no_secrets(r.json()) == [], path

    def test_lead_create_echo_has_no_secrets(self, api, tdb):
        user = create_test_user(tdb, email="sec2@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        headers = auth_headers(_tok(api, "sec2@example.com", slug="prime"))
        r = api.post("/api/v1/leads",
                     json={"display_name": "Anita", "phone": "+911111110051"},
                     headers=headers)
        assert r.status_code == 201, r.text
        assert _no_secrets(r.json()) == []


class TestErrorContract:
    @pytest.mark.parametrize("path", [
        "/api/v1/leads/00000000-0000-0000-0000-000000000000",
        "/api/v1/owner/combined",
    ])
    def test_error_envelope_and_request_id(self, api, tdb, path):
        user = create_test_user(tdb, email="err1@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        headers = auth_headers(_tok(api, "err1@example.com", slug="prime"))
        r = api.get(path, headers=headers)
        assert r.status_code in (403, 404), r.text
        body = r.json()
        assert set(body) == {"error"} and {"code", "message"} <= set(body["error"])
        assert r.headers.get("X-Request-ID")

    def test_unauthorized_and_validation_envelopes(self, api):
        r = api.get("/api/v1/auth/me")
        assert r.status_code == 401 and r.json()["error"]["code"] == "http_error"
        r = api.post("/api/v1/auth/login", json={"email": "x", "password": "y"})
        assert r.status_code in (401, 422)
        assert "error" in r.json()


class TestPaginationContract:
    def test_defaults_clamp_and_sort_allowlist(self, api, tdb, owner_headers):
        r = api.get("/api/v1/leads", headers=owner_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"items", "total", "limit", "offset"}
        assert body["limit"] == 50 and body["offset"] == 0
        # Absurd limit clamps to 100; bogus sort falls back (never 500).
        r = api.get("/api/v1/leads",
                    params={"limit": 10000, "sort": "DROP TABLE leads;--"},
                    headers=owner_headers)
        assert r.status_code == 200, r.text
        assert r.json()["limit"] == 100
        r = api.get("/api/v1/leads",
                    params={"direction": "sideways"},
                    headers=owner_headers)
        assert r.status_code == 200, r.text


class TestIdempotencyContract:
    def test_same_key_is_per_business(self, api):
        key = f"prompt3-{uuid.uuid4().hex[:12]}"
        headers = {"Idempotency-Key": key}
        r1 = api.post("/api/v1/public/prime/leads",
                      json={"name": "Prime Idem", "phone": "+911111110061"},
                      headers=headers)
        r2 = api.post("/api/v1/public/nest/leads",
                      json={"name": "Nest Idem", "phone": "+911111110062"},
                      headers=headers)
        assert r1.status_code == 201, r1.text
        # Same key on the OTHER business is a distinct operation (no collision).
        assert r2.status_code == 201, r2.text
        assert r1.json()["lead_id"] != r2.json()["lead_id"]
        # Same key replayed on the SAME endpoint replays without duplication.
        r3 = api.post("/api/v1/public/prime/leads",
                      json={"name": "Prime Idem", "phone": "+911111110061"},
                      headers=headers)
        assert r3.status_code in (200, 201), r3.text
        assert r3.json()["lead_id"] == r1.json()["lead_id"]


class TestMoneyAndTimeContract:
    def test_money_serializes_as_decimal_strings(self, api, tdb, owner_headers):
        member = api.post("/api/v1/members",
                          json={"display_name": "Pay Member", "phone": "+911111110071"},
                          headers=owner_headers).json()
        pay = api.post("/api/v1/payments",
                       json={"amount": "1500.00", "currency": "INR", "method": "upi",
                             "member_id": member["id"]},
                       headers=owner_headers)
        assert pay.status_code == 201, pay.text
        assert pay.json()["amount"] == "1500.00"
        assert isinstance(pay.json()["amount"], str)
        rev = api.get("/api/v1/owner/revenue", headers=owner_headers).json()
        assert rev["summary"]["collected"] == "0.00"

    def test_timestamps_are_tz_aware_iso(self, api, owner_headers):
        body = api.get("/api/v1/owner/overview", headers=owner_headers).json()
        parsed = datetime.fromisoformat(body["generated_at"])
        assert parsed.tzinfo is not None


class TestOwnerShapes:
    def test_overview_shape_and_seat_capability(self, api, tdb, owner_headers):
        prime = api.get("/api/v1/owner/overview", headers=owner_headers).json()
        assert {"business", "generated_at", "membership", "revenue", "leads",
                "bookings", "attendance_today", "renewals"} <= set(prime)
        assert prime["business"]["slug"] == "prime"
        assert prime["seats"] is None  # Prime lacks seat_management capability
        nest_tok = _tok(api, "owner@prime-nest-dashboard.com",
                        password="OwnerDemo123!", slug="nest")
        nest = api.get("/api/v1/owner/overview",
                       headers=auth_headers(nest_tok)).json()
        assert nest["seats"] is not None  # Nest capability present

    def test_combined_shape(self, api, owner_headers):
        body = api.get("/api/v1/owner/combined", headers=owner_headers).json()
        assert {"generated_at", "scope", "totals", "businesses"} <= set(body)
        assert {b["business"]["slug"] for b in body["businesses"]} == {"prime", "nest"}
        for item in body["businesses"]:
            assert {"business", "revenue", "leads", "membership",
                    "attendance_today", "renewals"} <= set(item)


class TestAuthContract:
    def test_me_and_businesses(self, api, tdb):
        user = create_test_user(tdb, email="auth1@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime",
                            role_name="MANAGER", is_default=True)
        body = login_token(api, email="auth1@example.com", business_slug="prime")
        assert body["token_type"] == "bearer" and body["access_token"]
        assert body["business"]["slug"] == "prime"
        assert "leads.read" in body["permissions"]
        headers = auth_headers(body["access_token"])
        me = api.get("/api/v1/auth/me", headers=headers).json()
        assert me["user"]["email"] == "auth1@example.com"
        assert me["business"]["slug"] == "prime"
        assert me["membership"]["role"] == "MANAGER"
        biz = api.get("/api/v1/auth/businesses", headers=headers).json()
        assert isinstance(biz, list)
        assert [(b["business"]["slug"], b["role"]) for b in biz] == [("prime", "MANAGER")]


class TestSessionDeps:
    def test_explicit_session_aliases(self, tdb):
        from app.api import deps as api_deps

        assert "get_platform_db" in api_deps.__all__
        assert "get_business_db" in api_deps.__all__


class TestOpenAPIContract:
    def test_openapi_frozen_and_valid(self):
        from app.main import create_app

        app = create_app()
        paths = app.openapi()["paths"]
        operations = sum(
            1 for _path, item in paths.items() for method in item
            if method in ("get", "post", "put", "patch", "delete", "options", "head")
        )
        # Frozen contract surface (Prompt 1: 160 routes incl. ops/docs;
        # Prompt 5: +4 paths/+4 ops — renewals/{id}/status, payments/webhook,
        # domain-events, members/{id}/timeline).
        # Prompt 6: +6 paths/+6 ops — owner alerts, growth, renewals,
        # payments, attendance, automation-health.
        # Pre-Prompt-7 foundation: +2 paths/+3 ops — integrations/status,
        # whatsapp/webhook/{business_key} (GET verify + POST inbound, pinned).
        # Prompt 7: +2 paths/+2 ops — bookings/{id}/trial-outcome,
        # communications/handoff (growth engine staff APIs).
        # Prompt 8: +2 paths/+2 ops — automation/executions/dead-letter,
        # automation/executions/{execution_id}/retry (dead-letter
        # visibility + controlled manual retry; see production-reliability.md).
        # WhatsApp production hardening: +1 path/+1 op —
        # communications/ai-resume (explicit staff resume of autonomous
        # WhatsApp AI after a human handoff; additive, no existing
        # contract changed).
        assert len(paths) == 142, len(paths)
        assert operations == 174, operations
        # Anchors every frontend needs.
        for anchor in ("/api/v1/auth/login", "/api/v1/auth/switch-business",
                       "/api/v1/auth/businesses", "/api/v1/owner/combined",
                       "/api/v1/owner/overview", "/api/v1/owner/alerts",
                       "/api/v1/owner/growth", "/api/v1/owner/renewals",
                       "/api/v1/owner/payments", "/api/v1/owner/attendance",
                       "/api/v1/owner/automation-health",
                       "/api/v1/integrations/status",
                        "/api/v1/whatsapp/webhook",
                        "/api/v1/whatsapp/webhook/{business_key}",
                        "/api/v1/bookings/{booking_id}/trial-outcome",
                        "/api/v1/communications/handoff",
                        "/api/v1/public/{slug}/leads",
                        "/api/v1/public/{slug}/bookings", "/api/v1/leads",
                        "/api/v1/automation/executions/dead-letter",
                        "/api/v1/automation/executions/{execution_id}/retry"):
            assert anchor in paths, anchor
        # No duplicate operation IDs; security schemes declared.
        op_ids = [op.get("operationId") for item in paths.values()
                  for op in item.values() if isinstance(op, dict)]
        op_ids = [o for o in op_ids if o]
        assert len(op_ids) == len(set(op_ids))
        schemes = app.openapi()["components"].get("securitySchemes", {})
        assert "HTTPBearer" in schemes
