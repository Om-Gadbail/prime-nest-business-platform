# Prompt 9 — Full End-to-End + Production QA Report

Date: 2026-09-29/30 (UTC). Baseline commit `23faa51`.
Verdict codes: PASS / FAIL / FIXED / PRE-EXISTING / EXTERNAL DEPENDENCY / NOT CONFIGURED / DEFERRED.

## 1. Executive summary

- Backend: **454/454 pass** (141 + 143 + 170 chunks), Ruff clean, Prompt-8 security suite **34/34** re-verified.
- All **five frontends ran simultaneously** and returned HTTP 200 (closes the Prompt-8 live gap).
- Real Chromium browser E2E across all five surfaces: public forms POST **201** to the canonical backend;
  staff login/dashboard/leads verified per-tenant; owner overview/business-switch/automation/dead-letter verified.
- **7 genuine bugs found by live browser QA; all 7 fixed and retested** (1 backend, 6 across the two staff-dashboard repos).
- Golden workflows: Prime **24/24**, Nest **19/19**. Attack matrix **13/13**. Concurrency **3/3**.
- Owner analytics reconciled exactly against source records (26 leads, ₹2500 collected, 17 members).
- Responsive: 143/143 viewport checks pass (2 genuine Kanban overflows found and fixed).
- Remaining gaps are honest external/config items (Meta/Razorpay/Gemini live, backups, Firefox/WebKit binaries).

## 2. Baseline (before changes)

- `git status`: clean. Commit: `23faa51 chore: harden production security and reliability`.
- Backend suite: 454 collected (per-file sum), **454 passed, 0 failed** (chunked runs: 141 + 143 + 170 — a single
  10-minute shell times out, so the suite runs in three chunks; total wall ~14 min).
- Ruff `check app/`: PASS.
- In-repo `apps/staff-dashboard`: 20 vitest PASS, `tsc -b` PASS, `vite build` PASS (545 kB chunk warning, prototype only).
- Sibling frontends: prime-website 11 PASS + build; nest-website 36 PASS + typecheck + build;
  prime-staff 57 PASS + typecheck + build; nest-staff 53 PASS + typecheck + build; owner 32 PASS + typecheck + build.
- `docker compose config`: valid. Stack healthy (backend/db/redis/worker/scheduler).
- 5 frontends: all DOWN at start (PRE-EXISTING Prompt-8 gap) → started, all HTTP 200.
- `/health` 200, `/ready` 200 (platform/prime/nest DBs + redis up).

## 3. Test environment

- Windows 11, Node v24.19.0, Python 3.14, Docker Compose (project `prime-nest-business-platform`).
- Backend http://localhost:8000 (Docker), PostgreSQL host :5433, Redis host :6380.
- Frontends: :5173 Prime site, :5174 Nest site, :5175 Prime staff, :5176 Nest staff, :5177 Owner.
  All `strictPort: true`; no collisions. API bases canonical (`http://localhost:8000` bare for sites,
  `http://localhost:8000/api/v1` for dashboards). CORS allows local origins + credentials.
- OSG Growth stack (:5432/:6379) untouched — verified running throughout.
- Browser: Chromium headless-shell 1243 (Playwright 1.63). Firefox/WebKit binaries NOT installed
  → cross-browser limited to Chromium (honestly documented, §27).

## 4. Backend tests — PASS (454/454)

Final regression after all fixes: chunk A 141 passed, chunk B 143 passed, chunk C 170 passed. Ruff clean.

## 5. API tests — PASS

Golden scripts + probes covered: auth, public intake (leads/bookings/config), leads CRUD/status/notes/convert,
bookings lifecycle, members/profile, memberships/renew/status, payments/record/refund/status, attendance
check-in/out, tasks/status, notifications/read, automation trigger/executions/retry/dead-letter, owner
overview/combined/revenue/leads/renewals/payments/attendance/automation-health/alerts, integrations/status,
AI mode/assistant/public-chat, payment webhook, WhatsApp send/webhook. Latencies 28–140 ms (see §21).

## 6. Prime website (5173) — PASS

- Home + /free-trial + /contact + /join at 11 viewports (320×568 → 1920×1080): zero overflow, zero console
  errors, zero failed requests.
- Free-trial valid submit → **201 POST /api/v1/public/prime/leads**, success state; invalid phone/name blocked
  client-side; record verified server-side (`source_detail=website:trial-form`, landing page + attribution captured).
