# Staff Dashboard Integration (Blocks 5–7 routes)

Canonical app: `apps/staff-dashboard` (one codebase for Prime + Nest).
Business identity comes from the backend session; `VITE_BUSINESS_SLUG`
only seeds the login-screen preset.

## New routes (all behind `RequireAuth` + permission-gated nav)

| Route | Permission | Page |
|---|---|---|
| `/owner` | `owner.dashboard.read` (or combined) | Owner command center |
| `/members`, `/members/:id` | `members.read` | list + 360° profile |
| `/memberships` | `memberships.read` | enrol + status + renew |
| `/plans` | `membership_plans.read` | catalogue (manage-gated edits) |
| `/renewals` | `renewals.read` | pipeline |
| `/payments` | `payments.read` | record + settle + refund (gated) |
| `/attendance` | `attendance.read` | register + check-in/out |
| `/seats` | `seats.read` | availability + inventory + allocations |
| `/approvals` | `approvals.read` | request + decide (gated) |

## Conventions for future modules

- Hooks in `features/<module>/hooks.ts` with `keys.<module>(businessId, …)`
  (business id always in the key).
- Mutations invalidate their module keys + `ownerOverview`.
- Money via `formatMoney` (renders backend strings); rates via
  `formatRate`; dates via `formatDate/formatDateTime`.
- Every page: loading (`TableSkeleton`/`CardsSkeleton`), empty
  (`EmptyState`/`NoResults`), error (`ErrorState` + retry), permission
  (`ForbiddenState` / friendly 403 from `ApiError`).
- Responsive: cards stack, filters wrap, tables become lists, dialogs
  fit 360px; verified at 360/768/1280 with zero horizontal overflow.

## Owner dashboard

`OwnerPage` renders the single-business overview by default and the
combined view when `owner.combined.read` is present (scope pills
All/Prime/Nest, preset filters, refresh + last-updated). Styling reuses
the shared system; the Crown nav entry distinguishes Owner UX.
