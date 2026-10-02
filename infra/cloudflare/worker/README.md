# API Forwarder Worker (tiny, permanent)

Pages → this Worker → Cloudflare Access → Tunnel → VPS FastAPI → Neon.

## What it is

A ~120-line TypeScript forwarder (`src/index.ts`). It preserves METHOD, PATH,
QUERY, BODY, `Authorization`, `Cookie`, `Idempotency-Key`, `X-Request-ID`,
webhook signatures, and `Content-Type`; it returns upstream status/body plus
`Set-Cookie`, `Retry-After`, `WWW-Authenticate`. Only infrastructure failures
become 502/504. Application JSON envelopes are never modified.

## What it is NOT

No FastAPI, SQLAlchemy, psycopg/pg8000/asyncpg, DB credentials, business
logic, auth/RBAC, or tenant resolution. Bundle: **4.62 KiB total / 1.79 KiB
gzip** (measured 2026-10-02 via `npm run deploy:dry`) — never the old 20+ MB
Python bundle.

## Configure

```powershell
cd infra/cloudflare/worker
npm install
wrangler secret put UPSTREAM_BACKEND_URL      # e.g. https://origin-internal.example.com
wrangler secret put CF_ACCESS_CLIENT_ID
wrangler secret put CF_ACCESS_CLIENT_SECRET
npm test
npm run deploy:dry   # record bundle size here before real deploys
wrangler deploy
```

## Legacy

Root `wrangler.jsonc.legacy` + `backend/cloudflare_entry.py` + `backend/app/edge/` +
`backend/app/core/hyperdrive.py` are the SUPERSEDED Python-Workers experiment
(settled as non-viable for this sync app). They are not referenced by this
Worker and must not be deployed. Removal is scheduled once the VPS cutover is
verified; until then they stay inert in Git history.
