# Integration Architecture — Prime Fitness × Nest Library Business Operating System

**Date:** 2026-09-27
**Source:** discovered from code (not aspirational). Read `backend/app`, `apps/staff-dashboard/src`,
`integrations/nest-website`, `docker-compose.yml`, `backend/migrations/versions`, `docs/`.

## 1. Canonical topology (locked)

```text
Public browsers (Prime site / Nest site — thin clients, slug-addressed, no secrets)
  │  POST /api/v1/public/{slug}/leads|bookings (Idempotency-Key, honeypot, rate-limit)
  │  POST /api/v1/public/{slug}/ai/chat · GET /public/{slug}/business-info|availability
  ▼
ONE FastAPI backend  (backend/app/main.py :: create_app(), /health, /ready, /api/v1/*)
  │  api → services → repositories → models, core shared
  │  auth: Argon2id + JWT access (30m) + opaque rotated refresh (HttpOnly cookie + JSON)
  │  RBAC: roles/permissions/role_permissions/business_memberships, DB-authoritative per request
  │  tenancy: businesses root; BusinessScopedMixin (business_id FK NOT NULL) + apply_business_scope;
  │           client business_id NEVER trusted; context from JWT + fresh DB lookup
  ├── AI Gateway        (app/services/ai_gateway.py: ChatProvider/Noop/Gemini + ai_chat.py runtime + ai_tools.py 15 public/9 private)
  ├── Automation engine (app/services/automation.py: dispatch_event → rules → conditions → typed actions → idempotent executions → bounded retry)
  ├── Communications    (app/services/communications.py + messaging.py: LogProvider demo / WhatsAppCloudProvider prod; templates, opt-in, timeline)
  ├── Growth/Analytics  (app/services/growth.py, analytics.py, reports.py: attributions, referrals, cross-sell, metrics/snapshots, daily brief)
  ├── Operations        (members, memberships, payments, attendance, renewals, seats, approvals, tasks, audit, notifications, dashboard, owner)
  ▼
ONE PostgreSQL 16 (db service; migrations 0001→0007; models.Base metadata)
OPTIONAL Redis 7 (rate limiting, scheduler/worker coordination, cache) — added by full-platform integration
  ├── worker    (same image, CMD worker: drains retrying/pending automation per business, renewal scan, reports)
  └── scheduler (same image, CMD scheduler: periodic ticker calling the same per-business jobs with Redis lock)
```

**Rule:** Prime and Nest are `businesses` rows (`slug` prime/nest), NOT separate apps/backends.
New clients provision via `provision_business()` / seed + `business_settings.operational.capabilities`
(`fitness` vs `self_study_center` templates), never by cloning the backend.

## 2. Backend map (verified)

- Entrypoint: `backend/app/main.py` — `create_app()`, `BodySizeLimitMiddleware` (streaming 413),
  `RequestIDMiddleware`, safe CORS (exact origins union `BACKEND_CORS_ORIGINS ∪ PUBLIC_SITE_ORIGINS`),
  safe error envelope, `/health` (no DB) + `/ready` (DB ping) + `/api/v1/*`.
- Router: `backend/app/api/v1/router.py` — 26 routers: system, auth, business, leads, bookings,
  contacts, customers, notifications, public, ai, tasks, audit, dashboard, identity, members,
  memberships, payments, attendance, seats, approvals, owner, automation, communications,
  whatsapp, ai_chat, growth+analytics+brief.
- Layering (enforced): routers (HTTP only) → services (logic, no SQL) → repositories (SQL only) → models.
- Config: `app/core/config.py` (pydantic-settings, fails fast). Secrets live ONLY here (backend env).
- DB: `app/core/database.py` (sync psycopg, pool_pre_ping, 3s connect timeout). Migrations in
  `backend/migrations/versions/`: 0001 baseline → 0002 identity/multitenancy → 0003 leads/CRM →
  0004 tasks/audit/identity → 0005 operations → 0006 growth/AI → 0007 hardening (money Numeric, nullable provider ids, conversation dedupe index).
- Auth/RBAC: `app/services/auth.py`, `authorization.py`, `app/api/deps.py`
  (`get_current_context` + `require_permission`). JWT = identity only; permissions re-read from DB each request.
- Public intake: `app/api/v1/endpoints/public.py` + `services/public.py` (slug resolve + active check),
  `services/leads.py`/`bookings.py` (intake creates NEW lead / REQUESTED booking, never confirmed),
  `services/idempotency.py` (header `Idempotency-Key [A-Za-z0-9-_]{8,64}`, replay vs 409),
  `services/rate_limit.py` (in-process fixed window; `set_limiter()` swaps a Redis backend without code changes),
  `services/lead_routing.py` (slug/intent/transfer + audit).
