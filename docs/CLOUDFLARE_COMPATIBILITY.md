# Cloudflare Compatibility Audit — Prime Nest Business Platform

Date: 2026-10-01. Scope: existing FastAPI backend, no behavior changes.
Entrypoint audited: `backend/app/main.py` (`create_app()` + module-level `app`).

## 1. Canonical app

- Factory: `create_app() -> FastAPI` in `backend/app/main.py:50`.
- Module app: `app = create_app()` in `backend/app/main.py:122`.
- Routers: `app/api/v1/router.py` assembles 26 routers (`system, auth,
  business, leads, bookings, contacts, customers, notifications, public,
  ai, tasks, audit, domain_events, dashboard, identity, members,
  memberships, payments, attendance, seats, approvals, owner, automation,
  communications, whatsapp, integrations, ai_chat, growth_analytics x3`).
- Operational: `GET /health` (no DB touch), `GET /ready` (DB required,
  Redis informational), `GET /api/v1/version`.
- WhatsApp verification/inbound under `/api/v1/whatsapp/webhook` and
  `/api/v1/whatsapp/webhook/{business_key}` — therefore the required
  `GET|POST /api/v1/whatsapp/webhook/prime` paths exist with no change.

## 2. Startup / lifespan (`backend/app/main.py:31-47`)

- Logs startup, calls `rate_limit.configure_redis_limiter(settings)`.
- `configure_redis_limiter` never raises: returns `"redis"` on PING ok,
  else `"memory"` fallback. Workers-safe by design.
- No DB connection opened at import or lifespan. Engine is lazy
  (`get_engine()` builds on first request). Lifespan is ASGI-compatible
  (Cloudflare `asgi` runs lifespan startup/shutdown around requests).

## 3. Dependency verdict

| Dependency | Version | Workers verdict |
|---|---|---|
| `fastapi` | >=0.115,<1.0 | COMPATIBLE (official Workers FastAPI support via `workers.asgi`) |
| `pydantic`, `pydantic-settings` | >=2.7 / >=2.3 | COMPATIBLE (pure Python) |
| `PyJWT` | >=2.8 | COMPATIBLE (pure Python; HS256/384/512 HMAC) |
| `email-validator` | >=2.0 | COMPATIBLE (pure Python) |
| `httpx` | >=0.27 | COMPATIBLE for outbound HTTPS (Gemini `generateContent`, WhatsApp Cloud `graph.facebook.com`). Cloudflare lists httpx among fast-cold-start packages |
| `SQLAlchemy` | >=2.0 | INSTALLABLE but UNUSABLE for live DB in Workers (needs a DBAPI driver with TCP; see psycopg row) |
| `psycopg[binary]` | >=3.1 | **BLOCKER — INCOMPATIBLE.** Compiled C extension + raw PostgreSQL TCP sockets. Workers isolates have no raw TCP; only fetch/binding I/O. Direct `postgresql+psycopg://` cannot connect from the Worker |
| `redis` | >=5,<7 | **INCOMPATIBLE for live Redis.** Raw TCP sockets. Code already degrades safely: limiter falls back to in-memory, `/ready` reports `redis: down/disabled`, scheduler lease falls back to single-replica. Distributed rate limiting / leader locking unavailable in-Worker |
| `pwdlib[argon2]` | >=0.2 | **LIKELY INCOMPATIBLE / UNVERIFIED.** Requires native argon2 backend (argon2-cffi). Not on Cloudflare's confirmed pure-Python list. Password hashing/verification (`hash_password`/`verify_password`) may fail to import or run in-Worker. Login paths depend on it |
| `uvicorn[standard]` | >=0.30 | VPS/DOCKER-ONLY. Includes uvloop/httptools. Never deployed to Workers (Cloudflare provides the ASGI server) |
| `alembic` | >=1.13 | VPS/DOCKER-ONLY (migration CLI, `migrate` compose service) |
| `pytest` | >=8.0 | LOCAL/CI-ONLY, not a Worker dependency |

## 4. PostgreSQL / Redis access patterns

- `app/core/database.py`: sync `create_engine(database_url)` with
  `pool_pre_ping=True`, `connect_timeout=3`; `get_db()` yields a
  request-scoped `Session`. All request paths go through `get_db`.
- `app/core/db_routing.py`: per-key engines (`platform_db/prime_db/
  nest_db`) behind `threading.Lock`, `sessionmaker` per key, `ping_key/
  ping_all`. Co-located mode (default: all keys share `DATABASE_URL`)
  avoids extra connections; split mode opens one pool per distinct URL.
