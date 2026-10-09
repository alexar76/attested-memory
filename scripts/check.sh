#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/.upstreams/aimarket-hub"
UPSTREAM_PATCH="$ROOT/patches/aimarket-hub-production.patch"
VENDORED_MARKER="$ROOT/.upstreams/.monorepo-vendored"
if [ ! -f "$UPSTREAM/pyproject.toml" ]; then
  echo "Bundled Hub source is missing; run ./bootstrap-upstreams.sh" >&2
  exit 1
fi
if [ ! -f "$VENDORED_MARKER" ]; then
  if [ ! -d "$UPSTREAM/.git" ] || [ ! -f "$UPSTREAM_PATCH" ]; then
    echo "Pinned Hub checkout or production patch is missing." >&2
    exit 1
  fi
  if ! git -C "$UPSTREAM" apply --reverse --check "$UPSTREAM_PATCH" >/dev/null 2>&1; then
    echo "Bundled Hub does not contain the tracked production patch." >&2
    exit 1
  fi
fi
for service in memory-market truth-layer provenance-ledger; do
  echo "==> $service"
  PYTHONPATH="$ROOT/$service/src" python3 -m pytest -q "$ROOT/$service/tests"
done

echo "==> bundled Hub production guard"
if [ -f "$VENDORED_MARKER" ]; then
  PYTHONPATH="$UPSTREAM" python3 -m pytest -q \
    "$UPSTREAM/tests/test_production_postgres_guard.py" \
    "$UPSTREAM/tests/test_supply_operator_publishers.py" \
    "$UPSTREAM/tests/test_mcp_gateway.py"
else
  PYTHONPATH="$UPSTREAM" python3 -m pytest -q \
    "$UPSTREAM/tests/test_production_storage.py" \
    "$UPSTREAM/tests/test_supply_security.py::TestSupplySecurityUnit::test_operator_publisher_bypasses_only_collateral_gate"
fi

echo "==> cross-service contract"
PYTHONPATH="$ROOT/memory-market/src:$ROOT/truth-layer/src:$ROOT/provenance-ledger/src" \
  python3 -m pytest -q "$ROOT/tests"

python3 -m json.tool "$ROOT/contracts/memory-unit.schema.json" >/dev/null
bash -n "$ROOT/scripts/push_gitea_monorepo.sh"
if command -v node >/dev/null 2>&1; then
  node --check "$ROOT/memory-market/static/app.js"
fi
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose --project-directory "$ROOT" --env-file "$ROOT/.env.example" config --quiet
fi
echo "All hub checks passed."
