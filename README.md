# Prime Nest Business Platform — Backend + Staff Dashboard (Blocks 0–7)

One shared, lean **modular monolith** backend (FastAPI + PostgreSQL) that
serves Prime Fitness, Nest Library, staff dashboards, the Owner
Command Center, CRM, notifications, analytics, and AI systems — plus the
shared **staff dashboard** (`apps/staff-dashboard`) used by both
businesses.

> **Full-platform integration (this mission):** `docker compose up --build`
> brings up the complete local operating system — `db` (PostgreSQL 16) +
> `backend` (FastAPI) + `redis` (rate limiting / scheduler coordination) +
> `worker` + `scheduler` (per-business automation sweeps) — with Prime/Nest
> websites, staff/owner dashboards, central Gemini gateway, WhatsApp layer,
> and renewal automation all connected. Start here:
> `docs/INTEGRATION_ARCHITECTURE.md`, `docs/LOCAL_DOCKER_RUNBOOK.md`,
> `docs/END_TO_END_WORKFLOWS.md`, `docs/AI_INTEGRATION.md`,
> `docs/WHATSAPP_INTEGRATION.md`, `docs/PRODUCTION_READINESS.md`,
> `docs/FULL_PLATFORM_INTEGRATION_REPORT.md`. No production deploy.

- **Step 1 (verified):** app wiring, configuration, database, migrations,
  health/readiness, Docker, tests.
- **Block 1:** multi-tenant foundation + authentication + RBAC +
  business memberships + business settings.
- **Block 2:** leads/bookings/CRM, notifications, AI foundation, Prime
  website connection (see `docs/BLOCK2.md`, `docs/PRIME_INTEGRATION.md`).
- **Blocks 3 + 4 (this release):** Nest website connection, shared
  business API layer, lead routing, unified identity, tasks, audit
  system, dashboard APIs, Prime + Nest staff dashboards
  (see `docs/BLOCK_3_4_IMPLEMENTATION.md`).

## Architecture

```text
backend/
  app/
    main.py            # create_app() factory, /health, /ready, /api/v1/*
    api/               # HTTP layer (routers only, no business logic)
      deps.py          # get_current_context/user/business + require_permission
      v1/router.py + endpoints/ (system, auth, business)
    core/              # config, database engine/session, logging, security
    models/            # SQLAlchemy Base + ORM models (all exported for Alembic)
    schemas/           # Pydantic request/response contracts
    services/          # business logic (calls repositories, no SQL)
    repositories/      # SQL only (no business logic)
    middleware/        # request-id, error handlers
  migrations/          # Alembic env + versions (imports models.Base)
  tests/               # pytest suite (Blocks 1–4 SQLite integration, ~212 tests)
  Dockerfile
  requirements.txt
  alembic.ini
  pytest.ini
```

Layer rules: `api → services → repositories → models`, with `core` shared.
Routers never touch the DB directly; services never write SQL.

### Block 1: business / tenant model

One Postgres database, many businesses (tenants):

- `businesses` — tenant root (`id` UUID, unique `slug`, `name`,
  `business_type` ∈ {fitness, library, other}, `status` ∈ {active, inactive},
  contact/address/localization columns, `is_active`).
- Seed tenants: `prime` (Prime Fitness, fitness) and `nest` (Nest Library,
  library). Unknown values stay NULL — no fake emails/coordinates/hours.
- Tenant-owned tables carry `business_id → businesses.id` via
  `BusinessScopedMixin`. Repository helpers (`apply_business_scope`,
  `get_scoped`, `list_scoped`, `count_scoped`) make unscoped queries fail
  closed. Client-provided `business_id` (URL/query/body/header) is never
  trusted — the active business always comes from the authenticated context.

### Authentication architecture

- Passwords: Argon2id via `pwdlib` (`hash_password` / `verify_password`).
  Policy: 10–128 chars, no silent truncation. Hashes never leave the API,
  never logged.
- Login `POST /api/v1/auth/login` validates credentials with a generic
  `Invalid email or password.` failure (no account-enumeration leak), resolves
  the default business (or explicit `business_slug` verified against
  membership), issues a short-lived JWT access token + opaque refresh token,
  updates `last_login_at`.
- JWT (PyJWT, HS256 default): minimal claims only —
  `sub` (user id), `jti`, `iat`, `exp`, `type="access"`, `business_id`.
  No PII. Expiry default 30 min (`ACCESS_TOKEN_EXPIRE_MINUTES`).
