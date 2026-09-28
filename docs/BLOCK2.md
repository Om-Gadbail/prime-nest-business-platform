# Block 2 — Leads & CRM

Block 2 adds the shared CRM foundation on top of the Block 1 modular
monolith (one FastAPI backend, one PostgreSQL database, Prime + Nest as
tenants). Steps covered: Lead Management (5), Booking/Enquiry (6),
Customer/CRM (7), Notifications (8), AI Foundation (9), Prime Website
connection (10 — see `docs/PRIME_INTEGRATION.md`).

Layering is unchanged: `api → services → repositories → models`.
Routers contain no SQL; services own business rules; repositories own SQL.

## 1. Data model

All tables are business-scoped via `business_id` (`BusinessScopedMixin`,
except `notification_preferences` whose PK starts with `user_id` — it
still carries an indexed `business_id` and every query filters on it).

| Table | Purpose | Key fields |
|---|---|---|
| `contacts` | Reusable contact identity per business | `first_name/last_name/phone/email`, `normalized_phone/email` (match/search only), `preferred_contact_channel`, `source`, `status` ∈ active/inactive/archived |
| `customers` | Customer record linked to contact | `contact_id` + `UNIQUE(business_id, contact_id)` (concurrent-conversion safety), `status`, `customer_since`, `notes` |
| `leads` | Business-neutral lead lifecycle | `display_name`, normalized contact refs, `source`, `status` ∈ new/contacted/qualified/booked/converted/lost/spam, `assigned_user_id`, `service_interest`, `message`, `follow_up_at`, `converted_at`, `lost_reason`, `consent_marketing`, `landing_page/referrer/utm_*` |
| `lead_activities` | Append-only CRM history | `lead_id`, `actor_user_id`, `activity_type` ∈ note/status_changed/assigned/contacted/follow_up_scheduled/converted/lost/booking_created, `note` |
| `bookings` | Generic request (NOT availability) | `contact/customer/lead` links, `booking_type`, `status` ∈ requested/confirmed/completed/cancelled/no_show, `title`, `requested_start_at/end_at` (UTC), `cancellation_reason` |
| `notifications` | In-app inbox per staff user | `recipient_user_id`, `type`, `title/body/severity`, `read_at`, `source_type/source_id`, `data` (small JSON, never secrets), `dedupe_key` + `UNIQUE(business, recipient, dedupe_key)` |
| `notification_preferences` | Per-user opt-out per type | composite PK `(user_id, business_id, notification_type)`, `enabled` (default True) |
| `idempotency_records` | Public-POST dedup | `UNIQUE(business_id, endpoint, idem_key)`, `request_hash` (SHA-256 of canonical payload), `response_status/body` |
| `ai_runs` | AI audit metadata ONLY | `provider/model/capability/status/latency_ms/input_chars/output_chars/tokens/request_id/error`. No prompts/outputs stored (PII). |

Phone/email uniqueness is deliberately NOT enforced (families share
numbers); intake reuses contacts on normalized match.

Vocabularies live in `app/models/crm_vocab.py` (single source of truth;
validated in schemas/services, stored lowercase).

Migration: `migrations/versions/0003_block2_leads_crm.py`
(revises `0002_identity_multitenancy`). It also inserts the 9 new
permissions and grants them to system roles per the matrix below
(hardcoded in the migration so history never depends on future code).

## 2. Permissions / RBAC (additive — Block 1 grants untouched)

New keys: `contacts.read/create/update`, `customers.read/create/update`,
`notifications.read/update`, `ai.read`.

| Role | New grants |
|---|---|
| OWNER / ADMIN | all 9 |
| MANAGER | all 9 |
| STAFF | `contacts.read/create`, `customers.read`, `notifications.read` |
| VIEWER | `contacts.read`, `customers.read`, `notifications.read` |

Notable: lead conversion requires `leads.update` + `customers.create`
(STAFF cannot convert); notification preferences need
`notifications.update` (self-scoped writes still need the update grant);
AI insights need `ai.read` (MANAGER+).

## 3. Staff APIs (all `/api/v1`, Bearer + permission, business from token)

Pagination envelope everywhere: `{items, total, limit, offset}`
(limit clamped server-side to 100; sort allowlisted per resource —
unknown sort fields fall back safely, never into SQL).