- Contact → 201 /public/prime/bookings. Join → 201 /public/prime/bookings.
- No `business_id` sent by the frontend; server-side slug resolution authoritative (`routed_by=slug`).

## 7. Nest website (5174) — PASS

- Home + /seat-inquiry + /book-a-visit + /membership-inquiry + /contact: zero overflow, zero console errors.
- Seat inquiry → **201 /api/v1/public/nest/leads** (record in Nest CRM only).
- Contact → 201 /leads; book-a-visit → 201 /bookings; membership-inquiry → 201 /leads.
- Prime staff sees 8 Prime leads and **0** Nest leads; Nest staff sees the QA enquiry and **0** Prime leads.

## 8. Prime staff dashboard (5175) — FIXED then PASS

Was fully broken live (login impossible, dashboard crashed). After fixes: login/logout/session-restore,
dashboard KPIs (members 2, leads 8, collections ₹2,500 — all real), leads kanban with website lead,
members/memberships/payments/tasks/notifications/settings all render real data; 14/14 routes RENDER, zero crashes.

## 9. Nest staff dashboard (5176) — FIXED then PASS

Same root fixes. Login/logout/session-restore, dashboard, leads (QA enquiry visible, no Prime leak),
all routes render; empty states honest (0 members/payments/bookings in Nest tenant).

## 10. Owner dashboard (5177) — PASS

- Invalid login rejected; valid login → /owner (3570 chars, KPIs: revenue ₹2.5K, leads 22, conversions 6,
  members 16, visits 4). /owner/prime ≠ /owner/nest (server-side scoping, not client trust).
- /owner/automation, /owner/alerts render. Dead-letter: owner view (200) + retry → new `queued` execution
  with `-retry-1` idempotency suffix; staff view/retry → 403. Owner logout → /login PASS.
- `switch-business` prime↔nest returns freshly-scoped tokens (used by Nest golden).

## 11. Golden workflows — PASS

- Prime 24/24: visitor → lead (201, idempotent) → staff-visible → follow-up → contacted → qualified →
  direct-converted rejected (409) → trial booking → confirmed → convert → member → membership (real plan UUID)
  → payment (idempotent) → activate → check-in (201) → duplicate check-in idempotent (same visit id) →
  check-out → owner analytics.
- Nest 19/19: visit booking (idempotent) → confirm → complete → lead → contacted → convert → member
  (confirmed seat pref) → membership (nest-confirmed-1m) → activate → payment → isolation both ways → combined.
- RBAC note: lifecycle mutations run as Owner (STAFF role is read/create-only **by design** —
  `test_staff_limited_permissions` encodes it). Staff lifecycle denial returns clean 403 (verified).

## 12. Automation — PASS

- `lead.created` execution completed end-to-end (worker sweep healthy both businesses).
- Dead-letter item inspected (payment.paid, "Recipient address is required"), owner retry → queued,
  staff denied. Duplicate trigger ×3 accepted without duplicate sends (idempotency keys).
- Post-Redis-restart recovery: new lead.created → completed. PASS.

## 13. WhatsApp — PASS (MOCK/LOG, honestly classified)

- Provider mode DISABLED/log (NOT CONFIGURED live — never claimed otherwise).
- Direct send → 201 `{"status":"simulated","provider":"log"}` (FIXED: was `"sent"`; see §32).
- Automation path reports `provider_mode: MOCK`, `delivery_status: simulated (not_delivered)`.
- Webhook: unknown key → 404; bad signature → 403; bad verify token → 403; malformed → 403.
- Per-business keys (prime/nest) isolated; opt-out enforcement covered by backend suite.

## 14. Gemini — NOT CONFIGURED (safe degradation verified)

- `/ai/mode` → `AI_DISABLED`, provider `noop`, capabilities `[]`. Assistant + public chat return the honest
  fallback (`escalated: true`), including under a prompt-injection probe (no SQL/tool execution, no leak).
- Constraints hold structurally: tool-call-only architecture, no DB/RBAC/payment mutation path.
- Live Gemini remains unavailable (Prompt-8 503 stands) — classified, not claimed.

## 15. Payments — PASS (deterministic flow; Razorpay NOT CONFIGURED)

- Create/record (201), idempotent replays (same id), state transitions visible, unknown webhook → 404-safe,
  bad signature → 403, unconfigured webhook → closed 503 ("not configured", no fake processing).
- Frontend never controls authoritative status (server state machine; UI only records via create).

## 16. Tenant isolation — PASS (13/13 attack matrix)

