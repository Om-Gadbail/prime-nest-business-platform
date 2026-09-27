# Backend Audit — Canonical Consolidation (Prompt 1)

Date: 2026-09-28. Machine: `ossag` workstation. Repo: `prime-nest-business-platform`, branch `main`.
Method: filesystem inspection + code reading (never filenames alone) + route dump from
`create_app()` + test-suite execution in batches. No frontend code was modified. No database
was reset. No migrations were deleted.

## A. Backend locations

### A1. `backend/` — CANONICAL (sole production backend)

- Absolute path: `C:\Users\ossag\OneDrive\Desktop\prime-nest-business-platform\backend`
- Repository/project: `prime-nest-business-platform` (this repo).
- Purpose: the ONE shared FastAPI backend for Prime website, Nest website (via drop-in
  integration), staff dashboard, and owner views.
- Framework: FastAPI (>=0.115,<1.0) + SQLAlchemy 2.x (synchronous, psycopg) + Alembic +
  Pydantic v2 / pydantic-settings. Python 3.14 runtime observed.
- Entrypoint: `backend/app/main.py` — `create_app()` factory, module-level `app = create_app()`.
  This is the ONLY `FastAPI(...)` instantiation in the repo (verified by repo-wide grep
  excluding node_modules/.git/__pycache__/.ruff_cache).
- Database: single PostgreSQL (`DATABASE_URL`, default db `app_db`) via sync engine
  (`app/core/database.py`, `pool_pre_ping`, per-request session via `get_db`, closed in
  `finally`). SQLite is used ONLY by tests (StaticPool, in-memory).
- Authentication: Argon2id (pwdlib) passwords; short-lived HS256 JWT access tokens
  (30 min default) + opaque rotated refresh tokens (SHA-256 hash in `auth_sessions`,
  14-day default, HttpOnly cookie `refresh_token` scoped to `/api/v1/auth`).
- Major routers (all under `/api/v1`, assembled in `app/api/v1/router.py`): system, auth,
  business, leads, bookings, contacts, customers, notifications, public, ai, tasks, audit,
  dashboard, identity, members, memberships (+plans/renewals), payments, attendance, seats
  (+allocations/areas), approvals, owner, automation, communications, whatsapp, ai_chat,
  growth, analytics, brief. Route dump: 160 routes (see `docs/backend-api-inventory.md`).
- Major services: `auth`, `authorization`, `business_context`, `public`, `lead_routing`,
  `owner`, `rate_limit` (in-memory + Redis backend), `idempotency`, `audit`, `scheduler`,
  `worker`, `ai_gateway`, `communications/messaging`, `growth`, `reports`.
- Migration system: single Alembic env (`backend/migrations/env.py`, `backend/alembic.ini`),
  linear chain with NO branches: `0001_baseline` → `0002_identity_multitenancy` →
  `0003_block2_leads_crm` → `0004_block3_tasks_audit_identity` → `0005_block5_7_operations` →
  `0006_block8_12_growth_ai` → `0007_phase1_hardening_money_ids`.
- Test status: 278 tests collected, **278 passed** (run 2026-09-28 in batches; full-suite
  single run exceeds default shell timeouts because Argon2 hashing makes the suite take
  ~10+ min — see §16. Batch results: block1a 34, block1b 44, block2 76, block3 58,
  block5/6/7/8/57 54, full-platform-integration 12).
- Docker status: `backend/Dockerfile` (python:3.12-slim, uvicorn) + root
  `docker-compose.yml` (db, redis, backend, worker, scheduler). Compose-wide single
  `DATABASE_URL` → one shared `app_db` (see gap in §10).
- Consumed by: Prime website (public intake), staff dashboard (~80 authenticated routes +
  public AI-chat widget), Nest website drop-in (`integrations/nest-website`).
- Classification: **CANONICAL**.

### A2. `apps/api` (legacy Owner backend per plan) — NOT FOUND

- `apps/` on this machine contains ONLY `apps/staff-dashboard/` (Vite+React frontend).
  There is NO `apps/api` directory and NO `apps/owner-dashboard` directory.
