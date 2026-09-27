# Backend API Inventory (source of truth — dumped + AST-verified 2026-09-28)

Method: routes dumped from `create_app()` (160 total, incl. docs/health/ready);
per-route permission extracted by AST from each endpoint module's
`Depends(require_permission("<key>"))`. All paths below are mounted under `/api/v1`
(`settings.api_v1_prefix`). Business scope for every authenticated route = the
server-derived `ctx.business` (JWT hint + DB membership); cross-business access → 404,
except the explicitly double-gated owner-combined / lead-transfer / identity-cross-business
paths. Database for all rows today: the single shared PostgreSQL (`app_db`).
Status `KEEP` = frozen contract through Prompt 2. No duplicates found (DUPLICATE column
omitted — value would be "no" everywhere).

Legend — AUTH: `anon` = no token; `authN` = login/refresh-cookie flow; `Bearer+<perm>` =
`Authorization: Bearer` + listed permission (OWNER/ADMIN extra where noted).

## Ops / system (consumer: orchestrator, compose)

| Method | Path | Auth | Consumer | Status |
|---|---|---|---|---|
| GET | `/health` | anon | orchestrator | KEEP |
| GET | `/ready` | anon (DB check) | orchestrator | KEEP |
| GET | `/api/v1/version` | anon | dashboard | KEEP |

## Auth (consumer: staff dashboard session provider)

| Method | Path | Auth | Consumer | Status |
|---|---|---|---|---|
| POST | `/api/v1/auth/login` | anon (+auth rate limit) | dashboard | KEEP |
| POST | `/api/v1/auth/refresh` | refresh token (cookie/body) | dashboard | KEEP |
| POST | `/api/v1/auth/logout` | Bearer (any ctx) | dashboard | KEEP |
| GET | `/api/v1/auth/me` | Bearer | dashboard | KEEP |
| GET | `/api/v1/auth/businesses` | Bearer | dashboard | KEEP |
| POST | `/api/v1/auth/switch-business` | Bearer + verified membership | dashboard | KEEP |

## Public intake (consumer: Prime site live; Nest drop-in ready; AI widget)

| Method | Path | Auth | Consumer | Status |
|---|---|---|---|---|
| GET | `/api/v1/public/{slug}/config` | anon | Prime site, Nest drop-in | KEEP |
| POST | `/api/v1/public/{slug}/leads` | anon + guard/idempotency/honeypot | Prime TrialForm, Nest enquiry adapters | KEEP |
| POST | `/api/v1/public/{slug}/bookings` | anon + guard/idempotency/honeypot | Prime BookingForm, Nest visit adapter | KEEP |
| GET | `/api/v1/public/{slug}/availability` | anon | AI widget support | KEEP |
| GET | `/api/v1/public/{slug}/business-info` | anon | AI widget support | KEEP |
| POST | `/api/v1/public/{slug}/ai/chat` | anon + AI rate limit | WebsiteChat widget | KEEP |

## Leads (consumer: staff dashboard)

| Method | Path | Permission | Status |
|---|---|---|---|
| GET/POST | `/api/v1/leads` | `leads.read` / `leads.create` | KEEP |
| GET/PATCH | `/api/v1/leads/{lead_id}` | `leads.read` / `leads.update` | KEEP |
| GET | `/api/v1/leads/{lead_id}/activities` | `leads.read` | KEEP |
| POST | `/api/v1/leads/{lead_id}/assign` | `leads.update` | KEEP |
| POST | `/api/v1/leads/{lead_id}/status` | `leads.update` | KEEP |
| POST | `/api/v1/leads/{lead_id}/notes` | `leads.update` | KEEP |
| POST | `/api/v1/leads/{lead_id}/convert` | `customers.create` | KEEP |
| POST | `/api/v1/leads/{lead_id}/transfer` | `leads.transfer` + OWNER/ADMIN role, dual-audited | KEEP |

## Bookings / Members / Memberships / Payments / Attendance / Seats

| Method | Path | Permission | Status |
|---|---|---|---|
| GET/POST | `/api/v1/bookings` | `bookings.read` / `bookings.create` | KEEP |
| GET/PATCH | `/api/v1/bookings/{booking_id}` | `bookings.read` / `bookings.update` | KEEP |
| POST | `/api/v1/bookings/{booking_id}/{confirm,cancel,complete,no-show,reopen}` | `bookings.update` | KEEP |
| GET/POST | `/api/v1/members` | `members.read` / `members.create` | KEEP |
| GET/PATCH | `/api/v1/members/{member_id}` (+`/profile`) | `members.read` / `members.update` | KEEP |
| GET/POST | `/api/v1/membership-plans` (+`/{plan_id}`, PATCH) | `membership_plans.read` / `.manage` | KEEP |
| GET/POST | `/api/v1/memberships` (+`/{membership_id}`, `.../status`, `.../renew`) | `memberships.read` / `.create` / `.update` | KEEP |
| GET/POST | `/api/v1/renewals` (+`/{renewal_id}`) | `renewals.read` / `renewals.create` | KEEP |
| GET/POST | `/api/v1/payments` (+`/{payment_id}`, `.../status`, `.../refund`) | `payments.read` / `.create` / `.update` / `.refund` | KEEP |
| GET | `/api/v1/attendance` | `attendance.read` | KEEP |
| POST | `/api/v1/attendance/check-in`, `.../{id}/check-out` | `attendance.create` | KEEP |
| PATCH | `/api/v1/attendance/{attendance_id}` | `attendance.update` | KEEP |
| GET/POST | `/api/v1/seat-areas`, `/api/v1/seats` (+`/{seat_id}` PATCH, `/availability`, `/available`) | `seats.read` / `seats.manage` | KEEP |
| GET/POST | `/api/v1/seat-allocations` (+`.../release`, `.../transfer`) | `seats.read` / `seats.manage` | KEEP |

