# Blocks 8–12 Implementation — Automation + Communication + AI + Growth + Intelligence

One cohesive platform on the existing modular monolith (FastAPI + PostgreSQL).
Five phases, one architecture:

```text
BUSINESS EVENTS → EVENT BUS (dispatch) → AUTOMATION ENGINE
  → COMMUNICATION / TASK / AI ACTIONS → BUSINESS SERVICES → POSTGRESQL
  → ANALYTICS → AI INTELLIGENCE → OWNER COMMAND CENTER
```

## What already existed (reused, not duplicated)

- Multi-tenancy (`BusinessScopedMixin`, `apply_business_scope`), auth/RBAC,
  `BusinessContext`, audit system, CRM (leads/bookings/contacts/customers),
  tasks, notifications, members/memberships/payments/attendance/renewals/seats,
  approvals, owner analytics, `domain_events` emit-only hooks, capabilities
  (`business_settings.operational.capabilities`), public slug resolver +
  intake guards, provider-neutral `AIService` (noop), rate limiting, seed.
- Extended (additive only): `DOMAIN_EVENTS` (+14 events), `AUDIT_ACTIONS`
  (+16), `ALL_PERMISSIONS`/`ROLE_PERMISSIONS` (+10), `KNOWN_CAPABILITIES` (+7),
  `Settings` (+Gemini/WhatsApp/automation), `seed_development`.

## New tables (migration `0006_block8_12_growth_ai`)

`automation_rules`, `automation_executions` (unique `business_id+idempotency_key`),
`daily_reports` (unique `business_id+report_date`), `conversations`, `messages`
(unique `business_id+provider_message_id`), `message_templates`,
`communication_preferences`, `message_delivery_events`, `ai_conversations`,
`ai_messages`, `ai_tool_calls`, `ai_recommendations`, `growth_sources`,
`attributions`, `referrals`, `cross_sell_opportunities`,
`business_relationships` (global Prime↔Nest link), `analytics_snapshots`.
Plus 10 new permissions with system-role grants. Verified live on
PostgreSQL 16: `upgrade head → downgrade -1 → upgrade head`.

## Phase 1 — Block 8: Automation (`app/services/automation.py`, `/api/v1/automation/*`)

- `dispatch_event()` persists the domain event, then runs matching **active**
  rules: conditions (exact/`eq`/`neq`/`in`/`not_in`) → actions →
  per-action idempotency (`sha256(business:rule:event:slot)`) → bounded retry
  (`retrying` + `scheduled_at`, max attempts, never infinite).
- Actions: `send_message` (template resolved server-side), `create_task`,
  `create_notification` (fan-out, preference-aware), `schedule_followup`
  (durable delayed execution), `request_review` (neutral, no incentives),
  `track_referral`, `escalate`, `ai_recommendation`, `webhook_log`.
- Six default rules seeded per business (lead ack, 24h + 72h follow-ups +
  staff task, booking confirmation, renewal + review nudge, completed → review).
- Renewal reminders: `renewal_scan()` over **configurable offsets**
  (default 30/14/7/3/1/0) — `GET /api/v1/owner/renewals/scan`.
- Daily brief: `GET /api/v1/owner/brief` (yesterday/today/trend/exceptions/
  recommended-actions, cached in `daily_reports`).
- Scheduler: `POST /api/v1/automation/scheduler/run` (bounded replay of
  `retrying`/due `pending`); wire to cron/systemd for production.

## Phase 2 — Block 9: WhatsApp & Communication

- `MessagingProvider` interface + `WhatsAppCloudProvider` (template/text,
  15s timeout, typed errors) + `LogProvider` (demo/test fallback when
  credentials absent — workflows never break in demo mode).
- Webhook: `GET /api/v1/whatsapp/webhook` (challenge verification),
  `POST /api/v1/whatsapp/webhook` (HMAC `X-Hub-Signature-256` check,
  inbound dedupe on provider id, status updates → delivery events).
- Nine default templates per business (lead ack, trial confirm, reminders,
  follow-ups, membership/renewal/expiry, neutral review request).
- Opt-in respected before every send (`communication_preferences`).
- Staff timeline: `GET /api/v1/communications/timeline`
  (messages + bookings + tasks), direction/channel/status/provider ids tracked.

## Phase 3 — Block 10: AI Business Layer

- `AI Gateway` (`app/services/ai_gateway.py`): `ChatProvider` interface +
  `GeminiChatProvider` (REST `generateContent`, function calling, configurable
  `GEMINI_MODEL`, default `gemini-2.0-flash`) + `NoopChatProvider` (honest demo
  label). Advisory `AIService` gains `GeminiStructuredProvider`.
