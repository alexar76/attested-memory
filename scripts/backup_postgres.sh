#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
dest=${1:-"./backups/aicom-$(date -u +%Y%m%dT%H%M%SZ).dump"}
mkdir -p "$(dirname "$dest")"
umask 077
pg_dump --format=custom --no-owner --file="$dest" "$DATABASE_URL"
pg_restore --list "$dest" >/dev/null
printf 'backup verified: %s\n' "$dest"
