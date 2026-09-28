#!/bin/sh
# Prompt 5 migration entrypoint: fresh/local Docker startup must never hit
# "businesses.external_id does not exist" because migrations were forgotten.
#
# Flow: wait for Postgres -> alembic upgrade head (single replica-safe job
# when run as the `migrate` compose service) -> exec the service CMD.
# Existing databases upgrade in place; no data is destroyed (upgrade only).
set -eu

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

# Parse host/port from DATABASE_URL when set (psycopg URL form).
case "${DATABASE_URL:-}" in
  *@*)
    _rest="${DATABASE_URL#*@}"
    _rest="${_rest%%/*}"
    DB_HOST="${_rest%%:*}"
    case "${_rest}" in
      *:* ) DB_PORT="${_rest#*:}" ;;
    esac
    ;;
esac

echo "[entrypoint] waiting for postgres ${DB_HOST}:${DB_PORT}..."
for i in $(seq 1 60); do
  if python -c "import socket; socket.create_connection(('${DB_HOST}', ${DB_PORT}), timeout=2).close()" 2>/dev/null; then
    echo "[entrypoint] postgres reachable."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "[entrypoint] postgres not reachable after 60s; continuing anyway."
  fi
  sleep 1
done

if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
  echo "[entrypoint] running alembic upgrade head..."
  alembic upgrade head
  echo "[entrypoint] migrations complete."
else
  echo "[entrypoint] SKIP_MIGRATIONS=true; skipping alembic upgrade."
fi

exec "$@"