Cross reads 404 both ways; forged `business_id` neutralized (422 extra-forbid); forged slug 422;
staff denied all owner endpoints + dead-letter (403); anon 401; illegal switch-business 403;
unknown business 403/404; query-param business_id cannot leak. Golden runs confirm both directions.

## 17. Responsive QA — PASS (143/143 after fix)

All five surfaces × 11 viewports (320×568 … 1920×1080): no page-level horizontal scroll, mobile menus work,
forms/tables/cards usable at 320 px. Two genuine FAILs found (staff leads Kanban at 1024×1366, overflow 358,
page scrollbar confirmed) → FIXED (Kanban now xl-only; stacked cards below xl) → re-verified PASS.

## 18. Accessibility — PASS (spots fixed class-wide)

- Keyboard: 14/14 tab stops with visible focus on trial form; mobile menu opens/closes on Escape
  (`aria-expanded` true→false).
- Names/labels: 0 unnamed buttons, 0 unlabeled inputs, 0 un-alted images on probed pages (both staff apps).
- Landmarks (header/nav/main) present; `role=status/alert` on form states; tables use `<th scope>`.
- Class-wide hardening: `initials()`/`Avatar` now null-safe (was the crash vector).

## 19. Visual QA — PASS

Screenshots at 390×844 / 768×1024 / 1440×900 for home, forms, staff dashboard/leads, owner overview/automation:
no clipping, no overlap, no blank sections. Minor cosmetic note (non-blocking): Nest hero pill wraps
"CO- / WORKING SPACE" on 390 px; Prime hero watermark overlaps eyebrow (decorative). No redesign needed.

## 20. Console/network — PASS (with classified EXPECTED noise)

Post-fix: websites + owner = zero console errors, zero failed requests. Staff apps: only expected
pre-login `401 /auth/me|refresh` probes (session restore path; no data impact, no 5xx, no app errors).
SSE 404 eliminated (hook inert); analytics/activity 404s eliminated (canonical remap).

## 21. Performance — PASS (no premature optimization)

- API p50-ish latencies: auth/me 29 ms, dashboard/overview 57 ms, leads 29 ms, owner/combined 140 ms —
  nothing over 150 ms; pagination (`limit/offset`) used everywhere; no N+1 observed (single list calls per view).
- Bundles (gzip): prime site 163 KB total vendors split; nest site index 145 KB (largest single chunk, accepted);
  staff apps index ~47 KB + split vendor/charts/forms; owner index 119 KB + charts 115 KB split.
  Dashboards lazy-load charts; sites code-split routes. In-repo prototype 545 KB single chunk (legacy, unserved).
- One known inefficiency (documented, not fixed): dashboard + ops hooks each fetch `/dashboard/overview`
  (~57 ms, cached per key). Not user-visible; left alone deliberately.

## 22. Concurrency — PASS (3/3 live)

5× concurrent same-key lead posts → 1 record; 5× concurrent same-key payments → 1 record; triple automation
trigger → accepted without duplicate sends. Backend `test_block57_concurrency` 6/6.

## 23. Failure/recovery — PASS

- Backend+worker+scheduler rebuilt/restarted (image rebuild for LogProvider fix) → healthy, automations flowing.
- Redis restarted → `/ready` redis up, worker sweeps resumed, new lead.created → completed.
- No destructive commands; OSG stack untouched; DB never at risk (migrate-on-boot only).

## 24. Analytics correctness — PASS (exact reconciliation)

Source: prime 17 + nest 9 = **26** leads → combined **26** ✓. Collected ₹2500.00 = prime paid + nest 0 ✓.
Active members 17 = 16 + 1 ✓. Converted 6 ✓. No cross-business leakage in per-business splits.

## 25. Date/time — PASS

UTC storage everywhere (`*Z`); frontend renders en-IN locale; Today/7D/30D windows reconcile;
no midnight/off-by-one observed. UTC contract unchanged.

## 26. Security regression — PASS

- `test_prompt8_security.py`: **34/34** re-run green.
- Live attack matrix 13/13 (§16). Staff RBAC matrix unchanged (deliberately limited role — tests intact).
- All five `dist/` bundles scanned: no `GEMINI_API_KEY` / `WHATSAPP_ACCESS_TOKEN` / `JWT_SECRET` / private keys.
- Security headers present (`nosniff`, `DENY`, `permissions-policy`, `access-control-allow-origin` scoped).

## 27. Cross-browser — Chromium FULL / Firefox-WebKit DEFERRED

