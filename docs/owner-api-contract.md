# Owner API Contract (Prompt 3 — canonical, tested, no duplicates)

ONE coherent Owner API under `/api/v1/owner`. No second analytics API was
created: the dashboard's historical gap paths are not consumed by any local
frontend (see `docs/frontend-api-contract-matrix.md`).

## A. Current business (requires `owner.dashboard.read`)

- `GET /owner/overview?preset=&date_from=&date_to=&soon_days=` →
  `{business, generated_at, membership, revenue, leads, bookings,
  attendance_today, renewals, seats?}` (seats only when the business has the
  `seat_management` capability — Nest shape, not Prime).
- `GET /owner/revenue?...` → `{business_id, generated_at, window, summary,
  daily_trend[]}` (money as decimal strings).
- `GET /owner/leads?...` → `{business_id, generated_at, formulas, funnel,
  daily_trend[]}` (formulas document conversion math; zero-denominator → 0.0).
- `GET /owner/brief` → daily brief (`reports.read`).
- `GET /owner/renewals/scan` → expiring-membership pipeline (`reports.read`).

## B. Period comparison

Comparison is expressed through the range window (`today/7d/30d/month/
quarter/all` or explicit `date_from/date_to`), not a separate endpoint —
`daily_trend` arrays carry the series. No `/analytics/comparison` needed.

## C. Portfolio / combined (double-gated)

- `GET /owner/combined?scope=all|<slug>&...` requires
  `owner.combined.read` AND OWNER/ADMIN role AND an active membership in each
  returned business: `{generated_at, scope, totals, businesses[]}` with the
  same per-business shapes as (A). Unassigned scope → 403; unknown slug → 404.
  Every read is audit-logged (`report.generated`/`owner_combined`).

## Status

- Preserved: all six existing routes, shapes unchanged (dashboard types match).
- Added in Prompt 3: none (no gap found in actual consumers).
- Adapted: combined grant semantics (Prompt 2 security fix, documented with
  OLD/NEW/WHY in `docs/owner-identity-and-membership.md`).
- Intentionally not implemented: `/businesses`, `/analytics/comparison`,
  `/analytics/business/{id}`, `/analytics/alerts`, `/analytics/pulse`,
  `/analytics/retention`, `/analytics/growth`, owner-AI extras — unconsumed;
  adding them would create the duplicate analytics API this prompt forbids.
