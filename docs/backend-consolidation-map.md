# Backend Consolidation Map (Prompt 1)

## CURRENT (verified 2026-09-28 on `ossag` workstation)

```
CURRENT
  |
  +-- backend/  (CANONICAL — backend/app/main.py:create_app, /api/v1, 160 routes, 278 tests green)
  |     |-- platform concerns (users, auth_sessions, roles, permissions, memberships, businesses)
  |     |-- Prime operations (leads, bookings, members, memberships, payments, attendance, ...)
  |     +-- Nest operations  (same domains + seats/allocations; slug-routed, same tables today)
  |
  +-- apps/api  (LEGACY per plan — NOT FOUND on this machine; nothing to consolidate here)
  |
  +-- apps/staff-dashboard  (frontend, Bearer client — untouched in Prompt 1)
  +-- prime-fitness-website (frontend, public intake — untouched in Prompt 1)
  +-- integrations/nest-website (drop-in client package — untouched in Prompt 1)
  |
  v
ONE shared PostgreSQL (app_db) — tenant isolation is by business_id filtering,
enforced server-side per request.
```

## Classification of every backend component

| Component | Verdict | Rationale |
|---|---|---|
| `backend/app/main.py`, router, all 25 endpoint modules | KEEP | Serving all frontends; 278 tests green |
| Auth (security/auth/authz/deps/memberships/sessions) | KEEP | Sound; no rewrite justified |
| RBAC matrix + 140 permission gates | KEEP | Deny-by-default, DB-backed |
| Business context / tenant isolation | KEEP | Server-derived; 404-no-oracle |
| Public intake pipeline | KEEP | Honeypot/idempotency/flags/rate limits intact |
| Owner router+service+analytics | KEEP | Combined gate correct; migrate, don't duplicate |
| Scheduler / worker / Redis limiter | KEEP | Flag-gated, fallback-safe |
| AI/WhatsApp providers (noop default) | KEEP | Provider-neutral, disabled by default |
| Migrations 0001–0007 | KEEP | Linear, never rewrite |
| Seed (`seed_development`) | KEEP | Idempotent, no credentials |
| `apps/api` legacy backend | UNKNOWN — REQUIRES INVESTIGATION (off-machine) | Absent here; diff before any action |
| Single-DB → 3-DB split | MIGRATE (Prompt 2) | Needs per-DB Alembic + session routing + data move |
| Unified owner `owner@prime-nest-dashboard.com` | MIGRATE (Prompt 2) | Does not exist yet; belongs in platform identity |
| Non-v1 API paths (`/api/leads/...` style) | UNKNOWN — REQUIRES INVESTIGATION (Prompt 4) | No such routes here; check off-machine frontends |
| `-001` business IDs | MIGRATE vocabulary (docs) | Code uses slugs/UUIDs; plan docs must follow code |
| In-memory limiter as prod default | REMOVE LATER (docs warning now) | Redis exists; compose already wires it |

Nothing is classified REMOVE in Prompt 1: no replacement or consumer analysis could justify
deletion, and the plan forbids it.

## Endpoint migration table

There are NO duplicate endpoints and NO legacy namespace in this checkout, so the migration
table is the identity mapping: every route below KEEPs its contract through Prompt 2.
(Prefix for all: `/api/v1`. Public routes take `{slug}` = `prime` | `nest`.)

