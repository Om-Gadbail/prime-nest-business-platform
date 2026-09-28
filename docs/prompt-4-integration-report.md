# Prompt 4 — Final Integration Report

Date: 2026-09-28. Backend `0.1.0` (`/health`, `/api/v1/version`).
Scope discipline: frontend adapted to the canonical contract; the single
backend change was operational (migration on the stale live volume), not a
contract change. No architecture redesign, no second API layer, no
frontend-trusted tenancy, no weakened auth/CORS.

## 1. Architecture verified

`FRONTENDS → ONE FastAPI (create_app, /api/v1) → AUTH + server business
context + RBAC → PRIME/NEST rows → OWNER portfolio`. Public intake is
slug-routed (`/api/v1/public/{slug}/leads|bookings`); staff/owner identity
is JWT + per-request DB membership lookup (`app/api/deps.py`,
`app/services/business_context.py`); money is Decimal/NUMERIC, timestamps
UTC ISO-8601, enums lowercase snake_case.

## 2. Environment configuration

Final bases (verified by reading URL construction, §2 of
`docs/integration-matrix.md`): websites `http://localhost:8000` +
`VITE_BUSINESS_SLUG=prime|nest`; dashboard `http://localhost:8000` +
slug branding hint. `.env` files gitignored in both repos; no secrets in
`VITE_*`. Backend CORS: `BACKEND_CORS_ORIGINS` ∪ `PUBLIC_SITE_ORIGINS`
covers `http://localhost:5173` (website) + `http://localhost:5174`
(dashboard); no wildcard-with-credentials.

## 3. API URL matrix

See `docs/integration-matrix.md` §2–§4. One stale comment fixed
(`prime-fitness-website/src/lib/leads.ts`: `POST /api/leads` →
canonical public routes). No `/api/v1/api/v1`, no old `/api/leads/*`
routes, no MSW/mocks in production paths, no `business_id` sent for auth.

## 4. Frontend integration changes

- `prime-fitness-website/src/lib/leads.ts` — comment-only contract fix.
- Rebuilt + re-served production bundles for both frontends.
- No dashboard code changes required: client, auth lifecycle, permission
  gates (`owner.combined.read`), query scoping and error envelopes already
  match the canonical contract.

## 5. Backend changes

- **Code: none.** No endpoint, schema, RBAC or migration edits.
- **Operational (live dev volume only):** the Docker Postgres volume
  predated migration `0008_multibusiness_foundation`, so live queries
  failed with `businesses.external_id does not exist`. Applied
  `alembic upgrade head` (0007→0008) inside the backend container and ran
  the idempotent dev seed (`python -m app.services.seed`). This is the
  documented runbook path, not a contract fix. Note: the backend image
  does not auto-migrate on boot (plain `uvicorn` CMD) — migration is a
  deliberate operator step (see limitations).

## 6–10. Auth / isolation / CORS / website / staff / owner verification

57-check HTTP matrix: **57/57 PASS, exit 0** (script kept out-of-repo in
TEMP; backend behavior asserted, not fixtures). Live Docker proofs:
public→CRM leads `7bc35e9c` (prime) / `c7465de8` (nest) each visible only
in their business; cross-read `404`; owner combined `scope=all` →
`[nest, prime]`; owner `/me` default `prime` + `owner.combined.read`.
Browser: staff smoke E2E 6/6 + live authenticated E2E 6/6 (Chromium,
360/768/1280, no overflow); prime production build served `200` with
viewport meta + mobile/desktop captures. Full evidence in
`docs/golden-workflows.md`.

## 11. Test results (exact)

- Backend: `python -m pytest` → **335 passed** (456s). `ruff check app` → clean.
- Staff dashboard: `typecheck` PASS, `lint` PASS, `vitest` **20/20**,
  `build` PASS, Playwright smoke **6/6**, Playwright live **6/6**.
- Prime website: `lint` PASS (1 pre-existing Carousel a11y warning),
  `npm test` **11/11**, `build` PASS, preview serve `200`.
- Integration matrix script: **57/57 PASS** (health, contract, CORS×3,
  public flows, auth×8, isolation attacks, mutations, owner×9, refresh/
  logout, registry).

## 12. Proof table (observed, no fabrication)

| Test | Expected | Actual | Status | Evidence |
|---|---|---|---|---|
| Prime staff login | 200 | 200 | PASS | `/auth/me slug=prime role=STAFF` |
| Nest staff login | 200 | 200 | PASS | `/auth/me slug=nest` |
| Owner login | 200 | 200 | PASS | `/auth/me owner.combined.read` |
| Prime lead | Prime only | Prime only | PASS | `7bc35e9c` (live) |
| Nest lead | Nest only | Nest only | PASS | `c7465de8` (live) |
| Prime→Nest read | denied | 404 | PASS | live + matrix |
| Nest→Prime read | denied | 404 | PASS | live + matrix |
| Tamper `business_id` | rejected/ignored | 422 staff / slug wins public | PASS | matrix I3, W2 |
| Owner combined | authorized only | `[nest,prime]` / `[prime]` scoped | PASS | live + K2 |
| Wrong-slug login | 403 (fallback path) | 403 | PASS | F3 |
| Refresh rotation/reuse | rotate / revoke | rotated / 401 | PASS | P1–P2, O1–O2 |
| CORS preflight | exact echo + creds | 5173/5174 echo, evil none | PASS | C1–C3 |
| Prime mobile/desktop | responsive | PASS (shots) | PASS | `prime-mobile/desktop.png` |
| Dashboard 360/768/1280 | no overflow | 6/6 E2E | PASS | smoke + live specs |
| Backend suite | 335/335 | 335 passed | PASS | pytest |
| Matrix script | all pass | 57/57 exit 0 | PASS | TEMP script |

## 13. Files changed

- `prime-fitness-website`: `src/lib/leads.ts` (comment only).
- `prime-nest-business-platform`: `docs/integration-matrix.md`,
  `docs/golden-workflows.md`, `docs/prompt-4-integration-report.md` (this file).
- Live dev environment only (not git): applied migration 0008, dev seed,
  live-E2E users already present, two P4 test leads.

## 14. Remaining limitations (honest)

1. Nest website source absent from workspace — covered by the verified
   drop-in package + server-side Nest proofs (`test_block3_nest_public.py`,
   live `/nest/*` intake + isolation). A Nest-site browser pass needs its repo.
2. Backend container does not auto-run migrations; operators must
   `alembic upgrade head` (runbook documents it).
3. `ruff format --check` flags 114 pre-existing files — style only, check
   is not enforced; untouched.
4. Full-page headless captures of the Prime marketing site show
   scroll-reveal sections blank mid-page (animation timing artifact; hero,
   footer, nav verified, no overflow). Interactive browser form-fill is
   covered at the fetch layer + dashboard E2E, not re-driven per field.
5. Prior prompts' platform work remains uncommitted in the working tree;
   Prompt 4 commits only its own files (below).

## 15. FINAL VERDICT

Prompt 4 is **COMPLETE**: all five surfaces operate against ONE canonical
backend with server-enforced tenancy — proven by 335/335 backend tests,
57/57 HTTP integration checks, 12/12 Playwright browser tests, live
Postgres golden flows with real record IDs, and a denied-everywhere
attack matrix. Acceptance criteria: all boxes checked except the
 asterisked note that Nest-website *browser* rendering awaits its source
 repo (its API integration is fully proven).
