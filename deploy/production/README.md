# Production deploy README

## One-command deploy

Linux/VPS: `bash deploy/production/deploy.sh`
Windows: `./deploy/production/deploy.ps1`

Gates (fail-fast, in order): clean git → backend tests → worker tests →
backend image build → worker deploy → backend deploy → `/health` → `/ready`
→ smoke tests → summary. If `/ready` is not 200 the deploy is FAILED.

## Everyday commands

- Health: `bash deploy/production/health-check.sh` / `./deploy/production/health-check.ps1`
- Smoke: `bash deploy/production/smoke-test.sh` / `./deploy/production/smoke-test.ps1`
- Rollback: `bash deploy/production/rollback.sh [TAG]` / `./deploy/production/rollback.ps1 -Tag TAG`
- Env: copy `.env.production.example` → `.env.production` (mode 0600, never in Git).

## VPS first boot

1. Provision 1 vCPU / 1–2 GB RAM / 20+ GB Linux near Neon us-east-2 (measure,
   don't theorize). Install Docker + Compose, harden SSH (keys only),
   firewall (only 22/80/443), auto-updates, UTC+NTP, log rotation.
2. `git clone` this repo, place `.env.production`, set `TUNNEL_TOKEN`.
3. `docker compose -f deploy/production/docker-compose.production.yml up -d`
   then `./deploy/production/health-check.sh`.
4. Bind the Worker custom domain, set the five `VITE_API_BASE_URL`s, run smoke
   tests from a laptop against the public Worker URL.
