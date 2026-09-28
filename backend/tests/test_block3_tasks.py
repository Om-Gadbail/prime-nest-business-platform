"""Block 4 — staff task system (CRUD, lifecycle, assignment, isolation)."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, login_as  # noqa: F401


def _create(client, headers, **overrides):
    payload = {"title": "Follow up with lead", "priority": "high"}
    payload.update(overrides)
    return client.post("/api/v1/tasks", json=payload, headers=headers)


def test_create_get_list_task(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    resp = _create(b2["client"], h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "open"
    assert body["priority"] == "high"
    assert body["created_by_user_id"] is not None

    got = b2["client"].get(f"/api/v1/tasks/{body['id']}", headers=h)
    assert got.status_code == 200, got.text

    listed = b2["client"].get("/api/v1/tasks", headers=h)
    assert listed.json()["total"] == 1

    # Nest cannot see Prime's task.
    nest = auth_headers(b2["nest"]["access_token"])
    assert b2["client"].get(f"/api/v1/tasks/{body['id']}", headers=nest).status_code == 404
    assert b2["client"].get("/api/v1/tasks", headers=nest).json()["total"] == 0


def test_create_task_validation(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    assert _create(b2["client"], h, title="").status_code == 422
    assert _create(b2["client"], h, priority="urgent-now").status_code == 422
    assert _create(b2["client"], h, title="x" * 201).status_code == 422
    # Unknown fields rejected (no mass assignment).
    assert _create(b2["client"], h, status="completed").status_code == 422


def test_task_lifecycle_and_reopen(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    task_id = _create(b2["client"], h).json()["id"]

    assert b2["client"].post(
        f"/api/v1/tasks/{task_id}/status", json={"status": "completed"}, headers=h
    ).status_code == 200
    # Completed -> in_progress is forbidden.
    bad = b2["client"].post(
        f"/api/v1/tasks/{task_id}/status", json={"status": "in_progress"}, headers=h
    )
    assert bad.status_code == 409, bad.text
    # Explicit reopen to open is allowed.
    assert b2["client"].post(
        f"/api/v1/tasks/{task_id}/status", json={"status": "open"}, headers=h
    ).status_code == 200
    # Cancel then reopen.
    assert b2["client"].post(
        f"/api/v1/tasks/{task_id}/status", json={"status": "cancelled"}, headers=h
    ).status_code == 200


def test_task_assignment_notifies_and_audits(b2) -> None:
    owner = auth_headers(b2["prime"]["access_token"])
    staff = login_as(
        b2["client"], b2["db"], email="task-assignee@example.com",
        slug="prime", role="STAFF",
    )
    staff_user_id = staff["user"]["id"]

    task_id = _create(b2["client"], owner).json()["id"]
    resp = b2["client"].post(
        f"/api/v1/tasks/{task_id}/assign",
        json={"assigned_to_user_id": staff_user_id},
        headers=owner,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned_to_user_id"] == staff_user_id

    # Assignee got an in-app notification.
    staff_h = auth_headers(staff["access_token"])
    unread = b2["client"].get("/api/v1/notifications/unread-count", headers=staff_h)
    assert unread.json()["unread"] >= 1

    # Audit recorded the assignment.
    events = b2["client"].get("/api/v1/audit-events?action=task.assigned", headers=owner)
    assert events.json()["total"] >= 1

    # Cannot assign to a Nest-only user (no oracle, uniform 404).
    nest_owner_id = b2["nest_owner"].id
    foreign = b2["client"].post(
        f"/api/v1/tasks/{task_id}/assign",
        json={"assigned_to_user_id": str(nest_owner_id)},
        headers=owner,
    )
    assert foreign.status_code == 404, foreign.text


def test_task_related_entity_must_be_same_business(b2) -> None:
    prime = auth_headers(b2["prime"]["access_token"])
    nest = auth_headers(b2["nest"]["access_token"])
    nest_lead = b2["client"].post(
        "/api/v1/leads",
        json={"display_name": "Nest Lead", "phone": "+919800000001"},
        headers=nest,
    ).json()

    # Prime task linking a Nest lead -> 404 (no leak).
    resp = _create(
        b2["client"], prime, related_entity_type="lead",
        related_entity_id=nest_lead["id"],
    )
    assert resp.status_code == 404, resp.text

    # Same-business link works.
    prime_lead = b2["client"].post(
        "/api/v1/leads",
        json={"display_name": "Prime Lead", "phone": "+919800000002"},
        headers=prime,
    ).json()
    ok = _create(
        b2["client"], prime, related_entity_type="lead",
        related_entity_id=prime_lead["id"],
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["related_entity_id"] == prime_lead["id"]


def test_task_filters_pagination_search(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    _create(b2["client"], h, title="Call backtrial member", priority="urgent")
    _create(b2["client"], h, title="Restock towels", priority="low")
    _create(b2["client"], h, title="Call library vendor", priority="medium")

    listed = b2["client"].get("/api/v1/tasks?search=Call&limit=1&offset=0", headers=h)
    assert listed.json()["total"] == 2
    assert len(listed.json()["items"]) == 1

    urgent = b2["client"].get("/api/v1/tasks?priority=urgent", headers=h)
    assert urgent.json()["total"] == 1

    # Overdue filter.
    overdue = b2["client"].get("/api/v1/tasks?overdue_only=true", headers=h)
    assert overdue.status_code == 200


def test_task_rbac_matrix(b2) -> None:
    owner = auth_headers(b2["prime"]["access_token"])
    task_id = _create(b2["client"], owner).json()["id"]

    # VIEWER: read yes, create/update no.
    viewer = login_as(
        b2["client"], b2["db"], email="task-viewer@example.com",
        slug="prime", role="VIEWER",
    )
    vh = auth_headers(viewer["access_token"])
    assert b2["client"].get(f"/api/v1/tasks/{task_id}", headers=vh).status_code == 200
    assert _create(b2["client"], vh).status_code == 403
    assert b2["client"].patch(
        f"/api/v1/tasks/{task_id}", json={"title": "Nope"}, headers=vh
    ).status_code == 403

    # STAFF: full task ops.
    staff = login_as(
        b2["client"], b2["db"], email="task-staff@example.com",
        slug="prime", role="STAFF",
    )
    sh = auth_headers(staff["access_token"])
    assert _create(b2["client"], sh).status_code == 201
    assert b2["client"].patch(
        f"/api/v1/tasks/{task_id}", json={"title": "Updated by staff"}, headers=sh
    ).status_code == 200
