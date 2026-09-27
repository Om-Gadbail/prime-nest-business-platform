# Database Migration Report (Prompt 2)

Status: **DEV/SCRATCH VERIFIED**. Production migration NOT yet performed —
no production database exists in this program stage. Nothing below touched a
real database: all verification ran on disposable SQLite files which were
deleted after the run (paths under the OS temp dir).

## What migration 0008 does (and does not do)

- ADDS `businesses.external_id` (nullable, unique), `businesses.database_key`
  (NOT NULL, default `''`), `businesses.config_ref` (nullable).
- BACKFILLS `prime` → (`prime-fitness-001`, `prime_db`) and `nest` →
  (`nest-library-001`, `nest_db`) via idempotent UPDATEs.
- Creates unique index `uq_businesses_external_id`.
- Does NOT: drop/rename any table or column, delete or truncate any row,
  rewrite any prior revision, change any PK/FK, or move any operational row.
- Alembic chain stays linear: single head `0008_multibusiness_foundation`
  (asserted by test).

## Pre-migration record (scratch source `rehearse_app.db`)

Full seed + 3 Prime leads + 2 Nest leads + 1 member per business, 50 tables:

| Table | Source rows |
|---|---|
| `users` | 1 (unified owner) |
| `businesses` | 2 |
| `business_memberships` | 2 |
| `leads` | 5 (3 Prime + 2 Nest) |
| `members` | 2 (1 + 1) |
| all other 45 tables | seed/config rows, counts recorded per table |

## Post-split record (scratch targets)

| Target | Content | Validation |
|---|---|---|
| `platform_db` | 11 platform tables (`users`, `businesses`, `business_memberships`, `auth_sessions`, `roles`, `permissions`, `role_permissions`, `business_relationships`, `persons`, `identity_links`, `audit_events`); users=1, memberships=2 | counts match source |
| `prime_db` | 39 business tables filtered to Prime `business_id`; leads=3 | counts match source |
| `nest_db` | 39 business tables filtered to Nest `business_id`; leads=2 | counts match source |

Per-table reconciliation: all 50 tables `source == platform + prime + nest`
(zero mismatches). Isolation: no `Nest%` lead name in `prime_db`, no `Prime%`
in `nest_db`; zero orphan `business_id` values. **VALIDATION: PASS.**

## Production cutover plan (not yet executed)

1. Backup `app_db` (`pg_dump`) and record row counts + `alembic heads`.
2. `alembic upgrade head` on `app_db` (runs 0008: registry in place, co-located).
3. Create `platform_db` / `prime_db` / `nest_db`; run `alembic upgrade head`
   on each (identical schema; split is by rows, not by schema).
4. Copy rows per `docs/database-domain-classification.md` (platform tables
   whole; business tables partitioned by `business_id`; reject orphans).
5. Re-run the count + isolation reconciliation from this report.
6. Set `PLATFORM/PRIME/NEST_DATABASE_URL`, restart, verify `/ready`
   per-key `up`, run smoke (owner login, both businesses, combined).
7. Keep `app_db` online (untouched) until the split is declared healthy —
   rollback = point URLs back at `app_db`.

## Known warnings

- Cross-database FKs (`businesses.id`, `users.id` referenced from operational
  rows) become application-level invariants after the physical split (Postgres
  cannot enforce cross-DB FKs). Co-located mode keeps DB enforcement.
- The rehearsal ran on SQLite; Postgres-specific verification (pg_dump
  restore, concurrent cutover) is a deploy-time step, not claimed here.
