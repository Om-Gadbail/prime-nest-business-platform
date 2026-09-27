# Multi-Business Architecture (Prompt 2 — actual implementation)

```
                    ONE SHARED FASTAPI BACKEND
             backend/app/main.py:create_app()  ·  /api/v1 (160 routes)
                                  |
                    -------------------------------
                    |              |              |
                    v              v              v
               platform_db     prime_db       nest_db
```

ONE codebase · ONE FastAPI app · ONE auth system · ONE RBAC system · ONE
business registry · ONE user identity · ONE platform control plane ·
SEPARATE business operational databases (logical today, physical on cutover).

## Business registry (canonical, in `businesses`)

| Business | business_id (`external_id`) | slug | database | status |
|---|---|---|---|---|
| PRIME FITNESS | `prime-fitness-001` | `prime` | `prime_db` | active |
| NEST LIBRARY | `nest-library-001` | `nest` | `nest_db` | active |

Registry fields: `external_id` (stable platform key), `database_key`
(trusted routing key — server-written, never client input), `config_ref`
(informational). Added by Alembic `0008_multibusiness_foundation` (additive
only; chain stays linear). Repository: `get_by_slug` / `get_by_external_id` /
`list_all`.

## What changed in Prompt 2 (code)

- `app/models/business.py` — registry columns.
- `app/core/db_routing.py` (new) — allowlist, per-key engines/pools,
  request-scoped sessions, `tenant_redis_key`, `validate_business_job_scope`.
- `app/core/config.py` — `PLATFORM/PRIME/NEST_DATABASE_URL` (empty =
  co-located fallback), owner-seed settings.
- `app/services/business_context.py` — `BusinessContext` gains
  `database_key` + `access_scope` + slug/external-id accessors; `for_staff`
  and `for_public` fail closed on bad mappings.
- `app/api/deps.py` — mapping choke point behind all permission gates.
- `app/services/owner.py` — combined view bounded by explicit memberships
  (Attack #15 fixed); `app/api/v1/endpoints/owner.py` audits combined reads.
- `app/services/seed.py` — registry backfill + idempotent unified owner.
- `app/services/scheduler.py` — job-scope validation before every sweep.
- `app/services/health.py` — `/ready` reports per-key status (no leaks).
- `migrations/0008` — registry columns + backfill + unique index.
- `docker-compose.yml` / `.env.example` — split-ready config, co-located
  defaults.

## What did NOT change

- All 160 routes, request/response schemas, auth mechanics (Argon2id, JWT +
  rotated refresh family), RBAC matrix, public-intake pipeline, audit
  vocabulary, scheduler/worker topology. No frontend changes.
- No `DROP TABLE`, no truncation, no history rewrite, no data deletion.
  Old shared `app_db` is untouched and remains the co-located store.

## Topology modes

- **Co-located (today, default):** per-key URLs unset → every key shares
  `DATABASE_URL`. One physical DB, row-level isolation, routing live.
- **Split (cutover):** distinct per-key URLs → independent engines, pools,
  credentials per database. Flip config after the data-migration runbook
  (`docs/database-migration-report.md`); no code changes.

## Future businesses

Provisioning = create business row (with `external_id` + mapped
`database_key`) → run schema → seed config → create memberships → activate.
No new backend, auth, RBAC, or owner account. The provisioning factory itself
is a later prompt; the foundation (registry + mapping + fail-closed routing)
is what this document describes.

## Deliberately NOT introduced

PostgreSQL RLS (separate databases are the isolation boundary; RLS would add
untested complexity), microservices/service mesh, event sourcing, distributed
transactions, new brokers, or a parallel permission system.
