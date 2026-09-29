# Production Reliability & Security (Prompt 8)

Canonical hardening stage. Architecture unchanged (FastAPI + Postgres + Redis +
worker + scheduler, co-located `platform_db/prime_db/nest_db` row-level isolation;
`BusinessContext` server-authoritative; JWT is identity only).

## 1. Architecture (current)

- `backend/app/main.py` — `/health` (no DB), `/ready` (DB + per-key + Redis),
  `BodySizeLimit + RequestID + SecurityHeaders` middleware, exact-origin CORS.
- `auth` — Argon2id, short access JWT (30m), opaque refresh (sha256 stored,
  rotation + family-kill on reuse), HttpOnly cookie, generic failures.
- `RBAC` — deny-by-default permission gates (`require_permission`), never
  role-name compares (except combined-owner capability).
- `BusinessContext` — every protected request resolves user → membership →
  business → permissions → database key. Client `business_id/slug/scope`
  is never trusted.
- `automation` — event → rules → actions → execution (`queued/running/
  completed/failed/skipped/cancelled`), 2-layer idempotency (request key +
  `(business, idem)` unique), bounded retries (max 5), opt-out → `skipped`.
- `worker/scheduler` — DB-polling sweep per business, Redis tick lease
  (`SET NX EX`), stale-`running` reclaim (30m), graceful shutdown.
- `communications` — opt-out authoritative, template render, provider dedupe.
- `whatsapp` — business-scoped creds, verify-token + HMAC per business,
  safe-ack (never 500), MOCK/LOG/LIVE truthful statuses.
- `gemini` — intelligence only (`gemini-3.6-flash` pinned, verified live in
  Prompt 7); sanitized context, validated output, never mutates state.
- `payments` — deterministic state machine, HMAC webhook, idempotent ops.

## 2. Security boundaries

| Boundary | Rule |
|---|---|
| Tenant | `apply_business_scope` on every repo query; forged IDs → 404/403 |
| Owner combined | `owner.combined.read` + OWNER/ADMIN + membership grant set only; audited |
| Auth | generic 401, per-IP + per-account throttle, rotation, family-kill |
| Public | slug-resolved server-side, honeypot, size guard, per-IP bucket |
| Webhooks | HMAC fail-closed in prod, size guard, replay (24h entry.time), dedupe |
| Gemini | sanitized input, validated output, no secrets in logs/prompts |
| Errors | `{error:{code,message}}` envelope, no stack/SQL/secret in prod, X-Request-ID |

## 3. Reliability boundaries

| Dependency | Failure mode |
|---|---|
| Redis down | rate limiter fails OPEN (availability), scheduler lease fails open (idempotency absorbs dupes); documented, never cross-tenant |
| DB down | `/ready` 503, requests 5xx-safe, worker/scheduler retry with backoff |
| Gemini down | fallback wording + `ai_used=false`, `ai.generation_failed` audit |
| WhatsApp down | execution retries bounded → `failed` → dead-letter; mock never claims delivery |
| Worker crash | `running>30m` reclaimed; `queued/retrying` drained on restart |

Redis keys: `ratelimit:*`, `scheduler:tick:*` — never tenant-PII; automation/
owner buckets include business slug/id where tenant-aware. `tenant_redis_key()`
helper reserved for future caches (no bare cross-tenant keys).

## 4. Prompt-8 changes

1. `middleware/security_headers.py` — nosniff, referrer-policy, DENY frames,
   minimal permissions-policy, HSTS on HTTPS only (local HTTP unaffected).
2. `core/config.py` — `AUTH_COOKIE_SAMESITE=none` requires `SECURE=true` in
   prod (fail fast); new tunable buckets: owner/webhook/automation + per-account
   login throttle.
3. `services/rate_limit.py` — `enforce_login_account` (sha256(email) bucket),
   `enforce_owner`, `enforce_webhook`, `enforce_automation` (per-business).
4. `api/auth.py` — login stacks per-IP + per-account buckets; no account
   oracle (uniform 401/429, no existence leak).
5. `api/owner.py` — `overview` + `combined` bounded (429 instead of overload).
6. `api/automation.py` — `GET /executions/dead-letter` (operator visibility:
   reason/counts/timestamps/scope/correlation) + `POST
   /executions/{id}/retry` (controlled NEW queued execution; re-checks
   opt-out/eligibility/provider at drain; fresh idem key; audited
   `automation.retry_queued`).
7. `services/automation.py` — `requeue_dead_letter()` safety contract
   (scope + terminal-only + budget + known-action + idempotent).
8. `repositories/blocks812.py` — `get_execution` (scoped), `list_dead_letter`.
9. `api/whatsapp.py` — webhook rate limit, oversized-body safe-ack,
   24h `entry.time` replay guard (stale entries acked without writes).
10. Tests — `tests/test_prompt8_security.py` (≈30 cases: auth/RBAC/isolation/
    public/automation/dead-letter/comms/whatsapp/gemini/payments/errors).
11. Docs — this file + `docs/backup-recovery.md`.

## 5. Verification

- New regression suite passes; full backend suite shows no Prompt-8
  regressions (see final report for exact counts).
- Ruff: only the 11 pre-existing legacy-test lint hits remain (documented,
  untouched per instructions); no new violations in `app/`.
- Docker config/build validation + health/readiness + frontend smoke in
  final report.

## 6. Known limitations (honest)

- Co-located single Postgres: row-level isolation only, no PG RLS; physical
  split is config-only (`*_DATABASE_URL`) + migration runbook.
- Refresh-token JSON copy retained for non-browser clients (documented risk;
  browsers should use HttpOnly cookie only).
- In-memory limiter without `REDIS_URL` is single-process only; prod needs
  Redis for shared throttling.
- WhatsApp LIVE not configured (MOCK truthful `simulated/not_delivered`).
- Razorpay/live payments not live (deterministic manual/test adapters only).
- No CAPTCHA on public forms (honeypot + rate limit only); no per-recipient
  WhatsApp throttle; no inbound STOP parser (opt-out via preferences API).
- Audit write failures are swallowed (best-effort) — forensic loss possible;
  no retention/purge policy enforced.

## 7. Production deployment checklist

- [ ] `APP_ENV=production`, strong `SECRET_KEY`/`JWT_SECRET_KEY` (boot fails fast otherwise)
- [ ] Real `DATABASE_URL` (+ optional split URLs), migrations applied, backups verified
- [ ] `REDIS_URL` set (shared limiter + scheduler lease)
- [ ] `BACKEND_CORS_ORIGINS` exact production domains (no `*`), `AUTH_COOKIE_SECURE=true`
- [ ] `GEMINI_API_KEY` only if AI enabled; `*_WHATSAPP_*` per business; `PAYMENT_WEBHOOK_SECRET` set
- [ ] Owner/staff seeded via invite flow (dev seeds never run in prod)
- [ ] `/ready` 200, dead-letter dashboard watched, audit retention configured
