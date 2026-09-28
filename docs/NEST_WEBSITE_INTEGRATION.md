# Nest Website ↔ Backend Integration (Block 3)

The Nest Library website submits its seat/membership/visit forms to the
**same shared FastAPI platform** as Prime Fitness. The Nest website
source was not present in the workspace, so this document is the exact
verified contract plus a drop-in package (`integrations/nest-website/`).
Every payload below was tested live against the backend
(`backend/tests/test_block3_nest_public.py` + 43 live Docker checks).

## 1. What to copy into the Nest website

| Package file | Destination | Purpose |
|---|---|---|
| `integrations/nest-website/backend.ts` | `src/lib/backend.ts` | ONLY module that talks to the backend |
| `integrations/nest-website/attribution.ts` | `src/lib/attribution.ts` | UTM / referrer / landing-page capture |
| `integrations/nest-website/forms.ts` | `src/lib/nest-leads.ts` | `saveNestEnquiry` / `saveNestVisit` adapters |
| `integrations/nest-website/.env.example` | `.env` | `VITE_API_BASE_URL`, `VITE_BUSINESS_SLUG=nest` |

No routes, styling, SEO, or analytics changes are required.

## 2. Configuration

```bash
cp .env.example .env
# Local backend:
VITE_API_BASE_URL=http://localhost:8000
VITE_BUSINESS_SLUG=nest
```

- Leave `VITE_API_BASE_URL` empty and the adapters return an honest local
  message (no fake submission).
- Never put secrets in `VITE_*` variables. The website sends NO
  `business_id` (the slug in the path is backend-verified) and NO tokens.

Backend CORS must allow the site origin (`PUBLIC_SITE_ORIGINS` on the
backend — add the Nest origin alongside Prime's).

## 3. Wiring (exact)

Seat / membership / contact form:

```ts
import { saveNestEnquiry } from './lib/nest-leads';

const result = await saveNestEnquiry({
  name, phone, email,
  interest: 'Seat Inquiry', // 'Seat Inquiry' | 'Membership Inquiry' | 'Contact' | 'Other'
  preferredTime, message,
  source: 'website:seat-inquiry-form',
  honeypot, // hidden input, always "" from real users
});
if (result.ok) showSuccess(result.message);
else showError(result.message); // keep input for retry
```

Book-visit form (same shape, `saveNestVisit`, source
`website:visit-form`, plus `preferredDate: 'YYYY-MM-DD'`). Success copy
says "Request received — …", NEVER "Booking confirmed".

Honeypot input (hidden from real users via CSS):

```html
<input type="text" name="website_url" tabindex="-1" autocomplete="off"
       style="position:absolute;left:-9999px" aria-hidden="true" />
```

## 4. Endpoints used

Base `{VITE_API_BASE_URL}`, slug `nest` (backend-verified server-side).

- `POST /api/v1/public/nest/leads` — seat/membership/contact forms.
  JSON: `name`, `phone`, `email|null`, `message`, `service_interest`,
  `source_detail`, `preferred_time`, `consent_marketing: false`,
  `landing_page/referrer/utm_*`, `website_url` (honeypot).
  Header `Idempotency-Key: <uuid>` (fresh per submission).
  Success 201: `{success: true, status: "received", lead_id, message}`.
- `POST /api/v1/public/nest/bookings` — visit forms. Plus
  `booking_type` (`visit`/`trial`/`enquiry`), `title`,
  `requested_start_at` (local-midnight ISO), `preferred_time_label`.
  Success 201: `{success: true, status: "received", booking_id}` —
  the visit is REQUESTED; staff confirm it in the dashboard.
- `GET /api/v1/public/nest/config` — public flags
  (`lead_capture_enabled`, `booking_enabled`).

## 5. Error handling (`BackendError.kind`)

| kind | UI direction |
|---|---|
| `validation` | "Please check the form…" (keep input) |
| `rate_limited` | "Too many requests… try again" (+ Retry-After) |
| `disabled` | "Online enquiries paused… call/WhatsApp" |
| `timeout` / `server` / `unreachable` | "Could not reach… try again or call/WhatsApp" |

Always offer call/WhatsApp alternatives; capture `backendRequestId`.

## 6. Verification

1. Submit the form; note the success message + request ID.
2. Nest Staff Dashboard → Leads → search the phone → row is NEW with
   the right `source_detail` and `routed_by: slug`.
3. The lead does NOT appear in the Prime dashboard (isolation).
4. Double-submit with the same `Idempotency-Key` never duplicates.

## 7. Known limits

- No offline queue: unreachable backend → honest error + retry +
  call/WhatsApp options (same posture as the Prime integration).
- No staff dashboard in the website repo (staff verify in the dashboard
  app: `apps/staff-dashboard`).
