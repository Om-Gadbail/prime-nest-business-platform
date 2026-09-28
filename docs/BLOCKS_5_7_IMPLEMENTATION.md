# Blocks 5–7 Implementation — Owner Command Center + Prime/Nest Operations

Status: **implemented** (backend + dashboard + tests + migration).
Next: **integration + full end-to-end connection/QA** (websites stay thin
clients; the backend remains the source of truth).

Blocks 1–4 remain untouched in behavior except two intentional, documented
matrix evolutions (see §12).

## 1. What was built

**Block 5 — Owner Command Center** (steps 22–26)

- `GET /api/v1/owner/overview` — per-business snapshot: membership,
  revenue, leads funnel, bookings, today's attendance, renewal pipeline
  (+ seats when the `seat_management` capability is on).
- `GET /api/v1/owner/revenue?preset=` — collected/pending/overdue/
  refunded + payment counts + average transaction + by-status/by-method
  + daily paid-revenue trend. Presets: `today 7d 30d month quarter all`
  or explicit `date_from/date_to`.
- `GET /api/v1/owner/leads?preset=` — funnel with **documented formulas**
  (see §7), source breakdown, daily trend.
- `GET /api/v1/owner/combined?scope=all|prime|nest` — combined rollup +
  per-business cards. Gate: `owner.combined.read` **and** OWNER/ADMIN
  role (explicitly authorized, intentional, auditable).
- Owner approval foundation: `approvals` table + `/api/v1/approvals`
  (request/decide; requesters cannot self-decide; terminal decisions final).
- Dashboard: `OwnerPage` (single + combined, preset/scope filters,
  refresh + last-updated, truthful zeros, responsive, no overflow).

**Block 6 — Prime Fitness Operations** (steps 27–32)

- Members (`/api/v1/members` + `/profile` 360° view), membership plans
  (`/api/v1/membership-plans`, versioned catalogue), memberships
  (`/api/v1/memberships` + `/status` + `/renew`), payments
  (`/api/v1/payments` + `/status` + `/refund`), attendance
  (`/api/v1/attendance`, check-in/out, one-row-per-day idempotency),
  renewals (`/api/v1/renewals` pipeline + renewal-linked new rows).
- Seeded Prime catalogue: monthly/quarterly/half-yearly/annual
  (editable; history snapshotted).

**Block 7 — Nest Library Operations** (steps 33–38)

- Same shared primitives; Nest extras: exact 20-plan catalogue from the
  spec (regular/confirmed/opening offers, 12-month Best Value, no trial,
  no invented offers) living in `membership_plans` rows.
- Seat inventory (`/api/v1/seats`, `/api/v1/seat-areas`), server-computed
  availability (`/api/v1/seats/availability`, `/api/v1/seats/available`),
  exclusive allocation (`/api/v1/seat-allocations` + `/release` +
  `/transfer`) backed by **partial unique indexes** (one ACTIVE
  allocation per seat AND per member — race-safe at the DB layer).
- Seat-associated check-in; confirmed-seat renewal preserves seat history
  (expiry ≠ delete).

## 2. Table classification (isolation model)

| Table | Class | Notes |
|---|---|---|
| `businesses`, `roles`, `permissions`, `persons` | GLOBAL | Tenant root / system vocab / identity signals only |
| `members` | BUSINESS_SCOPED | `business_id` FK restrict; `uq_members_business_customer` |
| `membership_plans` | BUSINESS_SCOPED | `uq_membership_plans_business_code` |
| `memberships` | BUSINESS_SCOPED | `uq_memberships_business_idem`; price snapshot columns |
| `payments` | BUSINESS_SCOPED | `uq_payments_business_idem`; no secrets |
| `attendance` | BUSINESS_SCOPED | `uq_attendance_business_member_day` |
| `renewals` | BUSINESS_SCOPED | old → new membership links |
| `seat_areas`, `seats` | BUSINESS_SCOPED | `uq_seats_business_number` |
| `seat_allocations` | BUSINESS_SCOPED | partial uniques `uq_seat_alloc_active_{seat,member}` |
| `approvals` | BUSINESS_SCOPED | polymorphic entity refs |
| `domain_events` | BUSINESS_SCOPED | append-only hook log |
| `auth_sessions` | USER_SCOPED | existing |
| alembic revisions | SYSTEM | migration chain |

