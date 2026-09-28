# Local Docker Runbook — Full Platform (Windows PowerShell)

One command brings up the complete local operating system: backend + PostgreSQL +
Redis + worker + scheduler. No production deploy (per mission rule).

## 1. Prerequisites

- Docker Desktop + Docker Compose v2, ports 8000 / 5433 / 6379 free.
- No `.env` committed — copy the template first.

```powershell
Copy-Item .env.example .env
# Optional: host port 5432 is often taken (another Postgres). The template maps
# host 5433 -> container 5432; the backend still reaches the DB as db:5432.
```

## 2. Start everything

```powershell
docker compose up --build
# Background:
docker compose up --build -d
docker compose ps
docker compose logs -f backend
docker compose logs -f worker
docker compose logs -f scheduler
```

Expected services: `db` (healthy), `redis` (healthy), `backend` (healthy),
`worker` (healthy), `scheduler` (healthy).

## 3. Verify

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
Invoke-RestMethod http://localhost:8000/api/v1/version
# readiness includes informational redis status: up|down|disabled
```

- API docs (non-production only): http://localhost:8000/docs
- Staff dashboard (separate terminal): `cd apps/staff-dashboard; npm install; npm run dev`
  (expects `VITE_API_BASE_URL=http://localhost:8000`; see `apps/staff-dashboard/.env.example`).

## 4. Seed + demo data (idempotent, safe to re-run)

```powershell
docker compose exec backend python -m app.services.seed
# Optional labeled demo records (leads/members/expiring memberships/payments):
docker compose exec backend python -m app.services.seed_demo
```

Never creates real users/credentials — create staff logins via the API or tests.

## 5. Exercise the timed pipeline without waiting

```powershell
# Login (replace with a real seeded user), then trigger + sweep:
# POST /api/v1/automation/trigger  {event_type, payload}
# POST /api/v1/automation/scheduler/run   (per-business scoped ops fallback)
# The worker (15s) + scheduler (60s) already run these automatically per business.
```

## 6. Stop / reset

```powershell
docker compose down            # stop, keep data
docker compose down -v         # stop + DELETE db + redis volumes (data loss!)
docker compose up --build -d   # fresh start after code changes
```

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `5432 already allocated` | `POSTGRES_PORT=5433 docker compose up --build` (template default) |
| `backend` unhealthy | `docker compose logs backend`; check `DATABASE_URL`, `SECRET_KEY`, migrations at head (`alembic upgrade head` inside backend) |
| `redis` down | Worker/scheduler keep running in DB-polling fallback; `docker compose logs redis`; readiness shows `redis: down` (informational, API stays up) |
| `worker/scheduler` unhealthy | They healthcheck DB connectivity: `docker compose logs worker`; verify `DATABASE_URL` + `db` healthy |
| CORS errors from dashboard/website | Add the exact origin to `PUBLIC_SITE_ORIGINS` in `.env`, restart backend |
| AI always demo fallback | Set `AI_ENABLED=true`, `AI_PROVIDER=gemini`, `GEMINI_API_KEY=<key>`; without them Noop fake is intentional |
| WhatsApp never sends for real | Set `WHATSAPP_ENABLED=true` + token/phone-id (or `WHATSAPP_PHONE_NUMBER_MAP`); without them `LogProvider` records messages auditably |
