# Nest Website — Future Integration Guide (NOT connected yet)

The Nest Library website stays a **thin client**. Block 3 intake is
already live (`docs/NEST_WEBSITE_INTEGRATION.md` + `integrations/
nest-website/`); this guide covers the Blocks 5–7 operations the site
will use next.

## What the website will need

| Website feature | Backend contract (ready) | Notes |
|---|---|---|
| Enquiry / visit request | `POST /public/nest/leads|bookings` (live) | unchanged |
| Plan selection | `GET /membership-plans?category=` (staff auth today) | 20-plan catalogue is live data; needs public-read layer |
| Seat availability | `GET /seats/availability`, `GET /seats/available?seat_type=` (staff auth today) | server-computed; **never trust frontend availability** |
| Seat preference capture | `seat_preference` on member + `notes` on allocation | preference ≠ guarantee until staff allocates |
| Membership selection | plan `code`s (e.g. `nest-confirmed-3m`) are stable API identifiers | prices render from API strings |

## Required frontend changes (later)

1. Extend `integrations/nest-website/backend.ts` with catalogue reads.
2. `VITE_BUSINESS_SLUG=nest-library` (or `nest` per deployment).
3. Show `is_best_value` badge from API data (12-month tiers).
4. Never advertise a free trial (product rule); never invent offers —
   render catalogue rows only.

## Environment

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_BUSINESS_SLUG=nest
```

## Explicitly NOT done

Plan/seat browsing and booking-with-preference are documented but not
wired. No website code was changed in Blocks 5–7.
