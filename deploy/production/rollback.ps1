# Rollback (Windows): worker + backend to a previous image tag.
param([string]$Tag = "")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\\..")
if (-not $Tag) {
  $tags = docker images prime-nest-backend --format "{{.Tag}}" | Where-Object { $_ -ne "latest" }
  $Tag = $tags[1]
  if (-not $Tag) { Write-Error "No previous backend image tag found; pass -Tag explicitly."; exit 1 }
}
Write-Host "Rolling back worker..."
Set-Location infra/cloudflare/worker; wrangler rollback; Set-Location ../../..
$env:BACKEND_IMAGE = "prime-nest-backend:$Tag"
Set-Location deploy/production
docker compose -f docker-compose.production.yml up -d backend worker scheduler
Set-Location ../..
& ./deploy/production/health-check.ps1
Write-Host "ROLLBACK OK: backend=$Tag"
