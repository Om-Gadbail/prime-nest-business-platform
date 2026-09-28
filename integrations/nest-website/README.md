# Nest Website ↔ Backend Integration Package (Block 3)

> Status: **complete integration package, tested against the backend**.
> The Nest website source was not present in the workspace, so this
> package contains verified drop-in modules + the exact wiring contract.
> Nothing here is a placeholder: every payload below was tested live
> against the backend (see `backend/tests/test_block3_nest_public.py`).

## 1. Files in this package

| File | Action |
|---|---|
| `backend.ts` | Copy to `src/lib/backend.ts` — the ONLY module that talks to the backend |
| `attribution.ts` | Copy to `src/lib/attribution.ts` — UTM / referrer / landing-page capture |
| `forms.ts` | Copy to `src/lib/nest-leads.ts` — form adapters (`saveNestEnquiry`, `saveNestVisit`) |
| `.env.example` | Copy to `.env` — `VITE_API_BASE_URL`, `VITE_BUSINESS_SLUG=nest` |

No routes, styling, SEO, or analytics changes are required. Every
lead-generating form flows through `saveNestEnquiry` (leads) or
`saveNestVisit` (visit requests).

## 2. Configuration

```bash
cp .env.example .env
# Local backend:
VITE_API_BASE_URL=http://localhost:8000
VITE_BUSINESS_SLUG=nest
```

- Leave `VITE_API_BASE_URL` empty and the adapters return the honest
  local message (no fake submission).
- Never put secrets in `VITE_*` variables. The website sends NO
  `business_id` (the slug in the path is backend-verified) and NO tokens.

Backend CORS must allow the site origin (`PUBLIC_SITE_ORIGINS` on the
backend — add the Nest site's dev/prod origin alongside Prime's).

## 3. Wiring (exact)

Seat / membership / contact form submit handler:

```ts
import { saveNestEnquiry } from './lib/nest-leads';

const result = await saveNestEnquiry({
  name, phone, email,
  interest: 'Seat Inquiry',          // or 'Membership Inquiry' | 'Contact' | 'Other'
  preferredTime,
  message,
  source: 'website:seat-inquiry-form',
  honeypot,                          // hidden input, always "" from real users
});
if (result.ok) showSuccess(result.message);   // "Enquiry received — …"
else showError(result.message);               // keep input for retry
```

Book-visit form submit handler — same shape with `saveNestVisit`:

```ts
import { saveNestVisit } from './lib/nest-leads';

const result = await saveNestVisit({
  name, phone, email,
  interest: 'Book Visit',
  preferredDate,                     // 'YYYY-MM-DD'
  preferredTime,
  message,
  source: 'website:visit-form',
  honeypot,
});
// Success copy says "Request received — …", NEVER "Booking confirmed".
```

Add a honeypot input to each form (hidden from real users via CSS):

```html
<input type="text" name="website_url" tabindex="-1" autocomplete="off"
       style="position:absolute;left:-9999px" aria-hidden="true" />
```

## 4. Endpoints used

Base: `{VITE_API_BASE_URL}`, slug: `nest` (backend-verified).

### `POST /api/v1/public/nest/leads` — seat / membership / contact forms

Request (JSON):

```json
{
  "name": "Aarav Sharma",
  "phone": "+919876543210",
  "email": null,
  "message": "…",
  "service_interest": "Seat Inquiry",
  "source_detail": "website:seat-inquiry-form",
  "preferred_time": "Evening",
  "consent_marketing": false,
  "landing_page": "https://…",
  "referrer": "https://…",
  "utm_source": "instagram",
  "utm_medium": "cpc",
  "utm_campaign": "…",
  "utm_term": "",
  "utm_content": "",
  "website_url": ""
}
```

Header: `Idempotency-Key: <uuid>` (fresh per submission — safe retries).
Success 201: `{success: true, status: "received", lead_id: "…", message: "…"}`.

### `POST /api/v1/public/nest/bookings` — book-visit forms

Same shape, plus `booking_type` (`visit` for seat/visit interest),
`title`, `requested_start_at` (local-midnight ISO), and
`preferred_time_label`. Success 201 returns `booking_id` with status
`received` — the visit is REQUESTED and staff confirm it.

### `GET /api/v1/public/nest/config`

Public flags (`lead_capture_enabled`, `booking_enabled`) for graceful
"paused" states.

## 5. Error handling (typed `BackendError.kind`)

| kind | UI copy direction |
|---|---|
| `validation` | "Please check the form…" (keep input) |
| `rate_limited` | "Too many requests… try again" (+ Retry-After) |
| `disabled` | "Online enquiries paused… call/WhatsApp" |
| `timeout` / `server` / `unreachable` | "Could not reach… try again or call/WhatsApp" |

Capture `backendRequestId` for support troubleshooting.

## 6. How to verify the lead reached the correct business

1. Submit the form, note the success message + request ID.
2. Log in to the **Nest** Staff Dashboard → Leads → search the phone.
3. Confirm `source_detail` shows the form source and the row is NEW.
4. Confirm the lead does NOT appear in the Prime dashboard (isolation).

Backend proof: `backend/tests/test_block3_nest_public.py` submits to
`/api/v1/public/nest/*` and asserts Nest-scope visibility + Prime-scope
invisibility.

## 7. What remains pending (explicit)

Actual Nest website wiring is **pending** because the Nest website
source was unavailable in the workspace — no site files were modified.
When the site repo is available, the remaining work is exactly §1–§3
above (copy 4 files, set 2 env vars, hook 2 submit handlers, add the
honeypot input), then §6 to verify. Nothing else is required; no
redesign, no backend changes.