- AI: `services/ai_gateway.py` (ChatProvider interface; `NoopChatProvider` fake; `GeminiChatProvider`
  REST generateContent + functionDeclarations; configurable `GEMINI_MODEL`, timeouts, retries, structured
  `AIProviderError`, usage hook), `services/ai_chat.py` (ONE shared website↔WhatsApp turn pipeline:
  persist → context → gateway → validated allowlisted tool calls → final → persist → reply; kill switch
  `AI_ENABLED=false` → honest fallback; `ai_runs` + `ai_tool_calls` audit), `services/ai_tools.py`
  (15 PUBLIC + 9 PRIVATE tools; public callers get PermissionError on private tools; availability from
  real hours−bookings; booking creation returns `requested` only).
- Comms: `services/messaging.py` (MessagingProvider; `LogProvider` demo-safe; `WhatsAppCloudProvider`
  template/text, 15s timeout; `verify_whatsapp_signature` HMAC, fail-closed in prod),
  `services/communications.py` (templates, opt-in `communication_preferences`, send pipeline with
  provider-id idempotency, inbound dedupe, delivery events, timeline), endpoints
  `communications.py` (staff) + `whatsapp.py` (Meta verify/inbound/status + staff send).
  Business resolution for inbound: `phone_number_id → business` via per-business
  `business_settings.operational.whatsapp.phone_number_id` (+ `WHATSAPP_PHONE_NUMBER_MAP`
  `slug:phone_id` override), falling back to demo `business_slug` field outside production.
- Automation: `services/automation.py` (`dispatch_event` persists `domain_events` then runs matching
  active rules; per-action idempotency `sha256(business:rule:event:slot)`; bounded retry
  `retrying`+`scheduled_at`; 8 action types; 6 default rules/business), `services/reports.py`
  (daily brief + `renewal_scan` at configurable offsets 30/14/7/3/1/0), endpoint
  `automation.py` (`/rules`, `/executions`, `/trigger`, `/scheduler/run` per-business scoped,
  `/seed-defaults`).
- Scheduler/worker (full-platform addition): `app/services/scheduler.py` (per-business sweep:
  `retry_due` + renewal reminders + daily brief + idempotency purge; Redis lock when `REDIS_URL`
  set, DB-safe fallback otherwise; structured logging; idempotent; no cross-business execution),
  `app/worker.py` (`python -m app.worker`: continuous drain loop), `app/scheduler.py`
  (`python -m app.scheduler`: periodic ticker loop). Both share the backend image; compose runs
  them as `worker` and `scheduler` services with `depends_on` + healthchecks + graceful SIGTERM.
- Growth/intel: `services/growth.py` (sources, attributions, referrals, consent-gated cross-sell over
  `business_relationships`), `services/analytics.py` (metrics from source records + snapshots +
  trend/driver/exception/action findings), `services/owner.py` + `growth_analytics.py` endpoints
  (`/owner/*` per-business + combined gated on `owner.combined.read` + OWNER/ADMIN; empty → zeros).
- Ops: members (+360°), plans (versioned, history-safe), memberships (Decimal money, date-based expiry
  in business tz `Asia/Kolkata`), payments (idempotent, settle/refund gates), attendance
  (one-row-per-day), renewals (old→new links), seats (server availability, exclusive allocation +
  release/transfer + history), approvals (no self-decision), tasks, audit (append-only), notifications
  (fan-out, prefs), identity (strict matching, OWNER/ADMIN gates), dashboard summaries.

## 3. Frontend map

- `apps/staff-dashboard` — ONE shared dashboard for Prime/Nest/Owner (same routes, backend-driven
  identity). Router `src/App.tsx` (login + 20 authed routes: overview, owner, leads, bookings,
  contacts/customers, members/memberships/plans/renewals, payments, attendance, seats, approvals,
  automation, communications, assistant, growth, analytics, tasks, notifications, activity, settings).
- API: ONLY `src/lib/api.ts` talks to the backend (Bearer in memory + HttpOnly refresh cookie,
  15s timeout, one transparent refresh on 401, typed `ApiError`, `X-Request-ID` surfaced).
  Business identity from `/auth/me`; branding from `src/config/business.ts` presets (prime/nest/owner)
  + backend business record. No Gemini/WhatsApp keys in browser (verified by scan).
- Env: `VITE_API_BASE_URL`, `VITE_BUSINESS_SLUG`, `VITE_BUSINESS_NAME` only (see `.env.example`).
- Tests: vitest (unit), `tsc -b` typecheck, `oxlint` lint, `vite build`, Playwright smoke/operations/live
  (preview server, no backend) + documented live flows against Docker backend.

## 4. Website integrations

- Prime site (external repo `prime-fitness-website`): centralized `src/lib/backend.ts` +
  `src/lib/attribution.ts`, trial/booking forms → `POST /public/prime/leads|bookings`
  (Idempotency-Key, honeypot `website_url`, 12s timeout, typed BackendError, honest
  "request received" copy, call/WhatsApp fallback). Contract: `docs/PRIME_INTEGRATION.md`,
  `docs/API_INTEGRATION.md`.
