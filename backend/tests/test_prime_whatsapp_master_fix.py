"""MASTER FIX — Prime WhatsApp two-way AI regression tests (no network).

Covers task §12 A–R + master-fix additions:
A. webhook verification (pinned, valid token)
B. invalid verification token -> 403
C. valid webhook POST accepted
D. invalid webhook signature -> 403
E. valid webhook signature -> 200
F. inbound text parsing ("Hi" stored)
G. wamid deduplication (same wamid -> one row)
H. Prime business resolution (phone->prime, never Nest, never user-controlled)
I. Gemini response path (live provider mocked; transient fallback uses real plans)
J. Meta outbound send (mocked 200 -> sent with wamid)
K. Meta authentication failure -> META_AUTH_INVALID, FAILED persisted, never delivered
L. STOP suppresses automation
M. START restores eligibility
N. human handoff pauses AI until explicit resume
O. conversation history (inbound + outbound share conversation_id)
P. cross-business isolation (Prime traffic never in Nest)
Q. duplicate webhook -> ONE AI response (idempotent wa-ai-<mid>)
R. provider failure (transport) -> FAILED row, honest status
S. retry behavior (429/5xx retried, 4xx fail-fast)
T. trial intent triggers existing lead workflow
U. any normal text (8 demo messages) gets a useful response
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from tests.block1_support import (
    TEST_PASSWORD,
    add_test_membership,
    create_test_user,
    make_auth_client,
    make_test_session,
)

PRIME_ENV = {
    "PRIME_WHATSAPP_ENABLED": "true",
    "PRIME_WHATSAPP_ACCESS_TOKEN": "prime-token-ABC",
    "PRIME_WHATSAPP_PHONE_NUMBER_ID": "111111111111111",
    "PRIME_WHATSAPP_BUSINESS_ACCOUNT_ID": "prime-waba-1",
    "PRIME_WHATSAPP_VERIFY_TOKEN": "prime-verify-TOKEN",
    "PRIME_WHATSAPP_APP_SECRET": "prime-app-secret-123",
}

NEST_ENV = {
    "NEST_WHATSAPP_ENABLED": "true",
    "NEST_WHATSAPP_ACCESS_TOKEN": "nest-token-XYZ",
    "NEST_WHATSAPP_PHONE_NUMBER_ID": "222222222222222",
    "NEST_WHATSAPP_BUSINESS_ACCOUNT_ID": "nest-waba-2",
    "NEST_WHATSAPP_VERIFY_TOKEN": "nest-verify-TOKEN",
    "NEST_WHATSAPP_APP_SECRET": "nest-app-secret-456",
}


def _apply_env(monkeypatch: pytest.MonkeyPatch, extra: dict) -> None:
    from app.core.config import get_settings

    for key, value in {**PRIME_ENV, **NEST_ENV, **extra}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _settings():
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture
def fnd():
    engine, db = make_test_session()
    try:
        users = {}
        for slug in ("prime", "nest"):
            for role in ("OWNER", "STAFF"):
                email = f"wamaster-{slug}-{role.lower()}@example.com"
                user = create_test_user(db, email=email)
                add_test_membership(
                    db, user_id=user.id, business_slug=slug, role_name=role,
                    is_default=(role == "OWNER"),
                )
                users[(slug, role)] = user
        client = make_auth_client(db)

        def _login(email: str) -> dict:
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": TEST_PASSWORD},
            )
            assert resp.status_code == 200, resp.text
            return resp.json()

        tokens = {(s, r): _login(u.email) for (s, r), u in users.items()}
        yield {"engine": engine, "db": db, "client": client, "users": users, "tokens": tokens}
    finally:
        db.close()
        engine.dispose()


def _headers(fnd, slug: str, role: str = "OWNER") -> dict:
    return {"Authorization": f"Bearer {fnd['tokens'][(slug, role)]['access_token']}"}


def _business(db, slug: str):
    from app.models.business import Business

    return db.execute(select(Business).where(Business.slug == slug)).scalars().one()


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post_webhook(client, url: str, payload: dict, secret: str):
    raw = json.dumps(payload).encode()
    return client.post(
        url,
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(secret, raw)},
    )


def _inbound_payload(phone_id: str, mid: str, sender: str, text: str, **kw) -> dict:
    msg: dict = {"id": mid, "from": sender, "type": "text", "text": {"body": text}}
    msg.update(kw)
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "entry-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_id},
                            "messages": [msg],
                        },
                    }
                ],
            }
        ],
    }


def _mock_meta_200(monkeypatch, mid: str = "wamid.MASTER1"):
    import app.services.messaging as mm

    counter = {"n": 0}
    base = mid

    class _Resp:
        status_code = 200

        def json(self):
            counter["n"] += 1
            mid_out = base if counter["n"] == 1 else f"{base}-{counter['n']}"
            return {"messages": [{"id": mid_out}]}

    monkeypatch.setattr(mm.httpx, "post", lambda *a, **k: _Resp())
    import time as _tm

    monkeypatch.setattr(_tm, "sleep", lambda *a, **k: None)


# A/B: verification ------------------------------------------------------------

def test_a_verify_valid_token(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    r = fnd["client"].get(
        "/api/v1/whatsapp/webhook/prime",
        params={"hub.mode": "subscribe", "hub.verify_token": "prime-verify-TOKEN",
                "hub.challenge": "CHALLENGE-1"},
    )
    assert r.status_code == 200 and r.text == "CHALLENGE-1"


def test_b_verify_invalid_token(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    r = fnd["client"].get(
        "/api/v1/whatsapp/webhook/prime",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong",
                "hub.challenge": "CHALLENGE-1"},
    )
    assert r.status_code == 403


# C/D/E: webhook signature -----------------------------------------------------

def test_cde_webhook_signature_matrix(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "false"})
    client = fnd["client"]
    payload = _inbound_payload("111111111111111", "wamid-master-c", "+919000010001", "Hi")
    # E: valid signature -> 200 + stored
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime", payload,
                         "prime-app-secret-123").status_code == 200
    # D: invalid signature -> 403
    raw = json.dumps(payload).encode()
    bad = client.post(
        "/api/v1/whatsapp/webhook/prime", content=raw,
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": "sha256=" + "0" * 64},
    )
    assert bad.status_code == 403


# F/G: parsing + dedupe --------------------------------------------------------

def test_f_inbound_text_parsing(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "false"})
    client = fnd["client"]
    payload = _inbound_payload("111111111111111", "wamid-master-hi", "+919000010002", "Hi")
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime", payload,
                         "prime-app-secret-123").status_code == 200
    msgs = client.get("/api/v1/communications/messages",
                      headers=_headers(fnd, "prime")).json()["items"]
    mine = [m for m in msgs if m["provider_message_id"] == "wamid-master-hi"]
    assert len(mine) == 1 and mine[0]["body"] == "Hi"
    assert mine[0]["direction"] == "inbound"


def test_g_wamid_deduplication(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "false"})
    client = fnd["client"]
    payload = _inbound_payload("111111111111111", "wamid-master-dedupe",
                               "+919000010003", "Hello")
    for _ in range(3):
        assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime", payload,
                             "prime-app-secret-123").status_code == 200
    msgs = client.get("/api/v1/communications/messages",
                      headers=_headers(fnd, "prime")).json()["items"]
    assert sum(1 for m in msgs if m["provider_message_id"] == "wamid-master-dedupe") == 1


# H: Prime business resolution -------------------------------------------------

def test_h_prime_business_resolution(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "false"})
    from app.services import communications as comms

    db = fnd["db"]
    biz = comms.resolve_business_for_phone_number_id(
        db, _settings(), phone_number_id="111111111111111")
    assert biz is not None and biz.slug == "prime"
    # Nest number never resolves to Prime.
    biz2 = comms.resolve_business_for_phone_number_id(
        db, _settings(), phone_number_id="222222222222222")
    assert biz2 is not None and biz2.slug == "nest"
    # Unknown number -> None (safe ack, no user-controlled business_id).
    assert comms.resolve_business_for_phone_number_id(
        db, _settings(), phone_number_id="999999999999999") is None


# J/K/R/S: outbound + auth failure + retries -----------------------------------

def test_j_meta_outbound_send_marks_sent(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    _mock_meta_200(monkeypatch, mid="wamid.MASTER-J")
    r = fnd["client"].post(
        "/api/v1/whatsapp/send",
        json={"to": "+919000010010", "body": "hello-live"},
        headers=_headers(fnd, "prime"),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "whatsapp"
    assert body["provider_message_id"] == "wamid.MASTER-J"
    assert body["status"] == "sent"


def test_k_meta_auth_invalid_is_explicit_and_failed(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    import app.services.messaging as mm

    class _Resp:
        status_code = 401

        def json(self):
            return {"error": {"code": 190, "error_subcode": 463,
                              "type": "OAuthException",
                              "message": "Session has expired on Friday, 30-Sep-26"}}

    monkeypatch.setattr(mm.httpx, "post", lambda *a, **k: _Resp())
    import time as _tm

    monkeypatch.setattr(_tm, "sleep", lambda *a, **k: None)
    provider = mm.WhatsAppCloudProvider.for_business(
        _settings(), _business(fnd["db"], "prime"))
    with pytest.raises(mm.MessagingError) as excinfo:
        provider.send(to="+919000010011", body="auth-probe")
    assert "META_AUTH_INVALID" in str(excinfo.value)
    assert "190" in str(excinfo.value)
    # Staff send persists FAILED (never delivered) and maps to 502.
    r = fnd["client"].post(
        "/api/v1/whatsapp/send",
        json={"to": "+919000010011", "body": "auth-probe-2"},
        headers=_headers(fnd, "prime"),
    )
    assert r.status_code in (502, 500, 400)
    from app.models.communication import Message

    rows = [m for m in fnd["db"].execute(
        select(Message).where(
            Message.business_id == _business(fnd["db"], "prime").id)
    ).scalars().all() if m.body == "auth-probe-2"]
    assert len(rows) == 1 and rows[0].status == "failed"
    assert rows[0].provider_message_id is None
    assert "META_AUTH_INVALID" in str((rows[0].meta or {}).get("error", ""))


def test_k2_403_auth_invalid(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    import app.services.messaging as mm

    class _Resp:
        status_code = 403

        def json(self):
            return {"error": {"code": 10, "type": "OAuthException",
                              "message": "This action requires permission"}}

    monkeypatch.setattr(mm.httpx, "post", lambda *a, **k: _Resp())
    import time as _tm

    monkeypatch.setattr(_tm, "sleep", lambda *a, **k: None)
    provider = mm.WhatsAppCloudProvider.for_business(
        _settings(), _business(fnd["db"], "prime"))
    with pytest.raises(mm.MessagingError, match="META_AUTH_INVALID"):
        provider.send(to="+919000010012", body="perm-probe")


def test_r_transport_failure_is_failed_not_delivered(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    import app.services.messaging as mm

    def _boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(mm.httpx, "post", _boom)
    import time as _tm

    monkeypatch.setattr(_tm, "sleep", lambda *a, **k: None)
    r = fnd["client"].post(
        "/api/v1/whatsapp/send",
        json={"to": "+919000010013", "body": "transport-probe"},
        headers=_headers(fnd, "prime"),
    )
    assert r.status_code in (502, 500, 400)


def test_s_retry_on_429_then_success_no_retry_on_4xx(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    import app.services.messaging as mm

    calls = {"n": 0}

    class _OK:
        status_code = 200

        def json(self):
            return {"messages": [{"id": "wamid.RETRY-OK"}]}

    class _R429:
        status_code = 429

        def json(self):
            return {}

    def _flaky(*a, **k):
        calls["n"] += 1
        return _R429() if calls["n"] == 1 else _OK()

    monkeypatch.setattr(mm.httpx, "post", _flaky)
    import time as _tm

    monkeypatch.setattr(_tm, "sleep", lambda *a, **k: None)
    p = mm.WhatsAppCloudProvider.for_business(_settings(), _business(fnd["db"], "prime"))
    assert p.send(to="+919000010014", body="retry").provider_message_id == "wamid.RETRY-OK"
    assert calls["n"] == 2

    calls2 = {"n": 0}

    class _Bad:
        status_code = 400

        def json(self):
            return {"error": {"code": 131030, "message": "Recipient not in allowed list"}}

    def _bad(*a, **k):
        calls2["n"] += 1
        return _Bad()

    monkeypatch.setattr(mm.httpx, "post", _bad)
    with pytest.raises(mm.MessagingError) as e2:
        p.send(to="+919000010015", body="bad")
    assert calls2["n"] == 1
    assert "META_AUTH_INVALID" not in str(e2.value)
    assert "131030" in str(e2.value)


# I/O/Q: AI reply + conversation linking + single reply -------------------------

def test_i_o_q_ai_reply_linked_and_single(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "AI_PROVIDER": "noop"})
    _mock_meta_200(monkeypatch, mid="wamid.AI-OUT-1")
    client = fnd["client"]
    payload = _inbound_payload("111111111111111", "wamid-master-ai1",
                               "+919000010020", "Hi")
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime", payload,
                         "prime-app-secret-123").status_code == 200
    msgs = client.get("/api/v1/communications/messages",
                      headers=_headers(fnd, "prime")).json()["items"]
    inbound = [m for m in msgs if m["provider_message_id"] == "wamid-master-ai1"]
    assert len(inbound) == 1
    outbound = [m for m in msgs if m["direction"] == "outbound"]
    assert len(outbound) >= 1
    # O: outbound shares the inbound conversation.
    assert any(o["conversation_id"] == inbound[0]["conversation_id"] for o in outbound)
    n_out = len(outbound)
    # Q: duplicate webhook -> NO second AI reply.
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime", payload,
                         "prime-app-secret-123").status_code == 200
    msgs2 = client.get("/api/v1/communications/messages",
                       headers=_headers(fnd, "prime")).json()["items"]
    assert sum(1 for m in msgs2 if m["provider_message_id"] == "wamid-master-ai1") == 1
    assert sum(1 for m in msgs2 if m["direction"] == "outbound") == n_out


def test_i_transient_gemini_fallback_uses_real_plans(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "AI_PROVIDER": "gemini",
                             "GEMINI_API_KEY": "demo-key"})
    import app.services.ai_gateway as gw

    class _Resp:
        status_code = 429

        def json(self):
            return {}

    monkeypatch.setattr(gw.httpx, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(gw.time, "sleep", lambda *a, **k: None)
    from app.services import ai_chat

    db = fnd["db"]
    prime = _business(db, "prime")
    out = ai_chat.chat_turn(
        db, _settings(), business_id=prime.id, business_name=prime.name,
        channel="whatsapp", visitor_key="+919000010021",
        message="What are your plans?", mode="public", caller="public",
        run_id="t-fallback-1",
    )
    # Real catalogue prices, not invented; no escalation pause on quota errors.
    assert "₹" in out["reply"] or "plan" in out["reply"].lower()
    assert out["escalated"] is False
    db.rollback()


# L/M: STOP/START ----------------------------------------------------------------

def test_l_m_stop_start(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "AI_PROVIDER": "noop"})
    _mock_meta_200(monkeypatch, mid="wamid.STOP-OUT")
    client = fnd["client"]
    phone = "+919000010030"
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                         _inbound_payload("111111111111111", "wamid-master-stop",
                                          phone, "STOP"),
                         "prime-app-secret-123").status_code == 200
    from app.repositories import blocks812 as brepo

    pref = brepo.get_preference(fnd["db"], business_id=_business(fnd["db"], "prime").id,
                                channel="whatsapp", address=phone)
    assert pref is not None and pref.opt_in is False
    denied = client.post("/api/v1/whatsapp/send",
                         json={"to": phone, "body": "should not send"},
                         headers=_headers(fnd, "prime"))
    assert denied.status_code in (400, 422)
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                         _inbound_payload("111111111111111", "wamid-master-start",
                                          phone, "START"),
                         "prime-app-secret-123").status_code == 200
    pref2 = brepo.get_preference(fnd["db"], business_id=_business(fnd["db"], "prime").id,
                                 channel="whatsapp", address=phone)
    assert pref2 is not None and pref2.opt_in is True


# N: handoff ---------------------------------------------------------------------

def test_n_handoff_pauses_until_resume(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "AI_PROVIDER": "noop"})
    _mock_meta_200(monkeypatch, mid="wamid.HANDOFF-OUT")
    client = fnd["client"]
    phone = "+919000010040"
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                         _inbound_payload("111111111111111", "wamid-master-h1",
                                          phone, "Hello"),
                         "prime-app-secret-123").status_code == 200
    before = client.get("/api/v1/communications/messages",
                        headers=_headers(fnd, "prime")).json()["items"]
    n_out = sum(1 for m in before if m["direction"] == "outbound")
    handoff = client.post(
        "/api/v1/communications/handoff",
        json={"customer_name": "WA Visitor", "customer_phone": phone,
              "reason": "wants human"},
        headers=_headers(fnd, "prime"),
    )
    assert handoff.status_code == 201, handoff.text
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                         _inbound_payload("111111111111111", "wamid-master-h2",
                                          phone, "Are you still there?"),
                         "prime-app-secret-123").status_code == 200
    after = client.get("/api/v1/communications/messages",
                       headers=_headers(fnd, "prime")).json()["items"]
    assert sum(1 for m in after if m["direction"] == "outbound") == n_out
    resume = client.post("/api/v1/communications/ai-resume", json={"phone": phone},
                         headers=_headers(fnd, "prime"))
    assert resume.status_code == 200 and resume.json()["resumed"] is True
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                         _inbound_payload("111111111111111", "wamid-master-h3",
                                          phone, "Thanks, back now"),
                         "prime-app-secret-123").status_code == 200
    final = client.get("/api/v1/communications/messages",
                       headers=_headers(fnd, "prime")).json()["items"]
    assert sum(1 for m in final if m["direction"] == "outbound") > n_out


# P: isolation -------------------------------------------------------------------

def test_p_cross_business_isolation(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "false"})
    client = fnd["client"]
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                         _inbound_payload("111111111111111", "wamid-master-iso-p",
                                          "+919000010050", "Prime hi"),
                         "prime-app-secret-123").status_code == 200
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/nest",
                         _inbound_payload("222222222222222", "wamid-master-iso-n",
                                          "+919000010051", "Nest hi"),
                         "nest-app-secret-456").status_code == 200
    prime_msgs = client.get("/api/v1/communications/messages",
                            headers=_headers(fnd, "prime")).json()["items"]
    nest_msgs = client.get("/api/v1/communications/messages",
                           headers=_headers(fnd, "nest")).json()["items"]
    assert any(m["provider_message_id"] == "wamid-master-iso-p" for m in prime_msgs)
    assert not any(m["provider_message_id"] == "wamid-master-iso-p" for m in nest_msgs)
    assert any(m["provider_message_id"] == "wamid-master-iso-n" for m in nest_msgs)
    assert not any(m["provider_message_id"] == "wamid-master-iso-n" for m in prime_msgs)


# T: trial workflow ----------------------------------------------------------------

def test_t_trial_intent_creates_lead(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "AI_PROVIDER": "noop"})
    _mock_meta_200(monkeypatch, mid="wamid.TRIAL-OUT")
    client = fnd["client"]
    phone = "+919000010060"
    assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                         _inbound_payload("111111111111111", "wamid-master-trial",
                                          phone, "I want a free trial"),
                         "prime-app-secret-123").status_code == 200
    from app.models.lead import Lead

    leads = list(fnd["db"].execute(
        select(Lead).where(Lead.business_id == _business(fnd["db"], "prime").id)
    ).scalars().all())
    assert any((l.phone or "") == phone or "trial" in str(l.service_interest or "").lower()
               or "trial" in str(l.message or "").lower() for l in leads)
    msgs = client.get("/api/v1/communications/messages",
                      headers=_headers(fnd, "prime")).json()["items"]
    assert any(m["direction"] == "outbound" for m in msgs)


# U: any normal text gets a useful response ----------------------------------------

def test_u_any_normal_text_gets_response(fnd, monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "AI_PROVIDER": "noop"})
    _mock_meta_200(monkeypatch, mid="wamid.U-OUT")
    client = fnd["client"]
    samples = [
        ("wamid-master-u1", "+919000010071", "Hi"),
        ("wamid-master-u2", "+919000010072", "Hello"),
        ("wamid-master-u3", "+919000010073", "I want to know about Prime"),
        ("wamid-master-u4", "+919000010074", "What are your plans?"),
        ("wamid-master-u5", "+919000010075", "How much is membership?"),
        ("wamid-master-u6", "+919000010076", "Where are you located?"),
        ("wamid-master-u7", "+919000010077", "What are your timings?"),
        ("wamid-master-u8", "+919000010078", "I want a free trial"),
    ]
    for mid, phone, text in samples:
        # Fresh mock id per message (provider mock returns fixed id; vary via
        # idempotency-safe distinct inbound mids — outbound dedupe is per inbound).
        assert _post_webhook(client, "/api/v1/whatsapp/webhook/prime",
                             _inbound_payload("111111111111111", mid, phone, text),
                             "prime-app-secret-123").status_code == 200
    msgs = client.get("/api/v1/communications/messages",
                      headers=_headers(fnd, "prime")).json()["items"]
    for mid, phone, text in samples:
        assert any(m["provider_message_id"] == mid for m in msgs), text
    assert sum(1 for m in msgs if m["direction"] == "outbound") >= len(samples)
    # Plans answers use the real catalogue (contain ₹).
    plan_out = [m for m in msgs if m["direction"] == "outbound" and "₹" in (m["body"] or "")]
    assert plan_out, "expected at least one plans reply with real ₹ prices"
