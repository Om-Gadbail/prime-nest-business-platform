# Production Hardening Report — Phase 1

**Date:** 2026-09-27
**Scope:** full production-readiness audit + hardening of the ONE shared
FastAPI backend (`backend/`) + staff dashboard (`apps/staff-dashboard`).
**Deploy status:** NOT DEPLOYED (per mission rule — no deploy in any phase).

## 1. Architecture map (verified against code, not claims)

- **Canonical backend:** `backend/app/main.py` (`create_app()`), `/health`
  (no DB), `/ready` (DB ping), `/api/v1/*` (26 routers in
  `app/api/v1/router.py`: system, auth, business, leads, bookings,
  contacts, customers, notifications, public, ai, tasks, audit, dashboard,
  identity, members, memberships, payments, attendance, seats, approvals,
  owner, automation, communications, whatsapp, ai_chat, growth+analytics+brief).
- **Layering:** `api → services → repositories → models`, `core` shared.
  Verified: routers never touch DB directly; services never write SQL.
- **Tenancy:** one Postgres DB, `businesses` root, `BusinessScopedMixin`
  (`business_id → businesses.id NOT NULL`) on all tenant tables; global
  roots (`businesses`, `users`, `roles/permissions`, `persons`,
  `business_relationships`) intentionally unscoped. Client `business_id`
  never trusted — context comes from Bearer JWT + fresh DB
  membership/role lookup (`app/api/deps.py`, `services/authorization.py`).
- **Frontend:** single staff dashboard serves Prime/Nest/Owner via
  permission-gated nav; API base from `VITE_API_BASE_URL` only; no
  browser-side Gemini/WhatsApp SDKs (backend proxy only). Public website
  widget is backend-backed `<WebsiteChat/>`; Nest drop-in client in
  `integrations/nest-website/` (thin, slug-verified, idempotent).
- **Migrations:** `0001_baseline → 0002_identity → 0003_leads/crm →
  0004_tasks/audit/identity → 0005_operations → 0006_growth/AI →
  0007_phase1_hardening_money_ids` (new, this phase).

## 2. Database fixes (1A)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 1 | `attributions.revenue` was `VARCHAR(32)` — lexical sort, no `SUM`, truncation in `growth.py` | `NUMERIC(12,2)` NOT NULL DEFAULT 0.00 + `_coerce_money()` validator (rejects NaN/Inf/negatives/overflow, quantizes 2dp, 422 on bad input) | `models/growth.py`, `services/growth.py`, `migrations/0007` |
| 2 | `analytics_snapshots.value` was `VARCHAR(64)` — same class of bug; writer did `str(metrics[k])` round-trip | `NUMERIC(14,2)` NOT NULL DEFAULT 0.00; `upsert_snapshot()` coerces Decimal; API shape unchanged (ints for counts, `"%.2f"` for revenue) | `models/growth.py`, `services/analytics.py`, `repositories/blocks812.py`, `migrations/0007` |
| 3 | `messages.provider_message_id` / `message_delivery_events.provider_message_id` were `NOT NULL DEFAULT ''` with a scoped unique constraint — 2nd unset row violated it | Nullable, no default; `'' → NULL` backfill; `create_message()` normalizes falsy → NULL; `get_message_by_provider(None)` returns None (no false match) | `models/communication.py`, `repositories/blocks812.py`, `migrations/0007` |
| 4 | `conversations` had no dedupe guard — `get_or_create_conversation` check-then-insert raced | Partial UNIQUE INDEX `(business_id, channel, external_id) WHERE external_id <> ''` (PG + SQLite) in model + migration; repo uses savepoint + `IntegrityError` re-fetch | `models/communication.py`, `repositories/blocks812.py`, `migrations/0007` |

Money standard is now uniform: every monetary column is
`NUMERIC(12,2)`/`NUMERIC(14,2)` + Decimal (operations already were;
growth/analytics now match). Timestamps stay TZ-aware; FKs use
`RESTRICT`/`SET NULL`/`CASCADE` deliberately per relation.

## 3. Alembic (1B)

- `upgrade head → downgrade base → upgrade head` on PostgreSQL 16
  (Docker, host port 5433): **passes**, including new `0007`
  (fixed a `DROP DEFAULT`-before-`ALTER TYPE` cast error found during
  verification).
- `alembic check`: our three fixed columns + new conversations index
  show **zero drift** (model matches DB after this phase). Remaining
  output is pre-existing harmless noise across all tables
  (`modify_default` Python-default vs DB-server-default,
  `JSON` vs `JSONB`, auto `ix_*_business_id` from `index=True`,
  `users`/`businesses`/`permissions` unique-index naming) — left
  untouched per "never destroy migration history"; cleaning it would
  require rewriting 0001–0006.
- SQLite tests use `create_all` (not migrations) — unaffected.

## 4. Tenant isolation / Auth / RBAC (1C–1E)

Adversarial suites pass: `test_block{1,2,3}_isolation` (20),
`test_block{1,2,3}_rbac` + `test_block1_auth` (46). Hardening fixes:

1. **WhatsApp webhook fail-closed in prod** — `GET /webhook` no longer
   echoes challenge when unconfigured in production;
   `POST /webhook` rejects when `APP_ENV=production` with no
   `APP_SECRET`. Demo echo/accept remains only outside production
   (documented in `services/messaging.py`).
