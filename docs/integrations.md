# Integrations — Gemini + Dual WhatsApp Foundation (Pre-Prompt-7) + Prompt 7 Growth Engine

Foundation status: **PROMPT 7 IMPLEMENTED** (see §12–§21 below). The
foundation made no live calls; Prompt 7 owns automation and ran the live
Gemini test (PASS) plus the full mock-WhatsApp workflow (PASS).

## 1. Model

- **ONE shared Gemini demo credential** (`GEMINI_API_KEY` + `GEMINI_MODEL`).
  Business context is attached server-side per request; Gemini never decides
  authorization, ownership, membership/payment/attendance status, renewals,
  totals, or permissions (those stay deterministic backend/database work).
- **TWO separate WhatsApp credential sets** (`PRIME_WHATSAPP_*`,
  `NEST_WHATSAPP_*`) — one Meta app/number per business.
- **ONE shared provider implementation** (`WhatsAppCloudProvider`,
  `GeminiChatProvider`); only credentials differ.
- **Server-side resolution**: authenticated identity → `BusinessContext`
  (JWT + DB membership) → `integration_configs` → provider credentials.
  Frontend `business_id` is never trusted for credential selection.
- **Strict isolation**: Prime can never resolve Nest credentials and vice
  versa; unknown/future businesses resolve to disabled (fail closed).

## 2. Gemini setup

1. Get a key at <https://aistudio.google.com/apikey>.
2. Local dev: copy `.env.example` to `.env` (git-ignored) and set:
   `GEMINI_API_KEY=<paste-key>` (+ optional `AI_ENABLED=true`,
   `AI_PROVIDER=gemini`).
3. Model: `GEMINI_MODEL` (default `gemini-2.5-flash`). Note: `gemini-2.0-flash`
   was **shut down by Google (Jun 2026)** — do not use it. Newer Flash models
   are a config-only change (3.x drops `temperature`; the gateway sends 0.4,
   which 2.x supports).
4. Code: `app/services/ai_gateway.py` (`GeminiChatProvider`,
   `GeminiService`, `get_gemini_service`) + structured adapter
   `app/services/ai/gemini_structured.py`. `GeminiService.chat()` prefixes the
   verified business scope and strips forbidden keys via
   `sanitize_context_for_gemini()`.

## 3. Prime WhatsApp setup

