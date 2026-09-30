"""Prime Gym owner-demo dataset + business profile (FINAL demo mission).

Canonical, idempotent, non-destructive helpers — NOT a second backend:

- ``ensure_prime_profile(db)`` fills ONLY empty Prime contact/address/
  hours fields so the WhatsApp AI answers location/hours/plans from real
  configuration. Staff edits always win (never overwritten).
- ``seed_prime_owner_demo(db)`` creates a polished Prime-only demo
  dataset with clearly synthetic phones (``+91 00000xxxxx``) plus demo
  conversation history marked ``demo=True`` / provider ``log`` (never
  fabricated Meta delivery).

Nest is never touched here. Safe to re-run. Never runs in tests unless
explicitly called.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select as _select
from sqlalchemy.orm import Session

DEMO_TAG = "prime-owner-demo"

# Clearly synthetic demo phones (never real people; never auto-messaged).
DEMO_PHONES = [f"+9100000{1000 + i}" for i in range(60)]

PRIME_PROFILE = {
    "phone": "+910000090001",
    "whatsapp": "+910000090001",
    "email": "hello@primefitness.demo.example",
    "address_line_1": "2nd Floor, 80 Feet Road, Koramangala 4th Block",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postal_code": "560034",
    "country": "India",
}

PRIME_SETTINGS = {
    "branding": {"tagline": "Train smart. Stay consistent."},
    "contact": {"phone": "+910000090001", "whatsapp": "+910000090001"},
    "address": {
        "address_line_1": "2nd Floor, 80 Feet Road, Koramangala 4th Block",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560034",
    },
    "hours": {
        "weekly": {
            "monday": {"open": "05:30", "close": "22:00"},
            "tuesday": {"open": "05:30", "close": "22:00"},
            "wednesday": {"open": "05:30", "close": "22:00"},
            "thursday": {"open": "05:30", "close": "22:00"},
            "friday": {"open": "05:30", "close": "22:00"},
            "saturday": {"open": "06:00", "close": "21:00"},
            "sunday": {"open": "07:00", "close": "20:00"},
        },
        "notes": "Trial visits welcome during staffed hours.",
    },
    "localization": {"timezone": "Asia/Kolkata"},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_prime_profile(db: Session) -> dict[str, Any]:
    """Fill empty Prime contact/address/hours (never overwrite staff data)."""
    from app.repositories import businesses as business_repo
    from app.repositories import settings as settings_repo

    business = business_repo.get_by_slug(db, "prime")
    if business is None:
        return {"profile": "missing-prime"}
    filled_biz: list[str] = []
    for field, value in PRIME_PROFILE.items():
        if not getattr(business, field, None):
            setattr(business, field, value)
            filled_biz.append(field)
    row = settings_repo.ensure_for_business(db, business.id)
    filled_settings: list[str] = []
    for section, values in PRIME_SETTINGS.items():
        current = dict(getattr(row, section, None) or {})
        changed = False
        for key, val in values.items():
            if key not in current or current[key] in (None, "", {}):
                current[key] = val
                changed = True
        if changed:
            setattr(row, section, current)
            filled_settings.append(section)
    db.flush()
    return {"profile": "ok", "business_fields": filled_biz, "settings": filled_settings}


def seed_prime_owner_demo(db: Session) -> dict[str, int]:
    """Create the polished Prime-only owner-demo dataset (idempotent)."""
    from app.models.booking import Booking as _Booking
    from app.models.lead import Lead as _Lead
    from app.models.operations import Member as _Member
    from app.models.task import Task as _Task
    from app.repositories import businesses as business_repo
    from app.services import attendance as attendance_service
    from app.services import bookings as bookings_service
    from app.services import communications as comms
    from app.services import leads as leads_service
    from app.services import members as members_service
    from app.services import memberships as memberships_service
    from app.services import payments as payments_service
    from app.services import tasks as tasks_service

    ensure_prime_profile(db)
    business = business_repo.get_by_slug(db, "prime")
    assert business is not None
    bid = business.id
    created = {
        "leads": 0, "members": 0, "memberships": 0, "payments": 0,
        "bookings": 0, "attendance": 0, "tasks": 0, "conversations": 0,
    }

    # -- 14 leads, varied statuses -------------------------------------------
    lead_specs = [
        ("Aarav Sharma", "whatsapp", "Trial visit", "new"),
        ("Priya Nair", "website", "Membership Inquiry", "new"),
        ("Rohan Mehta", "instagram", "Monthly membership", "contacted"),
        ("Sneha Kulkarni", "google", "Weight training", "contacted"),
        ("Vikram Rao", "walk_in", "Annual membership", "qualified"),
        ("Ananya Iyer", "website", "Personal training", "qualified"),
        ("Karthik Menon", "referral", "Couple membership", "booked"),
        ("Divya Reddy", "whatsapp", "Trial visit", "booked"),
        ("Arjun Patel", "website", "3 month plan", "converted"),
        ("Meera Joshi", "instagram", "Yoga + gym", "converted"),
        ("Sahil Khan", "google", "Just browsing", "lost"),
        ("Ritu Verma", "walk_in", "Timing enquiry", "contacted"),
        ("Nikhil Bose", "website", "Corporate membership", "new"),
        ("Kavya Singh", "whatsapp", "Diet + training", "qualified"),
    ]
    for i, (lname, source, interest, status) in enumerate(lead_specs):
        display = f"{lname} (demo)"
        exists = db.execute(
            _select(_Lead).where(_Lead.business_id == bid, _Lead.display_name == display)
        ).scalars().first()
        if exists is not None:
            continue
        lead = leads_service.create_lead(
            db, business_id=bid,
            data={
                "display_name": display, "phone": DEMO_PHONES[i],
                "service_interest": interest, "source": source,
                "source_detail": DEMO_TAG, "consent_marketing": True,
                "message": f"{interest} — {DEMO_TAG}",
            },
        )
        try:
            if status != "new":
                if status == "contacted":
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="contacted")
                elif status == "qualified":
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="contacted")
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="qualified")
                elif status == "booked":
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="contacted")
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="qualified")
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="booked")
                elif status == "converted":
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="contacted")
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="qualified")
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="booked")
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="converted")
                elif status == "lost":
                    leads_service.set_status(db, business_id=bid, lead_id=lead.id, to_status="lost")
        except Exception:  # noqa: BLE001 - status shaping best-effort
            pass
        try:
            leads_service.add_note(db, business_id=bid, lead_id=lead.id, note=f"Demo note ({DEMO_TAG})")
        except Exception:  # noqa: BLE001
            pass
        created["leads"] += 1

    # -- 7 members + memberships ----------------------------------------------
    member_specs = [
        # (display, phone_idx, start_delta, end_delta, pay_state)
        ("Demo Active Ravi", 20, -60, +300, "paid"),      # healthy annual-ish
        ("Demo Expiring Asha", 21, -340, +7, "paid"),     # renewal demo (7d)
        ("Demo Thirty Imran", 22, -60, +30, "paid"),      # 30-day stage
        ("Demo Renewed Sara", 23, -400, +320, "paid"),    # recently renewed
        ("Demo Expired Dev", 24, -400, -5, "paid"),       # post-expiry win-back
        ("Demo Inactive Tara", 25, -120, +240, "paid"),   # inactive retention
        ("Demo FailedPay Kabir", 26, -30, +335, "failed"),  # payment recovery
    ]
    member_ids: dict[str, Any] = {}
    for display, pidx, start_d, end_d, pay_state in member_specs:
        member = db.execute(
            _select(_Member).where(_Member.business_id == bid, _Member.display_name == display)
        ).scalars().first()
        if member is None:
            member = members_service.create_member(
                db, business_id=bid,
                data={"display_name": display, "phone": DEMO_PHONES[pidx],
                      "source": "other", "notes": DEMO_TAG},
            )
            created["members"] += 1
        member_ids[display] = member
        membership, is_new = memberships_service.create_membership(
            db, business_id=bid,
            data={
                "member_id": str(member.id), "status": "active" if end_d >= 0 else "expired",
                "start_date": (date.today() + timedelta(days=start_d)).isoformat(),
                "end_date": (date.today() + timedelta(days=end_d)).isoformat(),
                "price": "2000.00", "currency": "INR",
                "idempotency_key": f"{DEMO_TAG}-ms-{display[:12]}",
            },
        )
        if is_new:
            created["memberships"] += 1
            try:
                payment, pay_new = payments_service.create_payment(
                    db, business_id=bid,
                    data={"member_id": str(member.id), "membership_id": str(membership.id),
                          "amount": "2000.00", "currency": "INR", "method": "upi",
                          "idempotency_key": f"{DEMO_TAG}-pay-{display[:12]}"},
                )
                if pay_new:
                    payments_service.set_status(
                        db, business_id=bid, payment_id=payment.id,
                        to_status="paid" if pay_state == "paid" else "failed",
                    )
                    created["payments"] += 1
            except Exception:  # noqa: BLE001 - payment shaping best-effort
                pass
    # Recently-renewed: successor row for Sara (stops further nudges).
    try:
        sara = member_ids.get("Demo Renewed Sara")
        if sara is not None:
            memberships_service.create_membership(
                db, business_id=bid,
                data={"member_id": str(sara.id), "status": "active",
                      "start_date": date.today().isoformat(),
                      "end_date": (date.today() + timedelta(days=365)).isoformat(),
                      "price": "12000.00", "currency": "INR",
                      "idempotency_key": f"{DEMO_TAG}-ms-renewed-sara-new"},
            )
            created["memberships"] += 1
    except Exception:  # noqa: BLE001
        pass

    # -- attendance (recent for active, stale for inactive) --------------------
    try:
        ravi = member_ids.get("Demo Active Ravi")
        if ravi is not None:
            attendance_service.check_in(db, business_id=bid, member_id=ravi.id, data={"source": "manual"})
            created["attendance"] += 1
    except Exception:  # noqa: BLE001
        pass

    # -- bookings: trial requested / upcoming / attended / no-show -------------
    booking_specs = [
        ("Demo Trial Requested", "trial", "Demo trial request (seed)", "requested"),
        ("Demo Trial Upcoming", "trial", "Demo trial upcoming (seed)", "confirmed"),
        ("Demo Trial Attended", "trial", "Demo trial attended (seed)", "completed"),
        ("Demo Trial NoShow", "trial", "Demo trial no-show (seed)", "no_show"),
    ]
    for i, (dname, btype, title, _state) in enumerate(booking_specs):
        exists = db.execute(
            _select(_Booking).where(_Booking.business_id == bid, _Booking.title == title)
        ).scalars().first()
        if exists is not None:
            continue
        try:
            bookings_service.create_booking(
                db, business_id=bid,
                data={"display_name": dname, "phone": DEMO_PHONES[30 + i],
                      "booking_type": btype, "title": title,
                      "source": "website", "notes": DEMO_TAG},
            )
            created["bookings"] += 1
        except Exception:  # noqa: BLE001
            continue

    # -- staff tasks ------------------------------------------------------------
    task_titles = [
        "Follow up: Demo Expiring Asha renewal (7 days)",
        "Handoff: demo visitor asked for human help",
        "Recover failed demo payment (Kabir)",
        "Reschedule missed demo trial",
    ]
    for title in task_titles:
        exists = db.execute(
            _select(_Task).where(_Task.business_id == bid, _Task.title == title)
        ).scalars().first()
        if exists is not None:
            continue
        try:
            tasks_service.create_task(db, business_id=bid, title=title,
                                      description=f"{DEMO_TAG} task", priority="medium")
            created["tasks"] += 1
        except Exception:  # noqa: BLE001
            pass

    # -- safe demo conversations (log provider, clearly marked) -----------------
    demo_chats = [
        ("+910000011101", "Hi, I would like to know about Prime."),
        ("+910000011102", "Where are you located?"),
        ("+910000011103", "What are your membership plans?"),
        ("+910000011104", "I want to book a trial."),
        ("+910000011105", "When does my membership expire?"),
        ("+910000011106", "I want to talk to someone."),
    ]
    for phone, body in demo_chats:
        try:
            comms.record_inbound(
                db, business_id=bid, channel="whatsapp", external_id=phone,
                sender=phone, body=f"{body} (demo)",
                provider_message_id=f"{DEMO_TAG}-in-{phone[-4:]}",
                raw={"demo": True, "tag": DEMO_TAG},
            )
            created["conversations"] += 1
        except Exception:  # noqa: BLE001 - inbound dedupe may skip reruns
            pass
    db.commit()
    return created


if __name__ == "__main__":  # pragma: no cover - manual demo entrypoint
    from app.core.database import get_session_factory

    _factory = get_session_factory()
    _db = _factory()
    try:
        print(ensure_prime_profile(_db))
        print(seed_prime_owner_demo(_db))
    finally:
        _db.close()
