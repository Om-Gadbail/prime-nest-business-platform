"""Periodic scheduler ticker (full-platform integration).

Runs the per-business sweep on a fixed interval with a Redis lease so only
one replica fires each tick:

    python -m app.scheduler

Same image as the API; run as the ``scheduler`` compose service. The manual
ops fallback ``POST /api/v1/automation/scheduler/run`` (per-business scoped)
is unchanged. SIGTERM/SIGINT shut down gracefully between ticks.
"""

from __future__ import annotations

import signal
import time
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger, setup_logging
from app.services import rate_limit as rate_limit_service
from app.services import scheduler as scheduler_service
from app.services import seed as seed_service

logger = get_logger(__name__)
_stop = False


def _handle_stop(signum, frame) -> None:  # type: ignore[no-untyped-def]
    global _stop
    logger.info("scheduler received signal=%s; shutting down gracefully", signum)
    _stop = True


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    rate_limit_service.configure_redis_limiter(settings)
    interval = max(10, int(settings.scheduler_interval_seconds or 60))
    logger.info("scheduler starting interval=%ss redis=%s",
                interval, "configured" if (settings.redis_url or "").strip() else "off")
    factory = get_session_factory()
    try:
        db = factory()
        try:
            seed_service.seed_development(db, include_owner=settings.seed_platform_owner)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduler seed skipped: %s", type(exc).__name__)
    while not _stop:
        tick = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
        try:
            if scheduler_service.acquire_tick_lease(
                    settings, tick=tick, lease_seconds=int(settings.scheduler_lease_seconds)):
                db = factory()
                try:
                    results = scheduler_service.run_all_businesses(db, settings)
                    logger.info("scheduler tick=%s businesses=%d", tick, len(results))
                finally:
                    db.close()
        except Exception as exc:  # noqa: BLE001 - never crash the loop
            logger.warning("scheduler tick=%s failed: %s", tick, type(exc).__name__)
        for _ in range(interval * 2):
            if _stop:
                break
            time.sleep(0.5)
    logger.info("scheduler stopped")


if __name__ == "__main__":
    main()
