# Prompt 5 — E2E Proof

## Golden workflows (`backend/tests/test_prompt5_workflows.py`, 6 tests)

| Test | Result |
|---|---|
| `test_prompt5_prime_golden_workflow` | PASS |
| `test_prompt5_nest_golden_workflow` | PASS |
| `test_prompt5_cross_tenant_denied` | PASS |
| `test_prompt5_payment_matrix` | PASS |
| `test_prompt5_attendance_entitlement_matrix` | PASS |
| `test_prompt5_seat_maintenance_denied_and_member_race_safe` | PASS |

Every step asserts real DB state through the HTTP surface (no mocks):
business_id scoping, audit rows, domain events, invoice numbering
(`INV-*`), single payment row on webhook replay, single pending renewal
row on repeat create, 409 matrices for FSM violations.

## Payment matrix (all PASS)

success → paid + entitlement sync; duplicate delivery → `duplicate:true`,
one row; wrong amount → 409 no mutation; wrong currency → 409; unknown
key → 404; bad signature → 401; paid→failed regression → 409; unconfigured
secret → 503.

## Renewal matrix (all PASS)

pending dedupe (repeat create returns same row); bogus status → 422;
pending→confirmed → 200; repeat confirmed → no-op 200; confirmed→pending
→ 409 terminal; renew creates new row + expires old.

## Seat matrix (all PASS)

available→allocated 201; same seat second member → 409; same member second
seat → 409 (existing suite); maintenance/blocked → 409; release → available;
renew preserves history; expired-membership linkage → 409.

## Attendance matrix (all PASS)

active → 201; same-day repeat → same row; expired → 409; explicit expired
linkage → 409; wrong tenant → 404.

## Nest browser verification (17/17 PASS)

`integrations/nest-website/verify/verify.mjs` + `verify-results.json`:
real Chromium, desktop (1280×800) + mobile (390×844), exact production
modules (`backend.ts`, `forms.ts`, `attribution.ts`) served via Vite.
Homepage, config fetch to `/api/v1/public/nest/config`, lead POST to
`/api/v1/public/nest/leads` with `Idempotency-Key`, never `/prime/`,
success + error states, honeypot `website_url` transmitted for backend
filtering. Note: Nest website source repo is absent from this machine —
verification is against the verified production drop-in package, NOT a
mock site. Live backend proof: `test_block3_nest_public.py` (real POSTs).

## Prime headless visibility (PASS)

`Reveal.tsx` fixed (visible first paint, Motion enhancement after mount,
headless/reduced-motion/no-IO static path, print CSS). Headless Chromium:
34/34 `[data-reveal]` sections computed opacity 1 without scrolling,
desktop + mobile, full-page screenshots in `docs/prime-shots/`.
`npm run lint` + `npm run build` pass in `prime-fitness-website`
(separate repo, committed there).

## Migration startup (PASS config-validated)

`backend/entrypoint.sh` (wait Postgres → `alembic upgrade head` → exec),
`migrate` compose service (single-replica, `service_completed_successfully`
gate for backend/worker/scheduler), linear alembic chain with single head
`0008`. `docker compose config` validates. No data destruction
(upgrade-only). Fresh-DB end-to-end `docker compose up` not run here
(Docker daemon unavailable in this environment) — documented in
`prompt-5-limitations-resolved.md`.

## Full backend suite

**341/341 passed, 0 failures** (JUnit XML evidence; baseline entering
Prompt 5 was 335 collected, Prompt 5 adds 6 workflow tests in
`test_prompt5_workflows.py`).
`ruff check app` → all checks passed; `ruff format --check app` → 166
files formatted. OpenAPI frozen-contract test updated for the 4 new
Prompt-5 paths (129 paths / 160 ops, was 125/156).
