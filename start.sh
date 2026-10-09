#!/usr/bin/env sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"

for command in docker git openssl; do
  command -v "$command" >/dev/null 2>&1 || { echo "$command is required" >&2; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required" >&2; exit 1; }

./bootstrap-upstreams.sh
./scripts/ensure_env.sh

docker compose up -d --build --force-recreate

echo "Attested Memory console: http://localhost:${MEMORY_MARKET_PORT:-8810}"
echo "AIMarket Hub:           http://localhost:${AIMARKET_HUB_PORT:-9084}"
echo "Truth API:               http://localhost:${TRUTH_LAYER_PORT:-8811}/docs"
echo "Provenance API:          http://localhost:${PROVENANCE_LEDGER_PORT:-8812}/docs"
echo "Payments: set PAYMENT_RECIPIENT in .env to your public Base wallet; no private key is used."
echo "Federation: set AIMARKET_PUBLIC_HUB_URL to public HTTPS; both roots are preconfigured."
