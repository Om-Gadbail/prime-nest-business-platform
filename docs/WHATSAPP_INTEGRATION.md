# WhatsApp Integration — Centralized, Business-Aware

## Architecture (locked)

```text
Meta Cloud API ⇄ backend adapter ⇄ communications service ⇄ Postgres
                   (app/services/messaging.py)   (communications.py)
                   ├─ WhatsAppCloudProvider (prod: template/text, 15s timeout, typed errors)
                   └─ LogProvider (demo/tests/no-creds: auditable record, no external send)
```

One shared service; no Prime/Nest branches. Every send persists a `messages` row +
conversation touch + delivery event; idempotent on `(business_id, provider_message_id)`.

## Configuration

| Env | Meaning |
|---|---|
| `WHATSAPP_ENABLED=false` | Demo mode → `LogProvider` (workflows never break) |
| `WHATSAPP_ENABLED=true` + `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` | Live single-number mode |
| `WHATSAPP_PHONE_NUMBER_MAP="prime:ID,nest:ID"` | Multi-number routing (env-level) |
| per-business `business_settings.operational.whatsapp.phone_number_id` | Owner-configured routing (wins over env) |
| `WHATSAPP_VERIFY_TOKEN` | `GET /whatsapp/webhook` challenge verification |
| `WHATSAPP_APP_SECRET` | HMAC `X-Hub-Signature-256` check (fail-closed in production) |

## Business resolution (no hardcoded assumptions)

Inbound `phone_number_id` (from `entry[].changes[].value.metadata`) → business via:
1. operational `whatsapp.phone_number_id` per business,
2. `WHATSAPP_PHONE_NUMBER_MAP` slug lookup,
3. (non-production only) demo `business_slug` field for local testing.

Unknown/unmapped → safe ack `{received: true}`, nothing created, no 500. Prime webhooks can
never create Nest records (and vice versa) — verified by isolation tests.

## Endpoints

- `GET /api/v1/whatsapp/webhook` — Meta verification (echoes only with matching token; prod fails closed).
- `POST /api/v1/whatsapp/webhook` — inbound + status updates (dedupe, delivery events, commit once).
- `POST /api/v1/whatsapp/send` (staff, `communications.manage`) and `POST /api/v1/communications/messages`.
- `GET /api/v1/communications/timeline` — unified staff view (messages + bookings + tasks, subject-scoped).

## Safety

Opt-in enforced (`communication_preferences`) before every send; 9 default templates/business;
server-side template rendering; safe retries (bounded, idempotent); no duplicate sends
(provider-id dedupe + execution idempotency); status tracking (`sent/delivered/read/failed`).