## Tasks / Contacts / Customers / Notifications / Approvals

| Method | Path | Permission | Status |
|---|---|---|---|
| GET/POST | `/api/v1/tasks` (+`/{task_id}`, PATCH, `.../assign`, `.../status`) | `tasks.read` / `.create` / `.update` | KEEP |
| GET/POST | `/api/v1/contacts` (+`/{contact_id}`, PATCH) | `contacts.read` / `.create` / `.update` | KEEP |
| GET/POST | `/api/v1/customers` (+`/{customer_id}`, PATCH) | `customers.read` / `.create` / `.update` | KEEP |
| GET | `/api/v1/notifications`, `.../unread-count` | `notifications.read` | KEEP |
| POST | `/api/v1/notifications/{id}/read`, `.../read-all` | `notifications.read` | KEEP |
| PUT | `/api/v1/notifications/preferences/{type}` | `notifications.update` | KEEP |
| GET/POST | `/api/v1/approvals` (+`/{approval_id}`, `.../decide`) | `approvals.read` / `.manage` | KEEP |

## Business / Identity / Audit

| Method | Path | Permission | Status |
|---|---|---|---|
| GET/PATCH | `/api/v1/business` | `business.read` / `business.update` | KEEP |
| GET/PATCH | `/api/v1/business/settings` | `settings.read` / `settings.update` | KEEP |
| GET | `/api/v1/identity/persons/{person_id}`, `/api/v1/identity/links` | `contacts.read` | KEEP |
| GET | `/api/v1/identity/persons/{person_id}/cross-business` | `identity.read` | KEEP (explicitly gated) |
| POST | `/api/v1/identity/links` | `identity.read` | KEEP |
| GET | `/api/v1/audit-events` (+`/{event_id}`) | `audit.read` | KEEP |

## Dashboard / Owner (consumer: staff dashboard, owner view)

| Method | Path | Permission | Status |
|---|---|---|---|
| GET | `/api/v1/dashboard/overview` | `dashboard.read` | KEEP |
| GET | `/api/v1/dashboard/leads/summary` | `leads.read` | KEEP |
| GET | `/api/v1/dashboard/bookings/summary` | `bookings.read` | KEEP |
| GET | `/api/v1/dashboard/activity` | `audit.read` | KEEP |
| GET | `/api/v1/dashboard/tasks` | `tasks.read` | KEEP |
| GET | `/api/v1/dashboard/notifications` | `notifications.read` | KEEP |
| GET | `/api/v1/owner/overview`, `/owner/revenue`, `/owner/leads` | `owner.dashboard.read` | KEEP |
| GET | `/api/v1/owner/combined` | `owner.combined.read` + OWNER/ADMIN | KEEP |
| GET | `/api/v1/owner/brief`, `/api/v1/owner/renewals/scan` | `reports.read` | KEEP |

## Automation / Communications / WhatsApp

| Method | Path | Permission | Status |
|---|---|---|---|
| GET/POST | `/api/v1/automation/rules` (+`/{rule_id}` PATCH) | `automation.read` / `.manage` | KEEP |
| GET | `/api/v1/automation/executions` | `automation.read` | KEEP |
| POST | `/api/v1/automation/trigger`, `/scheduler/run`, `/seed-defaults` | `automation.manage` | KEEP |
| GET/POST | `/api/v1/communications/conversations\|messages\|templates\|timeline` | `communications.read` / `.manage` | KEEP |
| PUT | `/api/v1/communications/templates`, `/communications/preferences` | `communications.manage` | KEEP |
| POST | `/api/v1/whatsapp/send` | `communications.manage` | KEEP |
| GET/POST | `/api/v1/whatsapp/webhook` | signature-gated (Meta) | KEEP |

## AI / Growth / Analytics (consumer: staff dashboard)

| Method | Path | Permission | Status |
|---|---|---|---|
| POST | `/api/v1/ai/assistant` | `ai.assist` | KEEP |
| GET | `/api/v1/ai/mode`, `/api/v1/ai/recommendations` | `ai.read` | KEEP |
| POST | `/api/v1/ai/recommendations/{id}/decide` | `ai.manage` | KEEP |
| POST | `/api/v1/ai/leads/{id}/{summary,classification}`, `/ai/customers/{id}/insight`, `/ai/bookings/{id}/recommendation` | `ai.read` | KEEP |
| GET/POST | `/api/v1/growth/{sources,funnel,relationships,referrals,cross-sell}` + convert/consent/attributions | `growth.read` / `growth.manage` | KEEP |
| GET | `/api/v1/analytics/metrics`, `/analytics/intelligence`, `/analytics/lead/{id}/intelligence` | `analytics.read` | KEEP |

## Notes for later prompts

1. No route overlaps/duplicates: nothing to merge at HTTP layer.
2. Plan-mentioned `POST /api/leads/contact|visit|membership|seat-inquiry` (non-v1) do NOT
   exist here — equivalent coverage is `POST /api/v1/public/{slug}/leads|bookings` with
   `service_interest` variants. Prompt 4 must confirm off-machine Nest frontends use the v1
   contract (the Nest drop-in in this repo already does).
3. `api.del()` exists in the dashboard client but has no call sites — no `DELETE` routes
   exist server-side; deletions are status-transitions by design. Not a gap.
4. Permission families referenced but with zero current call sites (e.g. `users.*`,
   `members.*` duplicates in `ALL_PERMISSIONS`) are future-proofing, not dead code to remove.
