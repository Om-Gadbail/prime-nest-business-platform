# Final Migration Architecture (Prompt 3 — verified, not assumed)

## Structure: ONE controlled migration chain, applied per database

```
backend/migrations/
  env.py                 # single env; Base.metadata; DATABASE_URL from settings
  versions/
    0001_baseline
    0002_identity_multitenancy
    0003_block2_leads_crm
    0004_block3_tasks_audit_identity
    0005_block5_7_operations
    0006_block8_12_growth_ai
    0007_phase1_hardening_money_ids
    0008_multibusiness_foundation   # ← head (Prompt 2, additive registry)
```

No `migrations/platform/` vs `migrations/business/` split: the schema is
IDENTICAL on all three databases (the split partitions rows, not tables), so
one chain applied per database is the cleanest correct architecture. Rule:

- `app_db` (today, co-located): `alembic upgrade head` → 0008.
- Cutover: `alembic upgrade head` on `platform_db`, `prime_db`, `nest_db`
  each, then row-copy per `docs/database-migration-report.md`.
- New change = new revision; never rewrite history; never delete migrations.

## Verification results (2026-09-28, scratch — no real data touched)

- Single head `0008_multibusiness_foundation` (ScriptDirectory API + test).
- Linear walk head→base covers all 8 revisions, no branches.
- Zero destructive operations in any `upgrade()` (all `drop_table`/
  `drop_column` hits are `downgrade()` rollback paths; 0001 baseline is
  intentionally non-reversible).
- Static drift analysis: all 50 metadata tables and every non-timestamp
  column are mentioned across migration sources — no unexplained drift.
- 0008 applies cleanly on a legacy-shaped scratch schema and backfills
  prime/nest registry rows (automated test).
- Fresh full-chain upgrade on SQLite is NOT a supported path: revisions use
  Postgres DDL (`now()` defaults, UUID binds). Fresh-install validation runs
  through `Base.metadata.create_all`, exercised by the entire 321-test suite
  on isolated SQLite. Live Postgres upgrade remains a deploy-time step with
  backup first (runbook in `docs/database-migration-report.md`).

## Data validation (Prompt 2 rehearsal, still current)

50-table split rehearsal on scratch files: per-table
`source == platform + prime + nest` with zero mismatches and zero orphan
`business_id` values; Prime/Nest row isolation confirmed. Status:
DEV/SCRATCH VERIFIED. Counts: users=1, businesses=2, memberships=2,
leads=5 (3+2), members=2. No new data migration in Prompt 3 (no schema
change required one) — nothing to re-validate.
