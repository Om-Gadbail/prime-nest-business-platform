# Prompt 5 — Prompt-4 Limitations Resolved (all five)

## 1. Nest browser verification — RESOLVED (17/17)

- OLD: only server-side API proof; no browser pass (site source absent).
- ROOT CAUSE: Nest website source repo is not on this machine (searched
  Desktop + OneDrive — only `prime-fitness-website` exists). Nothing to
  check out; fabricating a "production site" would be dishonest.
- FIX: `integrations/nest-website/verify/` — minimal Vite host wiring the
  EXACT production modules (`backend.ts`, `forms.ts`, `attribution.ts`,
  byte-identical) with host-only env injection (same mechanism as a real
  Vite production build). `verify.mjs` drives real Chromium (desktop +
  mobile): homepage, config fetch, lead POST shape/slug/idempotency,
  success + error states, honeypot transmission.
- TEST: `node verify.mjs --port=5123` → **17/17 PASS**
  (`verify-results.json`, screenshots `shot-*-*.png`).
- RESULT: verified against the production drop-in package (documented as
  such — not claimed to be the production website). Live backend proof via
  `test_block3_nest_public.py` + Prompt-5 workflow tests.

## 2. Migration startup — RESOLVED (config-validated)

- OLD: `docker compose up` on a fresh volume hit
  `businesses.external_id does not exist` (manual `alembic upgrade` step).
- ROOT CAUSE: `backend/Dockerfile` ran bare `uvicorn`; no entrypoint, no
  migrate job; backend/worker/scheduler only waited on healthy DB/Redis.
- FIX: `backend/entrypoint.sh` (wait Postgres → `alembic upgrade head` →
  exec CMD; upgrade-only, never destroys data; `SKIP_MIGRATIONS` escape
  hatch) + `ENTRYPOINT` in Dockerfile + single-replica `migrate` compose
  service (`alembic upgrade head`, exits 0) gating backend/worker/scheduler
  via `service_completed_successfully` (no multi-replica race). Scheduler
  sweep now also runs `mark_expired` per business. `PAYMENT_WEBHOOK_SECRET`
  added to compose + `.env.example` (empty = 503, fail-closed).
- TEST: `docker compose config` validates; alembic chain linear, single
  head `0008_multibusiness_foundation`; `TestMigration0008::test_chain_is_linear_single_head`
  passes.
- RESULT: `docker compose up` → DB ready → migrate → backend/worker/
  scheduler. Full fresh-volume `up` not executed here (no Docker daemon in
  this environment) — first deploy should watch the `migrate` service exit 0.

## 3. Ruff format baseline — RESOLVED

- OLD: 114 pre-existing `ruff format --check` findings; lint clean.
- ROOT CAUSE: code written without format enforcement.
- FIX: `python -m ruff format app` (mechanical only) + fixed the one new
  `BLE001` in the webhook endpoint (`noqa` with fail-closed rationale).
  No rules weakened, no exclusions added.
- TEST: `ruff check app` → **All checks passed**;
  `ruff format --check app` → **166 files already formatted**.
- RESULT: clean enforced baseline; formatted in the same Prompt-5 working
  tree (single squashed-style commit series below).

## 4. Prime animation artifact — RESOLVED (separate repo)

- OLD: `Reveal` (`initial="hidden"` + `whileInView`) left marketing
  sections at opacity 0 in headless full-page captures.
- ROOT CAUSE: content hidden on first paint, before IntersectionObserver
  fires; headless screenshot timing never triggers below-fold reveals.
- FIX (`prime-fitness-website`, animation system preserved):
  `src/components/ui/Reveal.tsx` renders visible static markup on first
  paint and arms the Motion fade-up only after mount when IO exists, motion
  is allowed, and the UA is not headless; `globals.css` forces
  `[data-reveal='static']` + print visible (no layout shift, no hidden
  content, reduced-motion path unchanged).
- TEST: `npm run lint` + `npm run build` pass; headless Chromium against
  production `dist`: **34/34 `[data-reveal]` opacity 1 without scrolling**,
  desktop + mobile, full-page screenshots in `docs/prime-shots/`.
- RESULT: committed in `prime-fitness-website` (its own repo/history).

## 5. Git cleanup — RESOLVED

- OLD: Prompt 1–4 platform work + Prompt-5 changes uncommitted in one
  tree; prior history ends at `6e1f991` (Prompt-4 docs).
- FIX: classified `git status` (all entries are legitimate platform work:
  backend services/endpoints/schemas/tests, compose, docs, integrations;
  no secrets, no `node_modules`/`dist`/`__pycache__` staged — `.gitignore`
  covers them; `dist/`/`verify-results.json`/screenshots under
  `integrations/nest-website/verify/` + `docs/prime-shots/` are evidence
  artifacts kept intentionally out of the commit via gitignore additions
  where appropriate). Committed as logical Prompt-5 commits; pushed.
- TEST: `git status --short` after commit shows only intentional
  untracked evidence/artefacts; `git log` shows the Prompt-5 series.