- Refresh sessions (`auth_sessions` table): only SHA-256 hash stored, opaque
  `secrets.token_urlsafe` value returned. Rotation on every use; reuse of a
  revoked token revokes the whole user session family. Logout revokes the
  active session. Expired/revoked sessions rejected.
- Browser storage: refresh token is set as a `Secure`/`HttpOnly`/`SameSite`
  cookie (`AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE`) AND returned as JSON
  for non-browser clients. Access token stays short-lived in memory — never
  persist long-lived credentials in `localStorage`. No BFF in this block.
- Endpoints (`/api/v1/auth`): `POST /login`, `GET /me`,
  `POST /refresh` (JSON body or cookie), `POST /logout`,
  `GET /businesses` (only my active memberships),
  `POST /switch-business` (`business_id` = UUID or slug, membership-verified,
  403 otherwise).

### RBAC architecture

- Tables: `roles` (`business_id` NULL = system role, non-NULL = future
  business-specific role), `permissions` (`key` unique), `role_permissions`
  (composite PK), `business_memberships`
  (`user_id`, `business_id`, `role_id`, `status` ∈ {active, suspended, revoked},
  `is_default`, unique(`user_id`, `business_id`)).
- System roles: `OWNER` (all 20 permissions), `ADMIN` (all except
  `users.disable`), `MANAGER` (operational management), `STAFF` (day-to-day),
  `VIEWER` (read-only). Explicit matrix in `app/models/rbac.py`; no
  role-name string checks in services — `resolve_permissions()` reads the
  `role_permissions` join and `require_permission("...")` enforces it.
- DB state is authoritative per request: revoked/suspended memberships,
  inactive users/businesses, and role changes take effect immediately on the
  next request (JWT is identity/context only, never the permission source).
- Permission vocabulary reserves future modules (`leads.*`, `bookings.*`,
  `payments.*`, `analytics.read`); Block 1 endpoints enforce only
  `business.read/update` and `settings.read/update` (+ `users.*`/`members.*`
  vocabulary for later blocks).

### Business membership model

A user may belong to Prime only, Nest only, both, or future businesses.
Only `active` memberships in `active` businesses yield a business context.
`GET /auth/businesses` + `POST /auth/switch-business` are the only legal
tenant-switch paths, both membership-verified.

### Business settings model

- `business_settings` — one row per business (`business_id` PK/FK), JSON
  sections: `branding`, `contact`, `address`, `hours`, `localization`,
  `operational`. Core identity stays on `businesses`.
- `GET /api/v1/business` (`business.read`), `PATCH /api/v1/business`
  (`business.update`), `GET /api/v1/business/settings` (`settings.read`),
  `PATCH /api/v1/business/settings` (`settings.update`).
- Pydantic + service validation: timezones (`zoneinfo`), locales
  (`en`/`en-US`), currencies (ISO-3), hex colors, http(s) URLs, phone shapes
  (lenient international), weekly-hours structure (`HH:MM`), booleans, unknown
  sections/fields rejected with 422. Partial-update (merge) semantics.

## Prerequisites

- Python 3.12+ (Docker image uses 3.12-slim)
- Docker + Docker Compose v2

## Quick start (Docker — recommended)

```bash
cp .env.example .env
docker compose up --build
```

- API: <http://localhost:8000>
- Docs (non-production): <http://localhost:8000/docs>
- Liveness: `GET /health` → `{"status": "ok", ...}` (no DB touch)
- Readiness: `GET /ready` → 200 `{"status": "ready", ...}` or 503 `{"status": "not_ready", ...}`
  (includes informational `redis: up|down|disabled`; API stays ready when Redis is down)
- Version: `GET /api/v1/version`
- Full stack: `db` + `redis` + `backend` + `worker` + `scheduler` (all with
  healthchecks; backend waits on `db`+`redis`; worker/scheduler wait on `backend`).
  Worker drains due automation every 15s; scheduler ticks every 60s with a Redis
  lease (single-replica fallback without Redis — every job is idempotent).
  Local-only throwaway live-E2E logins: `python backend/seed_live_e2e.py`
  (creates `prime.owner@live.example.com` / `nest.owner@live.example.com`).

> Port already in use? Another Postgres on your machine (e.g. a Phase 1
> stack) may hold host port 5432. The example env maps host `5433` — the
> backend still reaches the DB as `db:5432` inside the Compose network:
>
> ```bash
> POSTGRES_PORT=5433 docker compose up --build
> ```

