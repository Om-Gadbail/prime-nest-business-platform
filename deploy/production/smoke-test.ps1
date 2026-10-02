# Production smoke tests (Windows) through the public Worker domain or local backend.
$ErrorActionPreference = "Stop"
$API = if ($env:API_BASE_URL) { $env:API_BASE_URL } elseif ($env:VITE_API_BASE_URL) { $env:VITE_API_BASE_URL } else { "http://localhost:8000" }
Write-Host "Smoke tests against $API"
$fail = 0
function Check($name, $script, $want) {
  try {
    $code = & $script
    if ($code -eq $want) { Write-Host "PASS $name ($code)" } else { Write-Host "FAIL $name (want $want, got $code)"; $script:fail++ }
  } catch { Write-Host "FAIL $name ($($_.Exception.Message))"; $script:fail++ }
}
Check "health" { (Invoke-WebRequest -Uri "$API/health" -TimeoutSec 15).StatusCode } 200
Check "unauth owner denied" {
  try { (Invoke-WebRequest -Uri "$API/api/v1/owner/overview" -TimeoutSec 15).StatusCode } catch { [int]$_.Exception.Response.StatusCode }
} 401
Check "invalid JWT denied" {
  try { (Invoke-WebRequest -Uri "$API/api/v1/auth/me" -Headers @{Authorization="Bearer invalid.token.here"} -TimeoutSec 15).StatusCode } catch { [int]$_.Exception.Response.StatusCode }
} 401
if ($fail -gt 0) { Write-Error "SMOKE FAILED ($fail)"; exit 1 }
Write-Host "SMOKE OK"