Every repository filters by server-side `business_id`; services never
accept client business context; APIs enforce `require_permission`.
Cross-business rows behave as nonexistent (uniform 404, no oracle).

## 3. Capability map (reusability core)

No `if business.name == …` in generic code. Behavior flows from
`business_settings.operational.capabilities` (validated keys) over
template defaults in `app/services/capabilities.py`:

| Capability | Shared infra | Prime (fitness) | Nest (library) | Owner surface | Future event |
|---|---|---|---|---|---|
| crm/leads/bookings | existing B2 | on | on | funnel | `lead.created/converted`, `booking.created/completed` |
| members | `members` | on | on | active/new counts | `member.created` |
| memberships | `memberships` | on | on | active/expiring/expired | `membership.created/activated/expiring/expired/renewed/cancelled` |
| plans | `membership_plans` | on (4 plans) | on (20 plans) | — | — |
| payments | `payments` + provider adapters | on | on | revenue KPIs | `payment.created/paid/failed/overdue/refunded` |
| attendance | `attendance` | on | on (+seat) | today's visits | `attendance.checked_in/checked_out` |
| renewals | `renewals` | on | on | pipeline | `renewal.created/confirmed` |
| seat_management | `seat_areas/seats/seat_allocations` | **off** | **on** | availability | `seat.allocated/released/transferred` |
| fitness_tracking | (extension point) | on | off | — | — |
| approvals | `approvals` | on | on | approvals inbox | `approval.requested/decided` |
| analytics/owner_dashboard | `owner_analytics` | on | on | Owner CC | — |

New business = `provision_business(slug, name, template)` + enable
capabilities + seed catalogue. Templates: `fitness`, `self_study_center`
(`app/services/business_templates.py`).

## 4. Money & time rules

- NUMERIC(12,2) + explicit currency everywhere; Python `Decimal`
  quantized to 2dp; frontend renders backend strings only.
- Membership/attendance dates are DATEs; expiry math is date-based in
  the business timezone (`Asia/Kolkata` seeded; UTC fallback).
- Timestamps tz-aware; SQLite-naive reads normalized defensively.

## 5. API list (new, all `/api/v1`, paginated/filtered/sorted)

Members (5), plans (4), memberships (5), renewals (3), payments (5),
attendance (4), seats/areas/allocations (12), approvals (4), owner (4).
Full paths: see `docs/integrations/api-contracts.md`.

## 6. Permissions (new keys; least privilege)

`members.read` (already reserved, now enforced) + `memberships.*`,
`membership_plans.read/manage`, `payments.update/refund`,
`attendance.read/create/update`, `renewals.read/create/update`,
`seats.read/manage`, `analytics.owner`, `owner.dashboard.read`,
`owner.combined.read` (OWNER/ADMIN only), `approvals.read/manage`.
OWNER: all. ADMIN: all − `users.disable`. MANAGER: operate, no
refunds/plan-manage/seat-manage/combined. STAFF: register + check-in,
no updates/refunds/decisions. VIEWER: read (+ request approvals).

## 7. Analytics formulas (explicit)

```text
lead_conversion_rate    = converted / eligible, eligible = total − spam
booking_conversion_rate = converted / (booked + converted)
zero denominator        = 0.0 (never null, never invented)
average_transaction     = collected / payment_count (0.00 when none)
seat utilization        = allocated_active / total (from DB state)
```

Returned in `formulas` alongside every leads report.

## 8. Domain events (Block 8 hooks)

`domain_events` rows: `member.created`, `membership.*` (created,
activated, expiring, expired, renewed, cancelled), `payment.*`
(created, paid, failed, overdue, refunded), `attendance.checked_in/out`,
`seat.*` (allocated, released, transferred), `renewal.created/confirmed`,
`approval.requested/decided`, plus lead/booking events. Payloads carry
IDs + safe metadata only. Nothing consumes them yet by design.

## 9. Website-integration readiness (NOT connected yet)

Public site contracts are documented in `docs/integrations/`:
plan catalogue reads, seat availability reads, enquiry/booking intake
(all reuse existing public lead/booking endpoints — no new public
writes). Staff/owner APIs stay private. Honest pending list included.

