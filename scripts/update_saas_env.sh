#!/usr/bin/env bash
# Set the Attested SaaS gateway's keys in the shared .env.attested-saas.
#
# The file is SHARED. The Deal/Meter/Prove compose project
# (attested/deploy/compose.yml, deployed by attested/deploy/deploy_attested_saas.sh)
# reads the same one and keeps its admin and service tokens, its
# *_KEY_DERIVATION_SECRETs and its publisher tokens there. Rewriting the file
# whole drops them, and the trio's next deploy mints new derivation secrets —
# every API key and party token it ever issued stops verifying. So this sets
# only the gateway's keys, each in place, and leaves every other line as it is.
#
# usage: update_saas_env.sh <env-file>
#
# MEMORY_MARKET_API_KEY and SAAS_TEAM_AUTH_SECRET come from this hub's .env
# (ATTESTED_HUB_ENV overrides the path); the rest from the environment:
# PUBLIC_SAAS_URL PAYMENT_RECIPIENT KOVA_URL KOVA_API_KEY HUB_NETWORK.
# The file is never sourced, and no value is ever printed.
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "usage: $0 <env-file>"
env_file="$1"
hub_env="${ATTESTED_HUB_ENV:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env}"

for name in PUBLIC_SAAS_URL PAYMENT_RECIPIENT KOVA_URL KOVA_API_KEY HUB_NETWORK; do
  [[ -n "${!name:-}" ]] || die "$name is not set"
done
command -v openssl >/dev/null || die "openssl is required"

# Last assignment wins, as it did when the file was sourced.
get() { sed -n "s/^$1=//p" "$2" 2>/dev/null | tail -n 1; }

[[ -r "$hub_env" ]] || die "hub env not readable: $hub_env"
mm_key="$(get MEMORY_MARKET_API_KEY "$hub_env")"
team_secret="$(get SAAS_TEAM_AUTH_SECRET "$hub_env")"
[[ -n "$mm_key" ]] || die "MEMORY_MARKET_API_KEY is empty in $hub_env"
[[ -n "$team_secret" ]] || die "SAAS_TEAM_AUTH_SECRET is empty in $hub_env"

umask 077
[[ -f "$env_file" ]] || : > "$env_file"

tmp=""
trap '[[ -z "$tmp" ]] || rm -f "$tmp"' EXIT

# Replace KEY's first line in place (dropping any repeats) or append it. The
# value reaches awk through its environment, not argv: -v would expand
# backslashes in it and show it in the process table.
set_key() {
  tmp="$(mktemp "$env_file.XXXXXX")"
  KEY="$1" VALUE="$2" awk '
    BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VALUE"]; done = 0 }
    index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 }; next }
    { print }
    END { if (!done) print k "=" v }
  ' "$env_file" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$env_file"
  tmp=""
}

# An existing secret is kept; a missing or placeholder one is generated.
keep_or_mint() {
  local value
  value="$(get "$1" "$env_file")"
  case "$value" in
    ""|replace-with*|change-me|dev-*)
      value="$(openssl rand -hex 32)"
      echo "  generated $1"
      ;;
  esac
  set_key "$1" "$value"
}

# The file's value wins once it has one: the precedence sourcing it gave. The
# trio reads the same KOVA account from this file, so a stale value in a caller's
# shell must not replace a working one for both.
keep_or() {
  local value
  value="$(get "$1" "$env_file")"
  set_key "$1" "${value:-$2}"
}

set_key AIFACTORY_PROD 1
set_key SAAS_POSTGRES_USER aicom_saas
keep_or_mint SAAS_POSTGRES_PASSWORD
set_key SAAS_POSTGRES_DB saas
keep_or_mint SAAS_GATEWAY_API_KEY
keep_or_mint SAAS_EDGE_TOKEN
keep_or_mint SAAS_KEY_DERIVATION_SECRET
set_key SAAS_RECONCILE_SECONDS 15
set_key SAAS_KEY_REVEAL_HOURS 48
keep_or KOVA_URL "$KOVA_URL"
keep_or KOVA_API_KEY "$KOVA_API_KEY"
set_key SAAS_PAYMENT_RECIPIENT "$PAYMENT_RECIPIENT"
set_key SAAS_TEAM_AUTH_SECRET "$team_secret"
set_key SAAS_PUBLIC_ORIGIN "$PUBLIC_SAAS_URL"
set_key MEMORY_MARKET_URL http://memory-market:8810
set_key MEMORY_MARKET_API_KEY "$mm_key"
set_key ATTESTED_HUB_NETWORK "$HUB_NETWORK"
chmod 600 "$env_file"

echo "saas env updated: $env_file (other keys left as they were)"
