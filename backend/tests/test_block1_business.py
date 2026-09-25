"""Block 1 — business / multi-tenant foundation + settings model tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.block1_support import add_test_membership, create_test_user, make_test_session


@pytest.fixture
def tdb():
    engine, db = make_test_session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_seed_creates_prime_and_nest(tdb) -> None:
    from app.models.business import Business

    slugs = sorted(b.slug for b in tdb.execute(select(Business)).scalars().all())
    assert "prime" in slugs and "nest" in slugs
    prime = tdb.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    assert prime is not None
    assert prime.name == "Prime Fitness"
    assert prime.business_type == "fitness"
    assert prime.status == "active" and prime.is_active is True
    nest = tdb.execute(select(Business).where(Business.slug == "nest")).scalars().first()
    assert nest is not None
    assert nest.name == "Nest Library"
    assert nest.business_type == "library"


def test_business_ids_are_uuids_and_stable(tdb) -> None:
    import uuid

    from app.models.business import Business

    for b in tdb.execute(select(Business)).scalars().all():
        assert isinstance(b.id, uuid.UUID)


def test_business_slug_uniqueness_enforced(tdb) -> None:
    from app.models.business import Business

    tdb.add(Business(slug="prime", name="Dupe", business_type="other"))
    with pytest.raises(IntegrityError):
        tdb.flush()
    tdb.rollback()


def test_inactive_business_flag(tdb) -> None:
    from app.services import business as business_service

    b = business_service.create_business(
        tdb, slug="future-biz", name="Future Biz", business_type="other", status="inactive"
    )
    assert b.status == "inactive" and b.is_active is False


def test_business_settings_row_created_per_business(tdb) -> None:
    from app.models.business import Business
    from app.repositories import settings as settings_repo

    for b in tdb.execute(select(Business)).scalars().all():
        row = settings_repo.get_by_business(tdb, b.id)
        assert row is not None
        assert row.branding == {} and row.operational == {}


def test_settings_retrieval_and_update(tdb) -> None:
    from app.models.business import Business
    from app.services import settings as settings_service

    prime = tdb.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    assert prime is not None
    row = settings_service.get_settings(tdb, business_id=prime.id)
    assert row.business_id == prime.id
    updated = settings_service.update_settings(
        tdb,
        business_id=prime.id,
        payload={"branding": {"display_name": "Prime", "primary_color": "#112233"}},
    )
    assert updated.branding["display_name"] == "Prime"


def test_invalid_settings_rejected(tdb) -> None:
    from app.models.business import Business
    from app.services import settings as settings_service

    prime = tdb.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    assert prime is not None
    with pytest.raises(ValueError):
        settings_service.update_settings(
            tdb, business_id=prime.id, payload={"branding": {"primary_color": "not-a-color"}}
        )
    with pytest.raises(ValueError):
        settings_service.update_settings(
            tdb, business_id=prime.id, payload={"nope": {}}
        )
    with pytest.raises(ValueError):
        settings_service.update_settings(
            tdb, business_id=prime.id, payload={"localization": {"currency": "XX"}}
        )
    with pytest.raises(ValueError):
        settings_service.update_settings(
            tdb, business_id=prime.id, payload={"hours": {"weekly": {"funday": {}}}}
        )


def test_seed_is_idempotent(tdb) -> None:
    from sqlalchemy import func, select

    from app.models.business import Business
    from app.services import seed

    seed.seed_development(tdb)
    seed.seed_development(tdb)
    count = tdb.execute(select(func.count()).select_from(Business)).scalar()
    assert count == 2  # prime + nest only; seed never duplicates
