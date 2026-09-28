"""Block 2 — AI foundation tests (disabled-first, provider-neutral, honest)."""

from __future__ import annotations

import pytest

from tests.block2_support import auth_headers, b2, login_as  # noqa: F401


def _lead_id(b2) -> str:
    h = auth_headers(b2["prime"]["access_token"])
    resp = b2["client"].post(
        "/api/v1/leads",
        json={"display_name": "AI Subject", "phone": "+919876500020",
              "service_interest": "Trial", "message": "Wants morning batch."},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _enable_ai(monkeypatch, **overrides) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("AI_PROVIDER", overrides.get("provider", "noop"))
    get_settings.cache_clear()


def test_ai_disabled_by_default(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    mode = b2["client"].get("/api/v1/ai/mode", headers=h).json()
    assert mode == {
        "enabled": False, "mode": "AI_DISABLED", "provider": "noop",
        "capabilities": [],
    }
    lead_id = _lead_id(b2)
    resp = b2["client"].post(f"/api/v1/ai/leads/{lead_id}/summary", headers=h)
    assert resp.status_code == 503, resp.text
    # Platform works fully without AI: normal flows unaffected.
    assert b2["client"].get(f"/api/v1/leads/{lead_id}", headers=h).status_code == 200


def test_noop_summary_and_classification(b2, monkeypatch) -> None:
    _enable_ai(monkeypatch)
    h = auth_headers(b2["prime"]["access_token"])
    mode = b2["client"].get("/api/v1/ai/mode", headers=h).json()
    assert mode["mode"] == "AI_MOCK"
    lead_id = _lead_id(b2)
    summary = b2["client"].post(f"/api/v1/ai/leads/{lead_id}/summary", headers=h)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["mode"] == "AI_MOCK"
    assert body["insight"]["provider"] == "noop"  # honestly labeled
    assert body["insight"]["summary"]
    assert body["insight"]["confidence"] in ("low", "medium", "high")
    classified = b2["client"].post(
        f"/api/v1/ai/leads/{lead_id}/classification", headers=h
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["insight"]["category"] in ("hot", "warm", "cold", "spam_like")
    # Audit metadata persisted (no prompts/outputs stored).
    from sqlalchemy import select

    from app.models.ai_run import AIRun

    runs = b2["db"].execute(select(AIRun)).scalars().all()
    assert len(runs) == 2
    assert all(r.provider == "noop" and r.status == "success" for r in runs)
    assert all(r.request_id for r in runs)
    columns = {c.name for c in AIRun.__table__.columns}
    assert "prompt" not in columns and "output" not in columns and "raw" not in columns


def test_ai_unknown_provider_and_cross_business(b2, monkeypatch) -> None:
    _enable_ai(monkeypatch, provider="mystery-vendor")
    h = auth_headers(b2["prime"]["access_token"])
    lead_id = _lead_id(b2)
    resp = b2["client"].post(f"/api/v1/ai/leads/{lead_id}/summary", headers=h)
    assert resp.status_code == 502, resp.text  # clear misconfiguration signal
    # Cross-business lead id is a uniform 404 (no oracle), even for AI.
    monkeypatch.setenv("AI_PROVIDER", "noop")
    from app.core.config import get_settings

    get_settings.cache_clear()
    nh = auth_headers(b2["nest"]["access_token"])
    assert b2["client"].post(
        f"/api/v1/ai/leads/{lead_id}/summary", headers=nh
    ).status_code == 404


def test_ai_requires_permission(b2, monkeypatch) -> None:
    _enable_ai(monkeypatch)
    viewer = login_as(
        b2["client"], b2["db"], email="ai-viewer@example.com",
        slug="prime", role="VIEWER",
    )
    # VIEWER has no ai.read.
    assert b2["client"].get(
        "/api/v1/ai/mode", headers=auth_headers(viewer["access_token"])
    ).status_code == 403
    staff = login_as(
        b2["client"], b2["db"], email="ai-staff@example.com",
        slug="prime", role="STAFF",
    )
    # STAFF has no ai.read either (manager+ feature).
    assert b2["client"].get(
        "/api/v1/ai/mode", headers=auth_headers(staff["access_token"])
    ).status_code == 403


def test_ai_context_minimizes_pii_and_bounds_size() -> None:
    from types import SimpleNamespace

    from app.services.ai import contexts

    lead = SimpleNamespace(
        display_name="Aarav Sharma", status="new", source="website",
        service_interest="Trial", message="Call me " * 5000,
        normalized_phone="+919876543210", normalized_email="aarav.sharma@example.com",
        follow_up_at=None, assigned_user_id=None,
    )
    context = contexts.build_lead_context(lead, max_input_chars=8000)
    rendered = str(context)
    assert len(rendered) <= 8000
    assert "+919876543210" not in rendered  # raw phone never included
    assert "aarav.sharma@example.com" not in rendered
    assert "***3210" in rendered  # masked reference only
    assert "password" not in rendered and "token" not in rendered


def test_ai_output_validation_rejects_garbage() -> None:
    from pydantic import ValidationError

    from app.services.ai.outputs import LeadSummary

    with pytest.raises(ValidationError):
        LeadSummary.model_validate({"summary": 123, "confidence": "certain"})
    with pytest.raises(ValidationError):
        # Extra provider keys must not slip through.
        LeadSummary.model_validate(
            {"summary": "ok", "confidence": "low", "drop_table": True}
        )

def test_ai_provider_failure_is_audited(b2, monkeypatch) -> None:
    """Provider failures return 502 AND persist an error audit row."""
    import app.services.ai.providers as providers
    from app.services.ai.providers import AIProvider
    from app.services.errors import AIProviderError

    class _Broken(AIProvider):
        name = "broken"
        model = "broken-0"

        def generate_structured(self, **kw):
            raise AIProviderError("upstream exploded")

    monkeypatch.setitem(providers.PROVIDERS, "broken", _Broken)
    _enable_ai(monkeypatch, provider="broken")
    h = auth_headers(b2["prime"]["access_token"])
    lead_id = _lead_id(b2)
    resp = b2["client"].post(f"/api/v1/ai/leads/{lead_id}/summary", headers=h)
    assert resp.status_code == 502, resp.text
    from sqlalchemy import select

    from app.models.ai_run import AIRun

    runs = b2["db"].execute(select(AIRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "error" and runs[0].provider == "broken"
    assert runs[0].error  # message only, no PII payload
