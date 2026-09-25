# Prime Nest Business Platform — Backend (Phase 2, Blocks 0–1)

One shared, lean **modular monolith** backend (FastAPI + PostgreSQL) that will
eventually serve Prime Fitness, Nest Library, staff dashboards, the Owner
Command Center, CRM, notifications, analytics, and AI systems.

- **Step 1 (verified):** app wiring, configuration, database, migrations,
  health/readiness, Docker, tests.
- **Block 1 (this release):** multi-tenant foundation + authentication + RBAC +
  business memberships + business settings. No CRM/bookings/payments/AI yet.

## Architecture

```text
backend/
  app/
    main.py            # create_app() factory, /health, /ready, /api/v1/*
    api/               # HTTP layer (routers only, no business logic)
      deps.py          # get_current_context/user/business + require_permission
      v1/router.py + endpoints/ (system, auth, business)
    core/              # config, database engine/session, logging, security
    models/            # SQLAlchemy Base + ORM models (all exported for Alembic)
    schemas/           # Pydantic request/response contracts
    services/          # business logic (calls repositories, no SQL)
    repositories/      # SQL only (no business logic)
    middleware/        # request-id, error handlers
  migrations/          # Alembic env + versions (imports models.Base)
  tests/               # pytest suite (Step 1 mocked-DB + Block 1 SQLite integration)
  Dockerfile
  requirements.txt
  alembic.ini
  pytest.ini
```

Layer rules: `api → services → repositories → models`, with `core` shared.
Routers never touch the DB directly; services never write SQL.

### Block 1: business / tenant model

One Postgres database, many businesses (tenants):

- `businesses` — tenant root (`id` UUID, unique `slug`, `name`,
  `business_type` ∈ {fitness, library, other}, `status` ∈ {active, inactive},
  contact/address/localization columns, `is_active`).
- Seed tenants: `prime` (Prime Fitness, fitness) and `nest` (Nest Library,
  library). Unknown values stay NULL — no fake emails/coordinates/hours.
- Tenant-owned tables carry `business_id → businesses.id` via
  `BusinessScopedMixin`. Repository helpers (`apply_business_scope`,
  `get_scoped`, `list_scoped`, `count_scoped`) make unscoped queries fail
  closed. Client-provided `business_id` (URL/query/body/header) is never
  trusted — the active business always comes from the authenticated context.

### Authentication architecture

- Passwords: Argon2id via `pwdlib` (`hash_password` / `verify_password`).
  Policy: 10–128 chars, no silent truncation. Hashes never leave the API,
  never logged.
- Login `POST /api/v1/auth/login` validates credentials with a generic
  `Invalid email or password.` failure (no account-enumeration leak), resolves
  the default business (or explicit `business_slug` verified against
  membership), issues a short-lived JWT access token + opaque refresh token,
  updates `last_login_at`.
- JWT (PyJWT, HS256 default): minimal claims only —
  `sub` (user id), `jti`, `iat`, `exp`, `type="access"`, `business_id`.
  No PII. Expiry default 30 min (`ACCESS_TOKEN_EXPIRE_MINUTES`).
- Refresh sessions (`auth_sessions` table): only SHA-256 hash stored, opaque
  `secrets.token_urlsafe` value returned. Rotation on every use; reuse of a
  revoked token revokes the whole user session family. Logout revokes the
  active session. Expired/revoked sessions rejected.
- Browser storage: refresh token is set as a `Secure`/`HttpOnly`/`SameSite`
  cookie (`AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE`) AND returned as JSON
  for non-browser clients. Access token stays short-lived in memory — never
  persist long-lived credentials in `localStorage`. No BFF in this block.
- Endpoints (`/api/v1/auth`): `POST /login`, `GET /me`,
  `POST /refresh` (JSON body or cookie), `POST /logout`,
  `GET /businesses` (only my active memberships),
  `POST /switch-business` (`business_id` = UUID or slug, membership-verified,
  403 otherwise).

### RBAC architecture

- Tables: `roles` (`business_id` NULL = system role, non-NULL = future
  business-specific role), `permissions` (`key` unique), `role_permissions`
  (composite PK), `business_memberships`
  (`user_id`, `business_id`, `role_id`, `status` ∈ {active, suspended, revoked},
  `is_default`, unique(`user_id`, `business_id`)).
