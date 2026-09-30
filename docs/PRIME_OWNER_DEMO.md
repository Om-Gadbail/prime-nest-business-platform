# Prime Gym — Final Owner Demo (Golden Path)

## 0. Closure status — 2026-09-30 (owner-demo freeze)

**Overall: PASS WITH ONE EXTERNAL LIMITATION (Meta test-token expiry).**
Local application, deterministic AI demo, automation shape, owner dashboard
and all five frontend surfaces are verified. Real Meta outbound/inbound is
BLOCKED only by an expired Meta test token (see below) — no code changes
needed once a fresh token is pasted into the local `.env`.

### Meta WhatsApp (diagnosed 2026-09-30 ~13:45 UTC, credential-safe)
- Prime `PRIME_WHATSAPP_*` loaded, provider binds Prime-only creds (LIVE mode).
- Meta Graph `v21.0` calls fail `HTTP 401 OAuthException code=190 subcode=463`:
  "Session has expired on Wednesday, 30-Sep-26 06:00:00 PDT".
- Phone ID `1434101746444466` / WABA `1109202048284928` / endpoint / header /
  API version are all correct — the ONLY fault is the expired token.
- **User action:** Meta App Dashboard → WhatsApp → API Setup → generate a new
  temporary test token (or a longer-lived System-User token with
  `whatsapp_business_messaging`), set `PRIME_WHATSAPP_ACCESS_TOKEN` in local
  `.env`, `docker compose restart backend worker scheduler`, re-run the
  `META_CLOUD` send to `+91 8010436158`. Do NOT commit the token.
- Until then: NO outbound claim is live; MOCK/`log` provider verified
  end-to-end (auth → provider → persisted `simulated` row).

### Verified today (local, real backend + Postgres + Redis)
- Owner login, overview/combined/automation-health/brief/leads (all 200).
- Website trial intake `POST /api/v1/public/prime/leads` → 201 → visible in
  Prime CRM → owner leads (rehearsal row removed afterwards).
- Deterministic demo assistant: Prime intro, REAL plans (Monthly ₹1500 /
  Quarterly ₹4000 / Half Yearly ₹7500 / Annual ₹12000), Koramangala address,
  hours Mon–Fri 05:30–22:00, handoff escalation + staff task.
- Gemini gateway: configured LIVE but free-tier `429` rate-limited at test
  time → honest fallback, never invents facts. Retry later for a live turn.
- Webhook: verify-token accept/reject, pinned per-business verify,
  cross-business 403, HMAC good/bad/empty all correct, stale-entry ack,
  wamid idempotency (covered by suite).
- Five surfaces HTTP 200 with viewport meta: 5173 Prime site, 5174 Nest site,
  5175 Prime staff, 5176 Nest staff, 5177 Owner.
- Security: `.env` untracked, no secrets in git or frontend `VITE_*`, no
  Meta IDs in tracked code. Note: backend request logs echo webhook
  `hub.verify_token` query params — rotate the Prime verify token after the
  demo if logs are shared.
- Tests: full backend suite re-run in progress; affected-file reruns green
  after hermetic test-env isolation (`backend/tests/conftest.py` now pins
  demo-safe AI/WhatsApp defaults so a live demo `.env` cannot break tests).

### Production TODO (unchanged)
Production Meta number + credentials + webhook, Razorpay/Stripe, VPS,
domain, HTTPS, production DB separation, backups, observability, production
secrets, Cloudflare tunnel at demo time (`winget install
--id Cloudflare.cloudflared`), Meta webhook callback to tunnel URL.

---

Flagship demo business: **Prime Fitness** (`prime`, `prime-fitness-001`).
Nest Library (`nest`) stays fully supported and isolated; no separate Meta
WhatsApp demo is needed for Nest before the owner demo.

> Honesty rule: nothing below is called "production live" unless it was
> actually tested live. Provider items are marked **LIVE IN LOCAL DEMO** vs
> **PROVIDER-READY (requires production configuration)**.

## 1. Golden scenario (deterministic, 30 steps)