- No second FastAPI app, no second `alembic.ini`, no second `env.py` exists anywhere in the
  repo. Owner functionality lives INSIDE the canonical backend (`owner` router + service +
  `owner_analytics` repository + `test_block5_owner.py`).
- Classification: **NOT PRESENT on this machine — nothing to deprecate here.** If an
  `apps/api` legacy backend exists on another machine (e.g. the `gadba` workstation named
  in the plan), it was not available for inspection; treat any such copy as LEGACY until
  its routes are diffed against `docs/backend-api-inventory.md`.

### A3. Other project paths named in the plan — NOT FOUND on this machine

- `C:\Users\gadba\OneDrive\Desktop\nest-library-website` — NOT FOUND (different user profile,
  absent here). Covered instead by `integrations/nest-website/` drop-in + `test_block3_nest_public.py`.
- `...\nest-library-staff-dashboard`, `...\prime-fitness-staff-dashboard`,
  `...\prime-nest-business-platform owners dashboard` — NOT FOUND. Staff/owner surfaces are
  served by `apps/staff-dashboard` (single dashboard with `BUSINESS_PRESETS prime|nest|owner`,
  per-business JWT context, owner routes gated by `owner.*` permissions).
- `C:\Users\ossag\OneDrive\Desktop\prime-fitness-website` — EXISTS. Public lead/booking intake
  only (`src/lib/backend.ts` → `POST /api/v1/public/prime/leads|bookings`,
  `GET /api/v1/public/prime/config`). No auth. Compatible, must not break.
- Classification of missing paths: **UNKNOWN (out of scope of this machine) — documented, not assumed.**

### A4. `integrations/nest-website/` — PARTIAL (client-side drop-in, not a backend)

- `backend.ts` / `forms.ts` / `attribution.ts` / `.env.example` / `README.md`: copy-paste
  package for the Nest site (slug `nest`), mirroring the Prime `backend.ts` contract.
- No live Nest site is wired in this checkout (README states Nest site source absent).
- Classification: **PARTIAL — keep; server side already supports it.**

## B. Feature matrix

| Feature | `backend/` (canonical) | `apps/api` legacy | Notes |
|---|---|---|---|
| Authentication (login/me/refresh/logout/switch-business) | YES | N/A (absent) | Argon2id, generic 401, dummy-verify |
| JWT access + opaque refresh rotation + family-kill on reuse | YES | N/A | `auth_sessions`, HttpOnly cookie + JSON fallback |
| Users | YES | N/A | `users` repo, last-login, active/verified flags |
| Roles (OWNER/ADMIN/MANAGER/STAFF/VIEWER, system + future per-business) | YES | N/A | `roles`, role_id FKs only, no name-string checks |
| Permissions (~70 keys, deny-by-default matrix) | YES | N/A | 140 `require_permission` gates, 57 distinct keys used |
| Businesses registry (slugs `prime`/`nest`, UUID PKs) | YES | N/A | No `prime-fitness-001` style string IDs anywhere |
| Business memberships (status, default, role) | YES | N/A | Authoritative per-request |
| Business context (server-derived) | YES | N/A | JWT is hint only; DB re-validated every request |
| Tenant isolation (cross-business → 404, no oracle) | YES | N/A | `assert_same_business`, transfer double-gated |
| Database routing (platform/prime/nest split) | NOT IMPLEMENTED | N/A | Single `app_db`; target architecture is a Prompt-2 migration |
| Business settings / feature flags | YES | N/A | `lead_capture_enabled`, `booking_enabled`, missing=enabled |
| Public website config | YES | N/A | `GET /public/{slug}/config` |
| Leads (+ intake, assign, status, notes, convert, transfer) | YES | N/A | Idempotent public intake, honeypot, audit |
| Customers / Contacts / CRM vocab | YES | N/A | — |
| Bookings (request → confirm/cancel/complete/no-show/reopen) | YES | N/A | Intake creates REQUESTED only |
| Members / Memberships / Plans / Renewals | YES | N/A | State machines, idempotency keys |
| Payments (+ refund, paid_at on `paid`) | YES | N/A | Money hardening migration 0007 |
| Attendance (check-in/out, idempotent) | YES | N/A | — |
| Seats / areas / allocations (Nest) | YES | N/A | Availability endpoints |
| Notifications (+ prefs, unread-count) | YES | N/A | — |
| Analytics (dashboard, metrics, intelligence) | YES | N/A | — |
| Owner analytics (overview/revenue/leads/combined/brief/renewals-scan) | YES | N/A | Combined gated: `owner.combined.read` + OWNER/ADMIN |
| Automation rules / scheduler / worker | YES | N/A | Redis lease when configured, DB-poll fallback |
| WhatsApp Cloud API (send/webhook, multi-number map) | YES (flag-gated) | N/A | `WHATSAPP_ENABLED=false` default; log fallback |
| Gemini/AI gateway (assist, recommendations, public chat) | YES (flag-gated) | N/A | `AI_ENABLED=false` default; noop provider |
| Redis (rate limiting, scheduler lease) | YES (optional) | N/A | `RedisRateLimiter` fails open w/ warning; empty URL = in-memory |
| Audit logging | YES | N/A | `audit-events` read API; intake audit atomic with intake |
| Rate limiting (auth/public/global buckets) | YES | N/A | In-memory default; Redis required for multi-replica prod |
| Body-size limiting (pre-parse 413) | YES | N/A | Middleware, chunked-safe |
| Health checks (`/health` liveness, `/ready` readiness) | YES | N/A | Verified: 200 no-DB / 503 on DB-down |
| Migrations (linear, 7 revisions) | YES | N/A | No heads conflict; history never rewritten |
| Seed data (RBAC matrix, prime+nest, plans, seat areas, templates) | YES | N/A | Idempotent; creates NO users/credentials |
| Tests (278, all passing) | YES | N/A | SQLite isolation; no live DB needed |

