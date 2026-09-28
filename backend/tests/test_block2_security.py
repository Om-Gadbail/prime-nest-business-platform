"""Block 2 — security hardening tests (rate limits, CORS, logging, config)."""

from __future__ import annotations

from tests.block2_support import (  # noqa: F401
    auth_headers,
    b2,
    enable_rate_limit,
    public_lead_payload,
)


def test_auth_endpoints_rate_limited(b2, monkeypatch) -> None:
    from app.services.rate_limit import InMemoryRateLimiter, set_limiter

    enable_rate_limit(
        monkeypatch, public_requests=1000, auth_requests=3, auth_window=300
    )
    # Fresh budget: the fixture's own setup logins already consumed part of
    # the per-test bucket (the limiter is process-global by design).
    set_limiter(InMemoryRateLimiter())
    client = b2["client"]
    payload = {"email": "prime-owner@example.com", "password": "StrongPass-1234!"}
    for _ in range(3):
        assert client.post("/api/v1/auth/login", json=payload).status_code == 200
    resp = client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 429, resp.text
    assert resp.headers.get("Retry-After")


def test_rate_limiter_unit_contract() -> None:
    from app.services.rate_limit import InMemoryRateLimiter

    limiter = InMemoryRateLimiter()
    assert limiter.check(key="k", limit=2, window_seconds=60).allowed is True
    assert limiter.check(key="k", limit=2, window_seconds=60).allowed is True
    denied = limiter.check(key="k", limit=2, window_seconds=60)
    assert denied.allowed is False and denied.retry_after_seconds >= 1
    # Independent keys unaffected; reset restores.
    assert limiter.check(key="other", limit=2, window_seconds=60).allowed is True
    limiter.reset()
    assert limiter.check(key="k", limit=2, window_seconds=60).allowed is True


def test_rate_limit_disabled_flag(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services import rate_limit as rl

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    rl.enforce(get_settings(), key="any", limit=1, window_seconds=60)  # no raise
    get_settings.cache_clear()


def test_cors_no_wildcard_and_allows_idempotency_key(b2) -> None:
    # Authenticated API preflight echoes only configured origins (never *).
    resp = b2["client"].options(
        "/api/v1/leads",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Idempotency-Key",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-origin") != "*"
    # Unlisted origin gets no ACAO header.
    resp = b2["client"].options(
        "/api/v1/leads",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") in (None, "")


def test_public_cors_allows_prime_origin_when_configured(b2, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv(
        "PUBLIC_SITE_ORIGINS", "http://localhost:5173,https://prime.example"
    )
    get_settings.cache_clear()
    settings = get_settings()
    assert "https://prime.example" in settings.effective_cors_origins
    assert "*" not in settings.effective_cors_origins


def test_security_log_redaction() -> None:
    from app.services.security_log import sanitize_fields

    clean = sanitize_fields(
        {
            "event": "login",
            "password": "supersecret",
            "refresh_token": "abc",
            "Authorization": "Bearer xyz",
            "business_slug": "prime",
            "note": "x" * 500,
        }
    )
    assert "password" not in clean
    assert "refresh_token" not in clean
    assert "Authorization" not in clean
    assert clean["business_slug"] == "prime"
    assert len(clean["note"]) == 200  # truncated


def test_idempotency_key_and_hash_contract() -> None:
    import pytest

    from app.services import idempotency as idem

    assert idem.validate_key(None) is None
    assert idem.validate_key("  ") is None
    assert idem.validate_key("abc-DEF_123456") == "abc-DEF_123456"
    with pytest.raises(ValueError):
        idem.validate_key("short")
    with pytest.raises(ValueError):
        idem.validate_key("x" * 65)
    with pytest.raises(ValueError):
        idem.validate_key("has spaces!!")
    # Canonical hash: key order irrelevant, values matter.
    assert idem.payload_hash({"a": 1, "b": 2}) == idem.payload_hash({"b": 2, "a": 1})
    assert idem.payload_hash({"a": 1}) != idem.payload_hash({"a": 2})


def test_normalization_helpers() -> None:
    from app.services import normalize as norm

    assert norm.normalize_phone("+91 98765 43210") == "+919876543210"
    assert norm.normalize_phone("(098765) 43210") == "09876543210"
    assert norm.normalize_phone("123") is None
    assert norm.normalize_email("  Aarav@Example.COM ") == "aarav@example.com"
    assert norm.normalize_email("not-an-email") is None
    assert norm.split_name("  Aarav  Kumar Sharma ") == ("Aarav", "Kumar Sharma")
    assert norm.split_name("") == ("", "")
    assert norm.mask_phone_last4("+919876543210") == "***3210"
    assert "+919876543210" not in norm.mask_phone_last4("+919876543210")
    assert norm.mask_email("aarav@example.com") == "a***@example.com"


def test_block2_settings_and_migration_chain() -> None:
    from app.core.config import Settings

    s = Settings(
        app_env="testing",
        database_url="postgresql+psycopg://u:p@db:5432/app_db",
        secret_key="test-secret",
        public_site_origins="http://localhost:5173, https://prime.example",  # type: ignore[arg-type]
    )
    assert s.public_site_origins == ["http://localhost:5173", "https://prime.example"]
    assert s.rate_limit_enabled is True
    assert s.ai_enabled is False and s.ai_provider == "noop"
    # Migration chain intact (0003 follows 0002, tables match models).
    import importlib

    m3 = importlib.import_module("migrations.versions.0003_block2_leads_crm")
    assert m3.revision == "0003_block2_leads_crm"
    assert m3.down_revision == "0002_identity_multitenancy"
    from app.models import Base

    for table in (
        "contacts", "customers", "leads", "lead_activities", "bookings",
        "notifications", "notification_preferences", "idempotency_records",
        "ai_runs",
    ):
        assert table in Base.metadata.tables


def test_seed_operational_defaults(b2) -> None:
    # Seed leaves flags unset; missing reads as enabled (continuity for
    # pre-Block-2 settings rows; owners disable explicitly).
    from app.services import public as public_service

    config = public_service.public_config(b2["db"], slug="prime")
    assert config["lead_capture_enabled"] is True
    assert config["booking_enabled"] is True


def test_error_responses_never_leak_internals(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    # Malformed UUIDs, unknown enums, oversized search: safe envelopes only.
    for resp in (
        b2["client"].get("/api/v1/leads/%%zz", headers=h),
        b2["client"].get("/api/v1/bookings/%%zz", headers=h),
        b2["client"].get("/api/v1/contacts/%%zz", headers=h),
    ):
        assert resp.status_code in (404, 422)
        assert "Traceback" not in resp.text
        assert "psycopg" not in resp.text.lower()