- Leads: `GET /leads` (filters: status/source/assigned_user_id/
  created_from/to/follow_up_from/to/search), `POST /leads` (201),
  `GET/PATCH /leads/{id}`, `POST /leads/{id}/assign`,
  `POST /leads/{id}/status` (transition matrix enforced; LOST needs
  `lost_reason`), `POST /leads/{id}/notes` (201),
  `GET /leads/{id}/activities`, `POST /leads/{id}/convert`
  (transactional → customer; already-converted → 409).
- Bookings: `GET/POST /bookings`, `GET/PATCH /bookings/{id}`,
  `POST /bookings/{id}/confirm|cancel|complete|no-show` per
  `BOOKING_TRANSITIONS` (cancel needs `cancellation_reason`;
  cancelled/no-show reopen only to `requested` via staff action —
  there is no public cancel endpoint).
- Contacts: `GET/POST /contacts`, `GET/PATCH /contacts/{id}`
  (safe search ≤64 chars across name/phone/email, business-local).
- Customers: `GET/POST /customers`, `GET/PATCH /customers/{id}`
  (duplicate contact → 409).
- Notifications (always own + business scoped):
  `GET /notifications`, `GET /notifications/unread-count`,
  `POST /notifications/{id}/read`, `POST /notifications/read-all`,
  `PUT /notifications/preferences/{type}`.
- AI (advisory, read-only): `GET /ai/mode`,
  `POST /ai/leads/{id}/summary|/classification`,
  `POST /ai/customers/{id}/insight`,
  `POST /ai/bookings/{id}/recommendation`.

Error mapping: 400 malformed, 401 unauthenticated, 403 forbidden,
404 not-found-within-scope (uniform — foreign rows behave as
nonexistent), 409 conflict/idempotency/state, 413 body too large
(pre-parse middleware), 415 non-JSON, 422 validation, 429 rate limited
(+ `Retry-After`), 500 safe envelope, 502 AI provider failure,
503 AI disabled. No stack traces/SQL/IDs leak; `X-Request-ID` everywhere.

## 4. Public APIs (anonymous, slug-addressed)

- `GET /api/v1/public/{slug}/config` → `{slug, name, business_type,
  timezone, lead_capture_enabled, booking_enabled}` (no internal IDs).
- `POST /api/v1/public/{slug}/leads` → 201
  `{success, status: "received", lead_id, message}`.
- `POST /api/v1/public/{slug}/bookings` → 201
  `{success, status: "received", booking_id, message}` — creates
  REQUESTED, never confirmed; copy says "we'll confirm", never
  "confirmed".

Pipeline per POST: content-type (415) → pre-parse size cap 413
(`BodySizeLimitMiddleware`, Content-Length only) → rate limit 429
(per IP + business + endpoint; `RATE_LIMIT_PUBLIC_*`) → resolve active
business by slug (unknown/inactive → uniform 404) → feature flag
(`operational.lead_capture_enabled` / `booking_enabled`; missing reads
as enabled for pre-Block-2 rows, explicit `false` → 403) → honeypot
(`website_url` filled → fake 201, nothing stored, security-logged) →
idempotency (`Idempotency-Key`, optional; same key + same payload
replays stored response; same key + different payload → 409;
in-flight duplicate → 409) → intake (contact resolve/create + lead/
booking + activity + staff notifications, one transaction) → minimal
safe response.

No `business_id` is ever accepted from anonymous clients. Public
responses never contain internal IDs (except the created record's own
UUID for correlation), user IDs, tokens, or metadata.

## 5. Rate limiting

`app/services/rate_limit.py` defines the `RateLimiter` interface
(`check`/`reset`) with an in-process fixed-window implementation.
Endpoint code depends only on the interface + `enforce*` helpers, so a
Redis backend (same buckets) can be injected via `set_limiter()` with
no endpoint/service changes.

- Public intake: `RATE_LIMIT_PUBLIC_REQUESTS` / `_WINDOW_SECONDS`
  (default 20 / 600s), bucket `public:{endpoint}:{slug}:{ip}`.
- Auth: login/refresh enforce `RATE_LIMIT_AUTH_*` (default 30 / 300s),
  bucket `auth:{endpoint}:{ip}`.
- `RATE_LIMIT_ENABLED=false` disables (tests/local opt-out).

