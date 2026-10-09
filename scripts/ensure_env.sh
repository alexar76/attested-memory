#!/usr/bin/env sh
# Generate or rotate Attested Memory Hub secrets into .env.
# Placeholders from .env.example are treated as missing and replaced.
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

umask 077
if [ ! -f .env ]; then
  : > .env
fi

is_weak_secret() {
  value=$1
  length=${#value}
  case "$value" in
    ""|change-me|dev-secret|dev-only-change-me)
      return 0
      ;;
  esac
  case "$value" in
    replace-with*|*-change-me|dev-*-change-me|dev-gateway*|dev-team*)
      return 0
      ;;
  esac
  if [ "$length" -lt 32 ]; then
    return 0
  fi
  return 1
}

env_get() {
  key=$1
  # shellcheck disable=SC2002
  sed -n "s/^${key}=//p" .env | tail -n 1
}

env_set() {
  key=$1
  value=$2
  tmp=$(mktemp)
  if grep -q "^${key}=" .env 2>/dev/null; then
    awk -v k="$key" -v v="$value" '
      BEGIN { done=0 }
      $0 ~ ("^" k "=") {
        if (!done) { print k "=" v; done=1; next }
        next
      }
      { print }
      END { if (!done) print k "=" v }
    ' .env > "$tmp"
  else
    cat .env > "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  mv "$tmp" .env
  chmod 600 .env
}

ensure_default() {
  key=$1
  value=$2
  current=$(env_get "$key" || true)
  if [ -z "$current" ]; then
    env_set "$key" "$value"
  fi
}

ensure_strong_secret() {
  key=$1
  current=$(env_get "$key" || true)
  if is_weak_secret "$current"; then
    env_set "$key" "$(openssl rand -hex 32)"
    echo "rotated weak/missing secret: $key" >&2
  fi
}

# POSTGRES_PASSWORD is baked into the volume on first init. Never rotate it on
# an existing deployment — that leaves hub/services with a password the volume
# does not accept.
ensure_postgres_password() {
  current=$(env_get POSTGRES_PASSWORD || true)
  if is_weak_secret "$current"; then
    if [ -d data/postgres ] || [ -n "${ATTESTED_POSTGRES_VOLUME:-}" ]; then
      echo "ERROR: POSTGRES_PASSWORD is weak/missing but postgres data already exists." >&2
      echo "       Restore the original password into .env — do not rotate it." >&2
      exit 1
    fi
    env_set POSTGRES_PASSWORD "$(openssl rand -hex 32)"
    echo "generated initial POSTGRES_PASSWORD" >&2
  fi
}

command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }

ensure_strong_secret AIMARKET_ADMIN_TOKEN
ensure_postgres_password
ensure_strong_secret AIMARKET_CAPABILITY_TOKEN
ensure_strong_secret MEMORY_MARKET_PUBLISHER_TOKEN
ensure_strong_secret TRUTH_LAYER_PUBLISHER_TOKEN
ensure_strong_secret PROVENANCE_PUBLISHER_TOKEN
# The Attested SaaS trio publish into the same hub. Each needs its OWN credential:
# the hub keys them by publisher id, so a shared token authenticates as the wrong
# publisher and the registration is refused.
ensure_strong_secret ATTESTED_DEAL_PUBLISHER_TOKEN
ensure_strong_secret ATTESTED_METER_PUBLISHER_TOKEN
ensure_strong_secret ATTESTED_PROVE_PUBLISHER_TOKEN
ensure_strong_secret MEMORY_MARKET_API_KEY
ensure_strong_secret PROVENANCE_ADMIN_TOKEN
ensure_strong_secret SAAS_TEAM_AUTH_SECRET

ensure_default AIMARKET_HUB_PORT "9084"
ensure_default MEMORY_MARKET_PORT "8810"
ensure_default TRUTH_LAYER_PORT "8811"
ensure_default PROVENANCE_LEDGER_PORT "8812"
ensure_default AIMARKET_PUBLIC_HUB_URL "http://localhost:9084"
ensure_default AIMARKET_BOOTSTRAP_HUB_URLS "https://modelmarket.dev,https://independentai.network/hub"
ensure_default AIMARKET_PQC_REQUIRE "1"
ensure_default ATTESTED_PQC_ENABLED "1"
ensure_default ATTESTED_PQC_REQUIRE "1"
ensure_default PAYMENT_RECIPIENT ""
ensure_default PAYMENT_CHAIN_ID "8453"
ensure_default PAYMENT_ASSET "USDC"
ensure_default PAYMENT_USDC_ADDRESS "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
ensure_default PAYMENT_BASE_RPC_URLS "https://mainnet.base.org,https://base.drpc.org,https://gateway.tenderly.co/public/base,https://base-mainnet.public.blastapi.io"
ensure_default PAYMENT_MIN_CONFIRMATIONS "5"
ensure_default PAYMENT_ORDER_TTL_MINUTES "60"
ensure_default PAYMENT_LATE_GRACE_HOURS "24"
ensure_default PAYMENT_POLL_SECONDS "20"
ensure_default PAYMENT_LOG_SCAN_BLOCKS "40"
ensure_default PAYMENT_EXPLORER_URL "https://basescan.org"
ensure_default AIFACTORY_CRYPTO_ENABLED "0"
ensure_default POSTGRES_USER "aicom"
ensure_default POSTGRES_DB "aicom"
ensure_default AIFACTORY_PROD "1"

echo "hub env ready: $project_dir/.env"
