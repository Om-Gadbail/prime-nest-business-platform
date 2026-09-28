# Production Readiness (DO NOT DEPLOY per mission rule)

Staging/production cutover checklist for the full local platform. Nothing below has been
deployed; this is the gate before any authorized deploy.

## 1. Config gates (fail fast / fail closed)

- `APP_ENV=production` disables `/docs`, rejects weak `SECRET_KEY` (without strong `JWT_SECRET_KEY`).
- WhatsApp webhooks fail closed without `WHATSAPP_APP_SECRET`; GET verify never echoes unconfigured in prod.
- `DATABASE_URL` (managed Postgres) + `REDIS_URL` (managed Redis) required; exact
  `BACKEND_CORS_ORIGINS` + `PUBLIC_SITE_ORIGINS` (no wildcards); `AUTH_COOKIE_SECURE=true` on https.
- AI: `AI_PROVIDER=gemini` + real `GEMINI_API_KEY`, or `AI_ENABLED=false` for honest fallback.
- WhatsApp: real `WHATSAPP_*` + `WHATSAPP_PHONE_NUMBER_MAP` (or operational per-business numbers),
  or `WHATSAPP_ENABLED=false` for auditable log fallback.

## 2. Infrastructure

- Compose services `db`, `redis`, `backend`, `worker`, `scheduler` all healthy with healthchecks;
  backend waits on `db`+`redis`; worker/scheduler wait on `backend`.
- Scheduler lease (`SCHEDULER_LEASE_SECONDS`) prevents duplicate ticks across replicas;
  every job idempotent (execution/provider-id dedupe) so replays are no-ops.
- Graceful SIGTERM handling in worker/scheduler; structured logs; per-business commit isolation
  (one business failure never blocks others); no cross-business job execution.

## 3. Verification required before any deploy

- `alembic upgrade head` clean + `upgrade → downgrade → upgrade` round-trip on a Postgres copy.
- Backend: `pytest` green (incl. isolation/RBAC/concurrency/migration checks); frontend:
  `typecheck`, `lint`, `vitest`, `vite build`; Docker: `compose build` + `compose up` + `/health`
  + `/ready` (redis up) + DB/Redis/worker/scheduler health.
- Tenant isolation suite green (Prime↔Nest both directions, AI, WhatsApp, analytics).
- Failure drills green: Gemini down, WhatsApp down, Redis down, DB blip, invalid/expired JWT,
  insufficient permission, invalid slug, duplicate form/webhook/job, concurrent membership/renewal.
- Secret scan green: no `.env` tracked; no `GEMINI_API_KEY`/`WHATSAPP_*` values in git or bundles.

## 4. Remaining limitations (see final integration report)

- Rate limiting is Redis-distributed when `REDIS_URL` is set, in-process otherwise (documented).
- Gateway settlement stays pending-only; member self-service auth deferred; settings caching deferred.
- Full browser E2E against live backend is documented/manual; automated Playwright covers
  preview smoke + operations routes (backend-backed flows covered by pytest E2E instead).
