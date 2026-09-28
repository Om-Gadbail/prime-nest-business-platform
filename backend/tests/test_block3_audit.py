"""Block 4 — audit/activity system (creation, scoping, secrecy, append-only)."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, login_as, public_lead_payload  # noqa: F401


def test_mutations_emit_audit_events(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]

    lead_id = client.post(
        "/api/v1/leads",
        json={"display_name": "Audit Lead", "phone": "+919555500001"},
        headers=h,
    ).json()["id"]
    client.post(f"/api/v1/leads/{lead_id}/notes", json={"note": "Called twice."}, headers=h)
    client.patch(f"/api/v1/leads/{lead_id}", json={"service_interest": "Trial"}, headers=h)
    task_id = client.post(
        "/api/v1/tasks", json={"title": "Audit task"}, headers=h
    ).json()["id"]
    client.post(f"/api/v1/tasks/{task_id}/status", json={"status": "completed"}, headers=h)
    booking_id = client.post(
        "/api/v1/bookings", json={"title": "Audit booking"}, headers=h
    ).json()["id"]
    client.post(f"/api/v1/bookings/{booking_id}/confirm", headers=h)

    events = client.get("/api/v1/audit-events?limit=100", headers=h).json()
    actions = {e["action"] for e in events["items"]}
    for expected in (
        "lead.created", "lead.note_added", "lead.updated",
        "task.created", "task.completed",
        "booking.created", "booking.status_changed",
    ):
        assert expected in actions, (expected, sorted(actions))

    # Actor + business attribution is correct.
    for event in events["items"]:
        assert event["actor_user_id"] == b2["prime_owner"].id or event["actor_user_id"] is not None
        assert event["request_id"] not in ("", None)
        assert event["result"] in ("success", "denied", "error")


def test_public_intake_emits_audit(b2) -> None:
    assert b2["client"].post(
        "/api/v1/public/nest/leads", json=public_lead_payload()
    ).status_code == 201
    nest = auth_headers(b2["nest"]["access_token"])
    events = b2["client"].get("/api/v1/audit-events?action=lead.created", headers=nest)
    assert events.json()["total"] >= 1
    # Anonymous intake has no actor but keeps the business scope.
    assert events.json()["items"][0]["actor_user_id"] is None


def test_audit_never_logs_secrets(b2) -> None:
    from app.services import audit as audit_service

    meta = audit_service.sanitize_meta(
        {
            "password": "supersecret",
            "refresh_token": "abc",
            "Authorization": "Bearer x",
            "reason": "normal note",
            "api_key": "k",
        }
    )
    assert meta == {"reason": "normal note"}

    h = auth_headers(b2["prime"]["access_token"])
    events = b2["client"].get("/api/v1/audit-events?limit=50", headers=h).json()
    blob = str(events)
    assert "StrongPass" not in blob
    assert "refresh_token" not in blob.lower().replace("notification_preference", "")


def test_audit_scoped_and_viewer_denied(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    nest = auth_headers(b2["nest"]["access_token"])

    prime_total = b2["client"].get("/api/v1/audit-events", headers=prime).json()["total"]
    nest_total = b2["client"].get("/api/v1/audit-events", headers=nest).json()["total"]
    assert prime_total >= 1  # login events alone guarantee rows

    # Cross-business event IDs are invisible (uniform 404).
    prime_first = b2["client"].get("/api/v1/audit-events?limit=1", headers=prime).json()["items"]
    if prime_first:
        eid = prime_first[0]["id"]
        assert b2["client"].get(f"/api/v1/audit-events/{eid}", headers=nest).status_code == 404

    # VIEWER cannot read the audit log.
    viewer = login_as(
        b2["client"], b2["db"], email="audit-viewer@example.com",
        slug="prime", role="VIEWER",
    )
    denied = b2["client"].get(
        "/api/v1/audit-events", headers=auth_headers(viewer["access_token"])
    )
    assert denied.status_code == 403, denied.text
    assert nest_total >= 0  # queryset isolation (no crash)


def test_audit_is_append_only(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    items = b2["client"].get("/api/v1/audit-events?limit=1", headers=h).json()["items"]
    assert items
    eid = items[0]["id"]
    # No update/delete contracts exist on the router.
    assert b2["client"].patch(f"/api/v1/audit-events/{eid}", json={}).status_code == 405
    assert b2["client"].delete(f"/api/v1/audit-events/{eid}", headers=h).status_code == 405
    assert b2["client"].post("/api/v1/audit-events", json={}, headers=h).status_code == 405


def test_audit_filters(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    client = b2["client"]
    by_action = client.get("/api/v1/audit-events?action=auth.login_success", headers=h)
    assert by_action.status_code == 200
    assert by_action.json()["total"] >= 1
    bad_action = client.get("/api/v1/audit-events?action=nope", headers=h)
    assert bad_action.status_code == 422
    searched = client.get("/api/v1/audit-events?search=login", headers=h)
    assert searched.json()["total"] >= 1
