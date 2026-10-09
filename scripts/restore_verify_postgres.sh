#!/usr/bin/env sh
set -eu

: "${VERIFY_DATABASE_URL:?VERIFY_DATABASE_URL must point to a disposable PostgreSQL database}"
if [ -n "${DATABASE_URL:-}" ] && [ "$DATABASE_URL" = "$VERIFY_DATABASE_URL" ]; then
  echo "VERIFY_DATABASE_URL must not equal DATABASE_URL" >&2
  exit 1
fi
if [ -n "${DATABASE_URL:-}" ]; then
  production_identity=$(psql "$DATABASE_URL" -AtX -v ON_ERROR_STOP=1 -c \
    "SELECT COALESCE(inet_server_addr()::text, 'local-socket') || ':' || inet_server_port() || '/' || current_database()")
  verify_identity=$(psql "$VERIFY_DATABASE_URL" -AtX -v ON_ERROR_STOP=1 -c \
    "SELECT COALESCE(inet_server_addr()::text, 'local-socket') || ':' || inet_server_port() || '/' || current_database()")
  if [ "$production_identity" = "$verify_identity" ]; then
    echo "VERIFY_DATABASE_URL resolves to the production database; refusing destructive restore" >&2
    exit 1
  fi
fi
dump=${1:?usage: restore_verify_postgres.sh BACKUP.dump}
pg_restore --clean --if-exists --no-owner --dbname="$VERIFY_DATABASE_URL" "$dump"
psql "$VERIFY_DATABASE_URL" -v ON_ERROR_STOP=1 -c "SELECT current_database(), count(*) AS tables FROM information_schema.tables WHERE table_schema='public';"
psql "$VERIFY_DATABASE_URL" -v ON_ERROR_STOP=1 -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
psql "$VERIFY_DATABASE_URL" -v ON_ERROR_STOP=1 -c "SELECT 'restore-ok' AS status;"
