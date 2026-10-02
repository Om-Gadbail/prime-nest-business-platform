"""Demo bootstrap safety tests (first-boot only, self-disabling, no resets)."""

from __future__ import annotations


def _settings(enabled=True):
    from app.core.config import get_settings

    get_settings.cache_clear()
    import os

    os.environ["DEMO_PROVISION_ENABLED"] = "true" if enabled else "false"
    try:
        s = get_settings()
    finally:
        get_settings.cache_clear()
    # Ensure demo passwords meet length even in test env.
    assert len(s.owner_seed_password) >= 10
    assert len(s.staff_seed_password) >= 10
    return s


def test_bootstrap_provisions_empty_db_and_skips_after():
    import app.services.demo_bootstrap as demo
    from app.core.database import reset_engine_cache
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        s = _settings(enabled=True)
        assert demo.is_bootstrap_needed(db, enabled=True) is True
        result = demo.bootstrap_demo_access(db, s)
        assert result["skipped"] is False
        assert sorted(result["created"]) == sorted(
            [
                "owner@prime-nest-dashboard.com",
                "staff@primefitness.in",
                "staff@nestlibrary.in",
            ]
        )
        # Second run skips (non-empty, self-disabling).
        result2 = demo.bootstrap_demo_access(db, s)
        assert result2["skipped"] is True and result2["reason"] == "non_empty"
        assert demo.is_bootstrap_needed(db, enabled=True) is False
    finally:
        db.close()
        reset_engine_cache()


def test_bootstrap_disabled_flag_never_touches_db():
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker
    from app.models import Base
    from app.models.user import User

    import app.services.demo_bootstrap as demo

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        s = _settings(enabled=False)
        assert demo.is_bootstrap_needed(db, enabled=False) is False
        result = demo.bootstrap_demo_access(db, s)
        assert result["skipped"] is True and result["reason"] == "disabled"
        total = db.execute(select(func.count(User.id))).scalar_one()
        assert int(total or 0) == 0
    finally:
        db.close()
        from app.core.database import reset_engine_cache

        reset_engine_cache()


def test_bootstrap_never_resets_existing_password():
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.models import Base
    from app.models.business import Business

    import app.services.demo_bootstrap as demo
    from app.core import security
    from app.repositories import users as ur

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        # Seed a non-empty DB with one real user (bootstrap must skip entirely).
        from app.services import seed as seed_service

        seed_service.seed_development(db, include_owner=False, include_staff=False)
        real = ur.create(
            db,
            email="real@example.com",
            password_hash=security.hash_password("RealPassword123!"),
            full_name="Real",
            is_active=True,
            is_verified=True,
        )
        db.commit()
        digest_before = real.password_hash
        s = _settings(enabled=True)
        result = demo.bootstrap_demo_access(db, s)
        assert result["skipped"] is True and result["reason"] == "non_empty"
        after = ur.get_by_email(db, email="real@example.com")
        assert after is not None and after.password_hash == digest_before
        assert ur.get_by_email(db, email="owner@prime-nest-dashboard.com") is None
    finally:
        db.close()
        from app.core.database import reset_engine_cache

        reset_engine_cache()
