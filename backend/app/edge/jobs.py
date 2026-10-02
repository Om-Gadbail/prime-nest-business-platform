"""Cloudflare edge wrappers: Cron Trigger + Queue consumer (thin adapters).

Docker ``worker.py`` / ``scheduler.py`` infinite loops are UNTOUCHED and
remain the local fallback. These wrappers call the SAME business logic
(``run_business_sweep`` / ``run_all_businesses``) with the SAME validation,
transaction boundaries, retries, and idempotency — only the trigger differs:

  Cron Trigger (every 60s, mirrors SCHEDULER_INTERVAL_SECONDS)
      -> ``handle_cron_tick``: build tick, acquire distributed lease
         (REST Redis, never in-memory), list active businesses, return the
         list of business jobs to enqueue (never runs an unbounded sweep
         inline — the caller enqueues one Queue message per business).
  Queue consumer
      -> ``handle_queue_message``: re-validate ``business_id`` server-side
         via ``validate_business_job_scope`` (payload is routing info, NOT
         authorization), run ONE business sweep in its own transaction scope,
         return the sweep summary. Failures carry business_id + job identity
         for DLQ triage; cross-business execution is impossible (fail closed).

Retry/DLQ policy mirrors automation config: max attempts =
``AUTOMATION_MAX_ATTEMPTS`` (default 5); exhausted messages go to DLQ with
business_id + event identity preserved (Queue `retry`/`dlq` wiring lives in
``wrangler.jsonc``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def current_tick(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M")


def handle_cron_tick(settings: Settings | None = None) -> dict:
    """Cron entry: acquire lease, list due businesses. Never sweeps inline."""
    from app.core.database import get_session_factory
    from app.services import scheduler as sched

    cfg = settings or get_settings()
    if not cfg.scheduler_enabled:
        return {"tick": current_tick(), "leased": False, "reason": "disabled"}
    tick = current_tick()
    leased = sched.acquire_tick_lease(
        cfg, tick=tick, lease_seconds=cfg.scheduler_lease_seconds
    )
    if not leased:
        return {"tick": tick, "leased": False}
    factory = get_session_factory()
    db = factory()
    try:
        bids = sched.list_active_business_ids(db)
    finally:
        db.close()
    jobs = [{"business_id": str(b)} for b in bids]
    logger.info("cron tick=%s leased jobs=%d", tick, len(jobs))
    return {"tick": tick, "leased": True, "jobs": jobs}


def handle_queue_message(message: dict, settings: Settings | None = None) -> dict:
    """Queue entry: validate scope server-side, sweep ONE business."""
    from app.core import db_routing as routing
    from app.core.database import get_session_factory
    from app.services import scheduler as sched

    cfg = settings or get_settings()
    raw_bid = (message or {}).get("business_id")
    try:
        bid = uuid.UUID(str(raw_bid))
    except (ValueError, AttributeError, TypeError) as exc:
        raise routing.DatabaseRoutingError(
            f"Invalid queue business scope: {raw_bid!r}."
        ) from exc
    factory = get_session_factory()
    db = factory()
    try:
        # Fail closed: inactive/unknown/mis-mapped business never executes.
        routing.validate_business_job_scope(db, business_id=bid)
        result = sched.run_business_sweep(db, cfg, business_id=bid)
        db.commit()
        return {
            "business_id": str(bid),
            "ok": True,
            "result": result,
            "idempotency": str((message or {}).get("idempotency_key", ""))[:64],
        }
    except Exception:
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 - best effort
            pass
        raise
    finally:
        db.close()