- `app/services/rate_limit.py`: `RedisRateLimiter` (`INCR`+`EXPIRE` via
  `redis.Redis.from_url`) with fail-open downgrade; `InMemoryRateLimiter`
  (threading.Lock + deque) is the default.
- `app/services/health.py::_redis_status`, `app/services/scheduler.py::
  acquire_tick_lease`: best-effort Redis probes, never raise.
- `app/api/deps.py`: every business-scoped request re-validates
  membership/role from the DB and enforces `resolve_database_key`
  (fail-closed 403, no fallback tenant).

## 5. Filesystem / subprocess / threading / OS-specific

- `signal` + `time.sleep(0.5)` loops: `app/worker.py`, `app/scheduler.py`
  only. Workers have no SIGTERM/SIGINT and no long-lived loops; these
  files MUST stay VPS/Docker-only (never imported by the Worker entry).
- `threading.Lock`: `app/core/db_routing.py:116`,
  `app/services/rate_limit.py:56`. Single-isolate safe; NOT shared state
  across edge isolates. In-memory limiter is per-isolate only.
- `time.sleep` retries: `app/services/ai_gateway.py` (Gemini, max ~2s
  backoff), `app/services/messaging.py` (WhatsApp). Blocking sleeps burn
  Worker CPU time; keep retry budgets as-is for VPS, expect tighter
  effective budgets at the edge.
- `sys.stdout` logging (`app/core/logging.py`): compatible (Workers log).
- `os.environ` reads: `app/services/seed.py` (demo-password fallback),
  `migrations/env.py`, `seed_live_e2e.py`, tests only. Workers have no
  `.env` file; `pydantic-settings env_file=".env"` silently finds nothing
  and `extra="ignore"` tolerates it — config must come from Worker
  `vars`/`secrets` (see `docs/CLOUDFLARE_ENV.md`).
- `socket` raw TCP: only `backend/entrypoint.sh` (Docker Postgres wait).
  Never runs in Workers.
- No `subprocess`, `multiprocessing`, `shutil`, template-file reads in
  request paths. `Path(__file__)` appears in tests only.

## 6. Background worker / scheduler — MUST stay outside the Worker

- `python -m app.worker` (15s sweep, `run_all_businesses` per business,
  idempotent) and `python -m app.scheduler` (60s tick + Redis lease).
- Both install signal handlers, seed idempotently, loop forever.
- Cloudflare Workers cannot host them (no signals, no cron-loop
  semantics here, CPU/wall-clock limits). Keep `worker` + `scheduler`
  compose services intact. Cloudflare Cron Triggers are NOT adopted
  (would need a proven-safe redesign of idempotency/leases — out of
  scope; mission forbids blind moves).

## 7. VPS/Docker-only code (never in the Worker bundle path)

- `backend/Dockerfile`, `backend/entrypoint.sh`, `backend/alembic.ini`,
  `backend/migrations/`, `backend/seed_live_e2e.py`.
- `app/worker.py`, `app/scheduler.py`.
- `uvicorn`, `alembic`, `psycopg[binary]` live connections, `redis` live
  connections, Argon2 native hashing (until proven in the Workers build).

## 8. Decision

- Direct PostgreSQL connectivity from the Worker is **NOT viable**
  (psycopg TCP blocker + Argon2 unverified).
- No replacement invented. Production-safe topology (smallest change):

```text
Browsers/5 frontends ──HTTPS──> Cloudflare Worker (edge: routing, headers,
  CORS, request IDs, auth passthrough; NO DB credentials in frontend)
  ──HTTPS (authenticated, allowlisted)──> VPS Docker backend
  (FastAPI + worker + scheduler; holds DATABASE_URL/REDIS_URL/secrets)
  ──private──> PostgreSQL 16 + Redis 7 (never publicly exposed)
```

- The Worker CAN run the complete FastAPI ASGI app for stateless paths
  (`/health`, OpenAPI in non-prod, validation/422s, honest Gemini/WhatsApp
  fallbacks) but DB-backed routes are only live when the Worker forwards
  to (or is replaced by) the VPS backend. Until a Hyperdrive-style
  Postgres path is proven for `psycopg` + Argon2 on Python Workers, the
  Worker is the **HTTP edge layer**, not the system of record.
- PostgreSQL/Redis REMAIN where they are (private VPS/Docker network).
