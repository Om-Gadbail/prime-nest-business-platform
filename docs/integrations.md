# Integrations — Gemini + Dual WhatsApp Foundation (Pre-Prompt-7)

Foundation status: **READY FOR PROMPT 7**. No live calls are made by this
foundation; Prompt 7 owns automation and live provider testing.

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
