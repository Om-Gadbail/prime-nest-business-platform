# Prime Website ↔ Backend Integration (Block 2)

The Prime Fitness website (`prime-fitness-website`, Vite + React) submits
its trial/booking forms to the shared FastAPI platform. This document is
the exact contract — it describes what was actually implemented and
verified, not a roadmap.

## 1. What was changed in the website

| File | Change |
|---|---|
| `src/lib/backend.ts` (new) | Centralized typed API client — the ONLY module that talks to the backend |
| `src/lib/attribution.ts` (new) | UTM / referrer / landing-page capture (browser-guarded, truncated) |
| `src/lib/leads.ts` | `saveLead` routes through the backend client when configured; keeps an honest local backup; new `kind` (`lead`\|`booking`), `email`, `honeypot` inputs; `viaBackend`/`backendRequestId` on results; corrected `LEAD_API_CONTRACT` paths |
| `src/components/forms/TrialForm.tsx` | Sends `kind: 'lead'` + honeypot; success copy reflects backend vs local path |
| `src/components/forms/BookingForm.tsx` | Sends `kind: 'booking'` + date + honeypot; honest "request received" copy |
| `.env.example` (new) | `VITE_API_BASE_URL`, `VITE_BUSINESS_SLUG` (public, non-secret) |

No routes, styling, SEO, analytics events, or responsive behavior were
changed. Trial popup, booking modal, contact page, and conversion pages
all flow through the same `saveLead` path, so every form is connected.

## 2. Configuration

```bash
cp .env.example .env
# Local backend:
VITE_API_BASE_URL=http://localhost:8000
VITE_BUSINESS_SLUG=prime
```

- Leave `VITE_API_BASE_URL` empty and the site runs exactly as before
  (local device backup only) — useful for static previews.
- Never put secrets in `VITE_*` variables (they ship to browsers).
  The website sends NO `business_id` (the slug in the path is
  backend-verified) and NO tokens.

Backend CORS must allow the site origin (`PUBLIC_SITE_ORIGINS` on the
backend includes `http://localhost:5173` for Vite dev by default).

## 3. Endpoints used

Base: `{VITE_API_BASE_URL}`, slug: `{VITE_BUSINESS_SLUG}` (`prime`).

### `POST /api/v1/public/prime/leads` — trial / enquiry forms

Request (JSON):

```json
{
  "name": "Aarav Sharma",
  "phone": "+919876543210",
  "email": null,
  "message": "…",
  "service_interest": "Trial / Enquiry",
  "source_detail": "website:trial-form",
  "preferred_time": "Evening (4:00 PM – 10:00 PM)",
  "consent_marketing": false,
  "landing_page": "https://…/trial",
  "referrer": "https://…",
  "utm_source": "instagram",
  "utm_medium": "cpc",
  "utm_campaign": "…",
  "utm_term": "",
  "utm_content": "",
  "website_url": ""
}
```

`website_url` is the honeypot (always `""` from real users).
Header: `Idempotency-Key: <uuid>` (fresh per submission — safe retries).

Success 201:

```json
{
  "success": true,
  "status": "received",
  "lead_id": "…",
  "message": "Your enquiry has been received. We will contact you shortly."
}
```

### `POST /api/v1/public/prime/bookings` — booking / visit forms

Same shape, plus:

```json
{
  "booking_type": "trial",
  "title": "Trial / Enquiry",
  "requested_start_at": "2026-10-03T00:00:00",
  "preferred_time_label": "Morning (5:30 AM – 10:00 AM)"
}
```

Interest mapping (`mapInterestToBookingType`): Free Visit→`visit`,
Trial/Enquiry→`trial`, Personal Training/Physiotherapy→
`consultation`, Gym Membership/Other→`enquiry`. Success 201 returns
`booking_id` with status `received` — the booking is REQUESTED and
staff confirm it. The UI says "Request received — we'll confirm",
never "Booking confirmed".

### `GET /api/v1/public/prime/config`

Public business flags (`lead_capture_enabled`, `booking_enabled`).
Exported as `getPublicConfig()`; the forms degrade via the 403 path
("Online enquiries are currently paused…") when disabled.

## 4. Client behavior (`src/lib/backend.ts`)

- `submitLead()` / `submitBooking()` / `getPublicConfig()` with a 12s
  timeout (`AbortController`), safe JSON parsing, and typed
  `BackendError` (`validation` / `rate_limited` / `disabled` /
  `server` / `timeout` / `unreachable`, with `status`, `requestId`,
  `retryAfterSeconds` where applicable).
- `saveLead()` maps backend failures to actionable copy:
  422 → "Please check the form…", 429 → "Too many requests… try again",
  403 → "paused… call/WhatsApp", timeout/5xx → "Could not reach… try
  again or contact on call/WhatsApp". The form keeps the input for
  retry (no silent loss) and always offers call/WhatsApp alternatives.
- Double-submit is prevented while a request is pending (existing form
  state machine) AND by the `Idempotency-Key` (backend dedups retries).
- The backend `X-Request-ID` is captured (`backendRequestId`) for
  support troubleshooting.

## 5. Form field mapping (actual site fields → backend)

TrialForm: name→`name`, phone→`phone`, goal+time+experience+preference
→ `message`/`service_interest` context, `preferredTime`→
`preferred_time`, source `website:trial-form`, kind `lead`.

BookingForm: name/phone as-is, interest→`service_interest` (+
`booking_type`/`title` mapping), preferredDate→`requested_start_at`
(local-midnight ISO; time-of-day stays a label — no fake slot
precision), preferredTime→`preferred_time_label`, message→`message`,
source `website:booking-form`, kind `booking`.

Fields the site does not collect (email, consent, some UTMs) are sent
null/empty — never invented.

## 6. Verification performed

- `npm run build` (tsc + vite) passes; `npm run lint` (oxlint) shows
  only the pre-existing Carousel warning; `npm test` 11/11 pass.
- Live end-to-end against the Block 2 backend (see final report):
  trial + booking submissions return 201 with honest copy, appear in
  staff APIs as NEW/REQUESTED, and duplicate `Idempotency-Key`
  submissions replay without duplicates.
- No secrets in the bundle (`VITE_API_BASE_URL`/`VITE_BUSINESS_SLUG`
  only; no tokens/keys in source or `dist`).

## 7. Known limits

- No offline queue: if the backend is unreachable the visitor sees an
  honest error with retry + call/WhatsApp options (a device-history
  backup is still written, but never presented as submission).
- No public config gating in the UI yet (forms rely on server 403);
  no staff dashboard in this block (staff verify via API/docs).
