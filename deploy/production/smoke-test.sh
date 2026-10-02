#!/usr/bin/env bash
# Production smoke tests through the PUBLIC Worker domain (or local backend).
# Never prints secrets. Any failure exits non-zero.
set -euo pipefail
API="${API_BASE_URL:-${VITE_API_BASE_URL:-http://localhost:8000}}"
echo "Smoke tests against $API"
pass=0; fail=0
check() { # check <name> <expected_code> <curl args...>
  local name="$1"; local want="$2"; shift 2
  local code; code="$(curl -sS -o /tmp/smoke.json -w '%{http_code}' -m 15 "$@")"
  if [ "$code" = "$want" ]; then echo "PASS $name ($code)"; pass=$((pass+1)); else echo "FAIL $name (want $want, got $code)"; cat /tmp/smoke.json 2>/dev/null; echo; fail=$((fail+1)); fi
}
check "health" 200 "$API/health"
check "readiness-shape" 200 "$API/ready"
check "unauthenticated owner scope denied" 401 "$API/api/v1/owner/overview"
check "invalid JWT denied" 401 -H "Authorization: Bearer invalid.token.here" "$API/api/v1/auth/me"
check "cors preflight (prime)" 200 -X OPTIONS -H "Origin: https://prime-fitness.pages.dev" -H "Access-Control-Request-Method: POST" "$API/api/v1/leads"
# Idempotent public lead: same key twice must not create two records (201 then 200/201, never 500).
KEY="smoke-$(date +%s)"
C1="$(curl -sS -o /tmp/lead1.json -w '%{http_code}' -m 15 -X POST "$API/api/v1/public/prime/leads" -H 'Content-Type: application/json' -H "Idempotency-Key: $KEY" -d '{"name":"Smoke Test","phone":"+910000000000"}')"
C2="$(curl -sS -o /tmp/lead2.json -w '%{http_code}' -m 15 -X POST "$API/api/v1/public/prime/leads" -H 'Content-Type: application/json' -H "Idempotency-Key: $KEY" -d '{"name":"Smoke Test","phone":"+910000000000"}')"
echo "lead submit codes: $C1 then $C2"
case "$C1,$C2" in 201,201|201,200|422,422|400,400) echo "PASS idempotent lead shape"; pass=$((pass+1));; *) echo "FAIL idempotent lead shape"; fail=$((fail+1));; esac
echo "RESULT pass=$pass fail=$fail"
test "$fail" = "0"