## Local start (without Docker)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate  # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
copy ..\.env.example ..\.env   # then set DATABASE_URL to a reachable Postgres
uvicorn app.main:app --reload --port 8000
```

## Environment variables

| Name | Required | Example |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://postgres:postgres@db:5432/app_db` |
| `REDIS_URL` | no (empty = in-memory fallback) | `redis://redis:6379/0` (compose default) |
| `SCHEDULER_INTERVAL_SECONDS` / `SCHEDULER_LEASE_SECONDS` | no (`60` / `120`) | scheduler tick + Redis lease |
| `WORKER_INTERVAL_SECONDS` / `WORKER_BATCH_SIZE` | no (`15` / `50`) | worker drain loop |
| `WHATSAPP_PHONE_NUMBER_MAP` | no (empty) | `prime:<id>,nest:<id>` multi-number routing |
| `APP_ENV` | no (`development`) | `development` / `testing` / `production` |
| `APP_NAME` / `APP_VERSION` | no | `Prime Nest Business Platform` / `0.1.0` |
| `LOG_LEVEL` | no (`INFO`) | `INFO`, `DEBUG`, `WARNING` |
| `BACKEND_CORS_ORIGINS` | no (dev defaults apply) | `http://localhost:3000,http://localhost:5173` |
| `SECRET_KEY` | required in production | output of `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `JWT_SECRET_KEY` | no (overrides `SECRET_KEY` for JWT) | same generation as `SECRET_KEY` |
| `JWT_ALGORITHM` | no (`HS256`) | `HS256` / `HS384` / `HS512` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no (`30`) | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | no (`14`) | `14` |
| `AUTH_COOKIE_SECURE` | no (`false` dev) | `false` locally, `true` in production https |
| `AUTH_COOKIE_SAMESITE` | no (`lax`) | `lax` / `strict` / `none` |

Invalid/missing `DATABASE_URL` fails fast with a clear `ValidationError`.
In production (`APP_ENV=production`) docs are disabled and a default/weak
`SECRET_KEY` (without a strong `JWT_SECRET_KEY`) is rejected.

## Docker commands

```bash
docker compose up --build        # backend + postgres + redis + worker + scheduler
docker compose up -d             # background
docker compose logs -f backend   # follow backend logs
docker compose logs -f worker    # follow worker sweeps
docker compose logs -f scheduler # follow scheduler ticks
docker compose down              # stop
docker compose down -v           # stop + delete DB volume (data loss!)
```

## Database migrations

```bash
cd backend
alembic upgrade head              # apply all migrations
alembic current                   # show current revision
alembic revision --autogenerate -m "describe change"   # after editing models
alembic downgrade -1              # roll back one step
```

`migrations/env.py` reads `DATABASE_URL` from settings and loads
`app.models.Base.metadata`, so new models in `app/models/` are picked up
automatically once imported in `app/models/__init__.py`.

Migration history:

- `0001_baseline` — empty foundation (Step 1).
- `0002_identity_multitenancy` — Block 1: `businesses`, `users`, `roles`,
  `permissions`, `role_permissions`, `business_memberships`,
  `business_settings`, `auth_sessions` (+ indexes/constraints).
- `0003_block2_leads_crm` — Block 2: `contacts`, `customers`, `leads`,
  `lead_activities`, `bookings`, `notifications`,
  `notification_preferences`, `idempotency_records`, `ai_runs`
  (+ indexes/constraints and the 9 Block 2 permission/grant rows).
- `0004_block3_tasks_audit_identity` — Blocks 3/4: `tasks`,
  `audit_events`, `persons`, `identity_links`, `leads` routing columns
  (`routed_by`, `routing_reason`, `routed_at`) (+ the 7 Block 3/4
  permission/grant rows).

## Development seed (safe, idempotent)

```bash
cd backend
python -m app.services.seed
```

Creates system roles + permission matrix, `prime`/`nest` businesses, and one
empty `business_settings` row per business. Blocks 5–7 additionally seed
the membership plan catalogues (Prime 4-plan starter, Nest exact 20-plan
spec) and Nest seat areas — idempotently, never duplicating. Never
deletes data, never creates users/credentials — tests create their own
users. Safe to run repeatedly.

## Tests

```bash
cd backend
pytest
```

- Step 1 (13 tests): app boots, `/health`, `/ready` (up + down),
  `/api/v1/version`, invalid-config failures, DB-connection handling (mocked).
- Block 1 (~65 tests, SQLite-backed integration): businesses/seed/slug
  uniqueness, settings CRUD + validation, users/email uniqueness/Argon2id,
  login/me/refresh/logout/rotation/reuse/expiry/signature, memberships
  (Prime↔Nest isolation, both-business user, suspended/revoked/inactive,
  switch-business 403s), RBAC matrix (owner/admin/manager/staff/viewer,
  403s, escalation blocked, immediate role/revocation effect), adversarial
  tenant isolation (URL/query/body/forged-JWT/repository helpers).
- Block 2 (~75 tests, SQLite-backed integration + PG/Docker
  verification): staff lead/booking/contact/customer CRUD, filters,
  pagination/sorting, assignment, status/transition matrices, notes,
  activities, conversion (incl. reuse + atomicity), public intake
  (validation, honeypot, 413/415/429, idempotency replay/conflict,
  slug/inactive/disabled handling, no-leakage), notifications
  (fan-out, unread, recipient/business isolation, prefs), AI
  (disabled-first, noop, PII masking, audit, 502 path), RBAC matrix for
  the 9 new permissions, adversarial Prime↔Nest isolation, auth/public
  rate limits, CORS, redaction, migration-chain checks.
- Blocks 3 + 4 (58 tests + live verification): lead routing
  (slug/intent/transfer, dual-business audit), unified identity (strict
  matching, ambiguity, family sharing, masking, OWNER/ADMIN gates),
  tasks (CRUD, lifecycle, assignment, related-entity scoping, RBAC),
  audit events (creation, attribution, secrecy, append-only, VIEWER
  denied), dashboard APIs (overview/summaries/activity scoping),
  Nest public intake, booking reopen, adversarial isolation across all
  new resources, new-permission RBAC matrix, plus 43 live Docker checks
  on PostgreSQL and 12 Playwright dashboard E2E (see
  `docs/BLOCK_3_4_IMPLEMENTATION.md`).
- Blocks 5–7 (33 tests, SQLite-backed integration + live-Postgres
  migration/constraint verification): Prime operations (member CRUD +
  360° profile, plan catalogue/versioning/history-safety, membership
  lifecycle + Decimal money math, payment idempotency + refund gates,
  idempotent attendance + checkout, renewal linking), Nest operations
  (exact 20-plan catalogue, seat inventory + server availability,
  allocation exclusivity + release/transfer + history, seat check-in,
  confirmed-seat renewal continuity), owner analytics (truthful zeros,
  presets/trends, documented funnel formulas, combined gating),
  adversarial cross-business 404s for every entity + forged-link +
  viewer/staff boundaries, DB-constraint concurrency nets
  (seat/payment/attendance/renewal), and Prime/Nest/combined E2E flows.
  Migration `0005` verified live on PostgreSQL 16: upgrade head →
  downgrade → upgrade, partial-unique race indexes proven with
  conflicting inserts (see `docs/BLOCKS_5_7_IMPLEMENTATION.md` §11).

```bash
cd apps/staff-dashboard
npm install
npm test        # vitest (20 tests: config, keys, UI, permission nav, ops)
npm run e2e     # playwright (smoke + operations routes, 360/768/1280)
```

## Authentication API overview

| Method & path | Auth | Description |
|---|---|---|
| `POST /api/v1/auth/login` | no | `{email, password, business_slug?}` → tokens + context |
| `GET /api/v1/auth/me` | Bearer | Current user + business + role + permissions |
| `POST /api/v1/auth/refresh` | refresh token | Rotate session → fresh tokens |
| `POST /api/v1/auth/logout` | Bearer + refresh | Revoke active session |
| `GET /api/v1/auth/businesses` | Bearer | My active businesses only |
| `POST /api/v1/auth/switch-business` | Bearer | `{business_id (uuid\|slug)}` → fresh tokens |
| `GET /api/v1/business` | `business.read` | Current business |
| `PATCH /api/v1/business` | `business.update` | Update identity fields |
| `GET /api/v1/business/settings` | `settings.read` | Settings sections |
| `PATCH /api/v1/business/settings` | `settings.update` | Merge-update sections |

Business context behavior: derived server-side from the Bearer token +
fresh DB membership/role lookup. Frontend `business_id` is untrusted input.

## Block 2 — Leads & CRM (completed)

Shared CRM foundation for Prime + Nest on the same monolith/DB:

- **Models + migration `0003_block2_leads_crm`:** `contacts`,
  `customers`, `leads`, `lead_activities`, `bookings`, `notifications`,
  `notification_preferences`, `idempotency_records`, `ai_runs`
  (all business-scoped; see `docs/BLOCK2.md`).
- **Staff APIs** (`/api/v1`, RBAC): leads (CRUD, assign, status
  lifecycle, notes, activities, transactional convert→customer),
  bookings (CRUD + confirm/cancel/complete/no-show transition matrix),
  contacts/customers (safe search, family-shared phones allowed),
  notifications (own+scoped inbox, unread count, preferences),
  AI insights (advisory, disabled by default).
- **Public intake** (`/api/v1/public/{slug}/leads|bookings`):
  slug-verified, feature-flagged, rate-limited, 64KB pre-parse cap,
  honeypot, `Idempotency-Key` dedup, safe minimal responses.
  Public bookings are REQUESTED, never auto-confirmed.
- **Hardening:** `RateLimiter` interface (in-process dev backend;
  Redis required for multi-worker prod), explicit CORS origins
  (`BACKEND_CORS_ORIGINS` ∪ `PUBLIC_SITE_ORIGINS`), security-event
  logging without secrets, uniform 404s across tenant boundaries.
- **AI:** provider-neutral (`noop` default), PII-masked contexts,
  validated structured outputs, metadata-only audit. Works fully with
  `AI_ENABLED=false`.
- **Prime website:** `prime-fitness-website` submits trial/booking
  forms via a centralized client (`src/lib/backend.ts`) — see
  `docs/PRIME_INTEGRATION.md`.

New env (see `.env.example`): `PUBLIC_SITE_ORIGINS`, `RATE_LIMIT_*`,
`MAX_BODY_BYTES`, `AI_*`. Full reference: `docs/BLOCK2.md`.

## Blocks 5–7 — Owner Command Center + Prime/Nest Operations (completed)

Reusable operations platform on the same monolith/DB (see
`docs/BLOCKS_5_7_IMPLEMENTATION.md`, `docs/integrations/`):

- **Migration `0005_block5_7_operations`:** `members`,
  `membership_plans`, `memberships` (price snapshots, lifecycle ⊥ money),
  `payments` (idempotent, provider-neutral), `attendance`
  (one-row-per-day), `renewals` (old→new links), `seat_areas`/`seats`,
  `seat_allocations` (partial uniques: one ACTIVE per seat AND per
  member), `approvals`, `domain_events` — all business-scoped — plus 20
  new permissions with role grants.
- **Owner APIs** (`/api/v1/owner/*`, RBAC): per-business overview,
  revenue/KPI (presets `today 7d 30d month quarter all`), leads funnel
  with documented formulas, and a combined Prime+Nest view gated on
  `owner.combined.read` + OWNER/ADMIN. Empty businesses return zeros —
  no invented metrics.
- **Operations APIs:** members (+360° profile), plans (versioned,
  history-safe), memberships (+status/renew), payments (+settle/refund
  gates), attendance (idempotent check-in/out), renewals pipeline,
  seats (server-computed availability, exclusive allocation with
  release/transfer + history), approvals (request/decide, no
  self-decision). Money is NUMERIC/Decimal; expiry is date-based in the
  business timezone (`Asia/Kolkata` seeded).
- **Capabilities, not branches:** modules toggle via
  `business_settings.operational.capabilities` over template defaults
  (`fitness` vs `self_study_center`); new clients provision via
  `provision_business()` — no code forks.
- **Dashboard:** `/owner`, `/members`, `/memberships`, `/plans`,
  `/renewals`, `/payments`, `/attendance`, `/seats`, `/approvals`
  (permission-gated nav, loading/empty/error/forbidden states,
  responsive 360→1280+, no overflow).
- **Websites NOT connected yet:** contracts documented in
  `docs/integrations/` (plan/seat reads, intake reuse, onboarding);
  staff/owner APIs stay private.

## Blocks 8–12 — Automation + Communication + AI + Growth + Intelligence (completed)

One cohesive platform on the same monolith/DB (see
`docs/BLOCKS_8_12_IMPLEMENTATION.md`):

- **Migration `0006_block8_12_growth_ai`:** `automation_rules/executions`
  (idempotent), `daily_reports`, `conversations/messages/message_templates/
  communication_preferences/message_delivery_events`, `ai_conversations/
  ai_messages/ai_tool_calls/ai_recommendations`, `growth_sources/attributions/
  referrals/cross_sell_opportunities/business_relationships/
  analytics_snapshots` — plus 10 new permissions with role grants.
- **Automation** (`/api/v1/automation/*`): domain events → rules → conditions
  → typed actions (message/task/notification/follow-up/review/referral/
  escalate/AI) → audit → bounded retry; 6 default rules/business; renewal
  scan at configurable offsets; daily owner brief (`/api/v1/owner/brief`).
- **Communication** (`/communications`, `/whatsapp`): provider-neutral
  messaging (WhatsApp Cloud adapter + demo-safe log fallback), verified
  webhooks with HMAC + idempotent inbound, 9 templates/business, opt-in
  enforcement, unified staff timeline.
- **AI** (`/public/{slug}/ai/chat`, `/public/{slug}/business-info`,
  `/public/{slug}/availability`, `/ai/assistant`, `/ai/recommendations`):
  shared website↔WhatsApp runtime, Gemini gateway (configurable model,
  default `gemini-2.0-flash`), 15 public + 9 private tools, real availability
  and `requested`-only bookings, kill switch + honest fallback, eval suite.
- **Growth** (`/api/v1/growth/*`): source attribution funnel, referrals,
  consent-gated cross-sell over configured Prime↔Nest relationships.
- **Intelligence** (`/api/v1/analytics/*`): reproducible metrics + snapshots,
  trend/driver/exception/action findings from measurements only.
- **Dashboard:** `/automation`, `/communications`, `/assistant`, `/growth`,
  `/analytics` + reusable `<WebsiteChat/>` for Prime/Nest sites.
- **Demo:** `seed.seed_demo_data(db)` adds labeled, idempotent demo records;
  mock data only in seed/tests — never in production code paths.

New env (see `.env.example`): `GEMINI_API_KEY`, `GEMINI_MODEL`,
`AI_MAX_OUTPUT_TOKENS`, `AI_MAX_TOOL_CALLS`, `AI_PUBLIC_CHAT_ENABLED`,
`WHATSAPP_*`, `AUTOMATION_ENABLED`, `AUTOMATION_MAX_ATTEMPTS`.

## Security notes

- Argon2id hashing; no plaintext/reversible/SHA256 passwords.
- JWT signed, minimal claims, short expiry; secret from env, never hardcoded.
- Refresh tokens opaque + rotated + hashed at rest; reuse revokes family.
- Generic login failures; 401 vs 403 semantics; safe error envelope (no SQL /
  traces / hashes / tokens / DSNs in responses); no password/token logging.
- Server-side authorization + least privilege + deny-by-default + tenant
  isolation tested adversarially.
- Abuse protection: per-IP rate limits (public intake + login/refresh),
  pre-parse 64KB body cap, honeypot + idempotency on public POSTs,
  strict Pydantic validation, safe error envelope (no SQL/traces/hashes/
  tokens/DSNs), no password/token logging. The dev limiter is
  in-process — multi-worker production requires Redis (same interface).
- TODO (later block, not implemented): account lockout/risk controls,
  refresh-abuse Redis deployment, scheduler for idempotency retention
  (`purge_expired` exists) — services are structured so a Redis/DB-backed
  limiter wraps `login`/`refresh` without refactoring.

## Development workflow

1. Add ORM model in `app/models/` and export it from `app/models/__init__.py`.
2. `alembic revision --autogenerate -m "..."` then `alembic upgrade head`.
3. Add Pydantic schemas in `app/schemas/`.
4. Add repository functions in `app/repositories/` (SQL only).
5. Add service functions in `app/services/` (logic, calls repositories).
6. Add router in `app/api/v1/endpoints/` and include it in `app/api/v1/router.py`.
7. Add/extend tests, run `pytest`, verify `/health` and `/ready`.

## Known future work (intentionally deferred)

Gateway webhook settlement (stubbed as pending-only), member self-service
auth, Redis-backed rate limiting (multi-worker), settings caching.
Production cutover: set `GEMINI_API_KEY` + `WHATSAPP_*` (see
`docs/BLOCKS_8_12_IMPLEMENTATION.md`), schedule
`POST /api/v1/automation/scheduler/run` via cron/systemd, and point the
Prime/Nest sites at the public APIs with the `<WebsiteChat/>` widget.
Next: **production hardening + load QA** (websites stay thin clients;
backend remains source of truth).
