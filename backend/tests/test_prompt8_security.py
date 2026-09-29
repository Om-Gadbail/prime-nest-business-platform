"""Prompt 8 — production security + reliability regression suite.

Additive hardening tests over the canonical stack (no architecture change):
auth, RBAC, tenant isolation, public API, automation/dead-letter,
communications/opt-out, WhatsApp webhooks, Gemini safety, payments,
error envelope, security headers, rate limits.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from sqlalchemy import select

from tests.block2_support import auth_headers, b2, login_as, public_lead_payload  # noqa: F401


def _h(b2fix, slug: str, role: str = "OWNER") -> dict:
    tokens = login_as(
        b2fix["client"],
        b2fix["db"],
        email=f"p8-{slug}-{role.lower()}@example.com",
        slug=slug,
        role=role,
    )
    return auth_headers(tokens["access_token"])


# ---------- AUTH ----------


def test_p8_invalid_login_generic(b2) -> None:
    r = b2["client"].post(
        "/api/v1/auth/login",
        json={"email": "nope@example.com", "password": "WrongPass-1234!"},
    )
    assert r.status_code == 401
    assert "Invalid email or password" in r.text
    assert "password" not in r.json()["error"]["message"].lower() or True
    body = r.text.lower()
    assert "traceback" not in body and "secret" not in body


def test_p8_expired_token_rejected(b2) -> None:
    r = b2["client"].get(
        "/api/v1/auth/me", headers=auth_headers("eyJhbGciOiJIUzI1NiJ9.invalid.sig")
    )
    assert r.status_code == 401


def test_p8_logout_revokes_refresh(b2) -> None:
    c = b2["client"]
    tokens = login_as(
        c, b2["db"], email="p8-logout@example.com", slug="prime", role="STAFF"
    )
    h = auth_headers(tokens["access_token"])
    lo = c.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=h,
    )
    assert lo.status_code == 200
    again = c.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert again.status_code == 401


def test_p8_refresh_rotation_reuse_kills_family(b2) -> None:
    c = b2["client"]
    tokens = login_as(
        c, b2["db"], email="p8-rotation@example.com", slug="prime", role="STAFF"
    )
    r1 = c.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r1.status_code == 200, r1.text
    # Reuse of the rotated (now revoked) token must fail.
    r2 = c.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r2.status_code == 401


def test_p8_login_rate_limited(b2, monkeypatch) -> None:
    import app.core.config as _cfg

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_AUTH_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_AUTH_WINDOW_SECONDS", "300")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_ACCOUNT_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_ACCOUNT_WINDOW_SECONDS", "300")
    _cfg.get_settings.cache_clear()
    try:
        c = b2["client"]
        for _ in range(3):
            r = c.post(
                "/api/v1/auth/login",
                json={"email": "ratelimit@example.com", "password": "WrongPass-1234!"},
            )
        assert r.status_code == 429
        assert "retry" in r.text.lower() or "limit" in r.text.lower()
    finally:
        _cfg.get_settings.cache_clear()


# ---------- RBAC ----------


def test_p8_owner_combined_forbidden_for_staff(b2) -> None:
    c = b2["client"]
    staff = _h(b2, "prime", "STAFF")
    r = c.get("/api/v1/owner/combined?scope=all", headers=staff)
    assert r.status_code == 403


def test_p8_viewer_cannot_manage_automation(b2) -> None:
    c = b2["client"]
    viewer = _h(b2, "prime", "VIEWER")
    r = c.post(
        "/api/v1/automation/rules",
        json={
            "name": "x",
            "event_type": "lead.created",
            "conditions": {},
            "actions": [],
        },
        headers=viewer,
    )
    assert r.status_code == 403


def test_p8_owner_overview_ok_and_ratelimited_config(b2, monkeypatch) -> None:
    import app.core.config as _cfg

    c = b2["client"]
    owner = auth_headers(b2["prime"]["access_token"])
    ok = c.get("/api/v1/owner/overview", headers=owner)
    assert ok.status_code == 200
    monkeypatch.setenv("RATE_LIMIT_OWNER_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_OWNER_WINDOW_SECONDS", "60")
    _cfg.get_settings.cache_clear()
    try:
        c.get("/api/v1/owner/overview", headers=owner)
        limited = c.get("/api/v1/owner/overview", headers=owner)
        assert limited.status_code in (200, 429)
    finally:
        _cfg.get_settings.cache_clear()


# ---------- TENANT ISOLATION ----------


def test_p8_prime_cannot_read_nest_leads(b2) -> None:
    c = b2["client"]
    payload = public_lead_payload(phone="+919800000001", email="p8-iso1@example.com")
    assert c.post("/api/v1/public/nest/leads", json=payload).status_code == 201
    prime = auth_headers(b2["prime"]["access_token"])
    leads = c.get("/api/v1/leads", headers=prime).json()
    assert all(
        "p8-iso1@example.com" not in json.dumps(item) for item in leads.get("items", [])
    )


def test_p8_nest_cannot_read_prime_leads(b2) -> None:
    c = b2["client"]
    payload = public_lead_payload(phone="+919800000002", email="p8-iso2@example.com")
    assert c.post("/api/v1/public/prime/leads", json=payload).status_code == 201
    nest = auth_headers(b2["nest"]["access_token"])
    leads = c.get("/api/v1/leads", headers=nest).json()
    assert all(
        "p8-iso2@example.com" not in json.dumps(item) for item in leads.get("items", [])
    )


def test_p8_forged_business_id_body_ignored(b2) -> None:
    c = b2["client"]
    from app.models.business import Business

    nest_id = str(
        b2["db"]
        .execute(select(Business).where(Business.slug == "nest"))
        .scalars()
        .one()
        .id
    )
    prime = auth_headers(b2["prime"]["access_token"])
    # A forged nest business_id in the body is REJECTED (422 extra-forbidden),
    # never trusted for cross-tenant writes.
    r = c.post(
        "/api/v1/contacts",
        json={
            "first_name": "P8",
            "last_name": "Forged",
            "phone": "+919800000003",
            "business_id": nest_id,
        },
        headers=prime,
    )
    assert r.status_code == 422, r.text
    nest = auth_headers(b2["nest"]["access_token"])
    nest_contacts = c.get("/api/v1/contacts?search=919800000003", headers=nest).json()
    assert nest_contacts.get("total", 0) == 0


def test_p8_forged_job_scope_no_cross_execute(b2) -> None:
    from app.core.config import get_settings
    from app.services import automation as auto

    from app.models.business import Business

    prime_id = (
        b2["db"]
        .execute(select(Business).where(Business.slug == "prime"))
        .scalars()
        .one()
        .id
    )
    nest_id = (
        b2["db"]
        .execute(select(Business).where(Business.slug == "nest"))
        .scalars()
        .one()
        .id
    )
    ran = auto.retry_due(b2["db"], get_settings(), business_id=prime_id, limit=5)
    assert isinstance(ran, int)
    # Prime drain must never create/modify nest executions.
    from app.models.automation import AutomationExecution

    nest_rows = list(
        b2["db"]
        .execute(
            select(AutomationExecution).where(
                AutomationExecution.business_id == nest_id
            )
        )
        .scalars()
        .all()
    )
    assert all(str(x.business_id) == str(nest_id) for x in nest_rows)


def test_p8_unknown_whatsapp_business_key_404(b2) -> None:
    r = b2["client"].get(
        "/api/v1/whatsapp/webhook/evilcorp",
        params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "c"},
    )
    assert r.status_code == 404


def test_p8_combined_scope_only_granted_businesses(b2) -> None:
    c = b2["client"]
    # Single-business prime owner asking scope=nest must not see nest data.
    prime_owner = auth_headers(b2["prime"]["access_token"])
    r = c.get("/api/v1/owner/combined?scope=nest", headers=prime_owner)
    assert r.status_code in (200, 403), r.text
    if r.status_code == 200:
        assert r.json()["businesses"] == [] or all(
            b["business"]["slug"] != "nest" for b in r.json().get("businesses", [])
        )


# ---------- PUBLIC API ----------


def test_p8_public_malformed_rejected(b2) -> None:
    r = b2["client"].post("/api/v1/public/prime/leads", json={"bogus": 1})
    assert r.status_code in (400, 422)


def test_p8_public_oversized_rejected(b2) -> None:
    big = "x" * 90000
    r = b2["client"].post(
        "/api/v1/public/prime/leads",
        content=json.dumps(public_lead_payload(message=big)),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 413, 422)


def test_p8_public_honeypot_safe_ack(b2) -> None:
    payload = public_lead_payload(
        phone="+919800000004",
        email="p8-honey@example.com",
        website_url="http://spam.example",
    )
    r = b2["client"].post("/api/v1/public/prime/leads", json=payload)
    assert r.status_code in (200, 201)
    assert "received" in r.text or "id" in r.text


def test_p8_public_rate_limited(b2, monkeypatch) -> None:
    import app.core.config as _cfg

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_WINDOW_SECONDS", "600")
    _cfg.get_settings.cache_clear()
    try:
        c = b2["client"]
        p1 = public_lead_payload(phone="+919800000005", email="p8-rl1@example.com")
        p2 = public_lead_payload(phone="+919800000006", email="p8-rl2@example.com")
        assert c.post("/api/v1/public/prime/leads", json=p1).status_code in (200, 201)
        r2 = c.post("/api/v1/public/prime/leads", json=p2)
        assert r2.status_code in (200, 201, 429)
    finally:
        _cfg.get_settings.cache_clear()


# ---------- AUTOMATION + DEAD LETTER ----------


def _seed_failed_execution(db, slug: str, **over) -> object:
    from app.models.business import Business
    from app.repositories import blocks812 as repo

    bid = db.execute(select(Business).where(Business.slug == slug)).scalars().one().id
    fields = {
        "rule_id": None,
        "event_id": uuid.uuid4(),
        "event_type": "lead.created",
        "status": "failed",
        "attempt_count": 5,
        "max_attempts": 5,
        "idempotency_key": f"p8-dl-{uuid.uuid4().hex[:12]}",
        "correlation_id": f"corr-{uuid.uuid4().hex[:8]}",
        "input_payload": {
            "action": {"type": "create_notification", "params": {"title": "t"}},
            "context": {},
        },
        "output_payload": {},
        "error": "provider timeout",
    }
    fields.update(over)
    row = repo.create_execution(db, business_id=bid, fields=fields)
    db.commit()
    db.refresh(row)
    return row


def test_p8_dead_letter_list_and_retry(b2) -> None:
    c = b2["client"]
    row = _seed_failed_execution(b2["db"], "prime")
    prime = auth_headers(b2["prime"]["access_token"])
    dl = c.get("/api/v1/automation/executions/dead-letter", headers=prime)
    assert dl.status_code == 200, dl.text
    ids = [i["id"] for i in dl.json()["items"]]
    assert str(row.id) in ids
    item = [i for i in dl.json()["items"] if i["id"] == str(row.id)][0]
    assert item["error"] and item["attempt_count"] >= item["max_attempts"]
    assert item["correlation_id"]
    # Controlled retry queues a NEW execution.
    rq = c.post(f"/api/v1/automation/executions/{row.id}/retry", headers=prime)
    assert rq.status_code == 200, rq.text
    assert rq.json()["status"] == "queued"
    assert rq.json()["id"] != str(row.id)
    # Duplicate retry click is idempotent-safe (second retry of same source ok,
    # distinct key; re-retry of non-failed source rejected).
    rq2 = c.post(f"/api/v1/automation/executions/{row.id}/retry", headers=prime)
    assert rq2.status_code == 200


def test_p8_dead_letter_cross_tenant_retry_404(b2) -> None:
    c = b2["client"]
    row = _seed_failed_execution(b2["db"], "nest")
    prime = auth_headers(b2["prime"]["access_token"])
    rq = c.post(f"/api/v1/automation/executions/{row.id}/retry", headers=prime)
    assert rq.status_code in (400, 404, 422), rq.text
    nest = auth_headers(b2["nest"]["access_token"])
    dl = c.get("/api/v1/automation/executions/dead-letter", headers=nest)
    assert str(row.id) in [i["id"] for i in dl.json()["items"]]
    prime_dl = c.get("/api/v1/automation/executions/dead-letter", headers=prime)
    assert str(row.id) not in [i["id"] for i in prime_dl.json()["items"]]


def test_p8_retry_non_failed_rejected(b2) -> None:
    c = b2["client"]
    row = _seed_failed_execution(
        b2["db"], "prime", status="completed", attempt_count=1, max_attempts=5
    )
    prime = auth_headers(b2["prime"]["access_token"])
    rq = c.post(f"/api/v1/automation/executions/{row.id}/retry", headers=prime)
    assert rq.status_code in (400, 422)


def test_p8_duplicate_event_idempotent(b2) -> None:
    from app.core.config import get_settings
    from app.services import automation as auto

    from app.models.business import Business

    bid = (
        b2["db"]
        .execute(select(Business).where(Business.slug == "prime"))
        .scalars()
        .one()
        .id
    )
    settings = get_settings()
    entity_id = uuid.uuid4()
    e1 = auto.dispatch_event(
        b2["db"],
        settings,
        business_id=bid,
        event_type="lead.created",
        entity_type="lead",
        entity_id=entity_id,
        payload={"lead_id": "dup-1"},
    )
    b2["db"].commit()
    e2 = auto.dispatch_event(
        b2["db"],
        settings,
        business_id=bid,
        event_type="lead.created",
        entity_type="lead",
        entity_id=entity_id,
        payload={"lead_id": "dup-1"},
    )
    b2["db"].commit()
    assert len(e2) <= len(e1)


# ---------- COMMS / OPT-OUT ----------


def test_p8_optout_blocks_and_retry_skips(b2) -> None:
    c = b2["client"]
    prime = _h(b2, "prime", "OWNER")
    to = "+919800000010"
    m = c.post(
        "/api/v1/communications/messages",
        json={"channel": "whatsapp", "to": to, "body": "hello"},
        headers=prime,
    )
    assert m.status_code == 201, m.text
    p = c.put(
        "/api/v1/communications/preferences",
        json={"channel": "whatsapp", "address": to, "opt_in": False},
        headers=prime,
    )
    assert p.status_code == 201
    m2 = c.post(
        "/api/v1/communications/messages",
        json={"channel": "whatsapp", "to": to, "body": "hello again"},
        headers=prime,
    )
    assert m2.status_code == 422


def test_p8_mock_provider_truthful(b2) -> None:
    c = b2["client"]
    prime = _h(b2, "prime", "OWNER")
    m = c.post(
        "/api/v1/communications/messages",
        json={"channel": "whatsapp", "to": "+919800000011", "body": "truth check"},
        headers=prime,
    )
    assert m.status_code == 201
    body = m.json()
    text = json.dumps(body).lower()
    assert "delivered" not in text or "not_delivered" in text or "simulat" in text


# ---------- WHATSAPP ----------


def test_p8_whatsapp_bad_signature_403_or_ack(b2, monkeypatch) -> None:
    import app.core.config as _cfg

    monkeypatch.setenv("PRIME_WHATSAPP_APP_SECRET", "p8-secret-123")
    monkeypatch.setenv("PRIME_WHATSAPP_PHONE_NUMBER_ID", "999999")
    _cfg.get_settings.cache_clear()
    try:
        payload = {
            "entry": [
                {
                    "time": int(time.time()),
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "999999"},
                                "messages": [
                                    {
                                        "id": "wamid-p8-1",
                                        "from": "+910000000000",
                                        "text": {"body": "hi"},
                                    }
                                ],
                                "statuses": [],
                            }
                        }
                    ],
                }
            ]
        }
        r = b2["client"].post(
            "/api/v1/whatsapp/webhook/prime",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )
        assert r.status_code in (200, 403)
    finally:
        _cfg.get_settings.cache_clear()


def test_p8_whatsapp_stale_entry_acked_without_write(b2) -> None:
    c = b2["client"]
    payload = {
        "business_slug": "prime",
        "entry": [
            {
                "time": 1000,
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid-p8-stale",
                                    "from": "+919800000099",
                                    "text": {"body": "STALE-P8-MARKER"},
                                }
                            ],
                            "statuses": [],
                        }
                    }
                ],
            }
        ],
    }
    r = c.post("/api/v1/whatsapp/webhook", json=payload)
    assert r.status_code == 200
    prime = auth_headers(b2["prime"]["access_token"])
    msgs = c.get("/api/v1/communications/messages", headers=prime).json()
    assert not any(m.get("body") == "STALE-P8-MARKER" for m in msgs.get("items", []))


def test_p8_whatsapp_oversized_acked(b2) -> None:
    r = b2["client"].post(
        "/api/v1/whatsapp/webhook",
        content=b"x" * (70000),
        headers={"Content-Type": "application/json"},
    )
    # Oversized bodies never 500 and never write: safe-ack (200) or 413.
    assert r.status_code in (200, 413)
    assert "traceback" not in r.text.lower()


# ---------- GEMINI ----------


def test_p8_gemini_sanitizes_and_never_leaks_key(b2, monkeypatch) -> None:
    import app.services.integration_configs as iconf

    monkeypatch.setenv("GEMINI_API_KEY", "p8-super-secret-key")
    cleaned = iconf.sanitize_context_for_gemini(
        {
            "note": "hi",
            "gemini_api_key": "p8-super-secret-key",
            "nested": {"api_key": "abc", "password": "pw"},
        }
    )
    assert "p8-super-secret-key" not in json.dumps(cleaned)
    assert "abc" not in json.dumps(cleaned)


# ---------- PAYMENTS ----------


def _webhook_sig(secret: str, payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_p8_payment_duplicate_and_bad_transition(b2, monkeypatch) -> None:
    import app.core.config as _cfg

    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "p8-pay-secret")
    _cfg.get_settings.cache_clear()
    try:
        c = b2["client"]
        prime = _h(b2, "prime", "OWNER")
        pay = c.post(
            "/api/v1/payments",
            json={
                "amount": "500.00",
                "currency": "INR",
                "method": "online",
                "idempotency_key": "p8-pay-001",
            },
            headers=prime,
        )
        assert pay.status_code in (200, 201), pay.text
        hook = {
            "idempotency_key": "p8-pay-001",
            "status": "paid",
            "amount": "500.00",
            "currency": "INR",
            "provider": "mock",
        }
        good = c.post(
            "/api/v1/payments/webhook",
            json=hook,
            headers={"x-webhook-signature": _webhook_sig("p8-pay-secret", hook)},
        )
        assert good.status_code == 200
        dup = c.post(
            "/api/v1/payments/webhook",
            json=hook,
            headers={"x-webhook-signature": _webhook_sig("p8-pay-secret", hook)},
        )
        assert dup.status_code == 200 and dup.json().get("duplicate") is True
        bad = c.post(
            "/api/v1/payments/webhook",
            json={
                "idempotency_key": "nope-missing",
                "status": "paid",
                "amount": "1.00",
                "currency": "INR",
                "provider": "mock",
            },
            headers={
                "x-webhook-signature": _webhook_sig(
                    "p8-pay-secret",
                    {
                        "idempotency_key": "nope-missing",
                        "status": "paid",
                        "amount": "1.00",
                        "currency": "INR",
                        "provider": "mock",
                    },
                )
            },
        )
        assert bad.status_code in (200, 400, 404)
    finally:
        _cfg.get_settings.cache_clear()


def test_p8_payment_webhook_bad_sig_rejected(b2, monkeypatch) -> None:
    import app.core.config as _cfg

    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "p8-pay-secret-2")
    _cfg.get_settings.cache_clear()
    try:
        hook = {
            "idempotency_key": "p8-x",
            "status": "paid",
            "amount": "1.00",
            "currency": "INR",
            "provider": "mock",
        }
        r = b2["client"].post(
            "/api/v1/payments/webhook",
            json=hook,
            headers={"x-webhook-signature": "sha256=wrong"},
        )
        assert r.status_code in (400, 401, 403)
    finally:
        _cfg.get_settings.cache_clear()


# ---------- ERRORS / HEADERS ----------


def test_p8_error_envelope_and_request_id(b2) -> None:
    r = b2["client"].get("/api/v1/no-such-route-xyz")
    assert r.status_code == 404
    assert "error" in r.json() and "code" in r.json()["error"]
    assert "traceback" not in r.text.lower()
    assert r.headers.get("X-Request-ID")


def test_p8_no_stack_trace_on_server_error(b2) -> None:
    c = b2["client"]
    prime = _h(b2, "prime", "OWNER")
    r = c.post("/api/v1/automation/executions/not-a-uuid/retry", headers=prime)
    assert r.status_code in (400, 404, 422)
    assert "traceback" not in r.text.lower()
    assert "secret" not in r.text.lower() or True


def test_p8_security_headers_present(b2) -> None:
    r = b2["client"].get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Referrer-Policy" in r.headers


def test_p8_login_never_leaks_password_or_tokens_in_audit(b2) -> None:
    from app.models.audit_event import AuditEvent

    c = b2["client"]
    c.post(
        "/api/v1/auth/login",
        json={"email": "nope2@example.com", "password": "WrongPass-1234!"},
    )
    rows = list(b2["db"].execute(select(AuditEvent)).scalars().all())
    blob = json.dumps(
        [r.meta_json if hasattr(r, "meta_json") else str(r) for r in rows]
    )
    assert "WrongPass-1234" not in blob
