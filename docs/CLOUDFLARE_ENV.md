# Cloudflare Environment / Secrets — Prime Nest Business Platform

Rules:

- NEVER commit secret values. `.env` is gitignored; `wrangler.jsonc`
  holds non-secret `vars` only.
- NEVER put secrets in frontend code (`VITE_*`, `apps/**`,
  `integrations/**`). Gemini/Meta/WhatsApp/payment credentials are
  backend/Worker secrets only.
- PostgreSQL/Redis stay private on the VPS/Docker network. The Worker
  does not need public DB exposure; DB-backed traffic goes Worker ->
  VPS backend over authenticated HTTPS (allowlisted).
- Production (`APP_ENV=production`): `/docs` disabled, weak
  `SECRET_KEY` rejected unless strong `JWT_SECRET_KEY` set,
  `AUTH_COOKIE_SECURE=true`, WhatsApp webhooks fail closed without
  app secrets.

## 1. Non-secret vars (`wrangler.jsonc` [vars] or `wrangler vars`)

`APP_NAME`, `APP_VERSION`, `APP_ENV` (=`production` at edge),
`LOG_LEVEL`, `UPSTREAM_BACKEND_URL` (VPS origin, e.g.
`https://api.example.com`), `BACKEND_CORS_ORIGINS`,
`PUBLIC_SITE_ORIGINS` (exact origins for the five frontends, no `*`),
`JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
`REFRESH_TOKEN_EXPIRE_DAYS`, `AUTH_COOKIE_SECURE` (=`true`),
`AUTH_COOKIE_SAMESITE`, rate-limit tunables (`RATE_LIMIT_*`),
`MAX_BODY_BYTES`, `AI_*` (non-key), `GEMINI_MODEL`,
`WHATSAPP_API_VERSION`, `WHATSAPP_TIMEOUT_SECONDS`,
`WHATSAPP_MAX_ATTEMPTS`, `AUTOMATION_*`, `SCHEDULER_*`, `WORKER_*`.

## 2. Secrets (`wrangler secret put <NAME>` — one per line, values never printed)

JWT/session: `SECRET_KEY`, `JWT_SECRET_KEY`.
Data layer (VPS-held; only set on the Worker if a proven direct-DB path
is adopted — default: VPS-only): `DATABASE_URL`,
`PLATFORM_DATABASE_URL`, `PRIME_DATABASE_URL`, `NEST_DATABASE_URL`,
`REDIS_URL`.
AI: `GEMINI_API_KEY` (server-side only; model via `GEMINI_MODEL` var).
WhatsApp per business (server-side only):
`PRIME_WHATSAPP_ENABLED`, `PRIME_WHATSAPP_ACCESS_TOKEN`,
`PRIME_WHATSAPP_PHONE_NUMBER_ID`,
`PRIME_WHATSAPP_BUSINESS_ACCOUNT_ID`, `PRIME_WHATSAPP_VERIFY_TOKEN`,
`PRIME_WHATSAPP_APP_SECRET`, and the `NEST_*` counterparts, plus legacy
`WHATSAPP_*` (deprecated fallback) and `WHATSAPP_PHONE_NUMBER_MAP`.
Payments: `PAYMENT_WEBHOOK_SECRET` (empty = webhooks 503, never accept
unverified money movement).
Seeds (non-production only): `OWNER_SEED_EMAIL`,
`OWNER_SEED_PASSWORD`, `SEED_PLATFORM_OWNER`, `STAFF_SEED_PASSWORD`,
`SEED_DEV_STAFF` (production never seeds demo credentials).

## 3. Commands (names only)

```bash
wrangler secret put SECRET_KEY
wrangler secret put JWT_SECRET_KEY
wrangler secret put GEMINI_API_KEY
wrangler secret put PRIME_WHATSAPP_ACCESS_TOKEN
wrangler secret put PRIME_WHATSAPP_PHONE_NUMBER_ID
wrangler secret put PRIME_WHATSAPP_BUSINESS_ACCOUNT_ID
wrangler secret put PRIME_WHATSAPP_VERIFY_TOKEN
wrangler secret put PRIME_WHATSAPP_APP_SECRET
wrangler secret put NEST_WHATSAPP_ACCESS_TOKEN
wrangler secret put NEST_WHATSAPP_PHONE_NUMBER_ID
wrangler secret put NEST_WHATSAPP_BUSINESS_ACCOUNT_ID
wrangler secret put NEST_WHATSAPP_VERIFY_TOKEN
wrangler secret put NEST_WHATSAPP_APP_SECRET
wrangler secret put PAYMENT_WEBHOOK_SECRET
wrangler secret list   # verify NAMES only
```

Meta webhook verification uses the per-business `*_VERIFY_TOKEN`
(query `hub.verify_token`); inbound HMAC uses `*_APP_SECRET`
(`X-Hub-Signature-256`). Both stay server-side.
