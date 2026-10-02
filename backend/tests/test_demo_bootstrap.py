"""Demo bootstrap tests (flag-gated, idempotent, canonical-only, heal)."""

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
    assert len(s.owner_seed_password) >= 10
    assert len(s.staff_seed_password) >= 10
    return s


def _fresh_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def test_bootstrap_creates_and_heals_idempotent():
    import app.services.demo_bootstrap as demo

    db = _fresh_db()
    try:
        s = _settings(enabled=True)
        r1 = demo.bootstrap_demo_access(db, s)
        assert r1["skipped"] is False and len(r1["created"]) == 3
        r2 = demo.bootstrap_demo_access(db, s)
        assert r2["skipped"] is False and r2["created"] == []  # heal-only, no dupes
        from sqlalchemy import func, select
        from app.models.user import User

        assert int(db.execute(select(func.count(User.id))).scalar_one() or 0) == 3
    finally:
        db.close()
        from app.core.database import reset_engine_cache

        reset_engine_cache()


def test_bootstrap_disabled_never_touches_db():
    from sqlalchemy import func, select
    from app.models.user import User
    import app.services.demo_bootstrap as demo

    db = _fresh_db()
    try:
        s = _settings(enabled=False)
        r = demo.bootstrap_demo_access(db, s)
        assert r["skipped"] is True and r["reason"] == "disabled"
        assert int(db.execute(select(func.count(User.id))).scalar_one() or 0) == 0
    finally:
        db.close()
        from app.core.database import reset_engine_cache

        reset_engine_cache()


def test_bootstrap_never_touches_arbitrary_users():
    from app.services import seed as seed_service
    from app.core import security
    from app.repositories import users as ur
    import app.services.demo_bootstrap as demo

    db = _fresh_db()
    try:
        seed_service.seed_development(db, include_owner=False, include_staff=False)
        real = ur.create(
            db, email="real@example.com",
            password_hash=security.hash_password("RealPassword123!"),
            full_name="Real", is_active=True, is_verified=True,
        )
        db.commit()
        before = real.password_hash
        s = _settings(enabled=True)
        demo.bootstrap_demo_access(db, s)
        after = ur.get_by_email(db, email="real@example.com")
        assert after is not None and after.password_hash == before
    finally:
        db.close()
        from app.core.database import reset_engine_cache

        reset_engine_cache()