1. Meta dashboard (<https://developers.facebook.com/apps>) → create the
   **Prime** app → WhatsApp > API Setup → test/sandbox number.
2. Paste into local `.env` (never commit, never `VITE_*`):
   `PRIME_WHATSAPP_ENABLED=true`, `PRIME_WHATSAPP_ACCESS_TOKEN=`,
   `PRIME_WHATSAPP_PHONE_NUMBER_ID=`, `PRIME_WHATSAPP_BUSINESS_ACCOUNT_ID=`,
   `PRIME_WHATSAPP_VERIFY_TOKEN=`, `PRIME_WHATSAPP_APP_SECRET=`.
3. Webhooks → subscribe the **pinned** URL
   `https://<backend>/api/v1/whatsapp/webhook/prime` with the Prime verify
   token (or the generic `/api/v1/whatsapp/webhook`, which accepts any
   configured business token and resolves the business from the
   credential-bound phone_number_id).
4. Mapping: `prime-fitness-001` → Prime config → Prime number (see
   `app/services/integration_configs.py::resolve_whatsapp_config`).

## 4. Nest WhatsApp setup

Same as Prime, with the **Nest** app/number and the `NEST_WHATSAPP_*` vars,
business `nest-library-001`, and pinned URL
`.../api/v1/whatsapp/webhook/nest`. The two sets are fully independent.

## 5. Environment variables

| Var | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | demo/live only | Shared credential, backend-only |
| `GEMINI_MODEL` | no (`gemini-2.5-flash`) | Configurable stable Flash model |
| `PRIME_WHATSAPP_ENABLED` / `NEST_WHATSAPP_ENABLED` | no (`false`) | Explicit per-business kill switch |
| `PRIME_WHATSAPP_ACCESS_TOKEN` / `NEST_...` | to go live | Provider credential, backend-only |
| `PRIME_WHATSAPP_PHONE_NUMBER_ID` / `NEST_...` | to go live | Credential-bound routing signal |
| `PRIME_WHATSAPP_BUSINESS_ACCOUNT_ID` / `NEST_...` | optional | WABA id (audit/reference) |
| `PRIME_WHATSAPP_VERIFY_TOKEN` / `NEST_...` | for webhooks | GET challenge verification |
| `PRIME_WHATSAPP_APP_SECRET` / `NEST_...` | for webhooks | HMAC `X-Hub-Signature-256` |
| `WHATSAPP_*` (global) | deprecated | Backwards compat only; scoped wins |

Empty/disabled = demo-safe `log` provider (auditable, clearly `MOCK`, never
presented as delivered). Docker Compose wires the scoped vars into
`backend`/`worker`/`scheduler` only — never frontend.

## 6. Security model

- Credentials live ONLY in backend env; status/logs carry booleans + provider
  names only (`GET /api/v1/integrations/status`, `settings.read` required).
- Sends resolve creds from `ctx.business` (server-side); forged `business_id`
  (query/body/header) is ignored — proven by tests.
- Webhooks verify HMAC against the resolved/pinned business's OWN app secret;
  cross-signed payloads are rejected; production fails closed with no secret.
- Gemini inputs pass `sanitize_context_for_gemini()` (keys/tokens/secrets/
  passwords stripped); Gemini output never mutates the DB without validation.
- Future businesses: add `<SLUG>_WHATSAPP_*` env + registry row — no forks.

## 7. Webhook foundation

- `GET /whatsapp/webhook` — verify against any configured business token.
- `GET /whatsapp/webhook/{prime|nest}` — pinned (only that business's token).
- `POST /whatsapp/webhook` — HMAC check (resolved business's secret, else any
  configured secret), business from credential-bound `phone_number_id`,
  idempotent inbound + delivery statuses, safe ack (never 500s).
- `POST /whatsapp/webhook/{prime|nest}` — pinned business + secret, with
  phone-id cross-check (mismatch acks WITHOUT writes).
- `business_slug` payload override works ONLY outside production (local tests).

## 8. Local development

```bash
cp .env.example .env   # then paste real keys into .env (ignored by git)
docker compose up --build
```

Check state (no secrets, no sends, no AI calls):
`GET /api/v1/integrations/status` (staff login) →
`{"gemini": {"configured": ..., "mode": ...},
  "whatsapp": {"business_key": "prime"|"nest", "mode": ...}}`.
Modes: `LIVE` (enabled+configured) / `DISABLED` (configured but off) /
`NOT_CONFIGURED` (missing values); provider `log` = MOCK, `whatsapp` = LIVE.

## 9. Mock / test mode

`backend/tests/test_prompt7_foundation.py` (31 tests): config resolution,
cross-tenant denial, forged-ID, RBAC, owner scoping, provider request
construction (redacted), normalized success/failure with stubbed transport,
webhook verify/HMAC/isolation/idempotency, secret-safety, `.env.example`
emptiness. No test touches the network or sends real messages.

## 10. How to enable each integration

- Gemini live: `AI_ENABLED=true`, `AI_PROVIDER=gemini`, `GEMINI_API_KEY=<key>`.
- Prime WhatsApp live: `PRIME_WHATSAPP_ENABLED=true` + Prime token/phone-id
  (+ verify/app-secret for webhooks).
- Nest WhatsApp live: same with `NEST_*`. Each toggles independently.

## 11. Deferred to Prompt 7 (NOT in this foundation)

Lead/welcome/trial/visit/renewal/payment/inactive-member automations,
campaigns/broadcasts, AI autonomous messaging, owner AI assistant, lead
scoring workflow, retention automation, event-driven automation engine,
scheduled rules, automatic sends, full inbound conversation workflows, and
the explicit live provider tests (real WhatsApp message + real Gemini call
after credentials are entered).

---

# Prompt 7 — Business Growth + Retention Operating System (IMPLEMENTED)

Status: **LIVE in the backend.** The platform is now event-driven:

```
BUSINESS EVENT -> AUTOMATION ENGINE -> ELIGIBILITY -> RULE -> ACTION
  -> GEMINI (optional draft) -> WHATSAPP / TASK / NOTIFICATION
  -> EXECUTION STATUS -> OWNER INTELLIGENCE
```

## 12. Event engine (extends, never replaces)

- Domain events remain the single bus (`app/services/domain_events.py`;
  no second bus). Prompt 7 adds real-state-backed types only:
  `lead.contacted`, `trial.booked/reminder_due/attended/no_show`,
  `visit.*` equivalents, `payment.success`, `member.inactive`,
  `seat.continuity_due`, `review.received/reply_required`,
  `automation.started/completed/failed`, `booking.no_show`,
  `scheduled.followup`. Trials/visits ride the **booking** state machine
  (`booking_type` + `requested/confirmed/completed/no_show`) — no parallel
  trial state was invented.
- Services emit fast event rows inside their own transactions
  (leads, bookings incl. transitions, payments, memberships).
  `automation.dispatch_event` **reuses identical recent events**
  (same business + type + entity + payload, 24h) instead of emitting
  duplicates — duplicated webhooks/retries/restarts can never double-send.

## 13. Automation engine (`app/services/automation.py` + `growth_engine.py`)

- One engine, one scheduler, one worker (extended, never duplicated).
- Canonical execution statuses: `queued | running | completed | failed |
  skipped | cancelled` (legacy `pending/succeeded/retrying` rows still
  read as equivalents; history untouched).
- Idempotency: `(business_id, idempotency_key)` unique constraint;
  re-delivery returns existing rows. Retry replays find the already-sent
  message by `automation_id` and return it — a provider that accepted a
  message whose response was lost is never sent twice.
- `skipped` is terminal (opt-out/ineligible, with reason) — never retried.
- Two trigger paths: synchronous `dispatch_event` (staff/ops/tests) and
  `enqueue_for_event` (public website: commits event + queued jobs fast;
  the worker executes Gemini/provider work via genuine `retry_due`).
- Bounded retries with backoff (`max_retries`, default 5); budget
  exhaustion resolves to observable `failed`. No infinite loops.
- Every important step is audited (`automation.started/completed/failed/
  skipped`, `communication.sent/skipped/failed`,
  `ai.generation_requested/succeeded/failed`, `handoff.created`) with the
  triggering actor threaded through — never secrets.

## 14. Growth workflows (generic engine, per-business data)

`app/services/growth_engine.py` — no Prime/Nest branches. Terminology,
plans, timing, templates, and capabilities resolve per business from
configuration (Business row + settings + templates + capabilities):

- New lead/enquiry -> follow-up + 24h/72h nurture + staff task.
- Trial/visit booked -> confirmation + reminder scheduling (durable
  `scheduled.followup` rows; sweep-to-sweep dedupe).
- Trial/visit outcome (`POST /bookings/{id}/trial-outcome`,
  attended/no_show) -> reschedule follow-up + task. Non-trial bookings
  are rejected (no invented attendance).
- Membership expiry (30/14/7/3/1/0-day stages) -> renewal reminders with
  eligibility gates (still active? already renewed? opted in? recent
  duplicate?). Renewal cancels pending nudges (`cancelled`, reason kept).
- Post-expiry win-back (48h window), inactive-member retention
  (deterministic no-attendance signal + member-age guard), payment
  success confirmation / failed recovery + task, seat-continuity
  reminders (seat-capable businesses with real allocations only).
- Razorpay is NOT live (demo scope): payment automation consumes the
  deterministic payment state machine only; the webhook contract is
  provider-neutral and ready for a real provider later.

## 15. Gemini usage + guardrails

- Used for: lead follow-up drafts, renewal/retention personalization,
  owner-brief narrative enhancement (numbers stay authoritative).
- Guardrails: structured verified context only (sanitized via
  `sanitize_context_for_gemini`); output validated (bounded, no
  placeholders/secrets/invented links); failures resolve to deterministic
  fallback templates — `ai_used` is True ONLY after a real successful
  call, never claimed otherwise. Gemini never mutates the DB, never
  selects credentials, never decides eligibility.
- Cost control: one draft per execution; retries reuse the sent message
  (no re-draft, no re-send).
- **Live test (Sep 2026): `Gemini live test = PASS
  (model=gemini-3.6-flash)`** — real `generateContent` call, minimal
  prompt, no secret recorded, no data mutated, no message sent.
  Note: `gemini-2.5-flash` now 404s ("no longer available to new users")
  for fresh keys, so the default `GEMINI_MODEL` moved to the live-verified
  `gemini-3.6-flash` (config-only override still supported).

## 16. WhatsApp mock/live modes

- **WhatsApp live = NOT CONFIGURED** (Meta credentials unavailable).
  **WhatsApp mock = PASS**: full workflow runs through the `log`
  provider; executions record `provider_mode=MOCK` and
  `delivery_status=simulated (not_delivered)` — never presented as
  delivered. Switching to LIVE later is config-only
  (`PRIME_/NEST_WHATSAPP_ENABLED=true` + credentials); the engine is
  unchanged. Business-scoped live resolution is proven by test
  (stubbed transport: Prime `whatsapp` + `wamid.*`, Nest `log`).

## 17. Communication preferences / opt-out

- `communication_preferences` (per business + channel + address) gate
  every automated send. Opt-out resolves to terminal `skipped` with the
  reason recorded — no send, no retry. Preferences are per-business
  (Prime opt-out never affects Nest).

## 18. Human handoff + communication center

- `POST /communications/handoff` creates a high-priority staff task with
  a verified-info-only summary (no secrets, own business only).
- Communication center = existing surfaces extended: messages expose
  `provider/provider_message_id/template_code/recipient/automation_id/
  provider_mode`; executions expose `output/provider/timing`.
- Owner automation-health now feeds real execution data
  (`executions_total/succeeded/skipped/by_status/pending_retry/
  last_success_at`), per business + combined (authorized only).

## 19. Scheduler / worker responsibilities

Per-business sweep stages (each bounded + failure-isolated): genuine
`retry_due` execution, event-backlog drain, expiry marking, staged
renewal reminders, expiry follow-ups, booking reminders, inactivity
retention, seat continuity, daily brief, idempotency purge. Redis lease
still elects one tick owner; without Redis, idempotency keeps
single-replica runs safe.

## 20. Tests (all deterministic, no network)

`backend/tests/test_prompt7_growth.py` (25 tests): Prime/Nest golden
workflows, public fast-path + worker drain, duplicate-event safety,
opt-out skips, trial/no-show, expiry + renew-stops-nudges, payments,
inactivity, seat continuity, Gemini fallback/success/failure, mock
honesty, scoped-live provider, brief optionality, bounded retries,
no-duplicate-on-retry, health data, isolation, forged-payload attacks,
RBAC, handoff, comm-center visibility.

## 21. How Prompt 8 should harden reliability

Scheduled follow-up delivery receipts, provider webhook delivery
reconciliation (sent -> delivered/read), dead-letter observability for
`failed` executions, per-business send-rate caps, quiet-hours
configuration, template-approval state tracking for Meta templates,
and backfill/migration tooling for the new execution statuses in
long-lived deployments. No redesign of this engine is needed.
