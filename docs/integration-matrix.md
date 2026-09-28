# Prompt 4 — Integration Matrix (all five surfaces → one canonical backend)

Verified 2026-09-28 against backend `0.1.0` (335/335 tests) + live Docker stack.
Rule applied throughout: **backend is authoritative** for auth, business
membership, business context, tenant isolation, owner access and RBAC.
Frontends only present permitted data; no `business_id` from the browser is
trusted for authorization.

## 1. Surface inventory (as found on disk)

Prompt 4 names five surfaces. The authoritative architecture (README,
`docs/INTEGRATION_ARCHITECTURE.md`, `docs/BLOCK_3_4_IMPLEMENTATION.md`)
implements them as **two codebases + one drop-in contract package** — this is
the design, not a gap:

| # | Surface | Implementation | Repo path |
|---|---|---|---|
| 1 | Prime Fitness Website | standalone Vite app | `C:\Users\ossag\OneDrive\Desktop\prime-fitness-website` (own git repo) |
| 2 | Nest Library Website | drop-in package + verified contract (source not in workspace) | `integrations/nest-website/` + `docs/NEST_WEBSITE_INTEGRATION.md` |
| 3 | Prime Staff Dashboard | shared dashboard, `VITE_BUSINESS_SLUG=prime` branding hint, session from backend | `apps/staff-dashboard` |
| 4 | Nest Staff Dashboard | **same** shared dashboard, `VITE_BUSINESS_SLUG=nest` hint, session from backend | `apps/staff-dashboard` |
| 5 | Owner Dashboard | **same** shared dashboard, `/owner` route gated on `owner.combined.read` + OWNER/ADMIN | `apps/staff-dashboard/src/features/owner/` |

Staff/owner are separated **server-side** (JWT `business_id` + fresh DB
membership/role lookup per request), never by frontend hiding.

## 2. Final API base configuration (do NOT "fix" these to /api/v1)

| Project | Env file | `VITE_API_BASE_URL` | `VITE_BUSINESS_SLUG` | How the final URL is built |
|---|---|---|---|---|
| Prime website | `.env` (gitignored) | `http://localhost:8000` | `prime` | `` `${base}/api/v1/public/${slug}/…` `` → `http://localhost:8000/api/v1/public/prime/leads` |
| Nest website | `.env` (per `integrations/nest-website/.env.example`) | `http://localhost:8000` | `nest` | `` `${base}/api/v1/public/${slug}/…` `` → `http://localhost:8000/api/v1/public/nest/leads` |
| Shared staff/owner dashboard | `apps/staff-dashboard/.env` (gitignored) | `http://localhost:8000` | `prime` (login branding hint only) | `` `${base}${path}` `` with paths already starting `/api/v1/…` → `http://localhost:8000/api/v1/auth/me` |

Setting any `VITE_API_BASE_URL` to `http://localhost:8000/api/v1` would
produce `/api/v1/api/v1/…` — verified by reading `src/lib/backend.ts`
(website) and `src/lib/api.ts` + `src/config/business.ts` (dashboard).

## 3. Canonical endpoints consumed (all verified live)

| Surface | Endpoints |
|---|---|
| Prime website | `GET /api/v1/public/prime/config`, `POST /api/v1/public/prime/leads`, `POST /api/v1/public/prime/bookings` (all with `Idempotency-Key`, honeypot `website_url`) |
| Nest website | `GET /api/v1/public/nest/config`, `POST /api/v1/public/nest/leads`, `POST /api/v1/public/nest/bookings` |
| Staff dashboards | `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/businesses`, `POST /api/v1/auth/switch-business`, `/api/v1/leads…`, `/api/v1/bookings…`, `/api/v1/contacts…`, `/api/v1/customers…`, `/api/v1/dashboard…`, `/api/v1/tasks…`, `/api/v1/notifications…`, members/memberships/payments/attendance/seats/renewals/approvals/automation/communications/growth/analytics/brief |
| Owner | `/api/v1/owner/overview`, `/api/v1/owner/revenue`, `/api/v1/owner/leads`, `/api/v1/owner/combined?scope=…`, `/api/v1/owner/brief` |

## 4. API URL audit result

Searched all frontends for `localhost`, `/api/`, `business_id`, `tenant`,
`slug`, `mock`, `MSW`, `fixture`:

- **CORRECT**: website `backend.ts` public-route construction; dashboard
  `api.ts` + all `features/*/hooks.ts` (no `business_id` sent in any
  query/body — it is only a React-Query cache key from `/auth/me`);
  `WebsiteChat.tsx` (`/api/v1/public/{slug}/ai/chat`); `LEAD_API_CONTRACT`.
- **FIXED (1)**: `prime-fitness-website/src/lib/leads.ts` stale comment
  referencing `POST /api/leads` → corrected to the canonical public routes.
- **No MSW / mock services / fixture data** in any production path.
  `vi.mock` appears only in dashboard unit tests; website `saveLead` local
  backup is explicitly labeled `viaBackend: false`, never fake success.
- **No** `/api/v1/api/v1`, `/api/leads/*`, wrong-slug, or hardcoded-component-URL defects found.

## 5. Contract corrections vs the Prompt 4 brief

These brief expectations were inaccurate for the canonical codebase; the
code/backend is correct and the brief is corrected here (no code changed):

1. Staff dashboards must use `VITE_API_BASE_URL=http://localhost:8000/api/v1`
   — **wrong**: the client already prefixes `/api/v1`; bare host is correct.
2. Seed logins `admin@primefitness.in / Prime@123`, `priya@nestlibrary.in /
   Nest@123`, `rahul@nestlibrary.in` — **do not exist**; seed creates only
   the platform owner. Staff users are per-test fixtures; live Docker E2E
   uses `prime.owner@live.example.com` / `nest.owner@live.example.com`
   (`backend/seed_live_e2e.py`). Verified live.
3. `/auth/me` returning `business_id = prime-fitness-001` — the response
   carries the business **UUID + slug** (`prime`); `prime-fitness-001` is the
   server-side `businesses.external_id` registry key (verified in DB +
   `test_prompt2_multibusiness.py`), never a browser credential.
4. "335/335" baseline — confirmed exactly (collection sums to 335).

## 6. Integration status

| Surface | Connected | Auth | Real API | Browser | Build | Status |
|---|---|---|---|---|---|---|
| Prime Website | yes | n/a (public) | yes, live | yes (Chromium shots) | PASS | ✅ |
| Nest Website | via verified package | n/a (public) | yes, live (`/nest/*` proven) | contract-level | n/a (source absent) | ✅ with noted limitation |
| Prime Staff | yes | yes, live | yes, live | yes (live E2E 6/6) | PASS | ✅ |
| Nest Staff | yes | yes, live | yes, live | yes (live E2E 6/6) | PASS | ✅ |
| Owner | yes | yes, live | yes, live (combined) | via staff shell | PASS | ✅ |