## 10. Tests (new: 21 backend + 6 frontend + 20 Playwright)

- `test_block6_prime.py` (7): member CRUD/validation, profile
  aggregates, plan versioning/history-safety, lifecycle + Decimal math,
  payment idempotency/refund gates, attendance idempotency/checkout,
  renewal linking.
- `test_block7_nest.py` (5): exact 20-price catalogue, seat
  inventory/availability, allocation exclusivity + release/transfer +
  history, seat check-in + renewal seat continuity, Nest E2E flow.
- `test_block5_owner.py` (6): truthful zeros, real-data overview,
  presets/trends/validation, funnel formulas, combined gating/content,
  auth/permission enforcement.
- `test_block57_security.py` (5): cross-business 404s for all entities,
  forged-link rejection, viewer/staff boundaries, self-decision block,
  garbage-UUID 404s.
- `test_block57_concurrency.py` (6): seat double-allocate (service +
  DB constraint), payment-key winner, check-in dedupe (+ DB backstop),
  renewal safety, transition-table units, Decimal math.
- `test_block57_e2e.py` (3): Prime / Nest / combined full flows.
- Frontend: `operations.test.tsx` (nav gating, money/rate, presets,
  query scoping); `e2e/operations.spec.ts` (auth redirects + overflow,
  360/768/1280).

## 11. Known limitations (honest)

1. SQLite serializes writes: concurrency tests prove constraint safety
   nets, not true thread races (documented race matrix untested live
   without Postgres).
2. `mark_expired` is a service function — no scheduler wires it yet
   (Block 8 automation).
3. `membership.expiring` events are defined but not emitted on a timer
   (same reason).
4. Payment `online` provider records intent only; gateway webhooks are a
   validated stub (`handle_webhook` returns pending, never settles).
5. Combined view requires the caller to hold membership in ONE business;
   cross-business *staff* work still uses the business switcher.
6. Frontend bundle is one chunk (~520KB; pre-existing pattern).
7. Playwright covers anonymous/UX states; authenticated dashboard E2E
   needs the live-backend pass (post-Block-7 integration).
8. Alembic upgrade/downgrade verified by review + SQLite parity in this
   pass; live-Postgres migration run belongs to the integration pass.

## 12. Intentional evolutions of earlier blocks

1. `test_block1_rbac.py::test_staff_limited_permissions` — STAFF gains
   `members.create` (front-desk registration; updates still denied).
2. `Operational` settings validation now accepts `capabilities`,
   `membership/payments/attendance/renewals/seats/dashboard` sections
   (validated; unknown keys rejected).
3. Tasks link to 7 new related-entity types (same-business verified).
4. Seed: Prime/Nest get `Asia/Kolkata` + `INR` + plan catalogues + Nest
   seat areas (idempotent; settings rows stay empty until owners edit).

## 13. Files created (backend)

Models/migration: `models/operations.py`, `migrations/versions/
0005_block5_7_operations.py`. Repos: `members.py`, `op_memberships.py`
(staff RBAC stays in `memberships.py`), `payments.py`,
`attendance.py`, `seats.py`, `approvals.py`, `owner_analytics.py`.
Services: `members.py`, `memberships.py`, `payments.py`,
`attendance.py`, `seats.py`, `approvals.py`, `owner.py`,
`domain_events.py`, `capabilities.py`, `business_templates.py`.
Schemas: `schemas/operations.py`, `schemas/owner.py`. Endpoints:
`members.py`, `memberships.py`, `payments.py`, `attendance.py`,
`seats.py`, `approvals.py`, `owner.py`. Tests: `block57_support.py`,
`test_block{5,6,7}_*.py`, `test_block57_{security,concurrency,e2e}.py`.

## 14. Files created (frontend)

`features/owner/` (hooks + OwnerPage), `features/members/` (hooks,
MembersPage, MemberDetailPage), `features/memberships/` (hooks,
MembershipsPage, PlansPage, RenewalsPage), `features/payments/`,
`features/attendance/`, `features/seats/`, `features/approvals/`,
`test/operations.test.tsx`, `e2e/operations.spec.ts`; extended
`types.ts`, `lib/query.ts`, `lib/list.ts` (money/rate/overdue),
`config/business.ts` (owner preset), `App.tsx`, `Shell.tsx`.
