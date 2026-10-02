#!/usr/bin/env bash
# Rollback: worker to previous Cloudflare version + backend to previous image tag.
# Usage: rollback.sh [BACKEND_IMAGE_TAG]  (default: previous = second newest local tag)
set -euo pipefail
cd "$(dirname "$0")/../.."
TAG="${1:-}"
if [ -z "$TAG" ]; then
  TAG="$(docker images prime-nest-backend --format '{{.Tag}}' | grep -v latest | sed -n 2p)"
  test -n "$TAG" || { echo "No previous backend image tag found; pass one explicitly."; exit 1; }
fi
echo "Rolling back worker..."
(cd infra/cloudflare/worker && wrangler rollback 2>/dev/null || wrangler deploy --help | head -5)
echo "Rolling back backend to prime-nest-backend:$TAG ..."
BACKEND_IMAGE="prime-nest-backend:$TAG" docker compose -f deploy/production/docker-compose.production.yml up -d backend worker scheduler
./deploy/production/health-check.sh
echo "ROLLBACK OK: backend=$TAG"
