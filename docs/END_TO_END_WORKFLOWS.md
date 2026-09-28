# End-to-End Workflows (verified against code)

All flows run on ONE backend + ONE Postgres (+ Redis/worker/scheduler in Docker).
Prime and Nest differ only by `businesses.slug` — never by code branches.

## A. Website → CRM → Dashboard (Prime example; Nest identical with slug `nest`)

```text
Visitor → Prime site form → POST /api/v1/public/prime/leads {name, phone, …, Idempotency-Key}
→ slug resolve (prime, active) → feature flag → honeypot → idempotency acquire
→ intake_lead (NEW) → attribution → audit → 201 {lead_id}
→ Prime staff dashboard: Leads list → Lead detail → timeline → assign/status/notes
→ Convert → customer/member → membership → payment → renewal tracking
```

Booking twin: `POST /api/v1/public/prime/bookings` → REQUESTED (never confirmed) →
staff Confirm/Cancel/Complete/No-show → automation (confirmation message, review nudge).

Verify: submit twice with the same `Idempotency-Key` → one row (replay, no duplicate);
submit with `website_url` filled → fake 201, nothing stored; Prime lead never appears
under a Nest login (uniform 404).

## B. Membership → Payment → Renewal automation

```text
Member → membership (active, end_date, price snapshot) → payment (pending → paid)
→ scheduler/worker sweep (per business): renewal_scan offsets 30/14/7/3/1/0
→ dispatch membership.expiring → default/owner rules → WhatsApp/message + task/notification
→ communications recorded → timeline updated → staff follows up
→ renewal membership (old→new link) → payment → membership updated
```

Money is `NUMERIC`/Decimal; expiry is date-based in the business timezone.

## C. AI receptionist (public)

```text
Visitor → <WebsiteChat/> → POST /api/v1/public/{slug}/ai/chat {message, visitor_key}
→ shared runtime: persist → PUBLIC tools only (profile/hours/location/services/plans/
availability/lead/booking-request) → gateway (Noop fake or Gemini) → validated tool calls
→ final reply → persist + ai_runs/ai_tool_calls audit → reply
```

Prime visitor asking plans/timings/location/trial gets Prime data; Nest visitor gets Nest
data. Private tools (`get_revenue_summary`, …) return `not_allowed` for public callers.
Sensitive actions (confirm payments, change memberships, delete records, change settings)
are NOT tools — they require authenticated staff workflows/approvals.

## D. Staff/Owner AI

```text
Dashboard /assistant → POST /ai/assistant (ai.assist; OWNER role → owner mode)
→ shared runtime with PRIVATE tools allowed (still business-scoped)
→ FACT/SIGNAL/RECOMMENDATION answers → recommendations queue
→ approve/reject (ai.manage; high-risk → approvals workflow)
Owner brief: GET /api/v1/owner/brief (yesterday/today/trend/exceptions/actions)
```

## E. WhatsApp

```text
Meta → POST /api/v1/whatsapp/webhook (HMAC X-Hub-Signature-256; fail-closed in prod)
→ phone_number_id → business (operational config → WHATSAPP_PHONE_NUMBER_MAP → demo slug fallback non-prod)
→ inbound dedupe (provider id) → conversation + message → delivery events → timeline
Staff/automation → send_message (opt-in check, server-side template resolve, provider
abstraction Log/WhatsApp, idempotent, status tracking) → delivery events → timeline
```

## F. Analytics / owner intelligence

Owner (`owner.combined.read` + OWNER/ADMIN): per-business overview, revenue/KPI presets,
leads funnel (documented formulas), combined Prime+Nest view; empty businesses → zeros.
`compute_metrics` persists snapshots for trends; `intelligence()` narrates
metric→trend→driver→exception→action from measurements only.
