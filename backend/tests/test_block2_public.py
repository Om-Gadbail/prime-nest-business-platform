"""Block 2 — public intake tests (leads + bookings, anonymous, adversarial)."""

from __future__ import annotations

import pytest

from tests.block2_support import (  # noqa: F401
    auth_headers,
    b2,
    enable_rate_limit,
    new_idem_key,
    public_booking_payload,
    public_lead_payload,
)


def _lead(client, slug="prime", headers=None, **overrides):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    return client.post(
        f"/api/v1/public/{slug}/leads", json=public_lead_payload(**overrides),
        headers=hdrs,
    )


def test_public_config(b2) -> None:
    resp = b2["client"].get("/api/v1/public/prime/config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == "prime" and body["lead_capture_enabled"] is True
    assert body["booking_enabled"] is True
    assert "id" not in body  # no internal database IDs
    assert b2["client"].get("/api/v1/public/nope/config").status_code == 404


def test_valid_public_lead_creates_records(b2) -> None:
    resp = _lead(b2["client"], headers={"Idempotency-Key": new_idem_key()})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["success"] is True and body["status"] == "received"
    assert body["lead_id"] and body["lead_id"] != "received"
    assert "enquiry" in body["message"].lower() or "received" in body["message"].lower()
    # No secret/internal leakage.
    for forbidden in ("business_id", "user_id", "password", "token", "secret"):
        assert forbidden not in body
    # Staff can see the lead; activity + notification exist.
    h = auth_headers(b2["prime"]["access_token"])
    got = b2["client"].get(f"/api/v1/leads/{body['lead_id']}", headers=h)
    assert got.status_code == 200 and got.json()["status"] == "new"
    acts = b2["client"].get(
        f"/api/v1/leads/{body['lead_id']}/activities", headers=h
    ).json()
    assert acts["total"] >= 1  # intake history recorded
    unread = b2["client"].get("/api/v1/notifications/unread-count", headers=h).json()
    assert unread["unread"] >= 1
    # Request ID correlation present.
    assert resp.headers.get("X-Request-ID")


def test_public_lead_nest_isolation(b2) -> None:
    resp = _lead(b2["client"], slug="nest", headers={"Idempotency-Key": new_idem_key()})
    assert resp.status_code == 201, resp.text
    lead_id = resp.json()["lead_id"]
    # Prime owner must not see the Nest lead (behaves as nonexistent).
    ph = auth_headers(b2["prime"]["access_token"])
    assert b2["client"].get(f"/api/v1/leads/{lead_id}", headers=ph).status_code == 404


def test_public_lead_validation(b2) -> None:
    assert _lead(b2["client"], name="A").status_code == 422  # too short
    assert _lead(b2["client"], phone="123").status_code == 422
    assert _lead(b2["client"], email="bad").status_code == 422
    assert _lead(b2["client"], phone=None, email=None).status_code == 422
    assert _lead(b2["client"], message="x" * 2001).status_code == 422
    # Missing name entirely.
    payload = public_lead_payload()
    del payload["name"]
    resp = b2["client"].post("/api/v1/public/prime/leads", json=payload)
    assert resp.status_code == 422


def test_public_lead_unknown_slug_and_inactive(b2) -> None:
    assert _lead(b2["client"], slug="no-such-biz").status_code == 404
    assert _lead(b2["client"], slug="prime'; DROP TABLE leads;--").status_code == 404
    # Deactivate prime -> uniform 404 (no existence signal change).
    from app.models.business import Business
    from sqlalchemy import select

    db = b2["db"]
    biz = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
    biz.is_active = False
    db.commit()
    try:
        assert _lead(b2["client"]).status_code == 404
        assert b2["client"].get("/api/v1/public/prime/config").status_code == 404
    finally:
        biz.is_active = True
        db.commit()


def test_public_lead_feature_disabled(b2) -> None:
    from app.services import settings as settings_service

    db = b2["db"]
    prime_id = settings_service.get_settings(db, business_id=_prime_id(db)).business_id
    settings_service.update_settings(
        db, business_id=prime_id, payload={"operational": {"lead_capture_enabled": False}}
    )
    try:
        assert _lead(b2["client"]).status_code == 403
        assert b2["client"].get("/api/v1/public/prime/config").json()[
            "lead_capture_enabled"
        ] is False
    finally:
        settings_service.update_settings(
            db, business_id=prime_id,
            payload={"operational": {"lead_capture_enabled": True}},
        )


def _prime_id(db):
    from sqlalchemy import select

    from app.models.business import Business

    return db.execute(select(Business).where(Business.slug == "prime")).scalars().first().id


def test_public_lead_honeypot(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    before = b2["client"].get("/api/v1/leads", headers=h).json()["total"]
    resp = _lead(b2["client"], website_url="http://spam.example")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["success"] is True  # bots learn nothing
    assert body["lead_id"] == "received"  # nothing stored
    after = b2["client"].get("/api/v1/leads", headers=h).json()["total"]
    assert after == before


def test_public_lead_content_type_and_payload_limit(b2, monkeypatch) -> None:
    enable_rate_limit(monkeypatch)
    client = b2["client"]
    # Wrong content type -> 415 (guarded before body parsing).
    resp = client.post(
        "/api/v1/public/prime/leads", content="{}",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 415, resp.text
    # Oversized body -> 413 pre-parse (real 70KB JSON body).
    big = "x" * 70000
    resp = client.post(
        "/api/v1/public/prime/leads", content=big,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413, resp.text
    assert resp.headers.get("X-Request-ID")
    assert "Traceback" not in resp.text


def test_public_lead_rate_limit(b2, monkeypatch) -> None:
    enable_rate_limit(monkeypatch, public_requests=2, public_window=600)
    client = b2["client"]
    assert _lead(client).status_code == 201
    assert _lead(client).status_code == 201
    resp = _lead(client)
    assert resp.status_code == 429, resp.text
    assert resp.headers.get("Retry-After")
    assert resp.headers.get("X-Request-ID")


def test_public_lead_idempotency(b2) -> None:
    client = b2["client"]
    key = new_idem_key()
    first = _lead(client, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    second = _lead(client, headers={"Idempotency-Key": key})
    assert second.status_code == 201
    assert second.json()["lead_id"] == first.json()["lead_id"]
    # Same key + different payload -> 409, no second lead.
    h = auth_headers(b2["prime"]["access_token"])
    before = client.get("/api/v1/leads", headers=h).json()["total"]
    third = _lead(client, headers={"Idempotency-Key": key}, name="Someone Else")
    assert third.status_code == 409, third.text
    assert client.get("/api/v1/leads", headers=h).json()["total"] == before
    # Malformed keys rejected safely.
    assert _lead(client, headers={"Idempotency-Key": "short"}).status_code == 422
    assert _lead(
        client, headers={"Idempotency-Key": "bad key with spaces!!"}
    ).status_code == 422
    # Keys are scoped per business: same key on nest is independent.
    nest = _lead(client, slug="nest", headers={"Idempotency-Key": key})
    assert nest.status_code == 201
    assert nest.json()["lead_id"] != first.json()["lead_id"]
    # Works without any key (frontend always sends one, but it is optional).
    assert _lead(client).status_code == 201


def test_public_lead_no_enumeration_oracle(b2) -> None:
    """Existing vs new contact emails produce identical public responses."""
    first = _lead(b2["client"], email="oracle-same@example.com")
    second = _lead(b2["client"], email="oracle-same@example.com")
    assert first.status_code == second.status_code == 201
    assert second.json()["lead_id"] != first.json()["lead_id"]
    assert "exists" not in second.text.lower()


def test_valid_public_booking_is_requested(b2) -> None:
    resp = b2["client"].post(
        "/api/v1/public/prime/bookings", json=public_booking_payload(),
        headers={"Content-Type": "application/json", "Idempotency-Key": new_idem_key()},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "received"
    assert "confirm" in body["message"].lower()  # honest: confirmation pending
    assert "Booking confirmed" not in body["message"]
    h = auth_headers(b2["prime"]["access_token"])
    got = b2["client"].get(f"/api/v1/bookings/{body['booking_id']}", headers=h)
    assert got.status_code == 200
    assert got.json()["status"] == "requested"  # never auto-confirmed


def test_public_booking_guards(b2, monkeypatch) -> None:
    client = b2["client"]
    payload = public_booking_payload()
    # Honeypot fake success.
    resp = client.post(
        "/api/v1/public/prime/bookings",
        json={**payload, "website_url": "spam"},
    )
    assert resp.status_code == 201 and resp.json()["booking_id"] == "received"
    # Validation.
    assert client.post(
        "/api/v1/public/prime/bookings", json={**payload, "phone": None, "email": None}
    ).status_code == 422
    assert client.post(
        "/api/v1/public/prime/bookings", json={**payload, "booking_type": "vip-suite"}
    ).status_code == 422
    # Unknown slug.
    assert client.post(
        "/api/v1/public/ghost/bookings", json=payload
    ).status_code == 404
    # Idempotent replay.
    key = new_idem_key()
    hdrs = {"Idempotency-Key": key}
    first = client.post("/api/v1/public/prime/bookings", json=payload, headers=hdrs)
    second = client.post("/api/v1/public/prime/bookings", json=payload, headers=hdrs)
    assert first.status_code == second.status_code == 201
    assert first.json()["booking_id"] == second.json()["booking_id"]
    # Rate limit enforced on bookings too.
    enable_rate_limit(monkeypatch, public_requests=1, public_window=600)
    from app.services.rate_limit import InMemoryRateLimiter, set_limiter

    set_limiter(InMemoryRateLimiter())
    assert client.post("/api/v1/public/prime/bookings", json=payload).status_code == 201
    assert client.post("/api/v1/public/prime/bookings", json=payload).status_code == 429


def test_public_booking_feature_disabled(b2) -> None:
    from app.services import settings as settings_service

    db = b2["db"]
    prime_id = _prime_id(db)
    settings_service.update_settings(
        db, business_id=prime_id, payload={"operational": {"booking_enabled": False}}
    )
    try:
        resp = b2["client"].post(
            "/api/v1/public/prime/bookings", json=public_booking_payload()
        )
        assert resp.status_code == 403, resp.text
    finally:
        settings_service.update_settings(
            db, business_id=prime_id, payload={"operational": {"booking_enabled": True}}
        )


def test_public_error_envelope_and_no_stack_traces(b2) -> None:
    resp = _lead(b2["client"], slug="ghost")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body and "code" in body["error"]
    assert "Traceback" not in resp.text
    assert "psycopg" not in resp.text.lower() and "sqlalchemy" not in resp.text.lower()


def test_inflight_duplicate_returns_409_without_side_effects(b2) -> None:
    """Same key while the first request is in flight -> 409 (SAVEPOINT path)."""
    import uuid as _uuid

    from app.services import idempotency as idem_service
    from app.services.errors import ConflictError

    db = b2["db"]
    business_id = _uuid.UUID(b2["prime"]["business"]["id"])
    key = new_idem_key()
    payload = {"name": "Inflight User", "phone": "+911111111111"}
    record, replay_body, replay_status = idem_service.acquire(
        db, business_id=business_id, endpoint="public-lead",
        idem_key=key, payload=payload,
    )
    assert record is not None and replay_body is None
    try:
        with pytest.raises(ConflictError):
            idem_service.acquire(
                db, business_id=business_id, endpoint="public-lead",
                idem_key=key, payload=payload,
            )
    finally:
        db.rollback()
    # Rolled-back placeholder means the key is reusable after a failure.
    record2, _, _ = idem_service.acquire(
        db, business_id=business_id, endpoint="public-lead",
        idem_key=key, payload=payload,
    )
    assert record2 is not None
    db.rollback()
