# One-command production deploy (Windows, same gates as deploy.sh).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\\..")

Write-Host "== [1/8] git state =="
git status --short --branch
if (git status --porcelain) { Write-Error "REFUSING: working tree is dirty. Commit or stash first."; exit 1 }

Write-Host "== [2/8] backend tests =="
python -m pytest backend/tests -q

Write-Host "== [3/8] worker tests =="
Set-Location infra/cloudflare/worker; npm test; Set-Location ../../..

Write-Host "== [4/8] build backend image =="
$sha = (git rev-parse --short HEAD).Trim()
docker build -t "prime-nest-backend:$sha" ./backend
docker tag "prime-nest-backend:$sha" prime-nest-backend:latest

Write-Host "== [5/8] deploy worker =="
Set-Location infra/cloudflare/worker; npm run deploy:dry; npm run deploy; Set-Location ../../..

Write-Host "== [6/8] deploy backend =="
Set-Location deploy/production
docker compose -f docker-compose.production.yml up -d --remove-orphans migrate backend worker scheduler redis cloudflared
Set-Location ../..

Write-Host "== [7/8] health + readiness =="
& ./deploy/production/health-check.ps1

Write-Host "== [8/8] smoke tests =="
& ./deploy/production/smoke-test.ps1

Write-Host "DEPLOY OK: $sha at $((Get-Date).ToUniversalTime().ToString('u'))"