2. **`retry_due` footgun closed** — `business_id` is now REQUIRED
   (was `None` = unscoped cross-tenant replay); the only caller
   (`POST /automation/scheduler/run`) already passes the authed business.
3. **Timeline over-exposure fixed** — `GET /communications/timeline`
   now honors `phone`/`lead_id` (subject-scoped conversation filter,
   empty-set on unknown lead) instead of ignoring them.
4. **AI assistant role bug fixed** — `getattr(ctx, "role", "")` (always
   empty → never `owner` mode) → `ctx.role_name == "OWNER"`.
5. **Public chat precedence bug fixed** —
   `payload.visitor_key or request.client.host if … else "anon"` →
   parenthesized fallback (was binding as
   `(visitor_key or host) if client else "anon"`).
6. **Body-size bypass closed** — middleware now counts actual streamed
   bytes (fixes chunked/missing/lying-`Content-Length` bypass) in
   addition to the header fast-path; 413 before parsing.

Unchanged (verified strong): Argon2id policy, JWT minimal claims +
short expiry, opaque rotated refresh with family-revoke, generic login
failures, 401/403 semantics, safe error envelope, per-IP rate limits,
honeypot + idempotency on public POSTs, `require_permission` on every
staff route, DB-authoritative permissions, uniform cross-tenant 404s.

## 5. Frontend / Docker / Git (1F–1H)

- **Contracts:** all dashboard calls go through `src/lib/api.ts`
  (Bearer in memory + HttpOnly refresh cookie, 15s timeout, single
  refresh retry, typed `ApiError`); `businessId` always from `/auth/me`;
  loading/empty/error/forbidden states present; no fake API behavior.
- **Frontend gates:** `typecheck` ✅, `lint (oxlint)` ✅,
  `vitest` 20/20 ✅, `vite build` ✅ (only a pre-existing >500kB
  chunk-size warning).
- **Docker (clean rebuild):** `db` healthy (PG16), `backend` rebuilt
  with Phase-1 code: `/health` ok, `/ready` ready, `/version` ok.
  Note: host port `5433` used (local 5432 already allocated); inside
  the Compose network the backend still uses `db:5432`.
- **Git security:** no `.env` tracked (`git ls-files` empty for
  `*.env/*.pem/*.key/dumps`); `.gitignore` covers `.env`; secret-value
  scans (`PRIVATE KEY`, `AKIA*`, `ghp_*`, non-empty `GEMINI_API_KEY=`)
  empty. `docker-compose.yml`/`config.py` dev-default secrets are
  blocked in production by `validate_secret_key` (`APP_ENV=production`
  refuses `change-me-in-production`/empty without strong
  `JWT_SECRET_KEY`). Working tree still has uncommitted Blocks 2–12 +
  Phase-1 files on top of the `Block 1 foundation` commit — commit
  deliberately left to the user (no commits without request).

## 6. Tests run (1I) — all green, none weakened

Backend (SQLite integration, `pytest`, this phase, after fixes):
health/config/database 13 · block1 65 · isolation 20 · rbac/auth 46 ·
`test_blocks812` 13 · block2_security 11 · block2_public+ai_eval 24 ·
block57_security+concurrency 12 · block2_ai/bookings/crm 21 ·
block2_leads/notifications 17 · block3 (6 files) 35 · block5_owner/6/7
18 · block57_e2e 3 — **zero failures**. `ruff check` passes;
`ruff format --check` flags 109 pre-existing files (style drift, not
enforced — left alone).

## 7. Known issues / non-blockers

- `alembic check` pre-existing noise (see §3) — harmless, documented.
- `ruff format` drift (109 files) — style only, no lint errors.
- Rate limiter is in-process (documented prod requirement: Redis for
  multi-worker) — unchanged, interface ready (`set_limiter()`).
- Scheduler has no cron/worker — external ticker calls
  `POST /automation/scheduler/run` (already the documented cutover).
- WhatsApp `business_slug` demo mapping in inbound webhook stays
  (real Meta payloads carry `phone_number_id`); safe now that
  signature verification is fail-closed in prod — full
  `phone_number_id → business` mapping is Phase 3 work.

## 8. Exit criteria

- [x] database clean (money Numeric, provider ids nullable, dedupe index)
- [x] migrations reproducible (upgrade→downgrade→upgrade on PG16)
- [x] tenant isolation passes (20 adversarial)
- [x] auth + RBAC pass (46)
- [x] Docker passes (rebuilt, health/ready/version)
- [x] frontend builds (typecheck/lint/unit/build)
- [x] tests pass, none weakened/removed
- [x] no critical security defect remains (fail-closed webhooks,
      required scheduler scope, timeline scoping, body-size streaming cap)
- [x] prod config separated from dev (prod validators + fail-closed paths)
- [x] docs updated (this report)

**Phase 1: COMPLETE. Do not deploy** (per mission — staging only after
Phase 6). Next: **Phase 2 — Central Gemini AI Gateway**
(provider abstraction + tenant-aware tools + allowlists + fake-provider
tests + key-never-in-browser verification).
