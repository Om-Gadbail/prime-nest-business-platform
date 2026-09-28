# Prime Website — Future Integration Guide (NOT connected yet)

The Prime Fitness website stays a **thin client**. The backend
(`/api/v1`) remains the source of truth. Block 2 intake is already
live (`docs/PRIME_INTEGRATION.md`); this guide covers the Blocks 5–7
operations the site will use next.

## What the website will need

| Website feature | Backend contract (ready) | Notes |
|---|---|---|
| Membership enquiry | `POST /public/prime/leads` (live) | unchanged |
| Trial booking | `POST /public/prime/bookings` (live) | always `requested`, staff confirms |
| Plan browsing | `GET /membership-plans` (staff auth today) | needs the public-read layer (integration pass) |
| Membership purchase | new public checkout (integration pass) | **do not** POST `/memberships` publicly — staff-only |
| Member check-in (mobile) | `POST /attendance/check-in` (staff auth today) | member-auth story belongs to integration pass |

## Required frontend changes (later)

1. Reuse `src/lib/backend.ts` pattern for catalogue reads (plans).
2. `VITE_BUSINESS_SLUG=prime-fitness` (or `prime` per deployment).
3. Render prices from API strings only (no local price tables).
4. Idempotency keys on purchase retries.

## Environment

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_BUSINESS_SLUG=prime
```

## Explicitly NOT done

Plan browsing/purchase and member self-service are documented but not
wired. No website code was changed in Blocks 5–7.
