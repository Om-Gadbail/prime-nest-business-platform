"""Dashboard service: efficient business-scoped operational aggregates (Block 4).

The overview endpoint serves the staff dashboard home (today's numbers,
assigned work, recent activity). All counts come from the dashboard
repository (SQL COUNT queries — never full-table fetches). No analytics
platform here: only the operational data this block requires.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.repositories import audit_events as audit_repo
from app.repositories import dashboard as dashboard_repo
from app.repositories import notifications as notif_repo
from app.repositories import tasks as tasks_repo


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_today(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def overview(db: Session, *, business_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """One-shot operational snapshot for the dashboard home."""
    now = _utcnow()
    today_start = _start_of_today(now)

    recent_leads = dashboard_repo.recent_leads(db, business_id=business_id, limit=5)
    recent_activity = dashboard_repo.recent_lead_activities(
        db, business_id=business_id, limit=8
    )

    return {
        "business_id": business_id,
        "generated_at": now,
        "leads": {
            "new": dashboard_repo.count_new_leads(db, business_id=business_id),
            "follow_ups_due": dashboard_repo.count_followups_due(
                db, business_id=business_id, now=now
            ),
            "created_today": dashboard_repo.count_leads_since(
                db, business_id=business_id, since=today_start
            ),
        },
        "bookings": {
            "requested": dashboard_repo.count_bookings_by_status(
                db, business_id=business_id, status="requested"
            ),
            "created_today": dashboard_repo.count_bookings_since(
                db, business_id=business_id, since=today_start
            ),
        },
        "notifications": {
            "unread": notif_repo.count_unread(
                db, business_id=business_id, recipient_user_id=user_id
            )
        },
        "tasks": {
            "mine_open": tasks_repo.count_open_for_assignee(
                db, business_id=business_id, user_id=user_id
            ),
            "mine_overdue": tasks_repo.count_overdue(
                db,
                business_id=business_id,
                now=now,
                assigned_to_user_id=user_id,
            ),
            "open_total": dashboard_repo.count_open_tasks(db, business_id=business_id),
        },
        "recent_leads": [
            {
                "id": lead.id,
                "display_name": lead.display_name,
                "status": lead.status,
                "source": lead.source,
                "created_at": lead.created_at,
            }
            for lead in recent_leads
        ],
        "recent_activity": [
            {
                "id": a.id,
                "lead_id": a.lead_id,
                "activity_type": a.activity_type,
                "note": (a.note or "")[:200],
                "actor_user_id": a.actor_user_id,
                "created_at": a.created_at,
            }
            for a in recent_activity
        ],
    }


def activity_feed(
    db: Session,
    *,
    business_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list, int]:
    """Unified recent-activity feed for the dashboard (audit events)."""
    from app.repositories.pagination import clamp_page

    limit, offset = clamp_page(limit, offset)
    return audit_repo.list_scoped(
        db,
        business_id=business_id,
        limit=limit,
        offset=offset,
        sort="created_at",
        direction="desc",
    )


def leads_summary(db: Session, *, business_id: uuid.UUID) -> dict:
    by_status = dashboard_repo.leads_by_status(db, business_id=business_id)
    return {"by_status": by_status, "total": sum(by_status.values())}


def bookings_summary(db: Session, *, business_id: uuid.UUID) -> dict:
    by_status = dashboard_repo.bookings_by_status(db, business_id=business_id)
    return {"by_status": by_status, "total": sum(by_status.values())}