- System roles: `OWNER` (all 20 permissions), `ADMIN` (all except
  `users.disable`), `MANAGER` (operational management), `STAFF` (day-to-day),
  `VIEWER` (read-only). Explicit matrix in `app/models/rbac.py`; no
  role-name string checks in services — `resolve_permissions()` reads the
  `role_permissions` join and `require_permission("...")` enforces it.
- DB state is authoritative per request: revoked/suspended memberships,
  inactive users/businesses, and role changes take effect immediately on the
  next request (JWT is identity/context only, never the permission source).
- Permission vocabulary reserves future modules (`leads.*`, `bookings.*`,
  `payments.*`, `analytics.read`); Block 1 endpoints enforce only
  `business.read/update` and `settings.read/update` (+ `users.*`/`members.*`
  vocabulary for later blocks).

### Business membership model

A user may belong to Prime only, Nest only, both, or future businesses.
Only `active` memberships in `active` businesses yield a business context.
`GET /auth/businesses` + `POST /auth/switch-business` are the only legal
tenant-switch paths, both membership-verified.

### Business settings model

- `business_settings` — one row per business (`business_id` PK/FK), JSON
  sections: `branding`, `contact`, `address`, `hours`, `localization`,
  `operational`. Core identity stays on `businesses`.
- `GET /api/v1/business` (`business.read`), `PATCH /api/v1/business`
  (`business.update`), `GET /api/v1/business/settings` (`settings.read`),
  `PATCH /api/v1/business/settings` (`settings.update`).
- Pydantic + service validation: timezones (`zoneinfo`), locales
  (`en`/`en-US`), currencies (ISO-3), hex colors, http(s) URLs, phone shapes
  (lenient international), weekly-hours structure (`HH:MM`), booleans, unknown
  sections/fields rejected with 422. Partial-update (merge) semantics.

## Prerequisites

- Python 3.12+ (Docker image uses 3.12-slim)
- Docker + Docker Compose v2

## Quick start (Docker — recommended)

```bash
cp .env.example .env
docker compose up --build
```

- API: <http://localhost:8000>
- Docs (non-production): <http://localhost:8000/docs>
- Liveness: `GET /health` → `{"status": "ok", ...}` (no DB touch)
- Readiness: `GET /ready` → 200 `{"status": "ready", ...}` or 503 `{"status": "not_ready", ...}`
- Version: `GET /api/v1/version`

> Port already in use? Another Postgres on your machine (e.g. a Phase 1
> stack) may hold host port 5432. The example env maps host `5433` — the
> backend still reaches the DB as `db:5432` inside the Compose network:
>
> ```bash
> POSTGRES_PORT=5433 docker compose up --build
> ```

