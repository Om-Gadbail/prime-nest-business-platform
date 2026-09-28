# Prompt 4 — Golden Workflows (evidence-backed)

All flows below were executed against the REAL backend twice: once over the
HTTP layer via TestClient (seeded SQLite, `TOTAL 57 PASS 57 FAIL 0`,
exit 0) and once against the live Docker stack (PostgreSQL 16 + Redis).
IDs shown are real records in the local dev database.

## Workflow 1 — Prime Website → Prime Backend → Prime Staff ✅

1. `POST /api/v1/public/prime/leads` (Idempotency-Key `p4-live-prime-1`)
   → `201 {lead_id: 7bc35e9c-422c-4f3e-9d70-9975ce49036f}`.
2. Login `prime.owner@live.example.com` → `GET /api/v1/leads`
   → list contains `P4 Live Prime`; `GET /api/v1/public/prime/bookings`
   intake likewise creates `REQUESTED` bookings (never confirmations).
3. Honeypot (`website_url` set) → `201 lead_id=received`, staff total
   unchanged. Idempotent replay → same `lead_id`; changed body + same key
   → `409`. Missing phone → `422`; wrong content-type → `415`;
   70 KB body → `413`; unknown slug → `404` — all with the safe
   `{error:{code,message}}` envelope.

## Workflow 2 — Nest Website → Nest Backend → Nest Staff ✅

1. `POST /api/v1/public/nest/leads` with tamper fields
   (`business_id=<prime-uuid>`, `businessId=prime`, `slug=prime`)
   → `201 {lead_id: c7465de8-9c3b-4a1b-a95f-dc12a90ea0cd}`.
2. Login `nest.owner@live.example.com` → list contains `P4 Live Nest`,
   does NOT contain `P4 Live Prime`.
3. Slug-route wins: the tampered request is stored under **Nest**
   (prime owner `GET` on the nest lead → `404`).

## Workflow 3 — Owner → Prime ✅

`owner@prime-nest-dashboard.com` login → `GET /api/v1/auth/me`
(`owner.combined.read` present) → `GET /api/v1/owner/overview`
(default business `prime`) → `200 slug=prime`; revenue + leads funnel `200`.

## Workflow 4 — Owner → Nest ✅

`POST /api/v1/auth/switch-business {business_id: nest}` → `200`
→ `GET /api/v1/owner/overview` → `200 slug=nest`.

## Workflow 5 — Owner → Combined Portfolio ✅

- `GET /api/v1/owner/combined?scope=all` → `200`, businesses `[nest, prime]`
  (live run confirmed `COMBINED-SCOPE: all` → `nest,prime`).
- `scope=prime` → `[prime]` only. Unknown slug → `404`.
- Single-business OWNER (`scope=all`) → `[prime]` only — no leakage.
- Every combined read writes an `audit_events(report.generated)` row
  (`owner_combined`, slugs only).

## Workflow 6 — Cross-business attack matrix ✅ (all denied server-side)

| # | Attack | Expected | Observed |
|---|---|---|---|
| 1 | Prime staff `GET` nest lead | 404 | 404 |
| 2 | Nest staff `GET` prime lead | 404 | 404 |
| 3 | Prime staff `POST /leads` with `business_id=<nest>` | 422 (extra=forbid) | 422 |
| 4 | Same from Nest side | 422 | 422 (symmetric schema) |
| 5 | Prime staff `switch-business` → nest | 403 | 403 |
| 6 | Nest staff `switch-business` → prime | 403 | 403 |
| 7 | Nest public form sends `businessId=prime` | stays Nest | stays Nest (W2) |
| 8 | Prime public form sends `businessId=nest` | stays Prime | stays Prime (W1 + symmetric test) |
| 9 | Staff `GET /owner/combined` | 403 | 403 |
| 10 | Single-business owner `scope=all` | own business only | `[prime]` only |
| + | STAFF `POST /leads/{id}/status` (no `leads.update`) | 403 | 403; MANAGER → 200 (least privilege by design) |
| + | VIEWER `POST /leads` | 403 | 403 |
| + | Refresh reuse after rotation | 401 + family revoked | 401 |
| + | Refresh after logout | 401 | 401 |
| + | Wrong password / unknown user | identical generic 401 | identical `Invalid email or password.` |
| + | Evil-origin CORS preflight | no ACAO echo | none (allowed 5173/5174 echo + `Allow-Credentials: true`) |

## Auth lifecycle (staff + owner) ✅

`login → access+refresh → /auth/me → app → requests → 401 → one
transparent refresh+retry (dashboard client) → logout → session revoked`.
Refresh rotation verified (`rotated=True`); cookie + JSON transports intact.
