# Shared API Integration Contract (Prime + Nest websites)

One backend, two websites. Both sites use the **same anonymous contract**;
only the business slug in the path differs (`prime` vs `nest`). The slug
is resolved and verified **server-side** — browsers never send
`business_id`.

## Base

`{VITE_API_BASE_URL}` + `/api/v1/public/{slug}/…`, JSON only
(`Content-Type: application/json`, else 415).

## Endpoints

| Method & path | Auth | Success | Notes |
|---|---|---|---|
| `GET /public/{slug}/config` | no | 200 `{slug, name, business_type, timezone, lead_capture_enabled, booking_enabled}` | unknown/inactive slug → 404 |
| `POST /public/{slug}/leads` | no | 201 `{success: true, status: "received", lead_id, message}` | lead is NEW |
| `POST /public/{slug}/bookings` | no | 201 `{success: true, status: "received", booking_id, message}` | booking is REQUESTED, never confirmed |

## Request rules (both sites)

- `Idempotency-Key: [A-Za-z0-9-_]{8,64}` header (fresh UUID per
  submission). Same key + same payload → replayed 201 (no duplicate).
  Same key + different payload → 409 (use a new key and retry).
- Honeypot `website_url` must be `""` (bots get fake 201, nothing stored).
- Attribution encouraged: `landing_page`, `referrer`, `utm_source`,
  `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`.
- 12s client timeout; safe error copy per `docs/NEST_WEBSITE_INTEGRATION.md`
  §5 (Prime: `docs/PRIME_INTEGRATION.md` §4).
- 429 carries `Retry-After`; 403 means intake is paused for that business.

## Staff API surface (dashboards only, Bearer + permission)

All under `/api/v1` (see OpenAPI at `/openapi.json` in non-production):

- Auth: `/auth/login|me|refresh|logout|businesses|switch-business`
- Business: `/business`, `/business/settings`
- CRM: `/leads` (+ `/assign|/status|/notes|/activities|/convert|/transfer`),
  `/bookings` (+ `/confirm|/cancel|/complete|/no-show|/reopen`),
  `/contacts`, `/customers`
- Operations: `/tasks` (+ `/assign|/status`), `/notifications`
  (+ `/unread-count|/{id}/read|/read-all|/preferences/{type}`),
  `/audit-events`, `/identity/*`
- Dashboard: `/dashboard/overview|/leads/summary|/bookings/summary|`
  `/activity|/tasks|/notifications`

Pagination envelope everywhere: `{items, total, limit, offset}`
(limit clamped to 100; sort is allowlisted per resource).
Errors: safe envelope `{error: {code, message}}` + `X-Request-ID`.
Cross-business rows behave as nonexistent (uniform 404, no oracle).
