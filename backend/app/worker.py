"""Background worker (full-platform integration).

Drains due automation work per business in a loop:

    python -m app.worker

Same image as the API; run as the ``worker`` compose service. Jobs are
idempotent per business; failures are logged, never raised; SIGTERM/SIGINT
shut down gracefully between batches. Redis is optional (coordination only).
"""

from __future__ import annotations

import signal
import time

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
    logger.info("worker received signal=%s; shutting down gracefully", signum)
    _stop = True


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    rate_limit_service.configure_redis_limiter(settings)
    interval = max(5, int(settings.worker_interval_seconds or 15))
    logger.info("worker starting interval=%ss batch=%s redis=%s",
                interval, settings.worker_batch_size,
                "configured" if (settings.redis_url or "").strip() else "off")
    factory = get_session_factory()
    # Ensure base seed exists so sweeps always have businesses/rules/templates.
    # The unified platform owner is included unless SEED_PLATFORM_OWNER=false.
    try:
        db = factory()
        try:
            seed_service.seed_development(db, include_owner=settings.seed_platform_owner)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - worker must keep running; next tick retries
        logger.warning("worker seed skipped: %s", type(exc).__name__)
    while not _stop:
        try:
            db = factory()
            try:
                results = scheduler_service.run_all_businesses(db, settings)
                if results:
                    logger.info("worker sweep businesses=%d", len(results))
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - never crash the loop
            logger.warning("worker sweep failed: %s", type(exc).__name__)
        for _ in range(interval * 2):
            if _stop:
                break
            time.sleep(0.5)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
