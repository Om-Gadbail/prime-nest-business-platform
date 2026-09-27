# Canonical Backend Architecture (Prompt 1 — as discovered, plus target)

## 1. Canonical backend location

`C:\Users\ossag\OneDrive\Desktop\prime-nest-business-platform\backend` — the sole backend.
No other FastAPI application exists in this checkout.

## 2. Canonical FastAPI entrypoint

`backend/app/main.py`: `create_app() -> FastAPI`, module-level `app = create_app()`.
Unversioned ops: `GET /health` (liveness, no DB), `GET /ready` (readiness, DB+Redis status).
Versioned API: `app.include_router(v1_router, prefix=settings.api_v1_prefix)` → `/api/v1/*`.
Docs (`/docs`, `/redoc`, `/openapi.json`) auto-disabled when `APP_ENV=production`.
Middleware order (outer→inner): CORS (exact origins only) → RequestID → BodySizeLimit.

## 3. Canonical config/settings

`backend/app/core/config.py`: `Settings` (pydantic-settings, `.env`, `extra="ignore"`).
Fails fast on missing/non-Postgres `DATABASE_URL`; fails fast on default secrets in
production; `JWT_SECRET_KEY` overrides `SECRET_KEY`; `effective_cors_origins` unions
`BACKEND_CORS_ORIGINS + PUBLIC_SITE_ORIGINS` (exact origins, never `*`).
Template: root `.env.example` (dev/test/staging/prod sections; no secrets committed).

## 4. Canonical auth system

- `core/security.py`: Argon2id (`pwdlib.recommended`); password length 10–128 only.
  Access JWT: `{sub, jti, iat, exp, type:"access", business_id?}`, HS256 (HS384/512 allowed),
  30 min default. Refresh: `secrets.token_urlsafe(48)`, only SHA-256 stored.
- `services/auth.py` + `repositories/sessions.py` (`auth_sessions`): login (generic 401 +
  dummy-verify anti-oracle), refresh rotation with reuse→revoke-all-family, logout revokes
  one session, `switch-business` verifies membership then issues a fresh pair.
- `authenticate_request` (every request): decode JWT → load user → reject inactive →
  if `business_id` claim present, reload business+membership and reject inactive/missing
  (403). JWT is identity/context hint; DB is authoritative.
- Transport: `Authorization: Bearer` (memory-only in dashboard) + HttpOnly refresh cookie
  (`Path=/api/v1/auth`, `Secure`/`SameSite` configurable) with JSON fallback.

## 5. Canonical RBAC system

`models/rbac.py`: `Role` (system roles `OWNER/ADMIN/MANAGER/STAFF/VIEWER`, `business_id`
nullable for future per-business roles), `Permission(key)`, `RolePermission` join.
`ALL_PERMISSIONS` (~70 keys) + deny-by-default `ROLE_PERMISSIONS` matrix; `OWNER` = all,
`ADMIN` = all except `users.disable`. Assignment always via `role_id` FK — no role-name
string checks in business logic. Enforcement: `deps.require_permission(key)` (140 call sites,
57 distinct keys) + `BusinessAccessPolicy.require/require_any/require_role`.

## 6. Canonical business registry

`businesses` table: UUID PK, unique `slug`, `business_type` (fitness/library/other), status +
`is_active` dual flags. Seeded: `prime` (Prime Fitness, fitness), `nest` (Nest Library,
library). NOTE: there are NO `prime-fitness-001` / `nest-library-001` string IDs anywhere in
this backend — businesses are addressed by slug (public) or UUID (server-side). Any plan
references to `-001` IDs predate this implementation and must be translated to slugs/UUIDs
in Prompt 2.

## 7. Canonical tenant context

`services/authorization.py:AuthenticatedContext` (user+business+membership+role+permissions,
built per request from DB) → `services/business_context.py:BusinessContext` (frozen,
`for_staff` fail-closed on inactive user/membership/business; `for_public` slug resolution).
`assert_same_business` maps cross-business access to 404 (no oracle). Zero endpoints accept
client-supplied `business_id` as authorization (verified by grep).

## 8. Canonical database routing — CURRENT vs TARGET

- CURRENT (verified): ONE PostgreSQL database (`app_db` in compose), ONE sync engine,
  per-request `Session` closed in `finally`. All tenants share tables, isolated by
  `business_id` filtering at the service/repository layer. No AsyncSession, no cross-task
  session reuse (request-scoped). Pool: `pool_pre_ping`, 3s connect timeout.
