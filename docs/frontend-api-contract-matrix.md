# Frontend API Contract Matrix (Prompt 3 — read-only inspection, no frontend changes)

All five surfaces speak the canonical `/api/v1` contract. No legacy non-v1
API paths (`/api/leads/...` style) are referenced by ANY local frontend —
they must NOT be reintroduced (Prompt 4: keep v1).

## 1. Prime Website (`prime-fitness-website`, external checkout — anonymous only)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/public/{slug}/config` | Feature flags, slug=`prime` |
| POST | `/api/v1/public/{slug}/leads` | Trial/enquiry intake (`name`, phone, interest…) |
| POST | `/api/v1/public/{slug}/bookings` | Visit/trial booking |
| GET | `/api/v1/public/{slug}/availability` | Used by site flows |

Slug-templated client; no auth, no business IDs, no secrets. Compatible as-is.

## 2. Nest Website (`integrations/nest-website` drop-in — anonymous only)

Same four paths with slug=`nest` (+ `business-info` support). No live Nest
site is wired in this checkout; the drop-in already targets v1. Compatible.

## 3+4. Staff Dashboards (Prime + Nest = ONE app `apps/staff-dashboard`)

Single dashboard with business presets; per-business Bearer context from
`POST /auth/login` (+ `business_slug`), `GET /auth/businesses`,
`POST /auth/switch-business`, `GET /auth/me`, refresh/logout. Consumes the
full staff surface: leads, bookings, members, membership-plans, memberships,
renewals, payments, attendance, seats (+areas/allocations/availability),
tasks, contacts, customers, notifications, approvals, dashboard/*,
automation/*, communications/*, ai/*, growth/*, analytics/*, business
settings. All paths verified present in backend OpenAPI. Compatible as-is.

## 5. Owner Dashboard (owner view inside the staff dashboard)

| Method | Path | Params used |
|---|---|---|
| GET | `/api/v1/owner/overview` | `preset`/`date_from`/`date_to` range |
| GET | `/api/v1/owner/revenue` | range + `daily_trend` |
| GET | `/api/v1/owner/leads` | range + `formulas`+`funnel` |
| GET | `/api/v1/owner/combined` | `scope` + range |
| GET | `/api/v1/owner/brief` | daily brief |

Response TS types (`OwnerBusinessOverview`, `OwnerRevenueReport`,
`OwnerLeadsReport`, `CombinedOverview`) match backend schemas field-for-field
(verified 2026-09-28). Historical gap paths (`/businesses`,
`/analytics/comparison`, `/analytics/business/{id}`, `/analytics/alerts`,
`/analytics/pulse`, `/analytics/retention`, `/analytics/growth`) are NOT
referenced by the dashboard — intentionally NOT implemented (no second
analytics API).

## Auth transport (all authenticated surfaces)

`Authorization: Bearer` access JWT (memory-only) + HttpOnly refresh cookie
(`Path=/api/v1/auth`) with JSON fallback. 401 = re-login; 403 = missing
grant (dashboard hides the UI, backend enforces).
