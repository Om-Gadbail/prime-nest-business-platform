# Cloudflare Deployment — Prime Nest Business Platform (Edge Adapter)

Status: adapter prepared and validated locally. **DO NOT deploy to
production yet** (mission rule).

## 1. What was added (no production behavior changed)

| File | Purpose |
|---|---|
| `backend/cloudflare_entry.py` | Worker entrypoint. Reuses canonical `app.main.create_app()`; exposes official `Default = asgi.entrypoint(app)`. Import-safe without the `workers` package (local/pytest/Docker still work) |
| `wrangler.jsonc` (repo root) | Worker config: `main=backend/cloudflare_entry.py`, `compatibility_date=2026-10-01`, `compatibility_flags=["python_workers"]`, non-secret `vars` only |
| `backend/pyproject.toml` `[project]` + `[dependency-groups]` | Cloudflare build metadata (edge-compatible deps only). Docker still installs `backend/requirements.txt` — unaffected |
| `docs/CLOUDFLARE_COMPATIBILITY.md` | Audit findings + blocker verdict |
| `docs/CLOUDFLARE_ENV.md` | Vars vs secrets matrix (names only, no values) |
| `docs/CLOUDFLARE_DEPLOYMENT.md` (this file) | Deploy/runbook |

Unchanged: `docker-compose.yml`, `backend/Dockerfile`,
`backend/requirements.txt`, `backend/app/**`, `backend/migrations/**`,
`backend/entrypoint.sh`, all APIs, auth/RBAC, worker/scheduler.

## 2. Architecture

```text
5 frontends ──HTTPS──> Worker (edge) ──HTTPS──> VPS backend ──private──> PG/Redis
```

- Worker serves HTTP/API at the edge (CORS, security headers, request
  IDs, rate-limit passthrough, auth headers passthrough).
- VPS Docker backend remains the system of record (PostgreSQL, Redis,
  worker, scheduler, Gemini/WhatsApp secrets).
- DB credentials NEVER leave the server. Frontend code holds no secrets.

## 3. Prerequisites

- `uv` + Node `wrangler` (official quickstart uses `uv run pywrangler dev`).
- A VPS (or existing host) running `docker compose up --build` with
  PostgreSQL + Redis on a private network.
- Cloudflare account + `wrangler login`.

## 4. Configure (names only — never commit values)

See `docs/CLOUDFLARE_ENV.md` for the full matrix. Summary:

```bash
# Non-secret edge config (wrangler vars / wrangler.jsonc [vars])
# APP_ENV=production, APP_NAME, APP_VERSION, LOG_LEVEL, UPSTREAM_BACKEND_URL

# Secrets — set via CLI only, one per prompt (values never echoed):
wrangler secret put SECRET_KEY
wrangler secret put JWT_SECRET_KEY
wrangler secret put DATABASE_URL
wrangler secret put REDIS_URL
wrangler secret put GEMINI_API_KEY
wrangler secret put PRIME_WHATSAPP_ACCESS_TOKEN
wrangler secret put PRIME_WHATSAPP_VERIFY_TOKEN
wrangler secret put PRIME_WHATSAPP_APP_SECRET
wrangler secret put NEST_WHATSAPP_ACCESS_TOKEN
wrangler secret put NEST_WHATSAPP_VERIFY_TOKEN
wrangler secret put NEST_WHATSAPP_APP_SECRET
wrangler secret put PAYMENT_WEBHOOK_SECRET
# ... plus remaining WHATSAPP_*/CORS/cookie vars per CLOUDFLARE_ENV.md
```

CORS origins (`BACKEND_CORS_ORIGINS`, `PUBLIC_SITE_ORIGINS`) must list the
five frontend origins exactly (no `*`); in production they are the real
`https://` dashboard/website origins.

## 5. Local validation (done in this mission)

```bash
cd backend
pytest                 # full suite
python -m ruff check app cloudflare_entry.py
python -m ruff format --check app cloudflare_entry.py
docker compose build backend
docker compose up --build -d
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/openapi.json
```

## 6. Worker local run (requires Cloudflare tooling)

```bash
# From the repo root (wrangler.jsonc lives here):
uv run pywrangler dev
# in another terminal:
curl http://localhost:8787/health
curl http://localhost:8787/ready
curl "http://localhost:8787/api/v1/whatsapp/webhook/prime?hub.mode=subscribe&hub.verify_token=<dev-token>&hub.challenge=123"
```

Tooling (`uv`, `pywrangler`, `wrangler`) was NOT installed in this
environment, so this step is documented-not-executed (see final report).

## 7. Deploy (ONLY when authorized — NOT part of this mission)

```bash
wrangler deploy
# point Meta webhook URLs at:
#   GET|POST https://<worker-host>/api/v1/whatsapp/webhook/prime
# point frontends at https://<worker-host> (exact CORS origins required)
# keep worker + scheduler + db + redis running on the VPS
```

## 8. Rollback

- DNS/frontends back to the VPS origin; `wrangler rollback` if needed.
- VPS `docker compose` is untouched and remains the fallback.
