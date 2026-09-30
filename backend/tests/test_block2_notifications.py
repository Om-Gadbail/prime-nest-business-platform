"""Block 2 — Notifications foundation tests."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, login_as  # noqa: F401


def test_new_lead_fans_out_to_managers(b2) -> None:
    manager = login_as(
        b2["client"], b2["db"], email="ntf-manager@example.com",
        slug="prime", role="MANAGER",
    )
    mh = auth_headers(manager["access_token"])
    assert b2["client"].get("/api/v1/notifications/unread-count", headers=mh).json()[
        "unread"
    ] == 0
    # Anonymous intake creates staff notifications.
    resp = b2["client"].post(
        "/api/v1/public/prime/leads",
        json={"name": "Notify Case", "phone": "+919876500010"},
    )
    assert resp.status_code == 201, resp.text
    assert b2["client"].get("/api/v1/notifications/unread-count", headers=mh).json()[
        "unread"
    ] >= 1
    items = b2["client"].get("/api/v1/notifications", headers=mh).json()["items"]
    assert any(n["notification_type"] == "new_lead" for n in items)


def test_list_read_flow(b2) -> None:
    h = auth_headers(b2["prime"]["access_token"])
    b2["client"].post(
        "/api/v1/public/prime/bookings",
        json={"name": "Booking Notify", "phone": "+919876500011"},
    )
    unread = b2["client"].get("/api/v1/notifications/unread-count", headers=h).json()
    assert unread["unread"] >= 1
    items = b2["client"].get("/api/v1/notifications", headers=h).json()["items"]
    nid = items[0]["id"]
    resp = b2["client"].post(f"/api/v1/notifications/{nid}/read", headers=h)
    assert resp.status_code == 200 and resp.json()["read_at"]
    assert b2["client"].post("/api/v1/notifications/read-all", headers=h).status_code == 200
    assert b2["client"].get("/api/v1/notifications/unread-count", headers=h).json()[
        "unread"
    ] == 0
    unread_only = b2["client"].get(
        "/api/v1/notifications?unread_only=true", headers=h
    ).json()
    assert unread_only["total"] == 0


def test_recipient_isolation(b2) -> None:
    h_owner = auth_headers(b2["prime"]["access_token"])
    staff = login_as(
        b2["client"], b2["db"], email="ntf-staff@example.com",
        slug="prime", role="STAFF",
    )
    sh = auth_headers(staff["access_token"])
    b2["client"].post(
        "/api/v1/public/prime/leads",
        json={"name": "Isolation Case", "phone": "+919876500012"},
    )
    owner_items = b2["client"].get("/api/v1/notifications", headers=h_owner).json()["items"]
    assert owner_items, "owner should have fan-out notifications"
    # Staff cannot read/mark the owner's notification (uniform 404).
    other_id = owner_items[0]["id"]
    assert b2["client"].post(
        f"/api/v1/notifications/{other_id}/read", headers=sh
    ).status_code == 404
    # Unknown id is the same 404 (no oracle).
    import uuid as _uuid

    assert b2["client"].post(
        f"/api/v1/notifications/{_uuid.uuid4()}/read", headers=sh
    ).status_code == 404


def test_business_isolation(b2) -> None:
    h_prime = auth_headers(b2["prime"]["access_token"])
    h_nest = auth_headers(b2["nest"]["access_token"])
    b2["client"].post(
        "/api/v1/public/prime/leads",
        json={"name": "Biz Iso", "phone": "+919876500013"},
    )
    prime_total = b2["client"].get("/api/v1/notifications", headers=h_prime).json()["total"]
    nest_total = b2["client"].get("/api/v1/notifications", headers=h_nest).json()["total"]
    assert prime_total >= 1 and nest_total == 0


def test_dedupe_and_preferences(b2) -> None:
    import uuid as _uuid

    from app.services import notifications as notif_service

    db = b2["db"]
    business_id = _uuid.UUID(b2["prime"]["business"]["id"])
    user_id = _uuid.UUID(b2["prime"]["user"]["id"])
    first = notif_service.create_notification(
        db, business_id=business_id, recipient_user_id=user_id,
        notification_type="system", title="Dedupe test", dedupe_key="test:dedupe:1",
    )
    assert first is not None
    db.commit()
    # Preference opt-out suppresses creation.
    notif_service.set_preference(
        db, business_id=business_id, user_id=user_id,
        notification_type="system", enabled=False,
    )
    db.commit()
    suppressed = notif_service.create_notification(
        db, business_id=business_id, recipient_user_id=user_id,
        notification_type="system", title="Suppressed", dedupe_key="test:dedupe:2",
    )
    assert suppressed is None
    # Manager (notifications.update) can set own preference via API;
    # release change (owner-ready): frontline STAFF can too (own prefs).
    manager = login_as(
        b2["client"], b2["db"], email="ntf-pref-manager@example.com",
        slug="prime", role="MANAGER",
    )
    mh = auth_headers(manager["access_token"])
    resp = b2["client"].put(
        "/api/v1/notifications/preferences/system", json={"enabled": False},
        headers=mh,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False
    staff = login_as(
        b2["client"], b2["db"], email="ntf-pref-staff@example.com",
        slug="prime", role="STAFF",
    )
    assert b2["client"].put(
        "/api/v1/notifications/preferences/system", json={"enabled": True},
        headers=auth_headers(staff["access_token"]),
    ).status_code == 200
    # Unknown preference type rejected.
    assert b2["client"].put(
        "/api/v1/notifications/preferences/sms-blast", json={"enabled": True},
        headers=mh,
    ).status_code == 422


def test_future_channels_raise_honestly(b2) -> None:
    from app.services import notifications as notif_service
    from app.services.notifications import ChannelNotConfiguredError

    import pytest

    with pytest.raises(ChannelNotConfiguredError):
        notif_service.EmailNotificationProvider().send(
            recipient="x@y.z", title="t", body="b"
        )
    with pytest.raises(ChannelNotConfiguredError):
        notif_service.WhatsAppNotificationProvider().send(
            recipient="+91", title="t", body="b"
        )
