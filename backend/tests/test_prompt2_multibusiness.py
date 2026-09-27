"""Prompt 2 — multi-business foundation verification matrix.

Covers the §20 matrix (auth / membership / switching / isolation / owner /
tampering) plus database routing, public slug routing, migration 0008,
seed idempotency, health/readiness, and worker job-scope validation.

All tests run on isolated in-memory SQLite (no destructive operations on
real data). The API contract is unchanged: same routes, same schemas.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from tests.block1_support import (
    TEST_PASSWORD,
    add_test_membership,
    auth_headers,
    create_test_user,
    login_token,
    make_auth_client,
    make_test_session,
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def tdb():
    engine, db = make_test_session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def api(tdb):
    return make_auth_client(tdb)


def _biz(tdb, slug):
    from app.models.business import Business

    return tdb.execute(select(Business).where(Business.slug == slug)).scalars().one()


def _tok(api, email, password=TEST_PASSWORD, slug=None):
    return login_token(api, email=email, password=password, business_slug=slug)[
        "access_token"
    ]


# --------------------------------------------------------------------------
# A. Authentication
# --------------------------------------------------------------------------


class TestAuthentication:
    def test_invalid_password_rejected(self, api, tdb):
        create_test_user(tdb, email="a1@example.com")
        r = api.post(
            "/api/v1/auth/login",
            json={"email": "a1@example.com", "password": "WrongPass-9999!"},
        )
        assert r.status_code == 401

    def test_inactive_user_rejected(self, api, tdb):
        create_test_user(tdb, email="a2@example.com", is_active=False)
        r = api.post(
            "/api/v1/auth/login",
            json={"email": "a2@example.com", "password": TEST_PASSWORD},
        )
        assert r.status_code == 401

    def test_invalid_token_rejected(self, api):
        r = api.get("/api/v1/auth/me", headers=auth_headers("not-a-token"))
        assert r.status_code == 401

    def test_expired_token_rejected(self, api, tdb):
        from app.core import security
        from app.core.config import get_settings

        user = create_test_user(tdb, email="a3@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        prime = _biz(tdb, "prime")
        token, _, _ = security.create_access_token(
            user_id=user.id,
            business_id=prime.id,
            secret=get_settings().effective_jwt_secret,
            algorithm="HS256",
            expires_minutes=-5,
        )
        r = api.get("/api/v1/auth/me", headers=auth_headers(token))
        assert r.status_code == 401

    def test_refresh_rotation_and_reuse_kills_family(self, api, tdb):
        user = create_test_user(tdb, email="a4@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        body = login_token(api, email="a4@example.com", business_slug="prime")
        r1 = api.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
        assert r1.status_code == 200, r1.text
        rotated = r1.json()["refresh_token"]
        # Reuse of the ORIGINAL (now revoked) token is rejected...
        r2 = api.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
        assert r2.status_code in (400, 401), r2.text
        # ...and the family is dead: even the rotated token no longer works.
        r3 = api.post("/api/v1/auth/refresh", json={"refresh_token": rotated})
        assert r3.status_code in (400, 401), r3.text


# --------------------------------------------------------------------------
# B. Business membership
# --------------------------------------------------------------------------


class TestMembership:
    def test_valid_membership_allowed(self, api, tdb):
        user = create_test_user(tdb, email="m1@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        token = _tok(api, "m1@example.com", slug="prime")
        r = api.get("/api/v1/leads", headers=auth_headers(token))
        assert r.status_code == 200, r.text

    def test_missing_membership_denied(self, api, tdb):
        user = create_test_user(tdb, email="m2@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        token = _tok(api, "m2@example.com", slug="prime")
        # Token is prime-bound; forging a nest lead id must 404 (no oracle).
        nest_owner = create_test_user(tdb, email="m2n@example.com")
        add_test_membership(tdb, user_id=nest_owner.id, business_slug="nest", role_name="OWNER")
        nest_tok = _tok(api, "m2n@example.com", slug="nest")
        lead = api.post(
            "/api/v1/leads",
            json={"display_name": "Nest Only", "phone": "+911111110002"},
            headers=auth_headers(nest_tok),
        )
        assert lead.status_code == 201, lead.text
        r = api.get(f"/api/v1/leads/{lead.json()['id']}", headers=auth_headers(token))
        assert r.status_code == 404

    def test_revoked_membership_denied(self, api, tdb):
        user = create_test_user(tdb, email="m3@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        token = _tok(api, "m3@example.com", slug="prime")
        assert api.get("/api/v1/leads", headers=auth_headers(token)).status_code == 200
        # Revoke mid-session: the NEXT request fails (membership re-checked).
        from app.repositories import memberships as membership_repo

        prime = _biz(tdb, "prime")
        ms = membership_repo.get_membership(tdb, user_id=user.id, business_id=prime.id)
        assert ms is not None
        ms.status = "revoked"
        tdb.commit()
        r = api.get("/api/v1/leads", headers=auth_headers(token))
        assert r.status_code in (401, 403), r.text


# --------------------------------------------------------------------------
# C. Business switching
# --------------------------------------------------------------------------


class TestSwitching:
    def _dual(self, tdb, api, email="s-dual@example.com"):
        user = create_test_user(tdb, email=email)
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="OWNER")
        add_test_membership(tdb, user_id=user.id, business_slug="nest", role_name="OWNER")
        return user

    def test_authorized_switch(self, api, tdb):
        self._dual(tdb, api)
        token = _tok(api, "s-dual@example.com", slug="prime")
        r = api.post(
            "/api/v1/auth/switch-business",
            json={"business_id": "nest"},
            headers=auth_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["business"]["slug"] == "nest"

    def test_unauthorized_switch_denied(self, api, tdb):
        user = create_test_user(tdb, email="s-single@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        token = _tok(api, "s-single@example.com", slug="prime")
        r = api.post(
            "/api/v1/auth/switch-business",
            json={"business_id": "nest"},
            headers=auth_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_nonexistent_business_denied(self, api, tdb):
        self._dual(tdb, api, email="s-dual2@example.com")
        token = _tok(api, "s-dual2@example.com", slug="prime")
        r = api.post(
            "/api/v1/auth/switch-business",
            json={"business_id": "no-such-business"},
            headers=auth_headers(token),
        )
        assert r.status_code in (403, 404), r.text

    def test_inactive_business_denied(self, api, tdb):
        from app.services import business as business_service

        business_service.create_business(
            tdb, slug="dormant", name="Dormant", business_type="other", status="inactive"
        )
        user = create_test_user(tdb, email="s-dorm@example.com")
        prime = _biz(tdb, "prime")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        # Inactive business is not even listable/switchable.
        token = _tok(api, "s-dorm@example.com", slug="prime")
        r = api.post(
            "/api/v1/auth/switch-business",
            json={"business_id": "dormant"},
            headers=auth_headers(token),
        )
        assert r.status_code == 403, r.text
        assert prime.slug == "prime"


# --------------------------------------------------------------------------
# D. Resource isolation (Prime <-> Nest)
# --------------------------------------------------------------------------


class TestResourceIsolation:
    @pytest.fixture
    def pair(self, api, tdb):
        prime_user = create_test_user(tdb, email="iso-prime@example.com")
        add_test_membership(tdb, user_id=prime_user.id, business_slug="prime", role_name="OWNER")
        nest_user = create_test_user(tdb, email="iso-nest@example.com")
        add_test_membership(tdb, user_id=nest_user.id, business_slug="nest", role_name="OWNER")
        return {
            "prime": auth_headers(_tok(api, "iso-prime@example.com", slug="prime")),
            "nest": auth_headers(_tok(api, "iso-nest@example.com", slug="nest")),
        }

    def _mk_lead(self, api, headers, name, phone):
        r = api.post(
            "/api/v1/leads",
            json={"display_name": name, "phone": phone},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()

    def test_lead_isolation(self, api, pair):
        nest_lead = self._mk_lead(api, pair["nest"], "Nest Lead", "+911111110011")
        assert api.get(f"/api/v1/leads/{nest_lead['id']}", headers=pair["prime"]).status_code == 404
        assert (
            api.patch(
                f"/api/v1/leads/{nest_lead['id']}", json={"display_name": "Hijacked"},
                headers=pair["prime"],
            ).status_code
            in (403, 404)
        )
        prime_lead = self._mk_lead(api, pair["prime"], "Prime Lead", "+911111110012")
        assert api.get(f"/api/v1/leads/{prime_lead['id']}", headers=pair["nest"]).status_code == 404

    def test_customer_and_payment_isolation(self, api, pair):
        contact = api.post(
            "/api/v1/contacts",
            json={"first_name": "Nest", "last_name": "Contact", "phone": "+911111110020"},
            headers=pair["nest"],
        )
        assert contact.status_code == 201, contact.text
        cust = api.post(
            "/api/v1/customers",
            json={"contact_id": contact.json()["id"]},
            headers=pair["nest"],
        )
        assert cust.status_code == 201, cust.text
        cid = cust.json()["id"]
        assert api.get(f"/api/v1/customers/{cid}", headers=pair["prime"]).status_code == 404

        member = api.post(
            "/api/v1/members",
            json={"display_name": "Nest Member", "phone": "+911111110022"},
            headers=pair["nest"],
        ).json()
        pay = api.post(
            "/api/v1/payments",
            json={"amount": "500.00", "currency": "INR", "method": "upi",
                  "member_id": member["id"]},
            headers=pair["nest"],
        )
        assert pay.status_code == 201, pay.text
        assert (
            api.get(f"/api/v1/payments/{pay.json()['id']}", headers=pair["prime"]).status_code
            == 404
        )

    def test_analytics_scoped(self, api, pair, tdb):
        # Each side's dashboard reflects its own context only.
        rp = api.get("/api/v1/dashboard/overview", headers=pair["prime"]).json()
        rn = api.get("/api/v1/dashboard/overview", headers=pair["nest"]).json()
        assert rp["business_id"] == str(_biz(tdb, "prime").id)
        assert rn["business_id"] == str(_biz(tdb, "nest").id)
        assert rp["business_id"] != rn["business_id"]


# --------------------------------------------------------------------------
# E. Unified owner
# --------------------------------------------------------------------------


class TestUnifiedOwner:
    def test_owner_identity_and_grants(self, tdb):
        from app.repositories import memberships as membership_repo
        from app.repositories import users as user_repo

        owner = user_repo.get_by_email(tdb, "owner@prime-nest-dashboard.com")
        assert owner is not None and owner.is_active and owner.is_verified
        # Exactly ONE canonical identity.
        assert (
            tdb.execute(
                select(user_repo.User).where(
                    user_repo.User.email == "owner@prime-nest-dashboard.com"
                )
            ).scalars()
        ).all().__len__() == 1
        grants = {
            m.business.slug
            for m in membership_repo.list_user_memberships(tdb, user_id=owner.id)
            if m.status == "active"
        }
        assert {"prime", "nest"} <= grants

    def test_owner_authenticates_and_reaches_both(self, api):
        body = login_token(api, email="owner@prime-nest-dashboard.com",
                           password="OwnerDemo123!", business_slug="prime")
        assert body["business"]["slug"] == "prime"
        prime_headers = auth_headers(body["access_token"])
        assert api.get("/api/v1/leads", headers=prime_headers).status_code == 200
        r = api.post(
            "/api/v1/auth/switch-business", json={"business_id": "nest"},
            headers=prime_headers,
        )
        assert r.status_code == 200, r.text
        assert api.get("/api/v1/leads",
                       headers=auth_headers(r.json()["access_token"])).status_code == 200

    def test_owner_combined_uses_only_grants(self, api, tdb):
        from app.services import business as business_service

        business_service.create_business(
            tdb, slug="gamma", name="Gamma", business_type="other", status="active"
        )
        token = _tok(api, "owner@prime-nest-dashboard.com",
                     password="OwnerDemo123!", slug="prime")
        headers = auth_headers(token)
        body = api.get("/api/v1/owner/combined", headers=headers).json()
        slugs = {b["business"]["slug"] for b in body["businesses"]}
        assert slugs == {"prime", "nest"}
        assert "gamma" not in slugs
        # Explicit unassigned scope is denied.
        r = api.get("/api/v1/owner/combined", params={"scope": "gamma"}, headers=headers)
        assert r.status_code == 403, r.text
        # Switch to the unassigned business is denied too.
        r = api.post("/api/v1/auth/switch-business", json={"business_id": "gamma"},
                     headers=headers)
        assert r.status_code == 403, r.text

    def test_combined_access_is_audited(self, api, tdb):
        from app.models.audit_event import AuditEvent

        token = _tok(api, "owner@prime-nest-dashboard.com",
                     password="OwnerDemo123!", slug="prime")
        r = api.get("/api/v1/owner/combined", headers=auth_headers(token))
        assert r.status_code == 200, r.text
        rows = (
            tdb.execute(
                select(AuditEvent).where(AuditEvent.entity_type == "owner_combined")
            ).scalars()
        ).all()
        assert len(rows) >= 1
        assert all("password" not in str((e.meta or {})) for e in rows)


# --------------------------------------------------------------------------
# F. Client tampering never bypasses membership authorization
# --------------------------------------------------------------------------


class TestClientTampering:
    @pytest.fixture
    def ctx(self, api, tdb):
        prime_user = create_test_user(tdb, email="tamper-prime@example.com")
        add_test_membership(
            tdb, user_id=prime_user.id, business_slug="prime", role_name="STAFF"
        )
        nest = _biz(tdb, "nest")
        return {
            "headers": auth_headers(_tok(api, "tamper-prime@example.com", slug="prime")),
            "nest_id": str(nest.id),
        }

    def test_body_business_id_ignored(self, api, tdb, ctx):
        # Staff schemas forbid unknown fields: a forged business_id is
        # rejected outright (422) — never honored, never a bypass.
        prime = _biz(tdb, "prime")
        r = api.post(
            "/api/v1/leads",
            json={"display_name": "Tamper", "phone": "+911111110031",
                  "business_id": ctx["nest_id"]},
            headers=ctx["headers"],
        )
        assert r.status_code == 422, r.text
        from app.models.lead import Lead

        assert (
            tdb.execute(
                select(Lead).where(
                    Lead.business_id == _biz(tdb, "nest").id,
                    Lead.display_name == "Tamper",
                )
            ).scalars()
        ).all() == []
        assert prime.slug == "prime"

    def test_query_business_id_ignored(self, api, ctx):
        r = api.get(
            "/api/v1/leads",
            params={"business_id": ctx["nest_id"]},
            headers=ctx["headers"],
        )
        assert r.status_code == 200, r.text
        assert all(item["business_id"] != ctx["nest_id"] for item in r.json().get("items", []))

    def test_header_database_ignored(self, api, ctx):
        headers = dict(ctx["headers"])
        headers["X-Database"] = "nest_db"
        headers["X-Business-Id"] = ctx["nest_id"]
        r = api.get("/api/v1/leads", headers=headers)
        assert r.status_code == 200, r.text

    def test_forged_jwt_signature_rejected(self, api, tdb):
        from app.core import security

        user = create_test_user(tdb, email="tamper-jwt@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        prime = _biz(tdb, "prime")
        forged, _, _ = security.create_access_token(
            user_id=user.id, business_id=prime.id,
            secret="wrong-secret", algorithm="HS256",
        )
        assert api.get("/api/v1/leads", headers=auth_headers(forged)).status_code == 401

    def test_forged_business_claim_rejected(self, api, tdb):
        from app.core import security
        from app.core.config import get_settings

        user = create_test_user(tdb, email="tamper-claim@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="prime", role_name="STAFF")
        forged, _, _ = security.create_access_token(
            user_id=user.id, business_id=uuid.uuid4(),
            secret=get_settings().effective_jwt_secret, algorithm="HS256",
        )
        r = api.get("/api/v1/leads", headers=auth_headers(forged))
        assert r.status_code in (401, 403), r.text


# --------------------------------------------------------------------------
# G. Database routing (trusted, fail-closed, no client control)
# --------------------------------------------------------------------------


class TestDatabaseRouting:
    def test_registry_mapping(self, tdb):
        prime, nest = _biz(tdb, "prime"), _biz(tdb, "nest")
        assert (prime.external_id, prime.database_key) == ("prime-fitness-001", "prime_db")
        assert (nest.external_id, nest.database_key) == ("nest-library-001", "nest_db")

    def test_context_carries_database_key(self, tdb):
        from app.services import authorization as authz
        from app.services.business_context import BusinessResolver
        from app.repositories import memberships as membership_repo
        from app.repositories import users as user_repo

        owner = user_repo.get_by_email(tdb, "owner@prime-nest-dashboard.com")
        assert owner is not None
        for slug, key in (("prime", "prime_db"), ("nest", "nest_db")):
            business = _biz(tdb, slug)
            ms = membership_repo.get_membership(tdb, user_id=owner.id, business_id=business.id)
            bctx = BusinessResolver.for_staff(
                authz.build_context(tdb, user=owner, business=business, membership=ms)
            )
            assert bctx.database_key == key
            assert bctx.business_slug == slug
            assert bctx.access_scope == "business"

    def test_unknown_mapping_fails_closed(self, tdb):
        from app.core import db_routing as routing

        with pytest.raises(routing.DatabaseRoutingError):
            routing.normalize_database_key("customer_db")
        with pytest.raises(routing.DatabaseRoutingError):
            routing.normalize_database_key("")
        with pytest.raises(routing.DatabaseRoutingError):
            routing.normalize_database_key(None)

    def test_business_without_mapping_cannot_serve(self, api, tdb):
        from app.services import business as business_service

        business_service.create_business(
            tdb, slug="unmapped", name="Unmapped", business_type="other", status="active"
        )
        user = create_test_user(tdb, email="unmapped@example.com")
        add_test_membership(tdb, user_id=user.id, business_slug="unmapped", role_name="STAFF")
        # Login succeeds (identity + membership valid) but NO staff route works:
        # fail closed, never a fallback database.
        body = login_token(api, email="unmapped@example.com", business_slug="unmapped")
        r = api.get("/api/v1/leads", headers=auth_headers(body["access_token"]))
        assert r.status_code == 403, r.text

    def test_no_client_controlled_routing_inputs(self):
        """No request input may select a database (real extraction patterns)."""
        import pathlib
        import re

        forbidding = re.compile(
            r"headers\.get\(\s*[\"']x-database[\"']"
            r"|headers\[\s*[\"']x-database[\"']"
            r"|body\.get\(\s*[\"']database_(url|name)[\"']"
            r"|query_params\.get\(\s*[\"']database_(url|name)[\"']",
            re.IGNORECASE,
        )
        offenders = [
            str(path) for path in pathlib.Path("app").rglob("*.py")
            if forbidding.search(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    def test_tenant_redis_keys_namespaced(self, tdb):
        from app.core import db_routing as routing

        prime, nest = _biz(tdb, "prime"), _biz(tdb, "nest")
        kp = routing.tenant_redis_key(prime.id, "ratelimit", "leads")
        kn = routing.tenant_redis_key(nest.id, "ratelimit", "leads")
        assert kp != kn and str(prime.id) in kp and str(nest.id) in kn


# --------------------------------------------------------------------------
# H. Public slug routing
# --------------------------------------------------------------------------


class TestPublicRouting:
    def test_prime_intake_stays_prime(self, api, tdb):
        r = api.post(
            "/api/v1/public/prime/leads",
            json={"name": "Web Prime", "phone": "+911111110041"},
        )
        assert r.status_code == 201, r.text
        prime = _biz(tdb, "prime")
        from app.models.lead import Lead

        lead = tdb.get(Lead, uuid.UUID(r.json()["lead_id"]))
        assert lead is not None and lead.business_id == prime.id

    def test_nest_intake_stays_nest(self, api, tdb):
        r = api.post(
            "/api/v1/public/nest/leads",
            json={"name": "Web Nest", "phone": "+911111110042"},
        )
        assert r.status_code == 201, r.text
        nest = _biz(tdb, "nest")
        from app.models.lead import Lead

        lead = tdb.get(Lead, uuid.UUID(r.json()["lead_id"]))
        assert lead is not None and lead.business_id == nest.id

    def test_unknown_slug_safe_failure(self, api):
        assert api.get("/api/v1/public/nope/config").status_code == 404
        assert (
            api.post(
                "/api/v1/public/nope/leads",
                json={"name": "Nobody", "phone": "+911111110043"},
            ).status_code
            == 404
        )

    def test_inactive_business_safe_failure(self, api, tdb):
        from app.services import business as business_service

        business_service.create_business(
            tdb, slug="shuttered", name="Shuttered", business_type="other", status="inactive"
        )
        assert api.get("/api/v1/public/shuttered/config").status_code == 404


# --------------------------------------------------------------------------
# I. Migration 0008 (scratch, non-destructive)
# --------------------------------------------------------------------------


class TestMigration0008:
    def test_chain_is_linear_single_head(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert list(heads) == ["0008_multibusiness_foundation"], heads

    def test_upgrade_backfills_registry_on_scratch(self):
        import importlib.util

        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        # Legacy-shaped businesses table WITHOUT the Prompt 2 columns.
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE businesses (id CHAR(32) NOT NULL PRIMARY KEY, "
                "slug VARCHAR(64) NOT NULL UNIQUE, name VARCHAR(200) NOT NULL, "
                "business_type VARCHAR(32) NOT NULL DEFAULT 'other', "
                "status VARCHAR(32) NOT NULL DEFAULT 'active', "
                "is_active BOOLEAN NOT NULL DEFAULT 1)"
            )
            conn.exec_driver_sql(
                "INSERT INTO businesses (id, slug, name) VALUES "
                "('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'prime', 'Prime Fitness'), "
                "('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'nest', 'Nest Library'), "
                "('cccccccccccccccccccccccccccccccc', 'other', 'Other Biz')"
            )
        spec = importlib.util.spec_from_file_location(
            "rev0008", "migrations/versions/0008_multibusiness_foundation.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mod.upgrade()
        from sqlalchemy import MetaData, Table, text

        with engine.connect() as conn:
            # Fresh reflection: the legacy-shaped table plus migrated columns.
            table = Table("businesses", MetaData(), autoload_with=conn)
            assert {"external_id", "database_key", "config_ref"} <= set(table.columns.keys())
            assert any(
                ix.unique and list(ix.columns) == [table.c.external_id]
                for ix in table.indexes
            )
            rows = {
                row.slug: (row.external_id, row.database_key)
                for row in conn.execute(
                    text("SELECT slug, external_id, database_key FROM businesses")
                ).mappings()
            }
            assert rows["prime"] == ("prime-fitness-001", "prime_db")
            assert rows["nest"] == ("nest-library-001", "nest_db")
            # Non-canonical rows are untouched (fail-closed, not reassigned).
            assert rows["other"] == (None, "")
        engine.dispose()


# --------------------------------------------------------------------------
# J. Seed idempotency
# --------------------------------------------------------------------------


class TestSeedIdempotency:
    def test_reseed_creates_nothing_duplicate(self, tdb):
        from app.repositories import memberships as membership_repo
        from app.repositories import users as user_repo
        from app.services import seed as seed_service

        owner = user_repo.get_by_email(tdb, "owner@prime-nest-dashboard.com")
        assert owner is not None
        before_ms = len(
            membership_repo.list_user_memberships(tdb, user_id=owner.id)
        )
        seed_service.seed_development(tdb)
        seed_service.seed_development(tdb)
        owners = (
            tdb.execute(
                select(user_repo.User).where(
                    user_repo.User.email == "owner@prime-nest-dashboard.com"
                )
            ).scalars()
        ).all()
        assert len(owners) == 1
        after_ms = len(membership_repo.list_user_memberships(tdb, user_id=owner.id))
        assert after_ms == before_ms == 2

    def test_owner_secret_never_plaintext(self, tdb):
        from app.models.user import User

        row = (
            tdb.execute(
                select(User).where(User.email == "owner@prime-nest-dashboard.com")
            ).scalars()
        ).one()
        assert "OwnerDemo123!" not in row.password_hash
        assert row.password_hash.startswith("$argon2")


# --------------------------------------------------------------------------
# K. Health / readiness + contract freeze
# --------------------------------------------------------------------------


class TestOps:
    def test_ready_reports_per_database(self, api):
        r = api.get("/ready")
        # Real SQLite session behind the override: ready.
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["database"] == "up"
        assert set(body["databases"]) == {"platform_db", "prime_db", "nest_db"}
        assert set(body["databases"].values()) <= {"up", "down", "shared"}

    def test_route_contract_unchanged(self):
        from app.main import create_app

        app = create_app()
        # Routers resolve lazily in app.routes on newer FastAPI: assert via
        # the OpenAPI schema (same technique as test_health).
        paths = app.openapi()["paths"]
        assert "/api/v1/auth/switch-business" in paths
        assert "/api/v1/auth/businesses" in paths
        assert "/api/v1/owner/combined" in paths
        assert "/api/v1/public/{slug}/leads" in paths
        assert "/health" in {getattr(r, "path", "") for r in app.routes}
        assert "/ready" in {getattr(r, "path", "") for r in app.routes}


# --------------------------------------------------------------------------
# L. Worker / scheduler job scope
# --------------------------------------------------------------------------


class TestWorkerScope:
    def test_valid_scope_resolves(self, tdb):
        from app.core import db_routing as routing

        prime = _biz(tdb, "prime")
        business = routing.validate_business_job_scope(tdb, business_id=prime.id)
        assert business.slug == "prime" and business.database_key == "prime_db"

    def test_invalid_scopes_rejected(self, tdb):
        from app.core import db_routing as routing
        from app.services import business as business_service

        with pytest.raises(routing.DatabaseRoutingError):
            routing.validate_business_job_scope(tdb, business_id=uuid.uuid4())
        with pytest.raises(routing.DatabaseRoutingError):
            routing.validate_business_job_scope(tdb, business_id="not-a-uuid")
        dormant = business_service.create_business(
            tdb, slug="dormant", name="Dormant", business_type="other", status="inactive"
        )
        with pytest.raises(routing.DatabaseRoutingError):
            routing.validate_business_job_scope(tdb, business_id=dormant.id)

    def test_sweep_skips_invalid_scope_without_fallback(self, tdb):
        from app.core.config import get_settings
        from app.services import scheduler as scheduler_service

        summary = scheduler_service.run_business_sweep(
            tdb, get_settings(), business_id=uuid.uuid4()
        )
        assert summary.get("skipped") == "invalid business scope"
        assert "database_key" not in summary
