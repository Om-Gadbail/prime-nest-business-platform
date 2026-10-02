# Health gate (Windows): /health ok AND /ready 200. Non-zero exit on failure.
$ErrorActionPreference = "Stop"
$API = if ($env:API_BASE_URL) { $env:API_BASE_URL } elseif ($env:VITE_API_BASE_URL) { $env:VITE_API_BASE_URL } else { "http://localhost:8000" }
Write-Host "Probing $API ..."
$h = Invoke-RestMethod -Uri "$API/health" -TimeoutSec 10
if ($h.status -ne "ok") { Write-Error "HEALTH FAILED"; exit 1 }
Write-Host "health ok: $($h.app) $($h.version) $($h.env)"
try {
  $r = Invoke-RestMethod -Uri "$API/ready" -TimeoutSec 15
  Write-Host "ready ok: $($r | ConvertTo-Json -Compress)"
} catch {
  Write-Error "READINESS FAILED: $($_.Exception.Message)"; exit 1
}
Write-Host "HEALTH+READY OK"
