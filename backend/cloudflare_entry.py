"""Cloudflare Python Workers entrypoint (edge adapter).

Official pattern (Aug 2026 docs)::

    from workers import asgi
    Default = asgi.entrypoint(app)

Phase 2 cutover: the Worker serves the EXISTING FastAPI app DIRECTLY via
Hyperdrive → PostgreSQL (no VPS proxy). Docker Compose is unchanged and
remains the local fallback + migration system of record.

- No rewrite of routes, auth, RBAC, tenant isolation, middleware.
- ``app`` is the canonical FastAPI app; ``Default`` is the Worker target.
- Direct PostgreSQL uses Hyperdrive bindings (PLATFORM/PRIME/NEST) mapped
  to ``HYPERDRIVE_<KEY>_HOST/PORT/USER/PASSWORD/DATABASE`` env by the
  Worker runtime (see ``_apply_hyperdrive_env``). When no binding is
  present the app fails closed with 503 on DB routes (never a fallback
  tenant) — Docker behavior is unaffected.
- Raw ``redis-py`` TCP is never used at the edge; the REST transport
  (``REDIS_REST_URL/TOKEN`` secrets) is selected automatically when set.
- Background worker (app/worker.py) and scheduler (app/scheduler.py)
  signal+sleep loops MUST remain Docker/VPS-only and are never imported
  here. Edge background work goes through ``app.edge.jobs`` (Cron Trigger
  -> Queue -> one-business sweep), which calls the SAME sweep logic.

Local behavior: the ``workers`` package only exists in the Cloudflare
build/runtime. When it is absent (local dev, pytest, Docker), this
module still imports cleanly and exposes ``app`` so existing tooling
(uvicorn, pytest, ruff) keeps working.
"""

from __future__ import annotations

import os

try:  # Real Worker runtime only; absent locally/in Docker/pytest.
    import workers  # type: ignore[import-not-found]

    _IN_WORKER = True
except ImportError:  # pragma: no cover - local fallback, never in Workers.
    _IN_WORKER = False

if _IN_WORKER:
    # Edge marker: short-lived NullPool connections for ANY Worker DB path
    # (Hyperdrive binding or direct-TCP DATABASE_URL secret). Never set
    # locally/in Docker, so the QueuePool path there is untouched.
    os.environ["WORKER_EDGE"] = "1"

if _IN_WORKER and not os.environ.get("DATABASE_URL", "").strip():
    # Edge boot placeholder (NOT a real database): pydantic Settings
    # requires the field at import time, but Worker connections NEVER use
    # it — every trusted key resolves via Hyperdrive bindings when present,
    # via the DATABASE_URL secret (direct-TCP fallback) otherwise, and fails
    # closed (503, no fallback tenant) when unreachable. pg8000 scheme: the
    # edge ships pg8000 (not psycopg), so a failed-closed connect must not
    # raise ModuleNotFoundError. Docker/local behavior is untouched (this
    # branch never runs there).
    os.environ["DATABASE_URL"] = (
        "postgresql+pg8000://edge-boot-placeholder@localhost:5432/edge_unused"
    )

from app.main import create_app

app = create_app()


def _apply_hyperdrive_env(env: object) -> None:
    """Map Hyperdrive bindings to the process env consumed by the adapter.

    Each binding exposes ``host/port/user/password/database``. Never logs
    values. Missing bindings are tolerated (routes fail closed per key).
    """
    mapping = (
        ("HYPERDRIVE", "HYPERDRIVE"),
        ("PLATFORM_HYPERDRIVE", "HYPERDRIVE_PLATFORM"),
        ("PRIME_HYPERDRIVE", "HYPERDRIVE_PRIME"),
        ("NEST_HYPERDRIVE", "HYPERDRIVE_NEST"),
    )
    for binding_name, prefix in mapping:
        binding = getattr(env, binding_name, None)
        if binding is None:
            continue
        for part in ("host", "port", "user", "password", "database"):
            try:
                value = getattr(binding, part, "")
            except Exception:  # noqa: BLE001 - binding shape drift
                continue
            if value is None:
                continue
            os.environ.setdefault(f"{prefix}_{part.upper()}", str(value))

try:  # Cloudflare runtime only; absent locally/in Docker/pytest.
    from workers import WorkerEntrypoint, asgi  # type: ignore[import-not-found]

    Default = asgi.entrypoint(app)

    class EdgeScheduler(WorkerEntrypoint):
        """Cron Trigger -> list due businesses -> enqueue one msg each."""

        async def scheduled(self, controller, event=None):  # pragma: no cover
            from app.edge.jobs import handle_cron_tick

            _apply_hyperdrive_env(self.env)
            result = handle_cron_tick()
            queue = getattr(self.env, "SWEEP_QUEUE", None)
            if queue is not None and result.get("leased"):
                for job in result.get("jobs", []):
                    await queue.send(job)
            return result

    class EdgeQueueConsumer(WorkerEntrypoint):
        """Queue consumer -> validate scope -> sweep ONE business."""

        async def queue(self, batch):  # pragma: no cover
            from app.edge.jobs import handle_queue_message

            _apply_hyperdrive_env(self.env)
            out = []
            for msg in batch.messages:
                try:
                    out.append(handle_queue_message(dict(msg.body)))
                    msg.ack()
                except Exception as exc:  # noqa: BLE001 - retry/DLQ path
                    msg.retry()
                    out.append({"error": type(exc).__name__})
            return out

except ImportError:  # pragma: no cover - local fallback, never in Workers.
    Default = app