- TARGET: `platform_db` (identity/RBAC/registry/owner access) vs `prime_db` / `nest_db`
  (operational data), routed per resolved `BusinessContext`. This is a Prompt-2+ migration:
  it requires per-database Alembic branches, session scoping per context, seed splitting,
  and data migration. No cross-database transactions unless proven necessary.

## 9. Platform DB responsibility (target)

Unified identity (users, auth sessions), RBAC (roles/permissions/memberships), business
registry + database mappings, owner access grants, platform/security metadata, audit log.

## 10. Prime DB responsibility (target)

Prime operational data only: leads, bookings, members, memberships, payments, attendance,
tasks, communications, automation state, growth data for business `prime`.

## 11. Nest DB responsibility (target)

Nest operational data only: same domains for business `nest`, plus seat areas/allocations.

## 12. Canonical migration strategy

Single linear Alembic chain (0001→0007, no branches). Rules: never delete history, never
rewrite revisions, new change = new revision. Prompt 2 must introduce per-database migration
branches WITHOUT touching 0001–0007. `migrations/env.py` imports `models.Base.metadata`.

## 13. Canonical seed strategy

`services/seed.py:seed_development` — idempotent, commits once, creates RBAC matrix +
`prime`/`nest` + settings rows + plans/seat areas/templates + automation/growth defaults +
Prime↔Nest `cross_sell` relationship. Creates NO users and NO credentials (tests and
`seed_live_e2e.py` create their own; live script uses `@live.example.com` throwaway
addresses only). The unified owner `owner@prime-nest-dashboard.com` does NOT exist yet —
correct canonical home is the platform identity layer (Prompt 2), NOT duplicated per database.

## 14. Canonical API namespace

- `GET /health`, `GET /ready` (unversioned ops).
- `/api/v1/auth/*`, `/api/v1/public/{slug}/*` (anonymous), `/api/v1/<domain>/*` (Bearer +
  permission gates). Full list: `docs/backend-api-inventory.md`.
- Legacy/duplicate namespaces: NONE found. No `/api/leads/*` (non-v1) routes exist here —
  the plan's `POST /api/leads/contact` style paths are NOT this backend's contract; the Nest
  drop-in and Prime site both use `/api/v1/public/{slug}/...`. Any frontend still calling
  non-v1 paths needs a compatibility check in Prompt 4 (documented mismatch, frontend
  untouched in Prompt 1).

## 15. Legacy backends

None present in this checkout (`apps/api` absent; see `docs/backend-audit.md` §A2).
Nothing deprecated in Prompt 1.

## 16. Components to migrate (Prompt 2+)

Single-DB → three-DB split (sessions, Alembic branches, seeds, data migration); unified
owner account creation in platform identity; Redis-backed rate limiting as prod default.

## 17. Components to deprecate

NONE in Prompt 1. Candidate for later: in-memory limiter as prod default (docs-only warning
for now); `GET /api/v1/public/{slug}/ai/chat` unauthenticated widget — keep, tighten rates.

## 18. Components intentionally preserved

All 160 routes, auth/refresh mechanics, RBAC matrix, public-intake pipeline (honeypot,
idempotency, feature flags), owner combined gate, scheduler/worker, AI/WhatsApp noop
fallbacks, all 7 migrations, seed idempotency.

## 19. Known risks

1. Single shared DB = blast-radius/regulatory risk until the split lands (accepted, tracked).
2. Non-prod error handler echoes exception text (by design for dev; must never run non-prod
   config against prod data).
3. Test suite is slow (~10+ min, Argon2) — CI must allow for it; do not "fix" by weakening hashes.
4. `apps/api` may exist on another workstation — must be diffed, never blindly merged.
5. Business-ID vocabulary mismatch: plan says `prime-fitness-001`; code uses slugs/UUIDs.

## 20. Prompt 2 implementation requirements

1. Design platform/prime/nest DB split + per-DB Alembic strategy (no history rewrite).
2. Create unified owner in platform identity with memberships to prime+nest; define how the
   single staff dashboard mints prime-only / nest-only / combined contexts.
3. Keep every route in `docs/backend-api-inventory.md` working throughout the migration.
4. Add server-side tests for each of the 15 tenant-isolation attacks BEFORE splitting.
5. Resolve `-001` business-ID vocabulary (adopt slugs/UUIDs; update plan docs, not code).
