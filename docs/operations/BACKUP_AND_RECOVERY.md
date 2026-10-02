# BACKUP AND RECOVERY

- **Neon (source of truth):** point-in-time restore from the Neon console
  (`prime-nest-production`, branch `production`); verify head `0008` with
  `alembic current` after restore. Test restores on a branch first, never on
  production directly.
- **Migrations:** `backend/migrations/versions/` in Git is the only schema
  writer. Roll forward with `alembic upgrade head`; downgrades are manual and
  reviewed (never automatic in deploy/rollback).
- **VPS rebuild:** fresh Linux → Docker → `git clone` → restore `.env.production`
  from encrypted backup → `docker compose -f deploy/production/docker-compose.production.yml up -d`
  → `health-check` → `smoke-test`. No manual dashboard state may be load-bearing.
- **Env backup (encrypted, OFF Git):** `gpg -c deploy/production/.env.production`
  stored in the owner vault; rotation procedure: generate → `wrangler secret put`
  (worker) + vault update (VPS) → restart → health-check.
- **Redis:** ephemeral by design (rate limits, leases, queues); rebuilds empty.
  Dead-letter + replay protection state re-derives from the DB.
- **Worker:** `wrangler rollback` or redeploy the pinned Git SHA; versions are
  kept by Cloudflare.
- **Tunnel/DNS:** named Tunnel recreates with `TUNNEL_TOKEN`; DNS records are
  re-attached by `cloudflared`. Keep token + zone IDs in the vault.
- **Git:** all five frontend repos + this platform repo are the recovery set;
  no production-only edits are ever allowed.
