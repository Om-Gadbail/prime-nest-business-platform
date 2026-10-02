# DEPLOY RUNBOOK (zero-time-waste future deploys)

## Normal change

```text
git checkout main && git pull
# make change, run backend tests + worker tests locally
git commit && git push
  -> backend-ci (tests) + worker-deploy (typecheck/test/dry-run/deploy)
  -> VPS: pull image, migrate, health-check, smoke-test -> LIVE
```

Never required: rebuilding the VPS, copying files, editing containers,
reconnecting Neon, recreating the Tunnel, re-pointing frontends, or hand-editing
schemas (migrations only).

## Emergency (one command)

`bash deploy/production/deploy.sh` (or `deploy.ps1` on Windows). Same gates as
CI, fail-fast; `/ready != 200` means FAILED. Roll back with
`bash deploy/production/rollback.sh [TAG]`.

## Human-only actions (owner does these, then we continue)

Only: VPS purchase/login, Cloudflare authorization, domain/Meta/Razorpay/GitHub
approvals, and pasting production secrets into the vault/`wrangler secret put`.
Everything else is automated.
