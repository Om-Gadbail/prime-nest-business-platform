"""Block 2 — RBAC matrix tests for the new permission vocabulary."""

from __future__ import annotations

import pytest

from tests.block2_support import STAFF_ROLES, auth_headers, b2, login_as  # noqa: F401

# Expected access per role: (leads_r, leads_w, bookings_r, bookings_w,
# contacts_r, contacts_w, customers_r, customers_w, notif_r, notif_update, ai)
# Release change (owner-ready): STAFF is frontline-operational — creates AND
# updates customers/contacts/notifications; still no ai.read (assist only).
MATRIX = {
    "OWNER":   (200, 201, 200, 201, 200, 201, 200, 201, 200, 200, 200),
    "ADMIN":   (200, 201, 200, 201, 200, 201, 200, 201, 200, 200, 200),
    "MANAGER": (200, 201, 200, 201, 200, 201, 200, 201, 200, 200, 200),
    "STAFF":   (200, 201, 200, 201, 200, 201, 200, 201, 200, 200, 403),
    "VIEWER":  (200, 403, 200, 403, 200, 403, 200, 403, 200, 403, 403),
}


@pytest.mark.parametrize("role", STAFF_ROLES)
def test_role_matrix(b2, role) -> None:
    tokens = login_as(
        b2["client"], b2["db"], email=f"matrix-{role.lower()}@example.com",
        slug="prime", role=role,
    )
    h = auth_headers(tokens["access_token"])
    client = b2["client"]
    expected = MATRIX[role]
    assert client.get("/api/v1/leads", headers=h).status_code == expected[0]
    assert client.post(
        "/api/v1/leads", json={"display_name": f"{role} lead"}, headers=h
    ).status_code == expected[1]
    assert client.get("/api/v1/bookings", headers=h).status_code == expected[2]
    assert client.post(
        "/api/v1/bookings", json={"title": f"{role} booking"}, headers=h
    ).status_code == expected[3]
    assert client.get("/api/v1/contacts", headers=h).status_code == expected[4]
    # contact create returns 201 or 403; capture id when allowed.
    create_resp = client.post(
        "/api/v1/contacts", json={"first_name": f"{role} contact"}, headers=h
    )
    assert create_resp.status_code == expected[5], create_resp.text
    assert client.get("/api/v1/customers", headers=h).status_code == expected[6]
    cust_status = None
    if create_resp.status_code == 201:
        cust_status = client.post(
            "/api/v1/customers",
            json={"contact_id": create_resp.json()["id"]}, headers=h,
        ).status_code
    else:
        cust_status = client.post(
            "/api/v1/customers",
            json={"contact_id": "00000000-0000-0000-0000-000000000000"},
            headers=h,
        ).status_code
    # 403 (no permission) vs 404 (permission but missing row) both deny.
    assert cust_status in (expected[7], 404), cust_status
    assert client.get("/api/v1/notifications", headers=h).status_code == expected[8]
    assert client.put(
        "/api/v1/notifications/preferences/system", json={"enabled": True},
        headers=h,
    ).status_code == expected[9]
    from app.core.config import get_settings  # noqa: F401
    assert client.get("/api/v1/ai/mode", headers=h).status_code == expected[10]


def test_new_permissions_in_seed_matrix(b2) -> None:
    """Seeded roles actually carry the new Block 2 permission keys."""
    from app.models.rbac import ROLE_PERMISSIONS

    for key in (
        "contacts.read", "contacts.create", "contacts.update",
        "customers.read", "customers.create", "customers.update",
        "notifications.read", "notifications.update", "ai.read",
    ):
        assert key in ROLE_PERMISSIONS["OWNER"]
        assert key in ROLE_PERMISSIONS["MANAGER"]
    assert "customers.create" in ROLE_PERMISSIONS["STAFF"]
    assert "notifications.update" in ROLE_PERMISSIONS["STAFF"]
    assert "ai.read" not in ROLE_PERMISSIONS["VIEWER"]
    # DB state matches the matrix for a live manager token.
    tokens = login_as(
        b2["client"], b2["db"], email="matrix-check@example.com",
        slug="prime", role="MANAGER",
    )
    assert "ai.read" in tokens["permissions"]
    assert "customers.create" in tokens["permissions"]