- **Shared runtime** (`app/services/ai_chat.py`): website chat AND WhatsApp use
  the same turn pipeline (persist → context → gateway → validated tool calls →
  final → persist → reply). Only the channel adapter differs.
- 15 public + 9 private tools (`app/services/ai_tools.py`); public callers get
  `PermissionError` on private tools. Availability is computed from hours minus
  real bookings; booking creation re-checks the slot and returns `requested`
  (never `confirmed`).
- Safety: allowlist, schema validation, scope checks, max tool calls,
  timeouts, `ai_runs` + `ai_tool_calls` audit, kill switch (`AI_ENABLED=false`
  → honest fallback), escalation detection, no secrets in logs.
- Public: `POST /public/{slug}/ai/chat`, `GET /public/{slug}/business-info`,
  `GET /public/{slug}/availability?date=`. Staff: `POST /ai/assistant`,
  `GET /ai/recommendations`, `POST /ai/recommendations/{id}/decide`
  (high-risk approvals route through the approvals workflow).
- Reusable `<WebsiteChat/>` widget (`apps/staff-dashboard/src/components/chat/`)
  for Prime/Nest sites: no API key in browser, quick actions invoke real tools.
- Eval suite: `backend/tests/test_block8_ai_eval.py` (8 grounding/refusal scenarios).

## Phase 4 — Block 11: Growth (`app/services/growth.py`, `/api/v1/growth/*`)

- `GrowthSource` rows (website/google/instagram/referral/campaign/walk-in/
  whatsapp/other) + `attributions` (source→lead→booking→conversion→revenue),
  funnel API, conversion marking.
- Referrals (lead auto-created, convert flow), cross-sell opportunities with
  **consent gate** (convert without consent → 422), `BusinessRelationship`
  rows configure Prime↔Nest (no `if business ==` branches).

## Phase 5 — Block 12: Intelligence (`app/services/analytics.py`, `/api/v1/analytics/*`)

- `compute_metrics()`: leads/conversion/customers/memberships/revenue/
  attendance/renewals/occupancy/funnel — all from source records, persisted as
  snapshots for trends. `intelligence()`: metric→trend→driver→exception→action
  narratives generated from measurements only.
- Lead/member intelligence returns FACT/SIGNAL/RECOMMENDATION splits
  (signals qualified as "may", never stated as fact).

## Frontend (`apps/staff-dashboard`)

New permission-gated routes: `/automation` (rules/executions/brief/scheduler),
`/communications` (timeline/send/templates), `/assistant` (chat +
recommendation approvals), `/growth` (funnel/referrals/cross-sell/sources),
`/analytics` (metrics + findings). All responsive 360→1920 with
loading/empty/error/forbidden states. `typecheck` + `lint` clean, 20 unit
tests pass, `vite build` succeeds.

## Environment (see `.env.example`)

`GEMINI_API_KEY` (https://aistudio.google.com/apikey), `GEMINI_MODEL`,
`AI_MAX_OUTPUT_TOKENS`, `AI_MAX_TOOL_CALLS`, `AI_PUBLIC_CHAT_ENABLED`,
`WHATSAPP_ENABLED`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`,
`AUTOMATION_ENABLED`, `AUTOMATION_MAX_ATTEMPTS`. App boots fully in demo mode
with providers unconfigured.

## Demo data

`seed_development()` now also seeds default rules/templates/sources and the
Prime↔Nest relationship. `seed.seed_demo_data(db)` (explicit, idempotent,
`demo-`-labeled) adds realistic leads/members/memberships (one expiring soon)/
paid payments/attendance/bookings/referrals/conversations per business.

## Tests

- `tests/test_blocks812.py` (13): automation CRUD/RBAC/isolation, brief,
  comms opt-out, webhook dedupe + isolation, public chat fallback, tool
  allowlist, assistant permissions, adversarial prompts, referral/xsell flows
  + consent gate, growth isolation, analytics correctness + reproducibility.
- `tests/test_ai_eval.py` (8): scripted receptionist questions + refusals.
- Full suite: 266 passed. Live PG: migration round-trip + 16-endpoint smoke
  (incl. real slots, tenant isolation) — `LIVE SMOKE OK`.
- Frontend: `typecheck`, `lint`, 20 vitest, `vite build` all green.
  (`npm test` also collects 3 Playwright e2e files — pre-existing behavior,
  run those via `npm run e2e`.)
