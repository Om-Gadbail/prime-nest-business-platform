# Owner Command Center — Analytics Architecture & KPI Definitions (Prompt 6)

Canonical backend: `backend/` in this repo. Owner frontend:
`prime-nest-owner-dashboard/apps/owner-dashboard` (separate repo).
The legacy demo analytics API in `prime-nest-owner-dashboard/apps/api`
is **superseded** for owner analytics — the dashboard reads only the
endpoints below.

All figures are server-computed live aggregates. Empty businesses return
zeros / honest "no data" states — never invented numbers.

## Endpoint inventory

| Method + path | Permission | Scope | Purpose |
|---|---|---|---|
| `GET /api/v1/owner/overview?scope=&preset=&date_from=&date_to=&soon_days=` | `owner.dashboard.read` | omitted = token business; slug = authorized grant (`owner.combined.read` + OWNER/ADMIN); `all` rejected (use combined) | Executive per-business snapshot |
| `GET /api/v1/owner/revenue?...` | `owner.dashboard.read` | same as overview | Revenue + daily paid trend |
| `GET /api/v1/owner/leads?...` | `owner.dashboard.read` | same as overview | Funnel + conversion formulas |
| `GET /api/v1/owner/combined?scope=all\|slug&...` | `owner.combined.read` + OWNER/ADMIN | grants only (never "all businesses") | Portfolio totals + per-business |
| `GET /api/v1/owner/alerts?scope=&...` | `owner.dashboard.read` (+ combined gate when scoped) | `None` = current; `all`/slug = gated | Rule-based exceptions |
| `GET /api/v1/owner/growth?scope=&...` | same | same | Current vs previous period |
| `GET /api/v1/owner/renewals?scope=` | same | same | Buckets 7/14/30d + overdue + rate |
| `GET /api/v1/owner/payments?scope=&...` | same | same | Health + attention queue |
| `GET /api/v1/owner/attendance?scope=&...&inactivity_days=` | same | same | Trend + decline/inactive signals |
| `GET /api/v1/owner/automation-health?scope=` | same | same | Read-only engine telemetry |
| `GET /api/v1/owner/brief` | `reports.read` | token business only | Daily report (yesterday/today/trend) |
| `GET /api/v1/owner/renewals/scan` | `reports.read` | token business only | Flat due list at offsets 30/14/7/3/1/0 |

Presets: `today | 7d | 30d | month | quarter | all`, or explicit
`date_from`/`date_to` (ISO). Scoped combined access is audit-logged
(`report.generated` with slugs only).

## KPI definitions

Money serializes as decimal strings. Rates are floats in [0, 1];
`delta_pct` is percent (12.4) or **null when there is no baseline**
(zero denominator never yields a percentage).

### Membership (`membership_counts`)

| Metric | Source | Date field | Status filter | Notes |
|---|---|---|---|---|
| `active_memberships` | `memberships` COUNT | — | `active` | |
| `active_members` | `members` COUNT | — | `active` | Operational profile, not staff identity |
| `new_members_today` | `members` COUNT | `created_at >= today 00:00 UTC` | — | UTC midnight (minor skew vs business TZ, documented) |
| `expiring_soon` | `memberships` COUNT | `end_date` in `[today(biz TZ), today+soon_days]` | `active` | `soon_days` 1..90, default 7 |
| `expired` | `memberships` COUNT | — | `expired` | Win-back candidates, not capacity |
| `by_status` / `total` | `memberships` GROUP BY | — | all | |

### Revenue (`revenue_summary`, window on `Payment.created_at`)

| Metric | Statuses summed |
|---|---|
| `collected` | `paid` |
| `pending` | `pending`, `partially_paid` |
| `overdue` | `overdue` |
| `refunded` | `refunded` |
| `payment_count` | all statuses in window |
| `average_transaction` | `collected / payment_count` (denominator includes non-paid rows — interpret with `by_status`) |
| `by_status` | per-status count + amount |
| `by_method` | **paid only** per-method count + amount |
| `daily_trend` (`revenue_by_day`) | `paid` grouped by `date(paid_at)`; only when both window bounds set |

"Net revenue" is intentionally NOT reported: the data supports
collected/outstanding/refunded, not a net definition.

### Leads (`lead_funnel`, window on `Lead.created_at`)

- `lead_conversion_rate = converted / eligible`, `eligible = total − spam`.
- `booking_conversion_rate = converted / (booked + converted)`.
- Zero denominators → `0.0`. Unknown sources render as their stored value;
  the UI never invents attribution (`utm_*` shown only when present).
- `lead_trend`: per-day counts on `created_at` (both bounds required).

### Bookings (`booking_summary`, window on `Booking.created_at`)

Counts grouped by `Booking.status`; no rate invented.

