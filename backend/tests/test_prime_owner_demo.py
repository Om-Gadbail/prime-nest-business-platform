"""Prime owner-demo additive tests (existing tests untouched)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.block1_support import make_test_session


@pytest.fixture
def tdb():
    engine, db = make_test_session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_opt_out_keywords_include_end():
    from app.api.v1.endpoints import whatsapp as wa

    for kw in ("STOP", "stop", "UNSUBSCRIBE", "CANCEL", "END", "end"):
        assert wa._is_opt_out_text(kw) is True
    assert wa._is_opt_in_text("START") is True
    assert wa._is_opt_out_text("hello") is False


def test_renewal_stages_cover_all_offsets():
    from app.services import growth_engine as ge
    from app.services import reports as rep

    assert tuple(ge.RENEWAL_STAGES) == (30, 14, 7, 3, 1, 0)
    assert tuple(rep.RENEWAL_OFFSETS_DEFAULT) == (30, 14, 7, 3, 1, 0)


def test_noop_demo_intro_uses_config(tdb):
    from app.core.config import get_settings
    from app.repositories import businesses as brepo
    from app.services import ai_chat

    prime = brepo.get_by_slug(tdb, "prime")
    settings = get_settings().model_copy(update={"ai_enabled": True, "ai_provider": "noop"})
    out = ai_chat.chat_turn(
        tdb, settings, business_id=prime.id, business_name=prime.name,
        channel="whatsapp", visitor_key="+910000099901",
        message="Hi, I would like to know about Prime.",
        mode="public", caller="public",
    )
    assert "Demo assistant" in out["reply"]
    assert "membership plans" in out["reply"].lower() or "trial" in out["reply"].lower()


def test_noop_demo_plans_use_real_catalogue(tdb):
    from app.core.config import get_settings
    from app.repositories import businesses as brepo
    from app.services import ai_chat

    prime = brepo.get_by_slug(tdb, "prime")
    settings = get_settings().model_copy(update={"ai_enabled": True, "ai_provider": "noop"})
    out = ai_chat.chat_turn(
        tdb, settings, business_id=prime.id, business_name=prime.name,
        channel="whatsapp", visitor_key="+910000099902",
        message="What are your membership plans?",
        mode="public", caller="public",
    )
    assert "Demo assistant" in out["reply"]
    assert "1500" in out["reply"] or "4000" in out["reply"] or "12000" in out["reply"]


def test_noop_demo_handoff_escalates(tdb):
    from app.core.config import get_settings
    from app.repositories import businesses as brepo
    from app.services import ai_chat

    prime = brepo.get_by_slug(tdb, "prime")
    settings = get_settings().model_copy(update={"ai_enabled": True, "ai_provider": "noop"})
    out = ai_chat.chat_turn(
        tdb, settings, business_id=prime.id, business_name=prime.name,
        channel="whatsapp", visitor_key="+910000099903",
        message="I want to talk to someone.",
        mode="public", caller="public",
    )
    assert out["escalated"] is True


def test_prime_profile_enrichment_idempotent(tdb):
    from app.services import prime_demo

    first = prime_demo.ensure_prime_profile(tdb)
    assert first["profile"] == "ok"
    second = prime_demo.ensure_prime_profile(tdb)
    assert second["profile"] == "ok"
    assert second["business_fields"] == []


def test_prime_demo_seed_scoped_to_prime(tdb):
    from app.models.lead import Lead
    from app.repositories import businesses as brepo
    from app.services import prime_demo

    counts = prime_demo.seed_prime_owner_demo(tdb)
    assert counts["leads"] >= 10
    assert counts["members"] >= 5
    nest = brepo.get_by_slug(tdb, "nest")
    nest_demo = tdb.execute(
        select(func.count()).select_from(Lead).where(
            Lead.business_id == nest.id, Lead.source_detail == "prime-owner-demo"
        )
    ).scalar() or 0
    assert int(nest_demo) == 0
