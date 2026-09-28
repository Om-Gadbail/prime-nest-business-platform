"""Block 3/4 — RBAC enforcement for every new permission.

Matrix (additive; Block 1/2 grants untouched):
- leads.transfer: OWNER/ADMIN only (plus role gate).
- identity.read: OWNER/ADMIN only (plus role gate on manual links).
- tasks.read/create/update: OWNER/ADMIN/MANAGER/STAFF + VIEWER read-only.
- audit.read: OWNER/ADMIN/MANAGER/STAFF; VIEWER denied.
- dashboard.read: all roles.
"""

from __future__ import annotations

import pytest

from tests.block2_support import auth_headers, b2, login_as  # noqa: F401

ROLES = ("OWNER", "ADMIN", "MANAGER", "STAFF", "VIEWER")


@pytest.mark.parametrize("role", ROLES)
def test_dashboard_read_all_roles(b2, role: str) -> None:
    if role == "OWNER":
        headers = auth_headers(b2["prime"]["access_token"])
    else:
        tokens = login_as(
            b2["client"], b2["db"], email=f"rbac-{role.lower()}@example.com",
            slug="prime", role=role,
        )
        headers = auth_headers(tokens["access_token"])
    resp = b2["client"].get("/api/v1/dashboard/overview", headers=headers)
    assert resp.status_code == 200, (role, resp.text)


@pytest.mark.parametrize(
    "role,allowed",
    [
        ("OWNER", True),
        ("ADMIN", True),
        ("MANAGER", True),
        ("STAFF", True),
        ("VIEWER", False),
    ],
)
def test_audit_read_matrix(b2, role: str, allowed: bool) -> None:
    if role == "OWNER":
        headers = auth_headers(b2["prime"]["access_token"])
    else:
        tokens = login_as(
            b2["client"], b2["db"], email=f"audit-{role.lower()}@example.com",
            slug="prime", role=role,
        )
        headers = auth_headers(tokens["access_token"])
    resp = b2["client"].get("/api/v1/audit-events?limit=1", headers=headers)
    assert (resp.status_code == 200) is allowed, (role, resp.text)


@pytest.mark.parametrize(
    "role,can_create,can_update",
    [
        ("OWNER", True, True),
        ("ADMIN", True, True),
        ("MANAGER", True, True),
        ("STAFF", True, True),
        ("VIEWER", False, False),
    ],
)
def test_tasks_matrix(b2, role: str, can_create: bool, can_update: bool) -> None:
    client = b2["client"]
    owner_headers = auth_headers(b2["prime"]["access_token"])
    task_id = client.post(
        "/api/v1/tasks", json={"title": "Matrix task"}, headers=owner_headers
    ).json()["id"]
    if role == "OWNER":
        headers = owner_headers
    else:
        tokens = login_as(
            client, b2["db"], email=f"task-{role.lower()}@example.com",
            slug="prime", role=role,
        )
        headers = auth_headers(tokens["access_token"])
    assert (client.post(
        "/api/v1/tasks", json={"title": "x"}, headers=headers
    ).status_code == 201) is can_create, role
    assert (client.patch(
        f"/api/v1/tasks/{task_id}", json={"title": "y"}, headers=headers
    ).status_code == 200) is can_update, role
    # Everyone with a membership can read tasks (VIEWER included).
    assert client.get(f"/api/v1/tasks/{task_id}", headers=headers).status_code == 200


def test_transfer_and_identity_owner_admin_only(b2) -> None:
    client = b2["client"]
    owner_headers = auth_headers(b2["prime"]["access_token"])
    lead_id = client.post(
        "/api/v1/leads",
        json={"display_name": "RBAC Lead", "phone": "+919888800001"},
        headers=owner_headers,
    ).json()["id"]
    person_id = client.get("/api/v1/identity/links", headers=owner_headers).json()["items"][0]["person_id"]

    for role in ("MANAGER", "STAFF", "VIEWER"):
        tokens = login_as(
            client, b2["db"], email=f"gate-{role.lower()}@example.com",
            slug="prime", role=role,
        )
        h = auth_headers(tokens["access_token"])
        assert client.post(
            f"/api/v1/leads/{lead_id}/transfer",
            json={"target_business_slug": "nest", "reason": "A proper reason here."},
            headers=h,
        ).status_code == 403, role
        assert client.get(
            f"/api/v1/identity/persons/{person_id}/cross-business", headers=h
        ).status_code == 403, role

    admin = login_as(
        client, b2["db"], email="gate-admin@example.com", slug="prime", role="ADMIN"
    )
    ah = auth_headers(admin["access_token"])
    assert client.get(
        f"/api/v1/identity/persons/{person_id}/cross-business", headers=ah
    ).status_code == 200


def test_seed_grants_new_permissions() -> None:
    from tests.block1_support import make_test_session

    engine, db = make_test_session()
    try:
        from app.repositories import memberships as membership_repo
        from app.models.rbac import ROLE_PERMISSIONS

        for role_name, expected in ROLE_PERMISSIONS.items():
            role = membership_repo.get_role_by_name(db, name=role_name)
            assert role is not None
            granted = set(membership_repo.list_role_permission_keys(db, role_id=role.id))
            for key in (
                "leads.transfer", "identity.read", "tasks.read", "tasks.create",
                "tasks.update", "audit.read", "dashboard.read",
            ):
                assert (key in granted) == (key in expected), (role_name, key)
    finally:
        db.close()
        engine.dispose()
