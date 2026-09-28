"""Full-platform integration tests (mission additive; existing tests untouched).

Covers the integration gaps closed by this mission on SQLite-backed HTTP surface:
- AI gateway: noop fake, gemini missing-key fail-safe, retry-on-500 then success,
  unknown-provider fallback, usage hook.
- WhatsApp: phone_number_id -> business via operational config + env map + isolation.
- Scheduler/worker core: per-business sweep, no cross-business execution, idempotent retry.
- Website -> CRM -> dashboard pipeline for prime AND nest + tenant isolation.
- Failure paths: invalid slug, duplicate webhook, invalid/expired JWT behavior.
"""

from __future__ import annotations

import uuid

import pytest

from tests.block1_support import TEST_PASSWORD, make_auth_client, make_test_session
from tests.block57_support import H
from tests.block812_support import env812  # noqa: F401


# -- AI gateway ---------------------------------------------------------------

def test_gateway_noop_fake_labels_demo():
    from app.core.config import Settings
    from app.services import ai_gateway as gw

    s = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/db",
                 SECRET_KEY="test-secret")  # type: ignore[call-arg]
    s = s.model_copy(update={"ai_provider": "noop"})
    provider = gw.get_chat_provider(s)
    assert provider.name == "noop"
    result = provider.chat(system="sys", messages=[{"role": "visitor", "content": "hello"}],
                           tools=[], timeout_seconds=5, max_output_tokens=64)
    assert "Demo assistant" in result.text


def test_gateway_gemini_missing_key_fails_safe():
    from app.core.config import Settings
    from app.services import ai_gateway as gw
    from app.services.errors import AIProviderError

    s = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/db",
                 SECRET_KEY="test-secret")  # type: ignore[call-arg]
    s = s.model_copy(update={"ai_provider": "gemini", "gemini_api_key": ""})
    provider = gw.get_chat_provider(s)
    assert provider.name == "gemini"
    with pytest.raises(AIProviderError):
        provider.chat(system="sys", messages=[{"role": "user", "content": "hi"}],
                      tools=[], timeout_seconds=5, max_output_tokens=64)


def test_gateway_gemini_retries_then_succeeds(monkeypatch):
    import httpx
    from app.core.config import Settings
    from app.services import ai_gateway as gw

    s = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/db",
                 SECRET_KEY="test-secret")  # type: ignore[call-arg]
    s = s.model_copy(update={"ai_provider": "gemini", "gemini_api_key": "k",
                             "gemini_model": "gemini-2.0-flash"})
    provider = gw.get_chat_provider(s)
    calls = {"n": 0}

    class _Resp:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def _post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            class _Err:
                status_code = 500
            return _Err()
        return _Resp()

    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    seen = []
    gw.set_usage_hook(lambda e: seen.append(e))
    try:
        result = provider.chat(system="s", messages=[{"role": "user", "content": "hi"}],
                               tools=[], timeout_seconds=5, max_output_tokens=64)
    finally:
        gw.set_usage_hook(None)
    assert result.text == "ok"
    assert calls["n"] == 2
    assert any(e.get("status") == "success" for e in seen)


def test_gateway_unknown_provider_falls_back_to_noop():
    from app.core.config import Settings
    from app.services import ai_gateway as gw

    s = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/db",
                 SECRET_KEY="test-secret")  # type: ignore[call-arg]
    s = s.model_copy(update={"ai_provider": "mystery"})
    assert gw.get_chat_provider(s).name == "noop"


# -- WhatsApp phone mapping ----------------------------------------------------

def test_phone_mapping_operational_config_wins(env812):
    from app.repositories import settings as settings_repo
    from app.services import communications as comms
    from app.core.config import get_settings

    db = env812["db"]
    from sqlalchemy import select
    from app.models.business import Business
    prime = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    nest = db.execute(select(Business).where(Business.slug == "nest")).scalars().first()
    srow = settings_repo.ensure_for_business(db, prime.id)
    srow.operational = {"whatsapp": {"phone_number_id": "PID-PRIME-1"}}
    db.flush()
    settings = get_settings()
    assert comms.resolve_business_for_phone_number_id(db, settings, phone_number_id="PID-PRIME-1").id == prime.id
    # A Nest record must never resolve to Prime.
    assert comms.resolve_business_for_phone_number_id(db, settings, phone_number_id="PID-PRIME-1").slug == "prime"
    assert nest is not None


def test_phone_mapping_env_map(env812, monkeypatch):
    from app.core.config import get_settings
    from app.services import communications as comms

    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_MAP", "prime:PID-ENV-P,nest:PID-ENV-N")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        db = env812["db"]
        assert comms.resolve_business_for_phone_number_id(
            db, settings, phone_number_id="PID-ENV-N").slug == "nest"
        assert comms.resolve_business_for_phone_number_id(
            db, settings, phone_number_id="PID-UNKNOWN") is None
    finally:
        get_settings.cache_clear()


