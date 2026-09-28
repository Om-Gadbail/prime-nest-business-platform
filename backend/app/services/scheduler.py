"""Full-platform scheduler/worker core (integration mission, additive).

ONE scheduler + ONE worker, shared backend image, per-business isolation.

- :func:`run_business_sweep` — all timed work for ONE business (idempotent):
  retry/due automation executions, renewal reminders (configurable offsets),
  daily owner brief, expired idempotency purge. Never touches another business.
- :func:`run_all_businesses` — iterate active businesses, sweep each in its own
  transaction scope (failure in one never blocks the others).
- Coordination: when ``REDIS_URL`` is set, a Redis ``SET NX`` lease elects one
  scheduler tick owner (no duplicate renewals/sends across replicas). Without
  Redis the sweep still runs (single-replica local mode) — safe because every
  job is idempotent (executions dedupe on ``business_id+idempotency_key``,
  messages dedupe on ``business_id+provider_message_id``).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def list_active_business_ids(db: Session) -> list[uuid.UUID]:
    from app.models.business import Business

    rows = list(
        db.execute(
            select(Business).where(
                Business.is_active.is_(True), Business.status == "active"
            )
        )
        .scalars()
        .all()
    )
    return [r.id for r in rows]


def acquire_tick_lease(settings: Settings, *, tick: str, lease_seconds: int) -> bool:
    """Return True when this replica owns the scheduler tick.

    Redis ``SET NX EX`` lease; no Redis configured → True (single-replica mode).
    Redis errors → True (fail OPEN for availability; jobs are idempotent so a
    duplicate tick degrades to no-op replays, never duplicate sends).
    """
    url = (getattr(settings, "redis_url", "") or "").strip()
    if not url:
        return True
    try:
        import redis as _redis

        client = _redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        owned = bool(
            client.set(
                f"scheduler:tick:{tick}",
                "1",
                nx=True,
                ex=max(30, int(lease_seconds or 120)),
            )
        )
        if not owned:
            logger.info(
                "scheduler tick=%s skipped (lease held by another replica)", tick
            )
        return owned
    except Exception as exc:  # noqa: BLE001 - degraded mode
        logger.warning(
            "scheduler lease degraded (%s); running tick anyway", type(exc).__name__
        )
        return True


def run_business_sweep(
    db: Session, settings: Settings, *, business_id: uuid.UUID
) -> dict:
    """Run all due jobs for ONE business. Returns a small result summary.

    The job's ``business_id`` is routing information, NOT authorization: the
    scope is re-validated against the trusted business registry (exists +
    active + valid database mapping) BEFORE any tenant-sensitive work. An
    invalid scope skips the sweep — it never falls back to another
    business's database.
    """
    from app.core import db_routing as routing
    from app.services import automation as auto_service
    from app.services import idempotency as idem_service
    from app.services import reports as reports_service

    started = time.monotonic()
    summary: dict = {
        "business_id": str(business_id),
        "retried": 0,
        "renewals_found": 0,
        "renewal_messages": 0,
        "brief": False,
        "purged": 0,
    }
    try:
        business = routing.validate_business_job_scope(db, business_id=business_id)
        summary["database_key"] = business.database_key
    except routing.DatabaseRoutingError as exc:
        logger.warning("sweep scope rejected business=%s err=%s", business_id, exc)
        summary["skipped"] = "invalid business scope"
        summary["latency_ms"] = int((time.monotonic() - started) * 1000)
        return summary
    try:
        # 1. Bounded replay of retrying / due-pending executions (per-business).
        #    Prompt 7: genuine execution (Gemini -> provider -> outcome),
        #    not a fake replay — see automation.retry_due.
        try:
            summary["retried"] = int(
                auto_service.retry_due(
                    db,
                    settings,
                    business_id=business_id,
                    limit=int(settings.worker_batch_size),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one stage never kills the sweep
            logger.warning(
                "sweep retry_due failed business=%s err=%s", business_id, exc
            )
        # 1b. Event backlog drain: enqueue automation for growth events that
        #     have no executions yet (fast website path completion).
        try:
            from app.services import growth_engine as growth_service

            summary["drained"] = int(
                growth_service.drain_event_backlog(
                    db, settings, business_id=business_id, limit=20
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sweep drain failed business=%s err=%s", business_id, exc)
            summary["drained"] = 0
        # 2. Renewal reminders at configured offsets -> automation events (idempotent).
        try:
            from app.services import memberships as membership_service

            expired = int(membership_service.mark_expired(db, business_id=business_id))
            summary["expired"] = expired
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sweep mark_expired failed business=%s err=%s", business_id, exc
            )
            summary["expired"] = 0
        try:
            due = reports_service.renewal_scan(db, business_id=business_id)
            summary["renewals_found"] = len(due)
            sent = 0
            for item in due:
                try:
                    from app.repositories import op_memberships as membership_repo

                    membership = membership_repo.get_membership(
                        db,
                        membership_id=uuid.UUID(str(item["membership_id"])),
                        business_id=business_id,
                    )
                    if membership is None:
                        continue
                    # Eligibility-gated (active? renewed? opted in? dup?).
                    executions = growth_service.on_membership_expiring(
                        db,
                        settings,
                        business_id=business_id,
                        membership=membership,
                        offset_days=int(item["offset_days"]),
                    )
                    sent += len(executions)
                except Exception:  # noqa: BLE001 - per-item safety
                    continue
            summary["renewal_messages"] = sent
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sweep renewal_scan failed business=%s err=%s", business_id, exc
            )
        # 2b. Post-expiry follow-up: memberships that expired in the last
        #     48h get one win-back automation (idempotent, opt-in gated).
        try:
            summary["expiry_followups"] = int(
                _sweep_expiry_followups(db, settings, business_id=business_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sweep expiry followup failed business=%s err=%s", business_id, exc
            )
            summary["expiry_followups"] = 0
        # 2c. Trial/visit reminders due within the horizon.
        try:
            summary["reminders"] = int(
                _sweep_booking_reminders(db, settings, business_id=business_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sweep reminders failed business=%s err=%s", business_id, exc
            )
            summary["reminders"] = 0
        # 2d. Inactive-member retention (deterministic signal only).
        try:
            summary["inactive"] = int(
                _sweep_inactive_members(db, settings, business_id=business_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sweep inactive failed business=%s err=%s", business_id, exc)
            summary["inactive"] = 0
        # 2e. Seat continuity reminders (seat businesses with real allocations).
        try:
            summary["seat_continuity"] = int(
                _sweep_seat_continuity(db, settings, business_id=business_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sweep seat continuity failed business=%s err=%s", business_id, exc
            )
            summary["seat_continuity"] = 0
        # 3. Daily owner brief (upserted into daily_reports; idempotent per date).
        try:
            reports_service.build_daily_report(db, business_id=business_id)
            summary["brief"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sweep daily brief failed business=%s err=%s", business_id, exc
            )
        # 4. Expired idempotency retention (bounded; service owns the call).
        try:
            summary["purged"] = int(idem_service.purge_expired(db))
        except Exception:  # noqa: BLE001
            pass
        db.commit()
    except Exception as exc:  # noqa: BLE001 - sweep must never raise
        db.rollback()
        logger.warning("business sweep failed business=%s err=%s", business_id, exc)
        summary["error"] = str(exc)[:300]
    summary["latency_ms"] = int((time.monotonic() - started) * 1000)
    logger.info(
        "sweep business=%s retried=%s renewals=%s brief=%s latency_ms=%s",
        business_id,
        summary["retried"],
        summary["renewals_found"],
        summary["brief"],
        summary["latency_ms"],
    )
    return summary


# -- Prompt 7 growth sweep stages (each bounded + isolated; failures logged) --


def _sweep_expiry_followups(
    db: Session, settings: Settings, *, business_id: uuid.UUID
) -> int:
    """Win-back automation for memberships expired in the last 48h."""
    from datetime import date as _date

    from sqlalchemy import select as _select
    from app.models.operations import Membership
    from app.services import growth_engine as growth_service

    today = _date.today()
    rows = list(
        db.execute(
            _select(Membership)
            .where(
                Membership.business_id == business_id,
                Membership.status == "expired",
                Membership.end_date >= today - timedelta(days=2),
                Membership.end_date <= today,
            )
            .limit(25)
        )
        .scalars()
        .all()
    )
    sent = 0
    for membership in rows:
        try:
            sent += len(
                growth_service.on_membership_expired(
                    db, settings, business_id=business_id, membership=membership
                )
            )
        except Exception:  # noqa: BLE001 - per-item safety
            continue
    return sent


def _sweep_booking_reminders(
    db: Session, settings: Settings, *, business_id: uuid.UUID
) -> int:
    """Confirmation/reminder automation for bookings due within the horizon."""
    from app.services import automation as auto_service
    from app.services import growth_engine as growth_service

    due = growth_service.detect_reminder_due_bookings(
        db, business_id=business_id, limit=20
    )
    sent = 0
    for item in due:
        try:
            booking = item["booking"]
            # Sweep-to-sweep idempotency: a reminder event already carrying
            # executions (queued or completed) is never re-emitted — the
            # worker drains/executed it exactly once.
            existing = growth_service._event_for_entity(
                db,
                business_id=business_id,
                event_type=item["event_type"],
                entity_id=getattr(booking, "id", None),
            )
            if existing is not None and growth_service.event_has_executions(
                db, business_id=business_id, event=existing
            ):
                continue
            event = auto_service.events.emit(
                db,
                business_id=business_id,
                event_type=item["event_type"],
                entity_type="booking",
                entity_id=getattr(booking, "id", None),
                payload=item["payload"],
            )
            db.flush()
            sent += len(
                auto_service.run_rules_for_event(
                    db,
                    settings,
                    business_id=business_id,
                    event=event,
                    event_type=item["event_type"],
                )
            )
        except Exception:  # noqa: BLE001 - per-item safety
            continue
    return sent


def _sweep_inactive_members(
    db: Session, settings: Settings, *, business_id: uuid.UUID
) -> int:
    """Retention automation for deterministically inactive members."""
    from app.services import automation as auto_service
    from app.services import growth_engine as growth_service

    found = growth_service.detect_inactive_members(
        db, business_id=business_id, limit=20
    )
    sent = 0
    for item in found:
        for event_type in ("customer.inactive",):
            try:
                existing = growth_service._event_for_entity(
                    db,
                    business_id=business_id,
                    event_type=event_type,
                    entity_id=item["member_id"],
                )
                if existing is not None:
                    # One retention automation per member per sweep cycle:
                    # skip when executions already exist for the event.
                    if growth_service.event_has_executions(
                        db, business_id=business_id, event=existing
                    ):
                        continue
                    event = existing
                else:
                    event = auto_service.events.emit(
                        db,
                        business_id=business_id,
                        event_type=event_type,
                        entity_type="member",
                        entity_id=uuid.UUID(item["member_id"]),
                        payload={
                            "member_id": item["member_id"],
                            "display_name": item["display_name"],
                            "name": item["display_name"],
                            "phone": item["phone"],
                            "normalized_phone": item["phone"],
                        },
                    )
                    db.flush()
                sent += len(
                    auto_service.run_rules_for_event(
                        db,
                        settings,
                        business_id=business_id,
                        event=event,
                        event_type=event_type,
                    )
                )
            except Exception:  # noqa: BLE001 - per-item safety
                continue
    return sent


def _sweep_seat_continuity(
    db: Session, settings: Settings, *, business_id: uuid.UUID
) -> int:
    """Seat continuity reminders (only for seat-capable businesses with data)."""
    from app.services import automation as auto_service
    from app.services import growth_engine as growth_service

    try:
        from app.services import capabilities as caps_service
        from app.repositories import businesses as business_repo

        business = business_repo.get_by_id(db, business_id)
        if business is not None and not caps_service.is_enabled(
            db,
            business_id=business_id,
            business_type=str(getattr(business, "business_type", "other")),
            capability="seat_management",
        ):
            return 0
    except Exception:  # noqa: BLE001 - capability check never blocks other stages
        pass
    due = growth_service.detect_seat_continuity_due(
        db, business_id=business_id, limit=20
    )
    sent = 0
    for item in due:
        try:
            existing = growth_service._event_for_entity(
                db,
                business_id=business_id,
                event_type="seat.continuity_due",
                entity_id=item["allocation_id"],
            )
            if existing is not None and growth_service.event_has_executions(
                db, business_id=business_id, event=existing
            ):
                continue
            event = auto_service.events.emit(
                db,
                business_id=business_id,
                event_type="seat.continuity_due",
                entity_type="seat_allocation",
                entity_id=uuid.UUID(item["allocation_id"]),
                payload={
                    "allocation_id": item["allocation_id"],
                    "membership_id": item["membership_id"],
                    "display_name": item["display_name"],
                    "name": item["display_name"],
                    "phone": item["phone"],
                    "normalized_phone": item["phone"],
                    "expiry": item["end_date"],
                    "end_date": item["end_date"],
                },
            )
            db.flush()
            sent += len(
                auto_service.run_rules_for_event(
                    db,
                    settings,
                    business_id=business_id,
                    event=event,
                    event_type="seat.continuity_due",
                )
            )
        except Exception:  # noqa: BLE001 - per-item safety
            continue
    return sent


def run_all_businesses(db: Session, settings: Settings) -> list[dict]:
    """Sweep every active business with per-business commit/rollback isolation."""
    results: list[dict] = []
    try:
        business_ids = list_active_business_ids(db)
    except Exception as exc:  # noqa: BLE001 - DB down → empty run, caller logs
        logger.warning("scheduler could not list businesses: %s", exc)
        return results
    for bid in business_ids:
        try:
            results.append(run_business_sweep(db, settings, business_id=bid))
        except Exception as exc:  # noqa: BLE001 - one business never blocks others
            logger.warning("sweep crashed business=%s err=%s", bid, exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            results.append({"business_id": str(bid), "error": str(exc)[:300]})
    return results
