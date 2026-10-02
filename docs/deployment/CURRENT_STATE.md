# CURRENT STATE — Prime × Nest Business Operating Platform

> Facts only. Last verified: 2026-10-02 (audit pass, local Docker running).
> Secrets are NEVER recorded here — only CONFIGURED / MISSING.

## 1. Repository

- Canonical backend/platform repo: `prime-nest-business-platform` (branch `main`, HEAD `f3fa7ac`).
- Remote: `https://github.com/Om-Gadbail/prime-nest-business-platform.git`.
- Working tree at audit: 9 modified + 6 untracked files (uncommitted Cloudflare
  Python-Worker experiment: `backend/cloudflare_entry.py`, `backend/app/edge/`,
  `backend/app/core/hyperdrive.py`, `backend/app/services/redis_rest.py`,
  `backend/app/middleware/worker_env.py`, `wrangler.jsonc`, `backend/pyproject.toml`,
  plus hardening hooks in `config.py`, `database.py`, `db_routing.py`, `main.py`,
  `health.py`, `rate_limit.py`, `scheduler.py`).
- No `deploy/`, `infra/`, `scripts/`, or `.github/workflows/` permanent
  deployment system existed before this change (created by the production
  foundation pass).

## 2. Application architecture (preserved)

- Synchronous FastAPI (`backend/app/main.py` → `create_app()`).
- Sync SQLAlchemy (`Session`) + `psycopg` driver → PostgreSQL.
- 161 route decorators across 176 Python files under `backend/app/`
  (counted 2026-10-02; do NOT rewrite to async).
- Operational endpoints: `GET /health` (liveness, no DB touch),
  `GET /ready` (readiness, DB + Redis probe, 200/503).
- Versioned API: `/api/v1/...` (leads, auth, CRM, bookings, memberships,
  payments, seats, attendance, owner analytics, automation, WhatsApp, AI, …).
- Middleware order: `WorkerEnvSyncMiddleware` (outer, no-op outside Workers) →
  CORS (exact origins) → `SecurityHeadersMiddleware` → `RequestIDMiddleware` →
  `BodySizeLimitMiddleware` (413 carries request ID).
- Background: `python -m app.worker` + `python -m app.scheduler` (Docker-only;
  never imported at the edge).
- Migrations: `backend/migrations/versions/0001` → `0008_multibusiness_foundation`
  (production head = `0008`). `alembic upgrade head` via one-shot `migrate` service.
- Backend tests: 53 test files under `backend/tests/` (pytest).

## 3. Local runtime (verified UP 2026-10-02)

| Service | Container | Ports | Health |
|---|---|---|---|
| db | `...-db-1` | host `5433` → 5432 | healthy |
| redis | `...-redis-1` | host `6380` → 6379 | healthy |
| backend | `...-backend-1` | host `8000` → 8000 | healthy |
| worker | `...-worker-1` | — | healthy |
| scheduler | `...-scheduler-1` | — | healthy |

- `GET http://localhost:8000/health` → `{"status":"ok",...,"env":"development"}`.
- Local ports: Prime 5173 / Nest 5174 / Prime-staff 5175 / Nest-staff 5176 /
  Owner 5177 / Backend 8000 (frontend repos are separate; only
  `apps/staff-dashboard` is vendored locally for reference).
- `apps/staff-dashboard/.env` (local): `VITE_API_BASE_URL=http://localhost:8000`.

## 4. OSG isolation (verified)

- OSG Growth AI Ops uses host PostgreSQL `5432` + Redis `6379` (UNTOUCHED).
- Prime/Nest local Docker uses `5433` / `6380` — no collision by design.
- Never touch OSG databases, ports, files, repos, or deployments.

## 5. Cloudflare state at audit

- `wrangler.jsonc` (repo root): OLD Python-Workers application architecture
  (`main: backend/cloudflare_entry.py`, Hyperdrive binding
  `004f96f9493f4ad0b69c6bce999c027d`, `python_workers` flags).
  **Superseded by the tiny TS forwarder** (`infra/cloudflare/worker/`).
  Do NOT deploy the old 20+ MB Python bundle again.
- Public Pages (verified HTTP 200 on 2026-10-02):
  Prime `https://prime-fitness.pages.dev`, Nest `https://nest-library.pages.dev`,
  Prime-staff `https://prime-fitness-staff.pages.dev`,
  Nest-staff `https://nest-library-staff.pages.dev`,
  Owner `https://prime-nest-owner.pages.dev`.
- Target API domain: `https://THE-FINAL-API-WORKER-DOMAIN` (placeholder until
  the Worker custom domain is bound; frontends use `VITE_API_BASE_URL`).

## 6. Production database

- Neon project `prime-nest-production`, branch `production`,
  region AWS US East 2 / Ohio, schema at `0008_multibusiness_foundation`.
- Connection strings: MISSING locally (production secrets live only in
  VPS env / `wrangler secret` / CI secrets — never in Git).
- Runtime uses the Neon **pooled** endpoint; migrations/DDL use the direct
  endpoint where required.

## 7. Proven technical constraint (settled — do NOT revisit)

- `sync SQLAlchemy + psycopg` cannot run inside Cloudflare Python Workers
  for this app (greenlet unavailable, direct TCP unviable, pg8000 CPU-killed).
- Final architecture: thin TS Worker → Access → Tunnel → VPS Docker
  (existing FastAPI) → Neon. Worker holds NO DB credentials or logic.

## 8. What was missing (now built)

- [x] Permanent `deploy/production/` (compose, env example, deploy/rollback/
      health/smoke scripts, backup + recovery notes).
- [x] Tiny forwarder Worker (`infra/cloudflare/worker/`) + `wrangler.jsonc`.
- [x] Forwarding-contract test (`scripts/verify/`).
- [x] CI (`.github/workflows/`) for Worker + backend.
- [x] Contract + runbooks + provisioning + acceptance docs.
