# Owner Dashboard Integration (command center contract)

The owner experience answers: what is happening, what needs attention,
how Prime and Nest perform. Route: `/owner` in `apps/staff-dashboard`.

## Data contracts (all live aggregates — zeros when empty)

- `GET /owner/overview` → `OwnerBusinessOverview`
- `GET /owner/revenue` → `OwnerRevenueReport` (`summary` + `daily_trend`)
- `GET /owner/leads` → `OwnerLeadsReport` (`funnel` + documented `formulas`)
- `GET /owner/combined?scope=` → `CombinedOverview` (`totals` + `businesses`)

TypeScript mirrors live in `src/types.ts` (`OwnerBusinessOverview`,
`RevenueStats`, `LeadFunnel`, `CombinedOverview`, …).

## Access model

- Single-business: `owner.dashboard.read` (OWNER/ADMIN/MANAGER/VIEWER).
- Combined: `owner.combined.read` **plus** OWNER/ADMIN role — enforced
  server-side; the UI only hides/shows the scope switcher.
- Combined queries are intentional (`scope` param) and auditable.

## Future (Block 8+) extension points

AI insights plug into `OwnerPage` sections as advisory cards (never
replacing deterministic aggregates); automation subscribes to
`domain_events` (`membership.expiring`, `payment.overdue`, …) and
surfaces owner alerts + staff tasks through existing channels.
