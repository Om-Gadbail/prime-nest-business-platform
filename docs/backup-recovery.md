# Backup & Recovery Readiness (Prompt 8)

Honest status labels: READY / CONFIGURED / DOCUMENTED / NOT CONFIGURED.

## 1. PostgreSQL

- Strategy (DOCUMENTED, NOT CONFIGURED by this repo): nightly `pg_dump -Fc`
  of each database (`platform_db/prime_db/nest_db` or the single co-located DB),
  off-site copy, 30-day retention, restore drill monthly.
- Compose volume `pgdata` is persistence, NOT a backup (NOT CONFIGURED as backup).
- Restore: `pg_restore -d <url> <latest.dump>`, then `alembic upgrade head`,
  then verify `/ready` + owner combined counts + dead-letter empty.
- Migration safety: `migrate` service runs `alembic upgrade head` once per
  `compose up` (upgrade-only, never destructive); new migrations must be
  additive + reversible where practical (DOCUMENTED).

## 2. Redis

- `redisdata` uses AOF (`--appendonly yes`) — crash recovery aid only.
- Authoritative data: Postgres. Redis holds rate-limit counters, scheduler
  leases (expiring) — all rebuildable (DOCUMENTED). Loss impact: throttle
  counters reset (fail open briefly), one duplicate scheduler tick absorbed
  by automation idempotency.

## 3. What is authoritative vs rebuildable

| Data | Status |
|---|---|
| Postgres rows (users, businesses, leads, bookings, payments, automation, comms, audit) | AUTHORITATIVE — must be backed up |
| Redis counters/leases | REBUILDABLE (expire) |
| Daily reports / analytics snapshots | REBUILDABLE (recomputed from source rows) |
| Frontend bundles | REBUILDABLE (`npm run build`) |

## 4. Worker / scheduler recovery

- Both are stateless; restart replays from DB (`queued/retrying` drain,
  stale `running>30m` reclaim). No manual intervention beyond `compose restart
  worker scheduler` (READY — code path tested).
- `docker compose up` ordering: `db → redis → migrate → backend → worker/
  scheduler` via health conditions (CONFIGURED).

## 5. Secrets recovery

- Secrets live ONLY in server env / `.env` (git-ignored, never committed).
- Recovery requires the operator's secret store (NOT CONFIGURED here — no
  committed secrets, no vault integration). Loss of `SECRET_KEY`/
  `JWT_SECRET_KEY` invalidates all sessions (forced re-login); loss of
  webhook secrets requires provider-dashboard rotation.

## 6. Disaster-recovery checklist

1. Provision Postgres + Redis (compose or managed).
2. Restore latest `pg_dump` dump; run `alembic upgrade head`.
3. Inject secrets via env (never from git).
4. `docker compose up --build`; verify `/health`, `/ready`, five frontends.
5. Drain check: automation dead-letter empty or triaged; audit tail clean.
6. Rotate any exposed credentials before going live.
