"""Shared fixtures for Blocks 8-12 tests (SQLite-backed integration)."""

from __future__ import annotations

import pytest

from tests.block1_support import TEST_PASSWORD, add_test_membership, create_test_user, make_test_session


@pytest.fixture
def env812():
    from app.api.deps import get_db
    from app.main import create_app
    from fastapi.testclient import TestClient

    engine, db = make_test_session()
    try:
        users = {}
        for slug in ("prime", "nest"):
            for role in ("OWNER", "STAFF", "VIEWER"):
                email = f"b812-{slug}-{role.lower()}@example.com"
                user = create_test_user(db, email=email)
                add_test_membership(db, user_id=user.id, business_slug=slug,
                                    role_name=role, is_default=True)
                users[(slug, role)] = user
        app = create_app()

        def _override():
            yield db

        app.dependency_overrides[get_db] = _override
        client = TestClient(app, raise_server_exceptions=False)
        tokens = {}
        for (slug, role), user in users.items():
            resp = client.post("/api/v1/auth/login",
                               json={"email": user.email, "password": TEST_PASSWORD})
            assert resp.status_code == 200, resp.text
            tokens[(slug, role)] = resp.json()
        yield {"engine": engine, "db": db, "client": client,
               "users": users, "tokens": tokens}
    finally:
        db.close()
        engine.dispose()
