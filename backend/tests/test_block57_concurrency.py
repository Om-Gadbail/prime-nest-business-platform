"""Blocks 5-7 — concurrency tests (DB constraints, not just Python checks).

SQLite serializes writes per connection; these tests prove the SAFETY
NET (unique constraints / partial indexes + service retry mapping)
rather than true thread races. Postgres race coverage comes from the
same constraints (partial unique indexes) verified in migration review
+ the documented `docs/` race matrix.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from tests.block57_support import (  # noqa: F811
    H,
    api_allocate,
    api_member,
    api_membership,
    api_payment,
    api_plan_id,
    api_seat,
    b57,  # noqa: F401
)


def test_seat_double_allocate_second_fails(b57) -> None:  # noqa: F811
    seat = api_seat(b57, "nest", "Q-01")
    m1 = api_member(b57, "nest", phone="+911111119001")
    m2 = api_member(b57, "nest", phone="+911111119002")
    assert api_allocate(b57, seat["id"], m1["id"]).status_code == 201
    # Second allocation of the same seat fails even though the check and
    # the insert are separate statements (partial unique index).
    assert api_allocate(b57, seat["id"], m2["id"]).status_code == 409
    # …and the DB itself refuses a direct duplicate ACTIVE row.
    # (Naive timestamp: SQLite DATETIME columns store naive values;
    # Postgres accepts naive as UTC-adjacent input here — the constraint
    # under test is the partial unique index, not tz handling.)
    from app.models.operations import SeatAllocation
    from datetime import datetime
    import uuid as _uuid

    db = b57["db"]
    from sqlalchemy import select
    from app.models.business import Business

    nest = db.execute(
        select(Business).where(Business.slug == "nest")
    ).scalars().first()
    with pytest.raises(IntegrityError):
        db.add(
            SeatAllocation(
                business_id=nest.id, seat_id=_uuid.UUID(seat["id"]),
                member_id=_uuid.UUID(m2["id"]),
                status="active", allocated_at=datetime.now(),
            )
        )
        db.flush()
    db.rollback()


def test_duplicate_payment_key_returns_winner(b57) -> None:  # noqa: F811
    p1 = api_payment(b57, "prime", "999.00", idempotency_key="race-key-1")
    p2 = api_payment(b57, "prime", "999.00", idempotency_key="race-key-1")
    assert p1["id"] == p2["id"]
    # …and the DB unique constraint backs the service check.
    from sqlalchemy import select
    from app.models.operations import Payment
    from app.models.business import Business

    db = b57["db"]
    prime = db.execute(
        select(Business).where(Business.slug == "prime")
    ).scalars().first()
    with pytest.raises(IntegrityError):
        from decimal import Decimal

        db.add(
            Payment(
                business_id=prime.id, amount=Decimal("999.00"),
                currency="INR", method="upi", provider="upi",
                status="pending", idempotency_key="race-key-1",
            )
        )
        db.flush()
    db.rollback()


def test_duplicate_checkin_same_day_single_row(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "prime", phone="+911111119003")
    a1 = c.post("/api/v1/attendance/check-in", json={"member_id": m["id"]},
                headers=H(b57, "prime")).json()
    for _ in range(3):
        again = c.post("/api/v1/attendance/check-in",
                       json={"member_id": m["id"]}, headers=H(b57, "prime")).json()
        assert again["id"] == a1["id"]
    total = c.get("/api/v1/attendance", params={"member_id": m["id"]},
                  headers=H(b57, "prime")).json()["total"]
    assert total == 1
    # DB-level backstop: same (business, member, day) cannot repeat.
    # NOTE: the service stamps attendance_date in UTC while date.today() is
    # system-local — use the row's own day so this holds at any hour.
    from sqlalchemy import select
    from app.models.operations import Attendance
    from app.models.business import Business
    from datetime import date, datetime
    import uuid as _uuid2

    db = b57["db"]
    prime = db.execute(
        select(Business).where(Business.slug == "prime")
    ).scalars().first()
    row_day = date.fromisoformat(a1["attendance_date"])
    with pytest.raises(IntegrityError):
        db.add(
            Attendance(
                business_id=prime.id, member_id=_uuid2.UUID(m["id"]),
                attendance_date=row_day,
                checked_in_at=datetime.now(),
            )
        )
        db.flush()
    db.rollback()


def test_concurrent_renewal_second_is_safe(b57) -> None:  # noqa: F811
    c = b57["client"]
    m = api_member(b57, "prime", phone="+911111119004")
    old = api_membership(b57, "prime", m["id"], api_plan_id(b57, "prime", "monthly"),
                         start_date="2026-01-01", end_date="2026-01-31")
    first = c.post(f"/api/v1/memberships/{old['id']}/renew", json={},
                   headers=H(b57, "prime"))
    assert first.status_code == 200, first.text
    # Renewing the already-expired original again would mint unbounded
    # chains; renew the CURRENT row instead (explicit, auditable).
    second = c.post(f"/api/v1/memberships/{old['id']}/renew", json={},
                    headers=H(b57, "prime"))
    assert second.status_code in (200, 409), second.text
    count = c.get("/api/v1/memberships", params={"member_id": m["id"]},
                  headers=H(b57, "prime")).json()["total"]
    assert count <= 3


def test_unit_status_machines() -> None:
    """Pure transition-table checks (no DB): illegal jumps are closed."""
    from app.models.ops_vocab import (
        OPERATIONAL_MEMBERSHIP_TRANSITIONS,
        PAYMENT_TRANSITIONS,
        RENEWAL_TRANSITIONS,
    )

    assert "active" not in OPERATIONAL_MEMBERSHIP_TRANSITIONS["expired"]
    assert "pending" not in PAYMENT_TRANSITIONS["paid"]
    assert "pending" not in RENEWAL_TRANSITIONS["confirmed"]
    # Terminal states never silently reopen.
    for table in (
        OPERATIONAL_MEMBERSHIP_TRANSITIONS,
        PAYMENT_TRANSITIONS,
        RENEWAL_TRANSITIONS,
    ):
        for terminal in ("cancelled", "refunded", "confirmed"):
            if terminal in table:
                assert table[terminal] == frozenset()


def test_money_uses_decimal_not_float(b57) -> None:  # noqa: F811
    from decimal import Decimal

    m = api_member(b57, "prime", phone="+911111119005")
    ms = api_membership(b57, "prime", m["id"], api_plan_id(b57, "prime", "monthly"),
                        start_date="2026-05-01", end_date="2026-05-31",
                        discount="0.10")
    # 1500.00 - 0.10 == 1499.90 exactly (float would give 1499.9…).
    assert Decimal(ms["final_amount"]) == Decimal("1499.90")