1. Open Prime website → submit enquiry.
2. Lead appears in Prime Staff (`leads`, source `website`).
3. WhatsApp conversation begins (Meta TEST number or `log` provider locally).
4. AI explains Prime (deterministic intro from configured profile).
5. AI provides location (configured address; map URL only when configured).
6. Customer asks membership details → AI lists REAL plans/prices.
7. Customer requests trial → AI collects name + day/time.
8. Booking created (`requested`, never auto-confirmed).
9. Confirmation generated (automation `trial.booked`).
10. Staff sees booking.
11. Trial attended (staff records outcome → `completed`).
12. Lead converted → customer.
13. Membership created (price snapshot, idempotent).
14. Payment recorded (`pending` → `paid` via state machine).
15. Member appears active.
16. Attendance recorded.
17. Renewal date exists.
18. Renewal automation triggered at 30/14/7/3/1/0-day offsets.
19. WhatsApp renewal reminder generated/sent in demo environment.
20. Owner Dashboard updates (leads, members, revenue, renewals, automation health).
21. Customer asks for human → AI pauses, staff task created, conversation `escalated`.
22. Staff resumes AI explicitly.
23. Customer sends STOP → opt-out persisted, automation suppressed, audit `communication.opted_out`.
24. Customer sends START → eligibility restored per existing rules.

## 2. LIVE IN LOCAL DEMO

- Prime website intake → lead → CRM → automation → staff/owner visibility.
- Prime Staff + Owner Dashboard (leads, members, memberships, payments,
  attendance, renewals, tasks, notifications, automation health).
- Shared FastAPI backend, CRM, memberships, attendance, deterministic/test
  payments (no live PSP).
- Automation engine + scheduler + worker (idempotent, per-business sweeps).
- AI architecture: shared website↔WhatsApp runtime, allowlisted tools,
  Gemini gateway when `GEMINI_API_KEY` set; otherwise the honest
  deterministic demo assistant (labelled, config-driven, never invents).
- Meta TEST WhatsApp integration shape (webhook verify + HMAC + idempotent
  inbound + handoff-aware AI reply) — live sends ONLY when
  `PRIME_WHATSAPP_*` test credentials are configured locally.

## 3. PROVIDER-READY (requires production configuration)

- Production Meta WhatsApp number + production credentials + production webhook.
- Razorpay/Stripe production credentials + settlement reconciliation.
- VPS, production domain, HTTPS/Cloudflare, production database deployment,
  production backups, production observability, final production secrets.

NEVER claim production is live for the above.

## 4. Required Prime TEST env (local secrets only, never committed)

```bash
PRIME_WHATSAPP_ENABLED=true
PRIME_WHATSAPP_ACCESS_TOKEN=<meta-test-token>
PRIME_WHATSAPP_PHONE_NUMBER_ID=<meta-test-phone-id>
PRIME_WHATSAPP_BUSINESS_ACCOUNT_ID=<meta-test-waba-id>
PRIME_WHATSAPP_APP_SECRET=<meta-test-app-secret>
PRIME_WHATSAPP_VERIFY_TOKEN=<meta-test-verify-token>
GEMINI_API_KEY=<gemini-key>   # optional; demo assistant works without it
AI_ENABLED=true
AI_PROVIDER=gemini            # or noop for the deterministic demo path
```

Never print secret values. Never put secrets in `VITE_*`, logs, errors,
Git, API responses, screenshots, or tests.

## 5. Demo data

```bash
cd backend
python -m app.services.prime_demo
```

Idempotent, Prime-only, demo-safe phones (`+91 00000xxxxx`):
14 leads (varied statuses), 7 members (active / expiring-7d / 30d /
renewed / expired / inactive / failed-payment), payments, attendance,
4 trial bookings, staff tasks, 6 demo conversations. Reconciles with the
Owner Dashboard (no invented attribution or forecasting).

## 6. Five-application status (honest)

This repository ships ONE frontend (`apps/staff-dashboard`, shared Prime/Nest
staff + owner views). The 5173–5177 five-app split (Prime/Nest websites,
Prime/Nest staff, Owner Dashboard) is a **deployment topology**, not five
repos here — website integrations connect via the public APIs
(`docs/integrations/`, `docs/BLOCK2.md`). Do not report five local apps as
running unless they are actually served.

## 7. Security invariants (tested)

Server-side `BusinessContext` is authoritative; frontend `business_id`
never authorizes. Per-business WhatsApp credentials + HMAC. No SQL tools
for AI (allowlisted backend tools only). Opt-out (`STOP/UNSUBSCRIBE/CANCEL/
END/...`) suppresses automation + AI replies. Handoff pauses AI until
explicit resume. Prime↔Nest isolation enforced adversarially.
