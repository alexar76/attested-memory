#!/usr/bin/env bash
# Finish publishing the three Attested providers on their own subdomains.
#
# Everything that does not depend on DNS is already deployed: each provider reads
# AIMARKET_PUBLIC_BASE for its own well-known (falling back to the invoke base, so it is
# inert until set), and nginx serves four read-only paths per name — the well-known, the
# signed manifest, /docs and /openapi.json — with everything else 404. What is left needs
# the A records to exist, so it lives here rather than in a runbook nobody re-reads:
#
#   1. refuse to do anything until all three names resolve to THIS host;
#   2. extend the existing certificate to cover them (certbot --expand);
#   3. tell each provider its public address, and the hub where its providers live;
#   4. recreate the four services and verify the result end to end.
#
# Idempotent: safe to run again, and safe to run early — it exits 0 with a clear message
# when DNS is not ready yet.
set -euo pipefail

ROOT=/opt/aicom/attested/attested-memory-hub

# The three names, in provider order: memory-market, truth-layer, provenance-ledger.
# Overridable because the DEFAULTS ARE A GUESS — they are what this script proposed, not
# what the zone necessarily has. Pass the real ones rather than editing the file:
#
#   ./finish_provider_subdomains.sh mm.example.net tl.example.net pl.example.net
if (( $# == 3 )); then
  NAMES=("$1" "$2" "$3")
elif (( $# == 0 )); then
  NAMES=(memory.attestedmemory.net truth.attestedmemory.net provenance.attestedmemory.net)
else
  echo "usage: $0 [<memory-name> <truth-name> <provenance-name>]" >&2
  exit 2
fi
MEMORY_NAME="${NAMES[0]}" TRUTH_NAME="${NAMES[1]}" PROV_NAME="${NAMES[2]}"
EXPECT_IP=$(curl -s -m 10 https://api.ipify.org || true)
[[ -n "$EXPECT_IP" ]] || { echo "cannot determine this host's public IP" >&2; exit 1; }

echo "this host: $EXPECT_IP"

# Asked of the AUTHORITATIVE nameservers, not a public resolver. Let's Encrypt resolves the
# name itself against authoritative servers, so their answer is what decides whether
# validation succeeds — while a public resolver can hold a stale NXDOMAIN for the zone's
# negative-cache TTL (3601s here) long after the record exists. Checking 8.8.8.8 would have
# refused to proceed for an hour on records that were already live; checking only 1.1.1.1
# could have proceeded on a half-published zone and burned ACME's five-failures-per-hour
# budget. Every nameserver in the delegation must agree.
AUTH_NS=$(dig +short NS attestedmemory.net 2>/dev/null | sed 's/\.$//' | grep -E '\S' || true)
[[ -n "$AUTH_NS" ]] || { echo "cannot find the zone's nameservers" >&2; exit 1; }
missing=0
for n in "${NAMES[@]}"; do
  agree=1 seen=""
  for ns in $AUTH_NS; do
    got=$(dig +short A "$n" @"$ns" 2>/dev/null | grep -E '^[0-9.]+$' | tail -1 || true)
    seen="$seen $ns=${got:-none}"
    [[ "$got" == "$EXPECT_IP" ]] || agree=0
  done
  if (( agree )); then
    echo "  ok       $n -> $EXPECT_IP (all authoritative)"
  else
    echo "  NOT YET  $n:$seen (expected $EXPECT_IP)"; missing=1
  fi
done
if (( missing )); then
  echo
  echo "The zone does not serve these names yet. Add A records pointing at $EXPECT_IP"
  echo "(or one wildcard *.attestedmemory.net), then run this script again. A public"
  echo "resolver may lag by up to the zone's negative TTL; this check does not."
  exit 0
fi

# ── 2. certificate ───────────────────────────────────────────────────────────
# --expand keeps the existing names; certbot reuses the same lineage, so the nginx
# `ssl_certificate` paths that the other three vhosts already point at stay valid.
covered=$(openssl x509 -in /etc/letsencrypt/live/attestedmemory.net/cert.pem -noout -text \
  | grep -A1 "Subject Alternative Name" | tail -1)
need_cert=0
for n in "${NAMES[@]}"; do [[ "$covered" == *"$n"* ]] || need_cert=1; done
if (( need_cert )); then
  echo "extending the certificate…"
  extra=()
  for n in "${NAMES[@]}"; do extra+=(-d "$n"); done
  certbot --nginx --expand --non-interactive --agree-tos --keep-until-expiring \
    -d attestedmemory.net -d www.attestedmemory.net -d hub.attestedmemory.net \
    -d monitor.attestedmemory.net "${extra[@]}"
else
  echo "certificate already covers all three names"
fi

# ── 3. addresses ─────────────────────────────────────────────────────────────
# Two different questions, two different variables. AIMARKET_INVOKE_BASE stays on the
# container network: it is where the hub sends PAID traffic, and routing that out through
# nginx and back would be slower and TLS-dependent for a call that never leaves the host.
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ROOT/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ROOT/.env"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ROOT/.env"
  fi
  echo "  $key set"
}
cp "$ROOT/.env" "$ROOT/.env.bak-$(date -u +%Y%m%d-%H%M%S)"
set_env MEMORY_MARKET_PUBLIC_URL      "https://$MEMORY_NAME"
set_env TRUTH_LAYER_PUBLIC_URL        "https://$TRUTH_NAME"
set_env PROVENANCE_LEDGER_PUBLIC_URL  "https://$PROV_NAME"
set_env AIMARKET_ECOSYSTEM_URLS \
  "memory-market=https://$MEMORY_NAME,truth-layer=https://$TRUTH_NAME,provenance-ledger=https://$PROV_NAME"

# ── 3b. nginx knows the proposed names; teach it the real ones ───────────────
# The vhost was written before the zone existed, so its `server_name`s are the same guess
# as the defaults above. A name nginx does not serve means certbot cannot validate it and
# the address published in step 3 answers from the wrong vhost.
VHOST=/etc/nginx/sites-enabled/attestedmemory.net
for pair in "memory.attestedmemory.net:$MEMORY_NAME" "truth.attestedmemory.net:$TRUTH_NAME" \
            "provenance.attestedmemory.net:$PROV_NAME"; do
  proposed="${pair%%:*}"; actual="${pair#*:}"
  if [[ "$proposed" != "$actual" ]] && grep -q "server_name $proposed;" "$VHOST"; then
    cp "$VHOST" "$VHOST.bak-$(date -u +%Y%m%d-%H%M%S)"
    sed -i "s|server_name $proposed;|server_name $actual;|" "$VHOST"
    echo "  nginx: $proposed -> $actual"
  fi
done
nginx -t >/dev/null 2>&1 || { echo "nginx config broken after renaming — restore from the .bak beside it" >&2; exit 1; }
systemctl reload nginx

# ── 4. apply and verify ──────────────────────────────────────────────────────
cd "$ROOT"
docker compose up -d memory-market truth-layer provenance-ledger hub
sleep 15

echo
echo "── each provider's own well-known now says where it is ──"
fail=0
for n in "${NAMES[@]}"; do
  url=$(curl -fsS -m 20 "https://$n/.well-known/ai-market.json" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["manifest_url"])' 2>/dev/null || echo FAILED)
  echo "  $n: $url"
  [[ "$url" == "https://$n/ai-market/v2/manifest" ]] || fail=1
done

echo
echo "── the hub publishes reachable addresses for them ──"
curl -fsS -m 25 https://hub.attestedmemory.net/.well-known/ai-market.json \
  | python3 -c '
import json, sys, urllib.request
nodes = (json.load(sys.stdin).get("ecosystem") or {}).get("nodes") or []
bad = 0
for n in nodes:
    url = n.get("url") or ""
    try:
        code = urllib.request.urlopen(url + "/.well-known/ai-market.json", timeout=20).status
    except Exception as exc:
        code = "unreachable (%s)" % exc
        bad += 1
    print("  %-20s %-46s %s" % (n.get("id"), url, code))
sys.exit(1 if bad else 0)
' || fail=1

echo
echo "── the write surface is still closed ──"
for pair in "$MEMORY_NAME:memories" "$TRUTH_NAME:verify" "$PROV_NAME:receipts"; do
  n="${pair%%:*}"; path="/${pair#*:}"
  code=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "https://$n$path")
  echo "  $code  $n$path"
  [[ "$code" == "404" ]] || { echo "    ^ EXPECTED 404" >&2; fail=1; }
done

echo
if (( fail )); then echo "FINISHED WITH FAILURES — see above" >&2; exit 1; fi
echo "all three providers are published, discovery-only, and reachable."
