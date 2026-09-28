# Staff Dashboard (Block 4)

One shared codebase serves the **Prime Fitness Staff Dashboard** and the
**Nest Library Staff Dashboard**. Business identity, accent, and data all
come from the backend session — there is no Prime-only or Nest-only fork.

## Run / build / test

```bash
cd apps/staff-dashboard
cp .env.example .env        # set VITE_API_BASE_URL (never commit .env)
npm install
npm run dev                 # http://localhost:5174
npm test                    # vitest (14 tests)
npm run typecheck           # tsc -b
npm run lint                # oxlint
npm run build               # production bundle -> dist/
npm run e2e                 # playwright (needs dist + optional live backend)
```

## Environment

| Variable | Required | Example |
|---|---|---|
| `VITE_API_BASE_URL` | yes | `http://localhost:8000` |
| `VITE_BUSINESS_SLUG` | no (`prime`) | `prime` / `nest` (login branding hint only) |
| `VITE_BUSINESS_NAME` | no | display-name override |

`VITE_BUSINESS_SLUG` is a **hint**, not a security boundary: after login
the active business always comes from the backend session, and users with
memberships in both businesses get a switcher in the header.

## Architecture

```
src/
  config/business.ts   # presets (prime/nest), env, display names
  types.ts             # backend contracts (single source of truth)
  lib/api.ts           # ONLY module that calls the backend (typed, refresh)
  lib/auth.tsx         # session provider (login/logout/switch/401 handling)
  lib/query.ts         # TanStack Query client + business-scoped keys
  lib/list.ts          # list params, date/due helpers
  components/ui/       # Button/Card/Badge/Modal/Drawer/forms/states/Toast
  components/layout/   # Shell (sidebar + header + mobile bottom nav)
  features/
    auth/              # LoginPage, RequireAuth, RequirePermission
    overview/          # dashboard home (KPIs, recent, quick actions)
    leads/             # list + detail (timeline, assign, status, convert, transfer)
    bookings/          # list + detail (confirm/cancel/complete/no-show/reopen)
    crm/               # contacts + customers
    tasks/             # task center (mine/overdue/completed, lifecycle)
    notifications/     # inbox + preferences
    activity/          # audit trail (read-only)
    settings/          # business info + intake flags (role-gated)
```

- Server state: TanStack Query only. Keys always start with the business
  id (`keys.*` in `lib/query.ts`); tokens never enter query keys.
- Mutations invalidate the affected scopes (lists + overview + summaries).
- Navigation filters by permission (`leads.read`, `tasks.read`, …);
  the backend enforces everything (frontend hiding is UX only).

## Auth model

- Access token: short-lived, memory only (never `localStorage`).
- Refresh token: backend HttpOnly cookie preferred, JSON copy fallback.
- 401 → one transparent refresh → else graceful logout (no spinners forever).
- Suspended/revoked memberships and inactive users take effect on the next
  request (backend re-resolves from the DB).

## Deploying for Prime vs Nest

Option A (recommended): deploy **once**; staff sign in and pick/switch
business. Set `VITE_BUSINESS_SLUG` to the primary brand for the login
screen.

Option B: deploy twice with different `VITE_BUSINESS_SLUG` /
`VITE_BUSINESS_NAME` per site (e.g. `prime-staff.example`,
`nest-staff.example`). Same build, different env — no code changes.

Backend CORS must allow the dashboard origin (`PUBLIC_SITE_ORIGINS`):
exact origins, never `*`.

## E2E

- `e2e/smoke.spec.ts` — anonymous states, validation, no-overflow at
  360/768/1280 (no backend needed).
- `e2e/live.spec.ts` — real sign-in + data against the Docker backend.
  Needs `dist/` built with `VITE_API_BASE_URL` set and the live seed
  users (see `docs/BLOCK_3_4_IMPLEMENTATION.md` § verification). The spec
  skips itself when the backend is unreachable.
