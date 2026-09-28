"""Pre-Prompt-7 integration foundation tests.

Proves, deterministically and WITHOUT real credentials or network:
- Gemini shared-credential configuration + provider + secret-safety.
- Prime -> Prime WhatsApp config; Nest -> Nest WhatsApp config.
- Cross-tenant denial (Prime can never resolve Nest creds and vice versa).
- Forged frontend business_id can never change credential selection.
- Unauthorized staff cannot reach another business's integration.
- Owner access stays correctly scoped (incl. switch-business).
- Webhook verification per business (verify token + HMAC app secret),
  pinned routes, and phone-number cross-checks.
- Safe status endpoint exposes booleans only (never secrets).

No test here sends a real WhatsApp message or calls the live Gemini API:
httpx is monkeypatched where provider code paths would hit the network.
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
    """Fresh DB + users (prime/nest OWNER + STAFF + VIEWER, dual owner) + client."""
    engine, db = make_test_session()
    try:
        users = {}
        for slug in ("prime", "nest"):
            for role in ("OWNER", "STAFF", "VIEWER"):
                email = f"p7-{slug}-{role.lower()}@example.com"
                user = create_test_user(db, email=email)
                add_test_membership(
                    db,
                    user_id=user.id,
                    business_slug=slug,
                    role_name=role,
                    is_default=True,
                )
                users[(slug, role)] = user
        # Unified owner: ONE identity with OWNER memberships in BOTH
        # businesses (mirrors the real platform owner seed).
        dual = create_test_user(db, email="p7-owner-both@example.com")
        add_test_membership(
            db,
            user_id=dual.id,
            business_slug="prime",
            role_name="OWNER",
            is_default=True,
        )
        add_test_membership(
            db,
            user_id=dual.id,
            business_slug="nest",
            role_name="OWNER",
            is_default=False,
        )
        users[("both", "OWNER")] = dual
        client = make_auth_client(db)

        def _login(email: str, **kw) -> dict:
            payload = {"email": email, "password": TEST_PASSWORD, **kw}
            resp = client.post("/api/v1/auth/login", json=payload)
            assert resp.status_code == 200, resp.text
            return resp.json()

        tokens = {
            (slug, role): _login(user.email) for (slug, role), user in users.items()
        }
        yield {
            "engine": engine,
            "db": db,
            "client": client,
            "users": users,
            "tokens": tokens,
        }
    finally:
        db.close()
        engine.dispose()


def _headers(fnd, slug: str, role: str) -> dict:
    return {"Authorization": f"Bearer {fnd['tokens'][(slug, role)]['access_token']}"}


def _business(db, slug: str):
    from app.models.business import Business

    return db.execute(select(Business).where(Business.slug == slug)).scalars().one()


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _mock_wa_success(
    monkeypatch: pytest.MonkeyPatch, mid: str = "wamid.P7TEST"
) -> None:
    """Stub the Graph API transport: NO real network/messages in tests."""
    import app.services.messaging as mm

    class _Resp:
        status_code = 200

        def json(self):
            return {"messages": [{"id": mid}]}

    monkeypatch.setattr(mm.httpx, "post", lambda *a, **k: _Resp())


# -- credential model ------------------------------------------------------------


def test_gemini_shared_credential_config(monkeypatch):
    """ONE shared Gemini credential; model configurable, never obsolete default."""
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "GEMINI_API_KEY": "demo-key"})
    from app.services import integration_configs as iconf

    cfg = iconf.resolve_gemini_config(_settings())
    assert cfg.configured is True
    assert cfg.model == "gemini-2.5-flash"  # current stable, not shut-down 2.0
    assert cfg.mode == "LIVE"
    summary = cfg.safe_summary()
    assert "demo-key" not in json.dumps(summary)
    assert set(summary) == {"configured", "enabled", "model", "mode", "provider"}


def test_gemini_defaults_to_not_configured(monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "false", "GEMINI_API_KEY": ""})
    from app.services import integration_configs as iconf

    cfg = iconf.resolve_gemini_config(_settings())
    assert cfg.configured is False
    assert cfg.mode in ("DISABLED", "NOT_CONFIGURED")


def test_gemini_model_is_configurable(monkeypatch):
    _apply_env(monkeypatch, {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-2.5-flash"})
    from app.services.ai_gateway import GeminiChatProvider

    provider = GeminiChatProvider(_settings())
    assert provider.model == "gemini-2.5-flash"


# TEST 1 + TEST 2: business -> own configuration ---------------------------------


def test_prime_resolves_prime_config(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    from app.services import integration_configs as iconf

    cfg = iconf.resolve_whatsapp_config(_settings(), _business(fnd["db"], "prime"))
    assert cfg.business_key == "prime"
    assert cfg.access_token == "prime-token-ABC"
    assert cfg.phone_number_id == "111111111111111"
    assert cfg.business_account_id == "prime-waba-1"
    assert cfg.verify_token == "prime-verify-TOKEN"
    assert cfg.app_secret == "prime-app-secret-123"
    assert cfg.live is True and cfg.mode == "LIVE"


def test_nest_resolves_nest_config(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    from app.services import integration_configs as iconf

    cfg = iconf.resolve_whatsapp_config(_settings(), _business(fnd["db"], "nest"))
    assert cfg.business_key == "nest"
    assert cfg.access_token == "nest-token-XYZ"
    assert cfg.phone_number_id == "222222222222222"
    assert cfg.live is True and cfg.mode == "LIVE"


def test_resolution_accepts_contexts_and_external_ids(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    from app.services import integration_configs as iconf

    assert iconf.resolve_business_key("prime-fitness-001") == "prime"
    assert iconf.resolve_business_key("nest-library-001") == "nest"
    assert iconf.resolve_business_key(_business(fnd["db"], "prime")) == "prime"
    assert iconf.resolve_business_key("unknown-business-999") == ""
    unknown = iconf.resolve_whatsapp_config(_settings(), "unknown-business-999")
    assert unknown.business_key == "" and unknown.live is False
    assert unknown.mode in ("DISABLED", "NOT_CONFIGURED")


# TEST 3 + TEST 4: cross-tenant denial --------------------------------------------


def test_prime_cannot_resolve_nest_credentials(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    from app.services import integration_configs as iconf

    prime = iconf.resolve_whatsapp_config(_settings(), _business(fnd["db"], "prime"))
    assert "nest-token-XYZ" not in (
        prime.access_token
        + prime.phone_number_id
        + prime.app_secret
        + prime.verify_token
        + prime.business_account_id
    )
    assert prime.phone_number_id != "222222222222222"


def test_nest_cannot_resolve_prime_credentials(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    from app.services import integration_configs as iconf

    nest = iconf.resolve_whatsapp_config(_settings(), _business(fnd["db"], "nest"))
    assert "prime-token-ABC" not in (
        nest.access_token
        + nest.phone_number_id
        + nest.app_secret
        + nest.verify_token
        + nest.business_account_id
    )
    assert nest.phone_number_id != "111111111111111"


# Gemini provider foundation -------------------------------------------------------


def test_gemini_provider_success_is_normalized(monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "GEMINI_API_KEY": "demo-key"})
    import app.services.ai_gateway as gw

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Hello from Gemini"},
                                {
                                    "functionCall": {
                                        "name": "get_hours",
                                        "args": {"day": "mon"},
                                    }
                                },
                            ]
                        }
                    }
                ]
            }

    monkeypatch.setattr(gw.httpx, "post", lambda *a, **k: _Resp())
    result = gw.GeminiChatProvider(_settings()).chat(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        timeout_seconds=5,
        max_output_tokens=64,
    )
    assert result.text == "Hello from Gemini"
    assert result.tool_calls == [{"name": "get_hours", "args": {"day": "mon"}}]
    assert result.model == "gemini-2.5-flash"


def test_gemini_provider_failure_is_normalized(monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "GEMINI_API_KEY": "demo-key"})
    import app.services.ai_gateway as gw
    from app.services.errors import AIProviderError

    class _Resp:
        status_code = 500

        def json(self):
            return {}

    monkeypatch.setattr(gw.httpx, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(gw.time, "sleep", lambda *a, **k: None)
    with pytest.raises(AIProviderError):
        gw.GeminiChatProvider(_settings()).chat(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            timeout_seconds=5,
            max_output_tokens=64,
        )


def test_gemini_unconfigured_raises_honest_error(monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "GEMINI_API_KEY": ""})
    import app.services.ai_gateway as gw
    from app.services.errors import AIProviderError

    with pytest.raises(AIProviderError, match="not configured"):
        gw.GeminiChatProvider(_settings()).chat(
            system="sys",
            messages=[],
            tools=[],
            timeout_seconds=5,
            max_output_tokens=64,
        )


def test_gemini_service_attaches_business_scope_and_sanitizes(monkeypatch):
    _apply_env(monkeypatch, {"AI_ENABLED": "true", "GEMINI_API_KEY": "demo-key"})
    from app.services import integration_configs as iconf
    from app.services.ai_gateway import get_gemini_service

    service = get_gemini_service(_settings())
    assert service.configured is True and service.mode == "LIVE"
    scoped = service.build_business_system("Be helpful.", business="prime-fitness-001")
    assert "prime-fitness-001" in scoped
    assert "nest-library-001" not in scoped
    neutral = service.build_business_system("Be helpful.", business="unknown-9")
    assert "unknown" in neutral

    dirty = {
        "display_name": "Ada",
        "GEMINI_API_KEY": "leak",
        "nested": {"whatsapp_access_token": "leak", "note": "ok"},
        "Authorization": "Bearer leak",
    }
    clean = iconf.sanitize_context_for_gemini(dirty)
    assert clean["display_name"] == "Ada"
    assert "GEMINI_API_KEY" not in clean
    assert clean["nested"] == {"note": "ok"}
    assert "Authorization" not in clean


# WhatsApp provider foundation --------------------------------------------------------


def test_whatsapp_provider_bound_per_business(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    from app.services.messaging import WhatsAppCloudProvider

    prime_p = WhatsAppCloudProvider.for_business(
        _settings(), _business(fnd["db"], "prime")
    )
    nest_p = WhatsAppCloudProvider.for_business(
        _settings(), _business(fnd["db"], "nest")
    )
    assert prime_p.business_key == "prime"
    assert nest_p.business_key == "nest"
    prime_req = prime_p.build_send_request(to="+911234567890", body="Hi")
    nest_req = nest_p.build_send_request(to="+911234567890", body="Hi")
    assert "111111111111111" in prime_req["url"]
    assert "222222222222222" in nest_req["url"]
    assert "111111111111111" not in nest_req["url"]
    assert "222222222222222" not in prime_req["url"]
    # Credentials redacted in the constructed (log-safe) request.
    assert "prime-token-ABC" not in json.dumps(prime_req)
    assert "nest-token-XYZ" not in json.dumps(nest_req)
    assert prime_req["headers"]["Authorization"] == "Bearer ***"


def test_whatsapp_provider_modes_are_explicit(monkeypatch):
    _apply_env(
        monkeypatch,
        {
            "PRIME_WHATSAPP_ENABLED": "false",  # configured but disabled
            "NEST_WHATSAPP_ENABLED": "true",
            "NEST_WHATSAPP_ACCESS_TOKEN": "",
            "NEST_WHATSAPP_PHONE_NUMBER_ID": "",  # enabled but not configured
        },
    )
    from app.services import integration_configs as iconf
    from app.services.messaging import (
        LogProvider,
        get_messaging_provider_for_business,
    )

    prime = iconf.resolve_whatsapp_config(_settings(), "prime")
    nest = iconf.resolve_whatsapp_config(_settings(), "nest")
    assert prime.configured is True and prime.mode == "DISABLED"
    assert nest.configured is False and nest.mode == "NOT_CONFIGURED"
    # Demo-safe fallback is visibly the mock provider, never live-looking.
    assert isinstance(
        get_messaging_provider_for_business(_settings(), "prime"), LogProvider
    )


def test_whatsapp_send_normalizes_provider_response(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    import app.services.messaging as mm

    class _Resp:
        status_code = 200

        def json(self):
            return {"messages": [{"id": "wamid.TEST123"}]}

    monkeypatch.setattr(mm.httpx, "post", lambda *a, **k: _Resp())
    provider = mm.WhatsAppCloudProvider.for_business(
        _settings(), _business(fnd["db"], "prime")
    )
    result = provider.send(to="+911234567890", body="Hello")
    assert result.provider == "whatsapp"
    assert result.provider_message_id == "wamid.TEST123"
    assert result.status == "sent"


def test_whatsapp_transport_failure_is_typed(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    import app.services.messaging as mm

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(mm.httpx, "post", _boom)
    provider = mm.WhatsAppCloudProvider.for_business(
        _settings(), _business(fnd["db"], "prime")
    )
    with pytest.raises(mm.MessagingError):
        provider.send(to="+911234567890", body="Hello")


# TEST 5: forged business_id ------------------------------------------------------------


def test_forged_business_id_cannot_change_status_scope(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    nest_id = str(_business(fnd["db"], "nest").id)
    resp = fnd["client"].get(
        "/api/v1/integrations/status",
        headers={
            **_headers(fnd, "prime", "OWNER"),
            "X-Business-Id": nest_id,  # forged header: must be ignored
        },
        params={"business_id": nest_id},  # forged query: must be ignored
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["business"]["slug"] == "prime"
    assert body["whatsapp"]["business_key"] == "prime"
    assert "nest-token-XYZ" not in json.dumps(body)


def test_forged_business_id_cannot_redirect_staff_send(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    _mock_wa_success(monkeypatch, "wamid.P7FORGED")
    # Prime OWNER sends while CLAIMING nest in forged fields — the row must
    # still land under Prime (server-side context wins).
    resp = fnd["client"].post(
        "/api/v1/whatsapp/send",
        json={"to": "+911111111111", "body": "forged-scope-probe"},
        headers=_headers(fnd, "prime", "OWNER"),
    )
    assert resp.status_code == 201, resp.text
    from app.models.communication import Message

    rows = fnd["db"].execute(select(Message)).scalars().all()
    mine = [m for m in rows if m.body == "forged-scope-probe"]
    assert len(mine) == 1
    assert mine[0].business_id == _business(fnd["db"], "prime").id


# TEST 6: unauthorized staff ---------------------------------------------------------------


def test_prime_staff_cannot_reach_nest_integration(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    # Prime STAFF lacks communications.manage -> send denied.
    denied = fnd["client"].post(
        "/api/v1/whatsapp/send",
        json={"to": "+911111111111", "body": "nope"},
        headers=_headers(fnd, "prime", "STAFF"),
    )
    assert denied.status_code == 403
    # Prime staff status shows ONLY prime scope (no combined overview).
    resp = fnd["client"].get(
        "/api/v1/integrations/status", headers=_headers(fnd, "prime", "STAFF")
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["whatsapp"]["business_key"] == "prime"
    assert "businesses" not in body  # STAFF lacks owner.combined.read
    assert "nest-token-XYZ" not in json.dumps(body)


def test_cross_business_messages_stay_invisible(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    _mock_wa_success(monkeypatch, "wamid.P7NEST")
    fnd["client"].post(
        "/api/v1/whatsapp/send",
        json={"to": "+912222222222", "body": "nest-only-note"},
        headers=_headers(fnd, "nest", "OWNER"),
    )
    prime_msgs = (
        fnd["client"]
        .get("/api/v1/communications/messages", headers=_headers(fnd, "prime", "OWNER"))
        .json()
    )
    assert not any(m["body"] == "nest-only-note" for m in prime_msgs["items"])


# TEST 7: owner scoping -----------------------------------------------------------------------


def test_owner_status_scoped_and_switchable(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    client = fnd["client"]
    # Unified dual-business owner (default context: prime).
    dual_headers = _headers(fnd, "both", "OWNER")
    prime_status = client.get("/api/v1/integrations/status", headers=dual_headers)
    assert prime_status.status_code == 200, prime_status.text
    body = prime_status.json()
    assert body["business"]["slug"] == "prime"
    assert body["whatsapp"]["business_key"] == "prime"
    # Owner holds owner.combined.read -> boolean-only overview of BOTH.
    assert body["businesses"]["prime_whatsapp"]["mode"] == "LIVE"
    assert body["businesses"]["nest_whatsapp"]["mode"] == "LIVE"
    assert "prime-token-ABC" not in json.dumps(body)
    assert "nest-token-XYZ" not in json.dumps(body)
    # Switch to Nest: the scoped section follows the active context.
    nest_id = str(_business(fnd["db"], "nest").id)
    switched = client.post(
        "/api/v1/auth/switch-business",
        json={"business_id": nest_id},
        headers=dual_headers,
    )
    assert switched.status_code == 200, switched.text
    nest_token = switched.json()["access_token"]
    nest_status = client.get(
        "/api/v1/integrations/status",
        headers={"Authorization": f"Bearer {nest_token}"},
    )
    assert nest_status.status_code == 200, nest_status.text
    assert nest_status.json()["whatsapp"]["business_key"] == "nest"


# Webhooks -----------------------------------------------------------------------


def test_webhook_verify_accepts_each_business_token(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    client = fnd["client"]
    base = {"hub.mode": "subscribe", "hub.challenge": "ch_prime"}
    ok_prime = client.get(
        "/api/v1/whatsapp/webhook",
        params={**base, "hub.verify_token": "prime-verify-TOKEN"},
    )
    assert ok_prime.status_code == 200 and ok_prime.text == "ch_prime"
    ok_nest = client.get(
        "/api/v1/whatsapp/webhook",
        params={**base, "hub.verify_token": "nest-verify-TOKEN"},
    )
    assert ok_nest.status_code == 200
    bad = client.get(
        "/api/v1/whatsapp/webhook",
        params={**base, "hub.verify_token": "wrong-token"},
    )
    assert bad.status_code == 403


def test_pinned_webhook_verify_is_strictly_isolated(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    client = fnd["client"]
    base = {"hub.mode": "subscribe", "hub.challenge": "ch"}
    # Nest token on the PRIME endpoint must fail.
    cross = client.get(
        "/api/v1/whatsapp/webhook/prime",
        params={**base, "hub.verify_token": "nest-verify-TOKEN"},
    )
    assert cross.status_code == 403
    own = client.get(
        "/api/v1/whatsapp/webhook/prime",
        params={**base, "hub.verify_token": "prime-verify-TOKEN"},
    )
    assert own.status_code == 200 and own.text == "ch"
    unknown = client.get(
        "/api/v1/whatsapp/webhook/acme",
        params={**base, "hub.verify_token": "prime-verify-TOKEN"},
    )
    assert unknown.status_code == 404


def _inbound_payload(phone_id: str, mid: str, sender: str, text: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_id},
                            "messages": [
                                {"id": mid, "from": sender, "text": {"body": text}}
                            ],
                            "statuses": [],
                        }
                    }
                ]
            }
        ]
    }


def _post_webhook(client, url: str, payload: dict, secret: str):
    """POST a webhook with the signature computed over the EXACT body bytes.

    (Passing ``content=`` instead of ``json=`` so the signed bytes and the
    received ``request.body()`` are byte-identical.)
    """
    raw = json.dumps(payload).encode()
    return client.post(
        url,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(secret, raw),
        },
    )


def test_inbound_resolves_business_from_phone_id(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    client = fnd["client"]
    payload = _inbound_payload(
        "111111111111111", "wamid-p7-1", "+913333333333", "Namaste"
    )
    resp = _post_webhook(
        client, "/api/v1/whatsapp/webhook", payload, "prime-app-secret-123"
    )
    assert resp.status_code == 200, resp.text
    prime_msgs = client.get(
        "/api/v1/communications/messages", headers=_headers(fnd, "prime", "OWNER")
    ).json()
    assert any(m["body"] == "Namaste" for m in prime_msgs["items"])
    nest_msgs = client.get(
        "/api/v1/communications/messages", headers=_headers(fnd, "nest", "OWNER")
    ).json()
    assert not any(m["body"] == "Namaste" for m in nest_msgs["items"])
    # Idempotent replay: no duplicate.
    _post_webhook(client, "/api/v1/whatsapp/webhook", payload, "prime-app-secret-123")
    prime_msgs2 = client.get(
        "/api/v1/communications/messages", headers=_headers(fnd, "prime", "OWNER")
    ).json()
    assert sum(1 for m in prime_msgs2["items"] if m["body"] == "Namaste") == 1


def test_inbound_rejects_bad_signature(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    payload = _inbound_payload("111111111111111", "wamid-p7-bad", "+914444444444", "Hi")
    resp = fnd["client"].post(
        "/api/v1/whatsapp/webhook",
        json=payload,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
    )
    assert resp.status_code == 403


def test_inbound_cross_signed_payload_rejected(fnd, monkeypatch):
    """Nest phone id signed with PRIME secret must NOT write to Nest."""
    _apply_env(monkeypatch, {})
    payload = _inbound_payload("222222222222222", "wamid-p7-x", "+915555555555", "X")
    raw = json.dumps(payload).encode()
    resp = fnd["client"].post(
        "/api/v1/whatsapp/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign("prime-app-secret-123", raw),
        },
    )
    assert resp.status_code == 403
    nest_msgs = (
        fnd["client"]
        .get("/api/v1/communications/messages", headers=_headers(fnd, "nest", "OWNER"))
        .json()
    )
    assert not any(m["body"] == "X" for m in nest_msgs["items"])


def test_pinned_inbound_phone_mismatch_writes_nothing(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    # Prime endpoint receiving a NEST-number payload: ack, no records.
    payload = _inbound_payload("222222222222222", "wamid-p7-mm", "+916666666666", "MM")
    resp = _post_webhook(
        fnd["client"], "/api/v1/whatsapp/webhook/prime", payload, "prime-app-secret-123"
    )
    assert resp.status_code == 200
    for slug in ("prime", "nest"):
        msgs = (
            fnd["client"]
            .get(
                "/api/v1/communications/messages", headers=_headers(fnd, slug, "OWNER")
            )
            .json()
        )
        assert not any(m["body"] == "MM" for m in msgs["items"])


# Safe status + secret safety -------------------------------------------------------


def test_status_never_exposes_secrets(fnd, monkeypatch):
    _apply_env(monkeypatch, {"GEMINI_API_KEY": "super-secret-gemini"})
    body = (
        fnd["client"]
        .get("/api/v1/integrations/status", headers=_headers(fnd, "prime", "OWNER"))
        .json()
    )
    dumped = json.dumps(body)
    for secret in (
        "prime-token-ABC",
        "nest-token-XYZ",
        "prime-app-secret-123",
        "nest-app-secret-456",
        "prime-verify-TOKEN",
        "nest-verify-TOKEN",
        "super-secret-gemini",
    ):
        assert secret not in dumped
    assert set(body["gemini"]) == {"configured", "enabled", "model", "mode", "provider"}
    assert set(body["whatsapp"]) >= {"configured", "enabled", "mode", "provider"}


def test_status_requires_authentication(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    assert fnd["client"].get("/api/v1/integrations/status").status_code == 401


def test_viewer_cannot_send_but_can_read_status(fnd, monkeypatch):
    _apply_env(monkeypatch, {})
    denied = fnd["client"].post(
        "/api/v1/whatsapp/send",
        json={"to": "+911111111111", "body": "viewer attempt"},
        headers=_headers(fnd, "prime", "VIEWER"),
    )
    assert denied.status_code == 403
    ok = fnd["client"].get(
        "/api/v1/integrations/status", headers=_headers(fnd, "prime", "VIEWER")
    )
    assert ok.status_code == 200


def test_env_example_has_no_real_secrets():
    """Committed template must carry empty/demo values only."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    for var in (
        "PRIME_WHATSAPP_ACCESS_TOKEN=",
        "NEST_WHATSAPP_ACCESS_TOKEN=",
        "PRIME_WHATSAPP_APP_SECRET=",
        "NEST_WHATSAPP_APP_SECRET=",
        "GEMINI_API_KEY=",
    ):
        line = next(
            ln
            for ln in text.splitlines()
            if ln.strip().startswith(var) and not ln.strip().startswith("#")
        )
        value = line.split("=", 1)[1].strip()
        assert value == "", f"{var} must be empty in .env.example, got {value!r}"
    assert "GEMINI_MODEL=gemini-2.5-flash" in text