### Attendance

- `attendance_today`: rows where `attendance_date = today(biz TZ)`.
- Check-ins without an explicit date are recorded on the **business-local**
  day (`attendance._business_today`), so near-midnight visits land on the
  right day in owner views.
- `attendance_window` (report): per-day trend on `checked_in_at`, totals,
  avg/day, distinct members, visits/member.
- **Decline signal (rule-based, not predictive):** split window in halves;
  flagged when first-half visits ≥ 4 AND second-half < 50% of first-half.
  Labeled "attention needed", never "will churn".
- **Inactive:** active members with zero visits in window; evaluated only
  when the window spans ≥ `inactivity_days` (default 14), otherwise returns
  `evaluated: false` with a reason instead of a misleading zero.

### Renewals (`renewal_buckets`, `today` = business TZ)

Cumulative buckets from today: `due_7d ⊆ due_14d ⊆ due_30d` (count + amount),
`overdue` (pending, `due_date < today`, count + amount),
`renewal_rate = confirmed / total renewals ever` (0.0 when none).
Renewal statuses: `pending | confirmed | cancelled | expired`.

### Payments (`payment_health`, window on `Payment.created_at`)

`outstanding = pending + partially_paid + overdue` (money to collect).
`attention`: latest ≤20 `failed`/`overdue` rows with safe identifiers only
(`id, invoice_no, amount, currency, status, method, created_at, due_at,
member_id`) — never `provider_ref` or secrets.

### Growth (`growth_report`)

Current window vs the immediately preceding **equal-length** window:
revenue collected, leads, conversions (+rate), new members
(`Member.created_at`), confirmed renewals (`Renewal.renewed_at`),
attendance (`Attendance.checked_in_at`). Open-ended windows (`preset=all`)
have no previous period → `previous`/`delta_pct` null ("no prior data").

### Alerts (`alerts_report`)

Deterministic rules over the above aggregates (no ML):

- `critical`: failed payments ≥ 5 OR failed automation executions ≥ 5 in 24h.
- `warning`: any failed/overdue payments, overdue renewals, never-contacted
  leads (>24h, `last_contacted_at` NULL), overdue follow-ups
  (`follow_up_at` past, non-terminal status), automation failures in 24h,
  ≥10 expiring memberships.
- `info`: renewals due in 7d, expiring/expired memberships, stale leads
  (>72h in `new`/`contacted`).

Each alert: severity, business, category, title, detail, count,
`observed_at`, `drill` (owner section hint). Sorted critical → warning →
info. Empty = zero alerts.

### Automation health (`automation_health`)

`automation_rules` totals/active + `automation_executions` counts by status
(`pending | running | succeeded | failed | retrying`), `failed_24h`,
`pending_retry`, `last_success_at`, `last_failure_at`. No executions ever →
timestamps null with an explanatory note. No workflow engine here —
read-only telemetry.

### Combined (`combined_overview`)

`scope=all` aggregates **only the caller's authorized grants** (active
memberships in active businesses). `scope=<slug>`: same gate, single
business (unknown slug → 404, unassigned → 403). Totals: collected,
pending, overdue, payments, leads, converted, eligible,
`lead_conversion_rate = converted / eligible` (spam-excluded, consistent
with single-business), plus portfolio rollups: active_memberships,
active_members, bookings, attendance_today, renewals_due_soon,
renewals_overdue, outstanding (= pending + overdue money).
"Business memberships" are counted per business; no cross-business
deduplication is claimed (no canonical cross-business identity model).

Seats: included per business only when the capability system reports
`seat_management`; occupancy denominator = usable seats
(`allocated_active / total`).

## Authorization (server-side, always)

- JWT carries identity only; every request re-resolves user → membership →
  business → permissions from DB state. Client business IDs are never trusted
  (single endpoints take no `business_id`; scope slugs are grant-checked).
- `owner.dashboard.read`: OWNER/ADMIN/MANAGER/VIEWER (single-business owner views).
- `owner.combined.read` + OWNER/ADMIN role: any explicit scope.
- STAFF: denied on all owner endpoints (403); unauthenticated: 401.
- Combined/scope access audit-logged (`report.generated`).

## Known limitations (honest, by design)

1. `new_members_today` uses UTC midnight, not business TZ (minor skew).
2. No revenue forecasting, no campaign attribution beyond stored `utm_*`,
   no fuzzy cross-business identity (counts labeled per-business).
3. `average_transaction` divides collected money by all-status payment count.
4. Daily owner brief covers the token's current business; the portfolio
   brief is composed from scope-aware reports.
5. Automation telemetry reflects execution records only (no scheduler heartbeat table).
6. `apps/api` in the owner-dashboard repo is superseded for owner analytics.
