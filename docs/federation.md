# Federation runbook

## Local verification

1. Run `./start.sh`.
2. Confirm the local Hub discovery document reports `capabilities_count: 12`.
3. Confirm `ecosystem.nodes` contains `memory-market`, `truth-layer`, and `provenance-ledger` with counts 5, 4, and 3.
4. Invoke one capability through the Hub and confirm the provider response includes its classical signature and ML-DSA-65 signature headers.

## Public activation

1. Terminate TLS at a public origin and route it to local port 9084.
2. Set `AIMARKET_PUBLIC_HUB_URL=https://your-origin.example` in `.env`.
3. Restart the stack. `federation-bootstrap` announces the signed discovery URL to both configured roots.
4. In the AIMarket root and the Independent root, review the pending peer, compare its discovery identity from an independent channel, approve it and pin the key.
5. In both Alien Monitors, confirm one Hub sphere and all three owned provider nodes.

The bootstrap retries roots independently with bounded exponential backoff. It does not contain root credentials and cannot approve itself.
