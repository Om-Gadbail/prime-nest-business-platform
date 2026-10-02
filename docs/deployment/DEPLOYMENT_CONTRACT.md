# DEPLOYMENT CONTRACT — Prime × Nest (permanent source of truth)

## 1. Topology

```text
LOCAL:  docker compose up  (db:5433, redis:6380, backend:8000, worker, scheduler, migrate)

STAGING / PRODUCTION:
  Cloudflare Pages (×5 frontends)
        ↓  VITE_API_BASE_URL = https://THE-FINAL-API-WORKER-DOMAIN
  Cloudflare Worker  (tiny TS forwarder, infra/cloudflare/worker)
        ↓  CF-Access-Service-Auth (CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET)
  Cloudflare Access (service auth protecting the origin)
        ↓
  Cloudflare Tunnel (cloudflared, VPS, named tunnel, restart-surviving)
        ↓  http://127.0.0.1:8000  (FastAPI listens privately; port 8000 NEVER public)
  VPS Docker Compose (deploy/production/docker-compose.production.yml)
    backend (existing sync FastAPI + SQLAlchemy + psycopg) ─┐
    worker ─┐                                                ├→ Neon PostgreSQL (pooled runtime)
    scheduler ─┤ → Redis (authoritative)                     │   (direct endpoint for migrations)
    migrate (one-shot alembic upgrade head) ─────────────────┘
```

## 2. Environments

| Env | Frontend | API | DB | Notes |
|---|---|---|---|---|
| local | `localhost:5173–5177` | `localhost:8000` | Docker Postgres `5433` | `docker compose up` |
| staging | `*.pages.dev` (+ staging Worker) | staging Worker domain | Neon staging branch | optional, same shape |
| production | `*.pages.dev` (custom domains later) | `https://THE-FINAL-API-WORKER-DOMAIN` | Neon `production` branch @ `0008` | cutover target |

## 3. Domains (current → future)

- Current: the five `*.pages.dev` URLs (see CURRENT_STATE.md).
- API: single shared Worker domain for all five frontends (never per-business backends).
- Future: `www.<business>` + shared `api.<platform>`; businesses are tenants,
  not backend deployments (see `docs/architecture/MULTI_BUSINESS_PROVISIONING.md`).

## 4. Secrets (never in Git; CONFIGURED / MISSING only)

| Secret | Lives in | Required in prod |
|---|---|---|
| Neon pooled `DATABASE_URL` | VPS env file (0600) + encrypted backup | yes |
| Neon direct URL (migrations) | VPS env file | yes |
| `SECRET_KEY` / `JWT_SECRET_KEY` | VPS env file | yes |
| `UPSTREAM_BACKEND_URL` | Worker secret | yes |
| `CF_ACCESS_CLIENT_ID/SECRET` | Worker secret | yes |
| Gemini key | VPS env (optional, `AI_ENABLED=false` until set) | no |
| WhatsApp tokens | VPS env (mock-safe until Meta grants) | no |
| Razorpay secrets | VPS env (test-safe until live keys) | no |
| Cloudflare API token | GitHub encrypted secret (Workers deploy only) | yes |

WhatsApp stays **mock/safe** and payments stay **deterministic/test-safe**
until real production credentials are provisioned — the code paths already
degrade honestly (no fake sends, no fake charges).

## 5. Health / readiness

- `GET /health` → liveness, no DB touch. Compose `healthcheck`, Tunnel checks,
  deploy scripts gate on it.
- `GET /ready` → 200 only when DB + Redis probes pass; else 503. A deploy is
  NOT successful unless `/ready` is 200.
- Both return `x-request-id`; logs are structured; never log tokens/cookies/
  bodies/secrets/passwords/API keys.

## 6. Migration process

- System of record: `backend/migrations/versions/` (head `0008`).
- Local: one-shot `migrate` service (`alembic upgrade head`) before backend boot.
- Production: same, via `deploy/production/docker-compose.production.yml`
  (`migrate` service, single replica, upgrade-only, never destroys data).
- Verify head after every deploy: `alembic current` must print `0008`.

## 7. Deployment order (binding)

0. Audit → 1. forwarding contract → 2. Worker → 3. VPS backend → 4. Neon →
5. Redis/worker/scheduler → 6. Tunnel → 7. Access → 8. Worker→Tunnel→VPS →
9. migrations → 10. identities/data → 11. CORS/auth → 12. five frontends →
13. Prime E2E → 14. Nest E2E → 15. Owner E2E → 16. security matrix →
17. failure/recovery → 18. performance → 19. CI/CD → 20. rollback →
21. docs → 22. owner demo → 23. acceptance. Never skip a dependency.

## 8. Smoke tests (post-deploy gate)

`deploy/production/smoke-test.{sh,ps1}` hits, through the public Worker domain:
`/health`, `/ready`, public lead/enquiry (201 + idempotent replay),
auth rejection (401), CORS preflight from each Pages origin, and owner/prime/
nest login shape. Any failure → non-zero exit → deploy marked FAILED.

## 9. Rollback

- Worker: `wrangler rollback` / redeploy previous version (versions kept by
  Cloudflare; `rollback.{sh,ps1}` wraps it).
- Backend: re-tag previous image + `docker compose up -d` + `alembic` does NOT
  downgrade automatically (downgrades are manual, documented in recovery.md).
- DB: Neon point-in-time restore (see BACKUP_AND_RECOVERY.md). Never lose data.

## 10. Ownership / disaster recovery

- Code + `deploy/` + `infra/` + `docs/` in Git are sufficient to rebuild the
  VPS from scratch. No undocumented dashboard settings may be load-bearing.
- Encrypted env backup lives OFF Git (procedure in backup-notes.md).
- Each client owns their own domain/Cloudflare/Meta/payment/analytics assets;
  OSG operates them only with authorization (CLIENT-OWNED ACCOUNTS rule).