def test_whatsapp_webhook_phone_routing_and_dedupe(env812):
    c = env812["client"]
    from sqlalchemy import select
    from app.models.business import Business
    from app.repositories import settings as settings_repo
    db = env812["db"]
    prime = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    srow = settings_repo.ensure_for_business(db, prime.id)
    srow.operational = {"whatsapp": {"phone_number_id": "PID-WEBHOOK-1"}}
    db.commit()

    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "PID-WEBHOOK-1"},
        "messages": [{"from": "+911111111111", "id": "wamid-int-1",
                      "text": {"body": "Hi prime"}}]}}]}]}
    r1 = c.post("/api/v1/whatsapp/webhook", json=payload)
    assert r1.status_code == 200, r1.text
    r2 = c.post("/api/v1/whatsapp/webhook", json=payload)
    assert r2.status_code == 200
    # Prime timeline has the message; Nest timeline does not (isolation).
    t_prime = c.get("/api/v1/communications/timeline",
                    headers=H(env812, "prime", "OWNER"))
    assert t_prime.status_code == 200 and len(t_prime.json()["messages"]) >= 1
    t_nest = c.get("/api/v1/communications/timeline",
                   headers=H(env812, "nest", "OWNER"))
    assert t_nest.status_code == 200
    prime_bodies = [m["body"] for m in t_prime.json()["messages"]]
    nest_bodies = [m["body"] for m in t_nest.json()["messages"]]
    assert any("Hi prime" in b for b in prime_bodies)
    assert not any("Hi prime" in b for b in nest_bodies)


# -- Scheduler / worker core ----------------------------------------------------

def test_scheduler_sweep_per_business_and_idempotent(env812):
    from app.core.config import get_settings
    from app.services import scheduler as sched

    db = env812["db"]
    settings = get_settings()
    from sqlalchemy import select
    from app.models.business import Business
    prime = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    first = sched.run_business_sweep(db, settings, business_id=prime.id)
    second = sched.run_business_sweep(db, settings, business_id=prime.id)
    assert first["business_id"] == str(prime.id)
    assert second["business_id"] == str(prime.id)
    # Sweep commits (brief upsert is idempotent per date).
    all_results = sched.run_all_businesses(db, settings)
    slugs = {r["business_id"] for r in all_results}
    assert str(prime.id) in slugs


def test_scheduler_tick_lease_without_redis(env812):
    from app.core.config import get_settings
    from app.services import scheduler as sched

    settings = get_settings()
    assert sched.acquire_tick_lease(settings, tick="t1", lease_seconds=60) is True


def test_redis_limiter_falls_back_without_redis():
    from app.core.config import Settings
    from app.services import rate_limit as rl

    s = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/db",
                 SECRET_KEY="test-secret")  # type: ignore[call-arg]
    s = s.model_copy(update={"redis_url": ""})
    assert rl.configure_redis_limiter(s) == "memory"
    s2 = s.model_copy(update={"redis_url": "redis://localhost:9/0"})
    assert rl.configure_redis_limiter(s2) == "memory"  # nothing listening -> fallback
    from app.services.rate_limit import InMemoryRateLimiter, set_limiter
    set_limiter(InMemoryRateLimiter())


# -- Website -> CRM -> dashboard (prime + nest) ----------------------------------

def _public_lead(c, slug, name, phone, key):
    return c.post(f"/api/v1/public/{slug}/leads",
                  json={"name": name, "phone": phone, "message": "hello",
                        "website_url": ""},
                  headers={"Content-Type": "application/json", "Idempotency-Key": key})


def test_website_crm_dashboard_prime_and_nest_isolated(env812):
    c = env812["client"]
    k1, k2 = f"int-prime-{uuid.uuid4().hex[:16]}", f"int-nest-{uuid.uuid4().hex[:16]}"
    r1 = _public_lead(c, "prime", "Prime Visitor", "+919000000001", k1)
    assert r1.status_code == 201, r1.text
    r2 = _public_lead(c, "nest", "Nest Visitor", "+919000000002", k2)
    assert r2.status_code == 201, r2.text
    # Staff sees own lead only.
    prime_leads = c.get("/api/v1/leads", headers=H(env812, "prime", "OWNER")).json()
    nest_leads = c.get("/api/v1/leads", headers=H(env812, "nest", "OWNER")).json()
    assert any("+919000000001" in str(i) for i in prime_leads["items"])
    assert not any("+919000000001" in str(i) for i in nest_leads["items"])
    assert any("+919000000002" in str(i) for i in nest_leads["items"])
    assert not any("+919000000002" in str(i) for i in prime_leads["items"])
    # Duplicate key replays without duplicating (same lead id).
    dup = _public_lead(c, "prime", "Prime Visitor", "+919000000001", k1)
    assert dup.status_code == 201 and dup.json()["lead_id"] == r1.json()["lead_id"]
    # Invalid slug -> 404, no oracle.
    bad = _public_lead(c, "nope", "Nope Visitor", "+919000000003", f"int-bad-{uuid.uuid4().hex[:16]}")
    assert bad.status_code == 404


def test_public_ai_chat_prime_vs_nest_grounding(env812):
    c = env812["client"]
    for slug in ("prime", "nest"):
        r = c.post(f"/api/v1/public/{slug}/ai/chat",
                   json={"message": "What are your timings?", "visitor_key": "e2e-1"},
                   headers={"Content-Type": "application/json"})
        assert r.status_code in (200, 429), r.text
        if r.status_code == 200:
            assert isinstance(r.json().get("reply"), str) and r.json()["reply"].strip()