## C. API inventory

Full table: `docs/backend-api-inventory.md` (160 routes dumped from `create_app()`).
Key contract anchors (all verified against code + frontend clients):

- Public (anonymous): `GET /api/v1/public/{slug}/config`, `POST /api/v1/public/{slug}/leads`,
  `POST /api/v1/public/{slug}/bookings`, plus `availability`, `business-info`, `ai/chat`.
- Auth: `POST /api/v1/auth/login|refresh|logout|switch-business`, `GET /api/v1/auth/me|businesses`.
- Staff (Bearer, 140 permission gates): leads, bookings, members, memberships, payments,
  attendance, seats, tasks, contacts, customers, notifications, approvals, dashboard, identity,
  automation, communications, whatsapp, ai, growth, analytics, owner, business settings.
- NO endpoint trusts client-supplied `business_id` (grep: zero occurrences in endpoints).
- NO duplicate/overlapping endpoint pairs found — nothing to merge at the HTTP layer.

## Canonical-backend decision

**Canonical: `backend/` (`backend/app/main.py:create_app`).** Reasons, against the plan's criteria:

1. Working functionality: 278/278 tests pass; serves Prime site + staff dashboard + Nest drop-in.
2. Prime compatibility: public `prime` intake + staff hooks all map to existing routes.
3. Nest compatibility: public `nest` intake + seats/allocations + `test_block3_nest_public.py`.
4. Owner compatibility: owner router/service/tests present; no separate owner backend exists here.
5. Auth quality: Argon2id, generic failures, refresh rotation + reuse family-kill, per-request
   DB re-validation. No rewrite justified.
6. RBAC quality: DB-backed roles/permissions, deny-by-default matrix, 140 gates.
7. Tenant isolation: server-derived context; cross-business reads 404; transfers double-gated.
8. Database architecture: single-DB today — the ONLY criterion it fails, and that is a
   documented Prompt-2 migration, not a reason to pick a backend that does not exist.
9–15. Migrations linear, tests comprehensive, API consistent (`/api/v1`), maintainable
   service/repo layering, Docker-ready (backend/worker/scheduler/redis), extensible
   (provider-neutral AI/WhatsApp), minimal destructive change (zero code changes in Prompt 1).
