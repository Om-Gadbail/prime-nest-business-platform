#!/usr/bin/env bash
# Health gate: /health must be ok AND /ready must be 200. Non-zero on any failure.
set -euo pipefail
API="${API_BASE_URL:-${VITE_API_BASE_URL:-http://localhost:8000}}"
echo "Probing $API ..."
H="$(curl -fsS -m 10 "$API/health")"; echo "$H"
echo "$H" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' || { echo "HEALTH FAILED"; exit 1; }
RCODE="$(curl -sS -o /tmp/ready.json -w '%{http_code}' -m 15 "$API/ready")"
cat /tmp/ready.json; echo
test "$RCODE" = "200" || { echo "READINESS FAILED (HTTP $RCODE)"; exit 1; }
echo "HEALTH+READY OK"
