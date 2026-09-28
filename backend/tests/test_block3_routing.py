"""Block 3 — lead routing between Prime / Nest.

Routing determines the OWNING business + auditable lineage; it never
grants cross-business visibility (see test_block3_isolation).
"""

from __future__ import annotations

import pytest

from tests.block2_support import auth_headers, b2, login_as, public_lead_payload  # noqa: F401


def _prime_lead(client, headers, **overrides):
    payload = {"display_name": "Route Me", "phone": "+919876543210"}
    payload.update(overrides)
    return client.post("/api/v1/leads", json=payload, headers=headers)


def test_public_prime_lead_owned_by_prime(b2) -> None:
    resp = b2["client"].post("/api/v1/public/prime/leads", json=public_lead_payload())
    assert resp.status_code == 201, resp.text
    lead_id = resp.json()["lead_id"]

    prime = auth_headers(b2["prime"]["access_token"])
    got = b2["client"].get(f"/api/v1/leads/{lead_id}", headers=prime)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["routed_by"] == "slug"
    assert "prime" in body["routing_reason"]
    assert body["routed_at"] is not None

    # Nest cannot see it (uniform 404).
    nest = auth_headers(b2["nest"]["access_token"])
    assert b2["client"].get(f"/api/v1/leads/{lead_id}", headers=nest).status_code == 404


def test_public_nest_lead_owned_by_nest(b2) -> None:
    resp = b2["client"].post("/api/v1/public/nest/leads", json=public_lead_payload())
    assert resp.status_code == 201, resp.text
    lead_id = resp.json()["lead_id"]

    nest = auth_headers(b2["nest"]["access_token"])
    got = b2["client"].get(f"/api/v1/leads/{lead_id}", headers=nest)
    assert got.status_code == 200, got.text
    assert got.json()["routed_by"] == "slug"

    prime = auth_headers(b2["prime"]["access_token"])
    assert b2["client"].get(f"/api/v1/leads/{lead_id}", headers=prime).status_code == 404


def test_staff_created_lead_has_routing_lineage(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    body = _prime_lead(b2["client"], h).json()
    assert body["routed_by"] == "staff"
    assert body["routing_reason"] != ""
    assert body["routed_at"] is not None


def test_transfer_owner_prime_to_nest(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    lead_id = _prime_lead(b2["client"], prime).json()["id"]

    resp = b2["client"].post(
        f"/api/v1/leads/{lead_id}/transfer",
        json={"target_business_slug": "nest", "reason": "Wants library seat, not gym."},
        headers=prime,
    )
    assert resp.status_code == 200, resp.text
    copy = resp.json()
    assert copy["routed_by"] == "staff"
    assert "prime" in copy["routing_reason"].lower() or "ransfer" in copy["routing_reason"]

    # Source row preserved in Prime.
    assert b2["client"].get(f"/api/v1/leads/{lead_id}", headers=prime).status_code == 200
    # Copy visible in Nest with the same phone.
    nest = auth_headers(b2["nest"]["access_token"])
    listed = b2["client"].get("/api/v1/leads?search=%2B919876543210", headers=nest)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1

    # Audit trails exist in BOTH businesses.
    for headers in (prime, nest):
        events = b2["client"].get("/api/v1/audit-events?action=lead.transferred", headers=headers)
        assert events.status_code == 200, events.text
        assert events.json()["total"] >= 1


def test_transfer_requires_reason_and_known_target(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    lead_id = _prime_lead(b2["client"], prime).json()["id"]

    short = b2["client"].post(
        f"/api/v1/leads/{lead_id}/transfer",
        json={"target_business_slug": "nest", "reason": "short"},
        headers=prime,
    )
    assert short.status_code == 422, short.text

    unknown = b2["client"].post(
        f"/api/v1/leads/{lead_id}/transfer",
        json={"target_business_slug": "nope", "reason": "A proper reason here."},
        headers=prime,
    )
    assert unknown.status_code == 404, unknown.text

    same = b2["client"].post(
        f"/api/v1/leads/{lead_id}/transfer",
        json={"target_business_slug": "prime", "reason": "A proper reason here."},
        headers=prime,
    )
    assert same.status_code == 409, same.text


def test_transfer_denied_for_staff_manager_viewer(b2) -> None:
    prime_owner = auth_headers(b2["prime"]["access_token"])
    lead_id = _prime_lead(b2["client"], prime_owner).json()["id"]
    payload = {"target_business_slug": "nest", "reason": "A proper reason here."}

    for role in ("MANAGER", "STAFF", "VIEWER"):
        tokens = login_as(
            b2["client"], b2["db"],
            email=f"transfer-{role.lower()}@example.com", slug="prime", role=role,
        )
        h = auth_headers(tokens["access_token"])
        resp = b2["client"].post(
            f"/api/v1/leads/{lead_id}/transfer", json=payload, headers=h
        )
        assert resp.status_code == 403, (role, resp.text)

    # The lead was NOT copied to Nest.
    nest = auth_headers(b2["nest"]["access_token"])
    listed = b2["client"].get("/api/v1/leads", headers=nest)
    assert listed.json()["total"] == 0


def test_transfer_admin_allowed(b2) -> None:
    tokens = login_as(
        b2["client"], b2["db"], email="transfer-admin@example.com",
        slug="prime", role="ADMIN",
    )
    h = auth_headers(tokens["access_token"])
    lead_id = _prime_lead(b2["client"], h).json()["id"]
    resp = b2["client"].post(
        f"/api/v1/leads/{lead_id}/transfer",
        json={"target_business_slug": "nest", "reason": "Admin-approved handoff."},
        headers=h,
    )
    assert resp.status_code == 200, resp.text


def test_intent_routing_rules() -> None:
    from tests.block1_support import make_test_session

    engine, db = make_test_session()
    try:
        from app.services import lead_routing as routing

        prime_id, reason = routing.resolve_by_intent(db, intent="I want gym trial membership")
        assert "prime" in reason
        nest_id, _ = routing.resolve_by_intent(db, intent="Need a quiet study seat for UPSC")
        assert prime_id != nest_id

        # Ambiguous without default -> explicit error (never guess silently).
        with pytest.raises(Exception, match="Prime Fitness or Nest Library"):
            routing.resolve_by_intent(db, intent="hello there")

        # Ambiguous with default -> default + review reason.
        did, dreason = routing.resolve_by_intent(
            db, intent="hello there", default_slug="nest"
        )
        assert did == nest_id
        assert "Ambiguous" in dreason
    finally:
        db.close()
        engine.dispose()