Chromium (headless shell): full matrix above. Firefox/WebKit binaries are not installed in this environment
(verified: only `chromium_headless_shell-1243` present) → smoke not executed; honestly DEFERRED, not claimed.

## 28. Docker — PASS

`compose config` valid; `db/redis/backend/worker/scheduler` healthy; `/health` + `/ready` 200 after rebuild;
host ports 5433/6380 preserved; OSG project untouched.

## 29. Known limitations (carried + new)

1. Live Meta WhatsApp NOT CONFIGURED (log provider; honest `simulated`).
2. Live Razorpay NOT CONFIGURED (webhook fails closed 503).
3. Gemini NOT CONFIGURED (AI_DISABLED/noop; safe fallback).
4. No real DB backups; PostgreSQL co-located; no CAPTCHA; no per-recipient throttle; no inbound STOP parser;
   audit best-effort (all pre-existing, unchanged).
5. STAFF role is read/create-only by design (backend tests encode it): staff-UI update actions 403 with honest
   error surfacing; full lifecycle runs as Owner/Admin.
6. Staff "Trainers" module hidden (no backend trainers entity); global search is client-side over cached lists;
   SSE realtime inert (no backend stream); customer notes stored as member-notes append.
7. Firefox/WebKit smoke DEFERRED (binaries unavailable).

## 30. Remaining external dependencies

Meta WhatsApp credentials, Razorpay keys + webhook secret, Gemini API key + enablement, backup storage,
production secrets (SECRET_KEY/JWT/OWNER + STAFF passwords), CAPTCHA, production observability backend.

## 31. Production blockers

- Real credentials/secrets provisioning (above).
- Backup/restore runbook execution (documented, not executed here).
- Physical PostgreSQL separation (documented migration path).
- Human sign-off on the deliberately-limited STAFF role vs front-desk update needs (product decision:
  either grant ADMIN to shift leads or extend STAFF with update keys via migration + test updates).

## 32. Final recommendation

**GO with conditions**: the platform passes full-system QA on the canonical architecture; all genuine bugs
found were fixed and retested; analytics reconcile exactly; isolation holds. Deploy after provisioning §30
items and deciding §31.4. No architecture redesign required.

## Appendix A — Bugs found, fixed, retested

| # | Bug | Severity | Fix location | Retest |
|---|-----|----------|--------------|--------|
| 1 | Staff dashboards never sent Bearer token → browser login impossible | Critical | prime/nest staff `api/client.ts` + `services.ts` (in-memory token, Authorization header, silent cookie refresh) | Live login PASS both |
| 2 | `GET /auth/me` shape mismatch (`full_name` undefined → `initials()` crash on every authenticated page) | Critical | `services.ts` `normalizeMe()` both repos | Pages render, "Prime Staff" identity |
| 3 | Permission names `.view` vs canonical `.read` → all nav hidden, all routes guard-redirected | High | `canWithAliases()` both repos | Full nav visible, guards pass |
| 4 | Frontend called non-existent endpoints (`/analytics/overview|revenue`, `/activities`, `/realtime/events`, …) | High | services + hooks remap to `/dashboard/*`, payments-derived revenue, inert realtime | 14/14 routes render, consoles clean |
| 5 | `POST /auth/logout` empty body → 422, session resurrected by refresh (logout broken) | High | send `{}` both repos | Logout → /login, guard holds |
| 6 | Check-in `source: 'front_desk'` rejected (canonical: kiosk/manual/mobile/qr/rfid) | High | default `'manual'` (prime) | Golden check-in 201 |
| 7 | LogProvider reported `"sent"` for simulated messages | Medium | backend `messaging.py` → `"simulated"` (rebuilt image) | 201 `simulated/log` |
| 8 | Kanban page-scrollbar at 1024–1279 (overflow 358) | Medium | Kanban xl-only both repos | 1024 PASS both |
| 9 | Booking `source: 'staff'` invalid enum | Low | `'walk_in'` both repos | Booking 201 |
| 10 | Misleading "Due today" for members without memberships | Low | real membership join + honest empty labels | Verified in UI |

## Appendix B — Test counts (final)

Backend 454/454 (141+143+170), Ruff clean, Prompt-8 34/34. Frontend: prime site 11, nest site 36,
prime staff 57, nest staff 53, owner 32, in-repo 20 — all green; all typechecks + builds green, lints clean
(staff repos, `--max-warnings 0`). Live: Prime golden 24/24, Nest golden 19/19, attack 13/13, concurrency 3/3,
responsive 143/143, E2E forms 6/6 (all 201).