## Local start (without Docker)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate  # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
copy ..\.env.example ..\.env   # then set DATABASE_URL to a reachable Postgres
uvicorn app.main:app --reload --port 8000
```

## Environment variables

| Name | Required | Example |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://postgres:postgres@db:5432/app_db` |
| `APP_ENV` | no (`development`) | `development` / `testing` / `production` |
| `APP_NAME` / `APP_VERSION` | no | `Prime Nest Business Platform` / `0.1.0` |
| `LOG_LEVEL` | no (`INFO`) | `INFO`, `DEBUG`, `WARNING` |
| `BACKEND_CORS_ORIGINS` | no (dev defaults apply) | `http://localhost:3000,http://localhost:5173` |
| `SECRET_KEY` | required in production | output of `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `JWT_SECRET_KEY` | no (overrides `SECRET_KEY` for JWT) | same generation as `SECRET_KEY` |
| `JWT_ALGORITHM` | no (`HS256`) | `HS256` / `HS384` / `HS512` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no (`30`) | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | no (`14`) | `14` |
| `AUTH_COOKIE_SECURE` | no (`false` dev) | `false` locally, `true` in production https |
| `AUTH_COOKIE_SAMESITE` | no (`lax`) | `lax` / `strict` / `none` |

Invalid/missing `DATABASE_URL` fails fast with a clear `ValidationError`.
In production (`APP_ENV=production`) docs are disabled and a default/weak
`SECRET_KEY` (without a strong `JWT_SECRET_KEY`) is rejected.

## Docker commands

```bash
docker compose up --build        # backend + postgres
docker compose up -d             # background
docker compose logs -f backend   # follow backend logs
docker compose down              # stop
docker compose down -v           # stop + delete DB volume (data loss!)
```

## Database migrations

```bash
cd backend
alembic upgrade head              # apply all migrations
alembic current                   # show current revision
alembic revision --autogenerate -m "describe change"   # after editing models
alembic downgrade -1              # roll back one step
```

`migrations/env.py` reads `DATABASE_URL` from settings and loads
`app.models.Base.metadata`, so new models in `app/models/` are picked up
automatically once imported in `app/models/__init__.py`.

Migration history:

- `0001_baseline` — empty foundation (Step 1).
- `0002_identity_multitenancy` — Block 1: `businesses`, `users`, `roles`,
  `permissions`, `role_permissions`, `business_memberships`,
  `business_settings`, `auth_sessions` (+ indexes/constraints).

## Development seed (safe, idempotent)

```bash
cd backend
python -m app.services.seed
```

Creates system roles + permission matrix, `prime`/`nest` businesses, and one
empty `business_settings` row per business. Never deletes data, never creates
users/credentials — tests create their own users. Safe to run repeatedly.

## Tests

```bash
cd backend
pytest
```

- Step 1 (13 tests): app boots, `/health`, `/ready` (up + down),
  `/api/v1/version`, invalid-config failures, DB-connection handling (mocked).
- Block 1 (~65 tests, SQLite-backed integration): businesses/seed/slug
  uniqueness, settings CRUD + validation, users/email uniqueness/Argon2id,
  login/me/refresh/logout/rotation/reuse/expiry/signature, memberships
  (Prime↔Nest isolation, both-business user, suspended/revoked/inactive,
  switch-business 403s), RBAC matrix (owner/admin/manager/staff/viewer,
  403s, escalation blocked, immediate role/revocation effect), adversarial
  tenant isolation (URL/query/body/forged-JWT/repository helpers).

## Authentication API overview

| Method & path | Auth | Description |
|---|---|---|
| `POST /api/v1/auth/login` | no | `{email, password, business_slug?}` → tokens + context |
| `GET /api/v1/auth/me` | Bearer | Current user + business + role + permissions |
| `POST /api/v1/auth/refresh` | refresh token | Rotate session → fresh tokens |
| `POST /api/v1/auth/logout` | Bearer + refresh | Revoke active session |
| `GET /api/v1/auth/businesses` | Bearer | My active businesses only |
| `POST /api/v1/auth/switch-business` | Bearer | `{business_id (uuid\|slug)}` → fresh tokens |
| `GET /api/v1/business` | `business.read` | Current business |
| `PATCH /api/v1/business` | `business.update` | Update identity fields |
| `GET /api/v1/business/settings` | `settings.read` | Settings sections |
| `PATCH /api/v1/business/settings` | `settings.update` | Merge-update sections |

Business context behavior: derived server-side from the Bearer token +
fresh DB membership/role lookup. Frontend `business_id` is untrusted input.

## Security notes

- Argon2id hashing; no plaintext/reversible/SHA256 passwords.
- JWT signed, minimal claims, short expiry; secret from env, never hardcoded.
- Refresh tokens opaque + rotated + hashed at rest; reuse revokes family.
- Generic login failures; 401 vs 403 semantics; safe error envelope (no SQL /
  traces / hashes / tokens / DSNs in responses); no password/token logging.
- Server-side authorization + least privilege + deny-by-default + tenant
  isolation tested adversarially.
- TODO (later block, not implemented): login-attempt throttling, refresh-abuse
  rate limits, account lockout/risk controls — services are structured so a
  Redis/DB-backed limiter can wrap `login`/`refresh` without refactoring.

## Development workflow

1. Add ORM model in `app/models/` and export it from `app/models/__init__.py`.
2. `alembic revision --autogenerate -m "..."` then `alembic upgrade head`.
3. Add Pydantic schemas in `app/schemas/`.
4. Add repository functions in `app/repositories/` (SQL only).
5. Add service functions in `app/services/` (logic, calls repositories).
6. Add router in `app/api/v1/endpoints/` and include it in `app/api/v1/router.py`.
7. Add/extend tests, run `pytest`, verify `/health` and `/ready`.

## Known future work (intentionally deferred)

Leads/CRM, customers, bookings, memberships-billing, payments, attendance,
seats, WhatsApp automation, AI agents, analytics/Owner Command Center, Staff
Dashboard UI, notifications, review/revenue intelligence, rate limiting,
settings caching. Next: **Block 2 — Leads + CRM** on this foundation.
