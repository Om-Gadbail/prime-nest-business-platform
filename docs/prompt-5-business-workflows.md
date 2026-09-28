# Prompt 5 — Business Workflows (Prime Fitness + Nest Library)

Status: complete. Canonical backend only (`backend/app`, `/api/v1`).

## Prime golden path (proven by `backend/tests/test_prompt5_workflows.py`)

Website/public lead → CRM (assign, status, follow-up task) → convert →
Customer → Member → Membership (plan snapshot, Decimal math) → Payment
(invoice `INV-*`, idempotent) → HMAC webhook verify → `paid` → entitlement
(`membership.payment_state=paid`) → check-in (duplicate-safe) → renewal
pipeline (dedupe + FSM) → confirmed renewal (new membership row, old expired)
→ member timeline + domain events + owner overview.

## Nest golden path (same test module)

Lead → convert → Member → Membership → Payment → Seat allocation (exclusive,
409 on conflict) → check-in with seat → release → renew (history preserved)
→ re-allocate → timeline.

## Workflow rules enforced server-side

- Payments: frontend success is never truth. Only HMAC-verified webhooks
  (`POST /api/v1/payments/webhook`, `PAYMENT_WEBHOOK_SECRET`) or explicit
  staff `paid` transitions move money. Amount/currency verified against the
  trusted row; mismatches → 409 with no mutation. Duplicates → idempotent
  replay flag, single payment row. No secret → 503.
- Renewals: `pending → confirmed/cancelled/expired` FSM
  (`POST /renewals/{id}/status`); one pending pipeline row per membership;
  `renew_membership` creates a NEW row and expires the old one.
- Attendance: explicit non-active membership → 409; member with history but
  no active membership → 409; zero-membership trial → allowed; same-day
  repeat → same row.
- Seats: linked membership must be active; `available` only; partial unique
  indexes guarantee one active allocation per seat AND per member.
- Member creation is race-safe (`IntegrityError → 409`); plans and seat
  areas likewise.
- `mark_expired` pages through ALL actives (no 100-cap) and runs in the
  scheduler sweep per business.
- Member 360: `GET /members/{id}/timeline` joins audit + domain events +
  lead activity; `GET /domain-events` exposes the event feed (`audit.read`).

## Cross-tenant isolation

Prime IDs via Nest auth (and reverse) → 404; search never leaks; timeline
and domain events are business-scoped. Proven by
`test_prompt5_cross_tenant_denied` plus the existing isolation suites.

## Test labelling

`mock`/`online` provider webhooks in tests use `PAYMENT_WEBHOOK_SECRET`
test values only — clearly TEST, never real money movement.
