# PRODUCTION ACCEPTANCE (factual, updated at cutover)

> Nothing below is claimed until it is measured. Fill each row with the real
> evidence command output at the production cutover.

| Criterion | Status | Evidence |
|---|---|---|
| Prime / Nest / Prime-staff / Nest-staff / Owner live | PENDING cutover | Pages URLs + smoke log |
| Worker tiny (KB bundle, dry-run recorded) | DONE (4.62 KiB / gzip 1.79 KiB, 2026-10-02) | `infra/cloudflare/worker`, `npm run deploy:dry` |
| Tunnel + Access live, port 8000 private | PENDING cutover | tunnel status + Access policy |
| VPS backend/Redis/worker/scheduler live | READY (compose exists) | `docker ps` + health-check |
| Neon connected, head `0008` | PENDING secrets | `alembic current` |
| Logins (owner/prime/nest) + isolation + combined owner | PENDING cutover | forwarding contract + E2E logs |
| Golden workflows Prime/Nest/Owner reconcile with DB | PENDING cutover | E2E transcripts |
| Security matrix (18 cases) all fail closed | PENDING cutover | matrix log |
| Failure/recovery (9 restarts, 502/504 shape) | PENDING cutover | recovery log |
| Performance p50/p95/p99 + Worker/origin/Neon latencies | PENDING cutover | measurements |
| Backend (53 files) + frontend + E2E + rollback pass | BACKEND GREEN 2026-10-02: 502 passed, 0 failed (4 chunks; 2 transient cwd-artifact failures re-run green from `backend/`) | chunk logs + CI |
| One-command deploy + rollback + docs | DONE in repo | `deploy/production/` |
| No secrets leaked; OSG untouched | VERIFIED (audit) | `git status` + ports `5433/6380` |

## Local verification already green (2026-10-02)

- `GET /health` → `status ok` (Docker, development env).
- Forwarding contract 20/20 + Worker unit tests 3/3 + typecheck clean (2026-10-02).
- Worker bundle 4.62 KiB / gzip 1.79 KiB (`deploy:dry`).
- Backend suite: 502 passed / 0 failed across 4 chunks (102 + 97 + 80 + 223;
  the 2 `TestMigration0008` failures in chunk 4 were a wrong-cwd invocation
  artifact from the repo root and pass from `backend/` where `alembic.ini` lives).
- 161 route decorators / 176 backend files / 53 backend test files inventoried.
- OSG isolation: Prime/Nest on `5433/6380`, OSG on `5432/6379`.

## Known limitations (honest)

- WhatsApp: mock-safe until Meta production credentials are provisioned.
- Payments: deterministic/test-safe until Razorpay live keys are provisioned.
- Custom domains: Pages URLs until client domains are bound.
- Python-Workers DB experiment superseded (inert files remain until cutover
  verification, then removed).
