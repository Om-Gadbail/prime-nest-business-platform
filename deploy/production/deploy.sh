#!/usr/bin/env bash
# One-command production deploy (Linux/VPS): tests -> build -> worker -> backend
# -> migrations -> /health -> /ready -> smoke tests. Fails fast, never hides errors.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "== [1/8] git state =="
git status --short --branch
test -z "$(git status --porcelain)" || { echo "REFUSING: working tree is dirty. Commit or stash first."; exit 1; }

echo "== [2/8] backend tests =="
python -m pytest backend/tests -q

echo "== [3/8] worker tests =="
(cd infra/cloudflare/worker && npm test -- --run 2>/dev/null || npm test)

echo "== [4/8] build backend image =="
docker build -t "prime-nest-backend:$(git rev-parse --short HEAD)" ./backend
docker tag "prime-nest-backend:$(git rev-parse --short HEAD)" prime-nest-backend:latest

echo "== [5/8] deploy worker =="
(cd infra/cloudflare/worker && npm run deploy:dry && npm run deploy)

echo "== [6/8] deploy backend =="
(cd deploy/production && docker compose -f docker-compose.production.yml up -d --remove-orphans migrate backend worker scheduler redis cloudflared)

echo "== [7/8] health + readiness =="
./deploy/production/health-check.sh

echo "== [8/8] smoke tests =="
./deploy/production/smoke-test.sh

echo "DEPLOY OK: $(git rev-parse --short HEAD) at $(date -u +%FT%TZ)"
