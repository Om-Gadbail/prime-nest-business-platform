"""Worker env sync (Cloudflare Python Workers adapter).

PROBLEM: on Python Workers, `vars` / secrets / bindings are delivered
per-request in the ASGI scope (`scope["env"]`), NOT in `os.environ`.
`pydantic-settings` reads `os.environ`, so without this middleware the app
would boot with defaults (APP_ENV=development, no secrets) in production.

FIX: outermost middleware copies the request's Worker env into
`os.environ` (explicit allowlist = `Settings` field names, uppercased, plus
the `HYPERDRIVE` binding parts) and clears the cached settings so every
request downstream rebuilds config from the synced env. All values are
identical for every request of one Worker (same bindings), so per-request
sync is race-safe. Outside Workers (`scope` has no `env`) this is a no-op —
Docker/local behavior is byte-for-byte unchanged.

No business logic, auth, or tenant code is touched.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware


class WorkerEnvSyncMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        scope_env = (request.scope or {}).get("env")
        if scope_env is not None:
            try:
                self._sync(scope_env)
            except Exception:  # noqa: BLE001 - sync must never break requests
                pass
        return await call_next(request)

    def _sync(self, scope_env: object) -> None:
        import os

        from app.core.config import Settings, get_settings

        for field in Settings.model_fields:
            name = field.upper()
            try:
                value = getattr(scope_env, name, None)
            except Exception:  # noqa: BLE001 - binding shape drift
                continue
            if isinstance(value, str) and value != "":
                os.environ[name] = value
        # Hyperdrive binding object -> HYPERDRIVE_* parts (never logged).
        # Deferred import: cloudflare_entry imports app.main at module load.
        try:
            from cloudflare_entry import _apply_hyperdrive_env as apply_hd

            apply_hd(scope_env)
        except Exception:  # noqa: BLE001 - entry layout drift, best effort
            pass
        get_settings.cache_clear()
        # Activate the shared REST limiter once its credentials arrive via
        # scope env (lifespan runs with boot env and cannot see them).
        try:
            from app.services import rate_limit as rl

            if isinstance(rl.get_limiter(), rl.InMemoryRateLimiter):
                rl.configure_redis_limiter(get_settings())
        except Exception:  # noqa: BLE001 - limiter fallback keeps serving
            pass