| Method + Path | Auth | Consumer today | Prompt-2 action |
|---|---|---|---|
| `GET /health`, `GET /ready`, `GET /version` | none | compose/orchestrator | KEEP |
| `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/switch-business`, `GET /auth/me`, `GET /auth/businesses` | cookie/Bearer (login+refresh anonymous) | staff dashboard | KEEP; identity moves to platform_db server-side, contract unchanged |
| `GET /public/{slug}/config`, `POST /public/{slug}/leads`, `POST /public/{slug}/bookings`, `GET /public/{slug}/availability`, `GET /public/{slug}/business-info`, `POST /public/{slug}/ai/chat` | none (+rate limit/honeypot/idempotency) | Prime site live; Nest drop-in ready | KEEP |
| `GET\|POST /leads`, `GET\|PATCH /leads/{id}`, `.../assign\|status\|notes\|convert\|transfer`, `.../activities` | Bearer + `leads.*` | staff dashboard | KEEP; operational rows move to prime/nest DBs by context |
| `GET\|POST /bookings`, `.../{id}`, `.../confirm\|cancel\|complete\|no-show\|reopen` | Bearer + `bookings.*` | staff dashboard | KEEP |
| `GET\|POST /members`, `GET\|PATCH /members/{id}`, `.../profile` | Bearer + `members.*` | staff dashboard | KEEP |
| `GET\|POST /membership-plans`, `.../{plan_id}`, `GET\|POST /memberships`, `.../{id}`, `.../status\|renew`, `GET\|POST /renewals` | Bearer + `memberships.*`/`membership_plans.*`/`renewals.*` | staff dashboard | KEEP |
| `GET\|POST /payments`, `.../{id}`, `.../status\|refund` | Bearer + `payments.*` | staff dashboard | KEEP |
| `GET /attendance`, `POST /attendance/check-in`, `.../{id}`, `.../check-out` | Bearer + `attendance.*` | staff dashboard | KEEP |
| `GET /seats`, `POST /seats`, `.../{seat_id}`, `/seats/availability`, `/seats/available`, `GET /seat-areas`, `POST /seat-areas`, `GET\|POST /seat-allocations`, `.../release\|transfer` | Bearer + `seats.*` | staff dashboard (Nest ops) | KEEP |
| `GET\|POST /tasks`, `.../{id}`, `.../assign\|status` | Bearer + `tasks.*` | staff dashboard | KEEP |
| `GET\|POST /contacts`, `GET\|PATCH /contacts/{id}`, `GET /customers`, `POST /customers`, `GET\|PATCH /customers/{id}` | Bearer + `contacts.*`/`customers.*` | staff dashboard | KEEP |
| `GET /notifications`, `.../unread-count`, `.../{id}/read`, `.../read-all`, `PUT .../preferences/{type}` | Bearer + `notifications.*` | staff dashboard | KEEP |
| `GET\|POST /approvals`, `.../{id}/decide` | Bearer + `approvals.*` | staff dashboard | KEEP |
| `GET /dashboard/overview\|activity`, `.../leads/summary`, `.../bookings/summary`, `.../tasks`, `.../notifications` | Bearer + `dashboard.read` | staff dashboard | KEEP |
| `GET /owner/overview\|revenue\|leads\|combined\|brief`, `GET /owner/renewals/scan` | Bearer + `owner.dashboard.read` (`combined` also needs OWNER/ADMIN) | staff dashboard owner view | KEEP; combined reads across prime+nest DBs post-split |
| `GET\|PATCH /business`, `GET\|PATCH /business/settings` | Bearer + `business.*`/`settings.*` | staff dashboard | KEEP |
| `GET /identity/persons/{id}`, `.../cross-business`, `GET\|POST /identity/links` | Bearer + `identity.read` | staff dashboard | KEEP; cross-business read stays explicitly gated |
| `GET /audit-events`, `GET /audit-events/{id}` | Bearer + `audit.read` | staff dashboard | KEEP (platform DB post-split) |
| `GET /automation/rules\|executions`, `POST /automation/rules\|trigger\|seed-defaults`, `PATCH .../{rule_id}`, `POST /automation/scheduler/run` | Bearer + `automation.*` | staff dashboard/worker | KEEP |
| `GET /communications/conversations\|messages\|templates\|timeline`, `POST .../messages`, `PUT .../preferences\|templates` | Bearer + `communications.*` | staff dashboard | KEEP |
| `POST /whatsapp/send`, `GET+POST /whatsapp/webhook` | Bearer for send; signature-gated webhook | Meta callbacks | KEEP |
| `POST /ai/assistant`, `GET /ai/mode\|recommendations`, `POST /ai/leads/{id}/classification\|summary`, `POST /ai/bookings/{id}/recommendation`, `POST /ai/customers/{id}/insight`, `POST .../recommendations/{id}/decide` | Bearer + `ai.*` | staff dashboard | KEEP |
| `GET /growth/sources\|funnel\|relationships\|cross-sell`, `POST .../attributions\|referrals\|cross-sell`, `.../{id}/convert\|consent`, `GET /analytics/metrics\|intelligence`, `GET /analytics/lead/{id}/intelligence` | Bearer + `growth.*`/`analytics.read`/`reports.read` | staff dashboard | KEEP |

## Target

```
CANONICAL (Prompt 2+)
  ONE FastAPI backend (this backend/, same /api/v1 contract)
    |-- platform  -> platform_db (identity, RBAC, registry, owner access, audit)
    |-- Prime     -> prime_db    (all prime operational rows, same routes)
    +-- Nest      -> nest_db     (all nest operational rows, same routes)
  shared services (auth, context, routing, idempotency, audit, scheduler/worker)
```

Rule for Prompt 2: the HTTP contract above is frozen; the split happens behind
`BusinessContext` (platform vs prime vs nest session) with per-database Alembic branches.
