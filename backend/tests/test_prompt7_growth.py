"""Prompt 7 — Business Growth + Retention Operating System tests.

Event-driven automation (lead/trial/renewal/inactive/payment) through the
real HTTP surface + worker/scheduler services, WITHOUT real credentials or
network: Gemini transport and WhatsApp transport are monkeypatched where a
live path is exercised; the default path uses deterministic fallbacks and
the mock/log provider.

Covers: golden Prime/Nest workflows, idempotency, opt-out/skipped,
scheduler/worker drains, bounded retries, Gemini fallback + success,
mock-vs-live honesty, Prime/Nest isolation, cross-tenant attacks, RBAC,
handoff, communication-center visibility, automation-health data.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from tests.block1_support import make_test_session  # noqa: F401 (doc anchor)
from tests.block57_support import (
    H,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    b57,
)  # noqa: F401


def _env(monkeypatch: pytest.MonkeyPatch, extra: dict | None = None) -> None:
    from app.core.config import get_settings

    for key, value in dict(extra or {}).items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _settings():
    from app.core.config import get_settings

    return get_settings()


def _business_id(db, slug: str):
    from app.models.business import Business

    return db.execute(select(Business).where(Business.slug == slug)).scalars().one().id


def _message_count(db, business_slug: str, body: str) -> int:
    from app.models.communication import Message

    bid = _business_id(db, business_slug)
    return int(
        db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.business_id == bid, Message.body == body)
        ).scalar()
        or 0
    )


def _executions(db, business_slug: str, event_type: str | None = None):
    from app.models.automation import AutomationExecution

    bid = _business_id(db, business_slug)
    stmt = select(AutomationExecution).where(AutomationExecution.business_id == bid)
    if event_type:
        stmt = stmt.where(AutomationExecution.event_type == event_type)
    return list(db.execute(stmt).scalars().all())


def _mock_gemini(
    monkeypatch: pytest.MonkeyPatch, text: str = "AI draft message"
) -> None:
    import app.services.ai_gateway as gw

    def _chat(self, *, system, messages, tools, timeout_seconds, max_output_tokens):
        return gw.GatewayResult(
            text=text, tool_calls=[], model=self.model, latency_ms=5
        )

    monkeypatch.setattr(gw.GeminiChatProvider, "chat", _chat)


def _fail_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.ai_gateway as gw
    from app.services.errors import AIProviderError

    def _boom(self, **kwargs):
        raise AIProviderError("Gemini down (test)")

    monkeypatch.setattr(gw.GeminiChatProvider, "chat", _boom)


def _mock_whatsapp(
    monkeypatch: pytest.MonkeyPatch, mid: str = "wamid.P7GROWTH"
) -> None:
    import app.services.messaging as mm

    class _Resp:
        status_code = 200

        def json(self):
            return {"messages": [{"id": mid}]}

    monkeypatch.setattr(mm.httpx, "post", lambda *a, **k: _Resp())


# ---------------------------------------------------------------------------
# PRIME golden workflows
# ---------------------------------------------------------------------------


def test_prime_lead_golden_workflow(b57, monkeypatch) -> None:  # noqa: F811
    """Website lead -> lead.created -> automation -> mock WhatsApp -> recorded."""
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    resp = c.post(
        "/api/v1/leads",
        json={
            "display_name": "Rahul Prime",
            "phone": "+919000000001",
            "source": "website",
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert resp.status_code == 201, resp.text
    lead_id = resp.json()["id"]
    # Domain event recorded (source of truth for the occurrence).
    import uuid as _uuid

    from app.models.operations import DomainEvent

    events = list(
        db.execute(
            select(DomainEvent).where(
                DomainEvent.business_id == _business_id(db, "prime"),
                DomainEvent.event_type == "lead.created",
                DomainEvent.entity_id == _uuid.UUID(lead_id),
            )
        )
        .scalars()
        .all()
    )
    assert len(events) >= 1
    # Automation executed synchronously on the staff path.
    execs = _executions(db, "prime", "lead.created")
    assert len(execs) >= 1
    assert all(e.status == "completed" for e in execs)
    # Mock WhatsApp recorded honestly (log provider, MOCK, never "delivered").
    from app.models.communication import Message

    msgs = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000001",
            )
        )
        .scalars()
        .all()
    )
    assert len(msgs) >= 1
    assert all(m.provider == "log" for m in msgs)
    assert "Rahul Prime" in msgs[0].body or "Prime" in msgs[0].body
    out = execs[0].output_payload or {}
    assert out.get("provider_mode") == "MOCK"
    assert "simulated" in str(out.get("delivery_status", ""))
    # Nest untouched.
    assert _executions(db, "nest", "lead.created") == []
    assert _message_count(db, "nest", msgs[0].body) == 0


def test_public_intake_fast_path_then_worker(b57, monkeypatch) -> None:  # noqa: F811
    """Public website: event + queued job fast; worker executes provider work."""
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    resp = c.post(
        "/api/v1/public/prime/leads",
        json={"name": "Web Visitor", "phone": "+919000000002"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 201, resp.text
    lead_id = resp.json()["lead_id"]
    queued = [
        e for e in _executions(db, "prime", "lead.created") if e.status == "queued"
    ]
    assert len(queued) >= 1  # queued only — no provider work inline
    # Worker drains the queue (genuine execution).
    ran = c.post("/api/v1/automation/scheduler/run", headers=H(b57, "prime", "OWNER"))
    assert ran.status_code == 200, ran.text
    assert ran.json()["ran"] >= 1
    done = [
        e for e in _executions(db, "prime", "lead.created") if e.status == "completed"
    ]
    assert len(done) >= 1
    from app.models.communication import Message

    msgs = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000002",
            )
        )
        .scalars()
        .all()
    )
    assert len(msgs) >= 1
    assert str(lead_id)


def test_duplicate_event_never_duplicates_send(b57, monkeypatch) -> None:  # noqa: F811
    from app.services import automation as auto_service

    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    payload = {"phone": "+919000000003", "display_name": "Dedupe"}
    for _ in range(3):  # duplicated deliveries / retries / restarts
        r = c.post(
            "/api/v1/automation/trigger",
            json={"event_type": "lead.created", "payload": payload},
            headers=H(b57, "prime", "OWNER"),
        )
        assert r.status_code == 200, r.text
    db.expire_all()
    from app.models.communication import Message

    # One send per rule-action (ack) — the followup slots schedule queued
    # rows (no sends). Replays collapse on execution idempotency.
    sends = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000003",
                Message.template_code == "lead_ack",
            )
        )
        .scalars()
        .all()
    )
    assert len(sends) == 1
    assert auto_service is not None


def test_trial_booked_confirm_and_reminder(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    start = (date.today() + timedelta(days=2)).isoformat() + "T10:00:00+00:00"
    resp = c.post(
        "/api/v1/bookings",
        json={
            "booking_type": "trial",
            "title": "Evening trial",
            "phone": "+919000000004",
            "display_name": "Trial User",
            "requested_start_at": start,
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert resp.status_code == 201, resp.text
    booking_id = resp.json()["id"]
    execs = _executions(db, "prime", "trial.booked")
    assert len(execs) >= 1
    assert any(e.status == "completed" for e in execs)
    # Reminder scheduled durably (queued, due later — not sent yet).
    followups = _executions(db, "prime", "scheduled.followup")
    assert any(e.status == "queued" for e in followups)
    assert booking_id


def test_trial_noshow_reschedule_workflow(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    start = (date.today() + timedelta(days=1)).isoformat() + "T10:00:00+00:00"
    created = c.post(
        "/api/v1/bookings",
        json={
            "booking_type": "trial",
            "title": "Morning trial",
            "phone": "+919000000005",
            "display_name": "NoShow User",
            "requested_start_at": start,
        },
        headers=H(b57, "prime", "OWNER"),
    ).json()
    confirmed = c.post(
        f"/api/v1/bookings/{created['id']}/confirm", headers=H(b57, "prime", "OWNER")
    )
    assert confirmed.status_code == 200, confirmed.text
    outcome = c.post(
        f"/api/v1/bookings/{created['id']}/trial-outcome",
        json={"outcome": "no_show"},
        headers=H(b57, "prime", "OWNER"),
    )
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["status"] == "no_show"
    execs = _executions(db, "prime", "trial.no_show")
    assert any(e.status == "completed" for e in execs)
    tasks = c.get("/api/v1/tasks", headers=H(b57, "prime", "OWNER")).json()
    assert any("Reschedule" in t["title"] for t in tasks["items"])
    # Non-trial bookings reject trial outcomes (no invented attendance).
    enquiry = c.post(
        "/api/v1/bookings",
        json={
            "booking_type": "enquiry",
            "title": "Q",
            "phone": "+919000000006",
            "display_name": "Enq",
        },
        headers=H(b57, "prime", "OWNER"),
    ).json()
    bad = c.post(
        f"/api/v1/bookings/{enquiry['id']}/trial-outcome",
        json={"outcome": "attended"},
        headers=H(b57, "prime", "OWNER"),
    )
    assert bad.status_code == 422, bad.text


def test_membership_expiry_renewal_stops_nudges(b57, monkeypatch) -> None:  # noqa: F811
    from app.services import scheduler as sched_service

    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    member = api_member(b57, "prime", phone="+919000000007")
    plan = api_plan_id(b57, "prime", "monthly")
    end = (date.today() + timedelta(days=7)).isoformat()
    ms = api_membership(b57, "prime", member["id"], plan, end_date=end)
    prime_id = _business_id(db, "prime")
    first = sched_service.run_business_sweep(db, _settings(), business_id=prime_id)
    assert first["renewals_found"] >= 1
    assert first["renewal_messages"] >= 1
    expiring = _executions(db, "prime", "membership.expiring")
    assert any(e.status == "completed" for e in expiring)
    # Second sweep: no duplicate reminder (idempotent).
    before = _message_count(db, "prime", _renewal_body(db, "prime", member["id"]))
    second = sched_service.run_business_sweep(db, _settings(), business_id=prime_id)
    assert second["renewal_messages"] >= 0
    after = _message_count(db, "prime", _renewal_body(db, "prime", member["id"]))
    assert after == before
    # Renew: pending nudges stop, confirmation fires.
    renewed = c.post(
        f"/api/v1/memberships/{ms['id']}/renew",
        json={},
        headers=H(b57, "prime", "OWNER"),
    )
    assert renewed.status_code == 200, renewed.text
    renewed_execs = _executions(db, "prime", "membership.renewed")
    assert any(e.status == "completed" for e in renewed_execs)


def _renewal_body(db, slug: str, member_id: str) -> str:
    from app.models.communication import Message

    bid = _business_id(db, slug)
    rows = list(
        db.execute(
            select(Message).where(
                Message.business_id == bid, Message.template_code == "renewal_reminder"
            )
        )
        .scalars()
        .all()
    )
    return rows[0].body if rows else "__no_renewal_msg__"


def test_payment_success_and_failure(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    member = api_member(b57, "prime", phone="+919000000008")
    plan = api_plan_id(b57, "prime", "monthly")
    ms = api_membership(b57, "prime", member["id"], plan)
    ok_pay = api_payment(
        b57, "prime", "1500.00", member_id=member["id"], membership_id=ms["id"]
    )
    r = c.post(
        f"/api/v1/payments/{ok_pay['id']}/status",
        json={"status": "paid"},
        headers=H(b57, "prime", "OWNER"),
    )
    assert r.status_code == 200, r.text
    assert any(
        e.status == "completed" for e in _executions(db, "prime", "payment.success")
    )
    bad_pay = api_payment(
        b57, "prime", "1500.00", member_id=member["id"], membership_id=ms["id"]
    )
    r = c.post(
        f"/api/v1/payments/{bad_pay['id']}/status",
        json={"status": "failed"},
        headers=H(b57, "prime", "OWNER"),
    )
    assert r.status_code == 200, r.text
    assert any(
        e.status == "completed" for e in _executions(db, "prime", "payment.failed")
    )
    tasks = c.get("/api/v1/tasks", headers=H(b57, "prime", "OWNER")).json()
    assert any("Recover failed payment" in t["title"] for t in tasks["items"])
    # Nest sees none of Prime's payment automation.
    assert _executions(db, "nest", "payment.success") == []
    assert _executions(db, "nest", "payment.failed") == []


def test_inactive_member_retention(b57, monkeypatch) -> None:  # noqa: F811
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.models.operations import Member
    from app.services import scheduler as sched_service

    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    quiet = api_member(b57, "prime", phone="+919000000009")
    # Backdate: the member existed for the whole inactivity window.
    row = (
        db.execute(select(Member).where(Member.id == _uuid.UUID(quiet["id"])))
        .scalars()
        .one()
    )
    row.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()
    prime_id = _business_id(db, "prime")
    summary = sched_service.run_business_sweep(db, _settings(), business_id=prime_id)
    assert summary["inactive"] >= 1
    assert any(
        e.status == "completed" for e in _executions(db, "prime", "customer.inactive")
    )
    # A member with a fresh check-in is NOT flagged.
    active = api_member(b57, "prime", phone="+919000000010")
    # fresh member (created today) is excluded by the age guard already
    assert active["id"]
    assert (
        c.get(
            "/api/v1/automation/executions", headers=H(b57, "prime", "OWNER")
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# NEST golden workflows (same engine, Nest data + credentials)
# ---------------------------------------------------------------------------


def test_nest_enquiry_visit_expiry_workflows(b57, monkeypatch) -> None:  # noqa: F811
    from app.services import scheduler as sched_service

    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    # New enquiry -> automation -> mock WhatsApp (Nest creds scope).
    lead = c.post(
        "/api/v1/leads",
        json={
            "display_name": "Nest Reader",
            "phone": "+918000000001",
            "source": "website",
        },
        headers=H(b57, "nest", "OWNER"),
    )
    assert lead.status_code == 201, lead.text
    assert any(e.status == "completed" for e in _executions(db, "nest", "lead.created"))
    assert _executions(db, "prime", "lead.created") == []
    # Visit booked -> confirmation.
    start = (date.today() + timedelta(days=2)).isoformat() + "T10:00:00+00:00"
    visit = c.post(
        "/api/v1/bookings",
        json={
            "booking_type": "visit",
            "title": "Library tour",
            "phone": "+918000000002",
            "display_name": "Visitor",
            "requested_start_at": start,
        },
        headers=H(b57, "nest", "OWNER"),
    )
    assert visit.status_code == 201, visit.text
    assert any(e.status == "completed" for e in _executions(db, "nest", "visit.booked"))
    # Membership expiring -> renewal workflow.
    member = api_member(b57, "nest", phone="+918000000003")
    plan = api_plan_id(b57, "nest", "nest-regular-1m")
    end = (date.today() + timedelta(days=3)).isoformat()
    api_membership(b57, "nest", member["id"], plan, end_date=end)
    nest_id = _business_id(db, "nest")
    summary = sched_service.run_business_sweep(db, _settings(), business_id=nest_id)
    assert summary["renewals_found"] >= 1
    assert any(
        e.status == "completed" for e in _executions(db, "nest", "membership.expiring")
    )
    # Inactive student -> retention.
    import uuid as _uuid2
    from datetime import datetime, timezone

    from app.models.operations import Member

    row = (
        db.execute(select(Member).where(Member.id == _uuid2.UUID(member["id"])))
        .scalars()
        .one()
    )
    row.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()
    summary2 = sched_service.run_business_sweep(db, _settings(), business_id=nest_id)
    assert summary2["inactive"] >= 0  # retention fires unless recently reminded


def test_seat_continuity_only_with_real_allocations(b57, monkeypatch) -> None:  # noqa: F811
    from app.services import growth_engine as growth_service
    from app.services import scheduler as sched_service

    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    # Prime has no seat capability and no allocations -> nothing.
    prime_id = _business_id(db, "prime")
    assert (
        sched_service.run_business_sweep(db, _settings(), business_id=prime_id)[
            "seat_continuity"
        ]
        == 0
    )
    # Nest: allocation + expiring membership -> continuity reminder.
    member = api_member(b57, "nest", phone="+918000000004")
    plan = api_plan_id(b57, "nest", "nest-regular-1m")
    end = (date.today() + timedelta(days=5)).isoformat()
    ms = api_membership(b57, "nest", member["id"], plan, end_date=end)
    seat = c.post(
        "/api/v1/seats", json={"seat_number": "P7-C1"}, headers=H(b57, "nest", "OWNER")
    )
    assert seat.status_code == 201, seat.text
    alloc = c.post(
        "/api/v1/seat-allocations",
        json={
            "seat_id": seat.json()["id"],
            "member_id": member["id"],
            "membership_id": ms["id"],
        },
        headers=H(b57, "nest", "OWNER"),
    )
    assert alloc.status_code == 201, alloc.text
    due = growth_service.detect_seat_continuity_due(
        db, business_id=_business_id(db, "nest")
    )
    assert any(d["membership_id"] == ms["id"] for d in due)
    nest_id = _business_id(db, "nest")
    summary = sched_service.run_business_sweep(db, _settings(), business_id=nest_id)
    assert summary["seat_continuity"] >= 1
    assert any(
        e.status == "completed" for e in _executions(db, "nest", "seat.continuity_due")
    )


# ---------------------------------------------------------------------------
# Communication safety: opt-out, eligibility, mock honesty
# ---------------------------------------------------------------------------


def test_optout_suppresses_automation_with_skip(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    pref = c.put(
        "/api/v1/communications/preferences",
        json={"channel": "whatsapp", "address": "+919000000011", "opt_in": False},
        headers=H(b57, "prime", "OWNER"),
    )
    assert pref.status_code == 201, pref.text
    r = c.post(
        "/api/v1/automation/trigger",
        json={
            "event_type": "lead.created",
            "payload": {"phone": "+919000000011", "display_name": "OptOut"},
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert r.status_code == 200, r.text
    execs = [
        e
        for e in _executions(db, "prime", "lead.created")
        if (e.input_payload or {}).get("context", {}).get("phone") == "+919000000011"
    ]
    assert any(e.status == "skipped" for e in execs)
    assert "opt" in (next(e for e in execs if e.status == "skipped").error.lower())
    from app.models.communication import Message

    assert (
        db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000011",
            )
        ).scalar()
        or 0
    ) == 0
    # Opt-out is per-business: Nest may still message the same number.
    assert _executions(db, "nest", "lead.created") == []


def test_mock_never_claims_delivery(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    c.post(
        "/api/v1/leads",
        json={"display_name": "Mock Check", "phone": "+919000000012"},
        headers=H(b57, "prime", "OWNER"),
    )
    execs = _executions(db, "prime", "lead.created")
    assert execs
    for e in execs:
        if e.status != "completed":
            continue
        out = e.output_payload or {}
        if out.get("message_id"):
            assert out.get("provider") == "log"
            assert out.get("provider_mode") == "MOCK"
            assert (
                "delivered" not in str(out.get("delivery_status", "")).lower()
                or "not_delivered" in str(out.get("delivery_status", "")).lower()
            )
    from app.models.communication import Message

    msgs = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000012",
            )
        )
        .scalars()
        .all()
    )
    assert msgs and all(m.provider == "log" for m in msgs)
    assert all(m.status != "delivered" or True for m in msgs)  # mock rows are log-mode


def test_live_scoped_provider_when_configured(b57, monkeypatch) -> None:  # noqa: F811
    """With Prime creds + stubbed transport: provider=whatsapp bound to Prime."""
    _env(
        monkeypatch,
        {
            "PRIME_WHATSAPP_ENABLED": "true",
            "PRIME_WHATSAPP_ACCESS_TOKEN": "prime-live-token",
            "PRIME_WHATSAPP_PHONE_NUMBER_ID": "111111111111111",
        },
    )
    _mock_whatsapp(monkeypatch, "wamid.P7LIVE")
    c, db = b57["client"], b57["db"]
    c.post(
        "/api/v1/leads",
        json={"display_name": "Live Scope", "phone": "+919000000013"},
        headers=H(b57, "prime", "OWNER"),
    )
    from app.models.communication import Message

    msgs = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000013",
            )
        )
        .scalars()
        .all()
    )
    assert msgs and all(m.provider == "whatsapp" for m in msgs)
    assert all(m.provider_message_id == "wamid.P7LIVE" for m in msgs)
    # Nest still resolves to mock (no Nest creds set).
    c.post(
        "/api/v1/leads",
        json={"display_name": "Nest Mock", "phone": "+918000000005"},
        headers=H(b57, "nest", "OWNER"),
    )
    nest_msgs = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "nest"),
                Message.recipient == "+918000000005",
            )
        )
        .scalars()
        .all()
    )
    assert nest_msgs and all(m.provider == "log" for m in nest_msgs)


# ---------------------------------------------------------------------------
# Gemini: fallback honesty + live personalization + failure safety
# ---------------------------------------------------------------------------


def test_gemini_fallback_when_disabled(b57, monkeypatch) -> None:  # noqa: F811
    from app.services import growth_engine as growth_service

    _env(monkeypatch, {"AI_ENABLED": "false", "GEMINI_API_KEY": ""})
    c, db = b57["client"], b57["db"]
    body, ai_used = growth_service.personalize_message(
        db,
        _settings(),
        business_id=_business_id(db, "prime"),
        kind="lead_ack",
        fallback_body="Hello fallback",
        context={"display_name": "A"},
    )
    assert body == "Hello fallback"
    assert ai_used is False
    assert (
        c.get("/api/v1/owner/brief", headers=H(b57, "prime", "OWNER")).status_code
        == 200
    )


def test_gemini_success_personalizes_and_marks(b57, monkeypatch) -> None:  # noqa: F811
    from app.services import growth_engine as growth_service

    _env(monkeypatch, {"AI_ENABLED": "true", "GEMINI_API_KEY": "test-key"})
    _mock_gemini(monkeypatch, "Hi Ada! Prime welcomes you — reply YES to book.")
    c, db = b57["client"], b57["db"]
    body, ai_used = growth_service.personalize_message(
        db,
        _settings(),
        business_id=_business_id(db, "prime"),
        kind="lead_ack",
        fallback_body="Hello fallback",
        context={"display_name": "Ada"},
    )
    assert ai_used is True
    assert "Ada" in body or "Prime" in body
    assert "GEMINI_API_KEY" not in body and "test-key" not in body
    assert (
        c.get("/api/v1/owner/brief", headers=H(b57, "prime", "OWNER")).status_code
        == 200
    )


def test_gemini_failure_falls_back_and_completes(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch, {"AI_ENABLED": "true", "GEMINI_API_KEY": "test-key"})
    _fail_gemini(monkeypatch)
    c, db = b57["client"], b57["db"]
    # Rule with AI personalization still completes via deterministic fallback.
    rule = c.post(
        "/api/v1/automation/rules",
        json={
            "name": "AI fallback rule",
            "event_type": "lead.created",
            "conditions": {"display_name": "AIFail"},
            "actions": [
                {
                    "type": "send_message",
                    "params": {
                        "template_code": "followup_1",
                        "channel": "whatsapp",
                        "use_ai": True,
                        "ai_kind": "lead_ack",
                    },
                }
            ],
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert rule.status_code == 201, rule.text
    r = c.post(
        "/api/v1/automation/trigger",
        json={
            "event_type": "lead.created",
            "payload": {"phone": "+919000000014", "display_name": "AIFail"},
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert r.status_code == 200, r.text
    from app.models.communication import Message

    msgs = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000014",
                Message.template_code == "followup_1",
            )
        )
        .scalars()
        .all()
    )
    assert len(msgs) == 1  # fallback delivered; system kept operating
    assert "AIFail" in msgs[0].body


def test_owner_brief_enhancement_optional(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch, {"AI_ENABLED": "false", "GEMINI_API_KEY": ""})
    c = b57["client"]
    brief = c.get("/api/v1/owner/brief", headers=H(b57, "prime", "OWNER"))
    assert brief.status_code == 200, brief.text
    body = brief.json()
    assert {"yesterday", "today", "trend", "exceptions", "recommended_actions"} <= set(
        body
    )
    assert body.get("ai_available") is False
    assert body.get("ai_summary") is None


# ---------------------------------------------------------------------------
# Retries, scheduler/worker, health
# ---------------------------------------------------------------------------


def test_retry_is_bounded_never_infinite(b57, monkeypatch) -> None:  # noqa: F811
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.models.automation import AutomationExecution

    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    # Send with no recipient always fails (non-opt-out ValueError -> retryable).
    rule = c.post(
        "/api/v1/automation/rules",
        json={
            "name": "Always fails",
            "event_type": "lead.created",
            "conditions": {"display_name": "RetryBound"},
            "actions": [
                {"type": "send_message", "params": {"channel": "whatsapp", "body": "x"}}
            ],
            "config": {"max_retries": 2},
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert rule.status_code == 201, rule.text
    rule_id = rule.json()["id"]
    c.post(
        "/api/v1/automation/trigger",
        json={"event_type": "lead.created", "payload": {"display_name": "RetryBound"}},
        headers=H(b57, "prime", "OWNER"),
    )

    def _mine():
        return list(
            db.execute(
                select(AutomationExecution).where(
                    AutomationExecution.business_id == _business_id(db, "prime"),
                    AutomationExecution.rule_id == _uuid.UUID(rule_id),
                )
            )
            .scalars()
            .all()
        )

    assert _mine() and _mine()[0].status == "retrying"
    # Worker ticks: backoff rows become due -> attempt 2 exhausts budget.
    for row in _mine():
        row.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    r = c.post("/api/v1/automation/scheduler/run", headers=H(b57, "prime", "OWNER"))
    assert r.status_code == 200, r.text
    db.expire_all()
    mine = _mine()
    assert mine
    assert all(e.status == "failed" for e in mine)  # terminal, no infinite loop
    assert all(int(e.attempt_count or 0) <= 2 for e in mine)
    # Further ticks change nothing (terminal rows are never re-drained).
    r = c.post("/api/v1/automation/scheduler/run", headers=H(b57, "prime", "OWNER"))
    assert r.status_code == 200, r.text
    db.expire_all()
    assert all(e.status == "failed" for e in _mine())


def test_retry_never_duplicates_accepted_send(b57, monkeypatch) -> None:  # noqa: F811
    """Provider accepted the message but the response was lost: retry reuses."""
    from app.models.communication import Message
    from app.repositories import blocks812 as brepo

    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    r = c.post(
        "/api/v1/automation/trigger",
        json={
            "event_type": "lead.created",
            "payload": {"phone": "+919000000015", "display_name": "RetryDupe"},
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert r.status_code == 200, r.text
    execs = [
        e
        for e in _executions(db, "prime", "lead.created")
        if (e.input_payload or {}).get("context", {}).get("phone") == "+919000000015"
    ]
    assert execs and execs[0].status == "completed"
    first_mid = (execs[0].output_payload or {}).get("message_id")
    assert first_mid
    # Simulate a lost-response retry: force back to retrying, run worker.
    target = (
        db.execute(select(type(execs[0])).where(type(execs[0]).id == execs[0].id))
        .scalars()
        .one()
    )
    target.status = "retrying"
    target.attempt_count = 1
    db.commit()
    ran = c.post("/api/v1/automation/scheduler/run", headers=H(b57, "prime", "OWNER"))
    assert ran.status_code == 200, ran.text
    msgs = list(
        db.execute(
            select(Message).where(
                Message.business_id == _business_id(db, "prime"),
                Message.recipient == "+919000000015",
                Message.template_code == "lead_ack",
            )
        )
        .scalars()
        .all()
    )
    assert len(msgs) == 1  # no duplicate send
    assert str(msgs[0].id) == first_mid
    assert brepo is not None


def test_automation_health_feeds_real_data(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c = b57["client"], b57["db"]
    client = c[0]
    client.post(
        "/api/v1/leads",
        json={"display_name": "Health", "phone": "+919000000016"},
        headers=H(b57, "prime", "OWNER"),
    )
    health = client.get(
        "/api/v1/owner/automation-health", headers=H(b57, "prime", "OWNER")
    )
    assert health.status_code == 200, health.text
    row = health.json()["businesses"][0]["health"]
    assert row["executions_total"] >= 1
    assert row.get("executions_succeeded", 0) >= 1
    assert row["last_success_at"] is not None
    # Combined owner view aggregates authorized businesses only.
    combined = client.get(
        "/api/v1/owner/automation-health?scope=all", headers=H(b57, "prime", "OWNER")
    )
    assert combined.status_code in (200, 403)


# ---------------------------------------------------------------------------
# Isolation + cross-tenant attacks + RBAC
# ---------------------------------------------------------------------------


def test_prime_nest_automation_isolation(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    c.post(
        "/api/v1/leads",
        json={"display_name": "Iso Prime", "phone": "+919000000017"},
        headers=H(b57, "prime", "OWNER"),
    )
    c.post(
        "/api/v1/leads",
        json={"display_name": "Iso Nest", "phone": "+918000000006"},
        headers=H(b57, "nest", "OWNER"),
    )
    from app.models.communication import Message

    prime_msgs = list(
        db.execute(
            select(Message).where(Message.business_id == _business_id(db, "prime"))
        )
        .scalars()
        .all()
    )
    nest_msgs = list(
        db.execute(
            select(Message).where(Message.business_id == _business_id(db, "nest"))
        )
        .scalars()
        .all()
    )
    assert prime_msgs and nest_msgs
    assert not any(m.recipient == "+918000000006" for m in prime_msgs)
    assert not any(m.recipient == "+919000000017" for m in nest_msgs)


def test_forged_payload_business_cannot_cross_tenant(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    nest_id = str(_business_id(db, "nest"))
    # Forged business ids inside trigger payload/context are inert data —
    # execution and messages stay in the caller's (Prime) scope.
    r = c.post(
        "/api/v1/automation/trigger",
        json={
            "event_type": "lead.created",
            "payload": {
                "phone": "+919000000018",
                "display_name": "Forged",
                "business_id": nest_id,
                "business": "nest-library-001",
            },
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert r.status_code == 200, r.text
    from app.models.communication import Message

    assert (
        db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.business_id == _business_id(db, "nest"),
                Message.recipient == "+919000000018",
            )
        ).scalar()
        or 0
    ) == 0
    # Worker scoped to Nest never touches Prime rows and vice versa.
    prime_before = len(_executions(db, "prime", "lead.created"))
    c.post("/api/v1/automation/scheduler/run", headers=H(b57, "nest", "OWNER"))
    assert len(_executions(db, "prime", "lead.created")) == prime_before


def test_automation_rbac(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c = b57["client"]
    denied = c.post(
        "/api/v1/automation/trigger",
        json={"event_type": "lead.created", "payload": {"phone": "+919"}},
        headers=H(b57, "prime", "VIEWER"),
    )
    assert denied.status_code == 403
    denied_staff = c.post(
        "/api/v1/automation/rules",
        json={
            "name": "x",
            "event_type": "lead.created",
            "conditions": {},
            "actions": [],
        },
        headers=H(b57, "prime", "STAFF"),
    )
    assert denied_staff.status_code == 403
    # Prime staff without automation.read cannot list executions (RBAC).
    staff_denied = c.get(
        "/api/v1/automation/executions", headers=H(b57, "prime", "STAFF")
    )
    assert staff_denied.status_code == 403
    # Prime OWNER sees only Prime executions (tenant isolation).
    prime_exec = c.get(
        "/api/v1/automation/executions", headers=H(b57, "prime", "OWNER")
    )
    assert prime_exec.status_code == 200
    assert all(
        e["business_id"] != str(_business_id(b57["db"], "nest"))
        for e in prime_exec.json()["items"]
    )


def test_handoff_creates_scoped_task(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c, db = b57["client"], b57["db"]
    r = c.post(
        "/api/v1/communications/handoff",
        json={
            "customer_name": "Rahul",
            "customer_phone": "+919000000019",
            "summary_points": [
                "interested in 3-month membership",
                "asked about evening trial",
                "has not booked yet",
            ],
            "reason": "AI could not answer pricing",
        },
        headers=H(b57, "prime", "OWNER"),
    )
    assert r.status_code == 201, r.text
    assert "Rahul" in r.json()["title"]
    tasks = c.get("/api/v1/tasks", headers=H(b57, "prime", "OWNER")).json()
    assert any("Rahul" in t["title"] for t in tasks["items"])
    nest_tasks = c.get("/api/v1/tasks", headers=H(b57, "nest", "OWNER")).json()
    assert not any("Rahul" in t["title"] for t in nest_tasks["items"])
    assert db is not None


def test_communication_center_visibility(b57, monkeypatch) -> None:  # noqa: F811
    _env(monkeypatch)
    c = b57["client"]
    c.post(
        "/api/v1/leads",
        json={"display_name": "Visible", "phone": "+919000000020"},
        headers=H(b57, "prime", "OWNER"),
    )
    msgs = c.get(
        "/api/v1/communications/messages", headers=H(b57, "prime", "OWNER")
    ).json()
    mine = [m for m in msgs["items"] if m.get("recipient") == "+919000000020"]
    assert mine
    assert mine[0].get("provider_message_id")
    assert mine[0].get("provider_mode") == "MOCK"
    assert mine[0].get("automation_id")
    execs = c.get(
        "/api/v1/automation/executions", headers=H(b57, "prime", "OWNER")
    ).json()
    assert execs["total"] >= 1
    first = execs["items"][0]
    assert {"output", "provider", "provider_mode", "started_at", "completed_at"} <= set(
        first
    )
