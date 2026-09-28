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
from datetime import datetime, timezone

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
        # 2. Renewal reminders at configured offsets → automation events (idempotent).
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
                    auto_service.dispatch_event(
                        db,
                        settings,
                        business_id=business_id,
                        event_type="membership.expiring",
                        entity_type="membership",
                        entity_id=uuid.UUID(str(item["membership_id"])),
                        payload={
                            "offset_days": item["offset_days"],
                            "end_date": item["end_date"],
                        },
                    )
                    sent += 1
                except Exception:  # noqa: BLE001 - per-item safety
                    continue
            summary["renewal_messages"] = sent
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sweep renewal_scan failed business=%s err=%s", business_id, exc
            )
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