- Nest site (drop-in package `integrations/nest-website/`): `backend.ts` + `attribution.ts` +
  `forms.ts` + `.env.example` (`VITE_BUSINESS_SLUG=nest`), same contract against `/public/nest/*`.
  Both sites additionally use `POST /public/{slug}/ai/chat` (+ `business-info`, `availability`)
  via the reusable `<WebsiteChat/>` widget (no API key in browser; slug server-verified).

## 5. Data-flow inventory (end-to-end)

1. **Website → CRM → dashboard:** visitor → site form → `POST /public/{slug}/leads|bookings`
   → business resolve → feature flag → honeypot → idempotency acquire → intake (NEW/REQUESTED)
   → attribution → audit → 201 `{lead_id|booking_id}` → staff dashboard (leads/bookings lists,
   timeline, tasks) → convert → customer/member → membership → payment → renewal.
2. **AI receptionist:** visitor → `<WebsiteChat/>` → `POST /public/{slug}/ai/chat`
   → shared runtime (gateway + PUBLIC tools only, business-scoped) → reply + `ai_*` audit.
3. **Staff/owner AI:** dashboard `/assistant` → `POST /ai/assistant` (`ai.assist`; role OWNER→owner mode)
   → shared runtime with PRIVATE tools allowed (still business-scoped) → recommendations workflow
   (`ai.read`/`ai.manage`; high-risk → approvals).
4. **WhatsApp:** Meta → `POST /whatsapp/webhook` (HMAC verify, `phone_number_id→business`, dedupe,
   status→delivery events) → conversation/message rows → timeline; staff/automation →
   `send_message` (opt-in check, template resolve server-side, provider abstraction, idempotent,
   status tracking) → provider → delivery events.
5. **Automation:** domain event (lead.created, booking.confirmed/completed, membership.renewed, …)
   → `dispatch_event` → matching active rules → typed actions (message/task/notification/followup/
   review/referral/escalate/AI/webhook_log) → executions audit → `retry_due`/scheduler replay
   (bounded, per-business) + renewal scan + daily brief (`/owner/brief`).
6. **Membership→renewal:** member → membership (active, end_date) → payment (paid) →
   `renewal_scan` (scheduler/worker, offsets) → automation rule → WhatsApp/message + task/notification
   → timeline → staff follow-up → renewal membership (old→new link) → payment.

## 6. Dependency map (what blocks what)

- Everything needs `db` healthy + migrations at head + `seed_development` (roles, prime/nest, settings, plans, rules/templates/sources, Prime↔Nest link).
- Public intake needs CORS (`PUBLIC_SITE_ORIGINS` includes site origins) + rate limiter + idempotency table.
- AI needs `AI_ENABLED=true`; real answers need `AI_PROVIDER=gemini` + `GEMINI_API_KEY` (+ optional `GEMINI_MODEL`);
  without them the Noop fake keeps every flow testable.
- WhatsApp needs `WHATSAPP_ENABLED=true` + token/phone-id for real sends; without them `LogProvider`
  keeps every flow testable. Inbound needs `WHATSAPP_APP_SECRET` (prod) / verify token for GET verify;
  per-business routing needs operational `whatsapp.phone_number_id` or `WHATSAPP_PHONE_NUMBER_MAP`.
- Automation needs `AUTOMATION_ENABLED=true`; timed follow-ups/renewals/briefs need `worker`+`scheduler`
  (+ optional `REDIS_URL` for distributed locking/rate limiting) — manual `POST /automation/scheduler/run`
  remains as an ops fallback.
- Dashboards need `VITE_API_BASE_URL` → backend + a seeded user/membership (tests create their own;
  local demo uses explicit seed scripts, never hardcoded credentials).

## 7. What was already working vs what integration added

- Already working (Blocks 0–12 + Phase-1 hardening): everything in §§2–5 except the scheduler/worker/Redis
  runtime, the `phone_number_id→business` production mapping, and Gemini retry/usage-hook hardening.
- Integration added (this mission, additive only): `REDIS_URL` + Redis-backed limiter (fallback-safe),
  `app/services/scheduler.py` + `app/worker.py` + `app/scheduler.py`, compose `redis`/`worker`/`scheduler`
  services with healthchecks/ordering, `WHATSAPP_PHONE_NUMBER_MAP` + operational phone mapping +
  webhook resolution order, Gemini retry/backoff + structured logging + usage hook + auto provider note,
  expanded `.env.example` (dev/test/staging/prod), API-contract audit, runbooks/workflows/AI/WhatsApp/
  readiness docs, platform E2E + isolation + failure tests, and `docs/FULL_PLATFORM_INTEGRATION_REPORT.md`.