PRODUCTION REQUIREMENT: the in-memory backend is per-process. Any
multi-worker/replica deployment MUST replace it with Redis (or
equivalent shared store) or limits will not hold globally.

## 6. Idempotency

Header `Idempotency-Key: [A-Za-z0-9-_]{8,64}` on public POSTs.
`app/services/idempotency.py`: `validate_key`, canonical `payload_hash`
(SHA-256 over sorted JSON), `acquire` (fast-path replay SELECT →
placeholder INSERT+flush → on `IntegrityError` full rollback per the
documented caller contract — acquire() runs before any write — then
resolve against the winner), `complete` (stores status+body),
`purge_expired` (default 30-day retention; ops/scheduler owns the call
— Block 8).

Deliberately no savepoints: on some SQLite drivers releasing an
outermost savepoint commits, which would break atomicity. The
constraint + rollback + resolve pattern is portable across PostgreSQL
and SQLite (verified by tests).

## 7. Notifications

`app/services/notifications.py` is the single creation path (Block 8
will swap direct calls for durable events). In-app delivery is real
(PostgreSQL rows). `EmailNotificationProvider` /
`WhatsAppNotificationProvider` exist as interfaces whose `send()` raises
`ChannelNotConfiguredError` — no fake delivery statuses anywhere.

Fan-out: new lead/booking/assignment notify OWNER/ADMIN/MANAGER
recipients (preference-aware, per-event `dedupe_key`). Assignment also
notifies the assignee directly.

## 8. AI foundation

`app/services/ai/`: `providers.py` (`AIProvider` ABC + deterministic
`NoopProvider`, `PROVIDERS` registry), `contexts.py` (allowlisted,
PII-masked — phone→last4, email→masked — size-bounded contexts),
`outputs.py` (strict Pydantic outputs: `LeadSummary`,
`LeadClassification`, `CustomerInsight`,
`OperationalRecommendation` — `extra="forbid"`, validated before use),
`service.py` (`AIService`: disabled-first, audit metadata per run).

Modes: `AI_DISABLED` (default; insight endpoints → 503; everything else
works), `AI_MOCK` (`AI_ENABLED=true` + `noop`: deterministic outputs
labeled `provider="noop"`), `AI_LIVE` (future registered provider).
Provider failures → 502 with a durable error audit row.

Rules: AI is advisory-only — no DB mutation from outputs, no
autonomous actions, no customer-facing messages, no booking
confirmation. Credentials live only in backend env (placeholders in
`.env.example`); nothing AI-related ships to the frontend.

Adding a real provider later: implement `AIProvider`
(HTTP + timeout + structured parsing, raising `AIProviderError`),
register in `PROVIDERS`, set `AI_PROVIDER` + key env. No
router/service changes.

## 9. Security hardening (Block 2)

- CORS: explicit origins only (`BACKEND_CORS_ORIGINS` ∪
  `PUBLIC_SITE_ORIGINS` via `effective_cors_origins`); never `*`;
  `Idempotency-Key` allowed; dev fallback localhost:3000/5173.
- Abuse: rate limits + pre-parse 64KB cap + strict Pydantic
  (`extra="forbid"` on staff inputs) + honeypot + content-type 415 +
  idempotency + `Retry-After`.
- Logging: `security_event()` redacts passwords/tokens/secrets/cookies
  (substring match), truncates values, carries `request_id`. No
  password/JWT/refresh-token/API-key logging anywhere.
- Tenant isolation: business always from the authenticated context
  (staff) or verified slug (public); repositories fail closed;
  adversarial tests cover path/query/body/forged-JWT/relationship/
  search/count oracles.

## 10. Configuration (see `.env.example`)

`PUBLIC_SITE_ORIGINS`, `RATE_LIMIT_*` (5 vars), `MAX_BODY_BYTES`,
`AI_ENABLED/AI_PROVIDER/AI_MODEL/AI_TIMEOUT_SECONDS/AI_MAX_INPUT_CHARS`.
Compose forwards all of them with safe defaults.

## 11. Deferred (explicitly NOT built)

Automation engine, WhatsApp/email delivery, payments, memberships,
attendance, seat allocation, owner command center, analytics platform,
Redis deployment, microservices/K8s, AI agents/autonomous actions,
real-time availability, production deploy. Extension points (provider
interfaces, event-ready notification service, Redis-swappable limiter)
are in place instead of fake implementations.
