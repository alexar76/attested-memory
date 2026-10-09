# Alien Monitor integration

No static Alien Monitor node is required. AIMarket's current Monitor discovers this deployment from federation and reads the Hub's signed `ecosystem.nodes` extension.

The root Compose configuration guarantees the required shape:

- Hub identity: `Attested Memory Hub`.
- Owned publishers: `memory-market`, `truth-layer`, `provenance-ledger`.
- Federation announcements: `https://modelmarket.dev` and `https://independentai.network/hub`.
- Each provider publishes at least one invokable capability, so it becomes an owned child node.

Production activation requires:

1. Set `AIMARKET_PUBLIC_HUB_URL` to this Hub's public HTTPS origin.
2. Start the stack and confirm all capability registrations in the local Hub manifest.
3. In both upstream Hubs, approve the pending peer and pin its Ed25519 identity. During PQ migration, also record the ML-DSA-65 public key exposed by this deployment before enabling a per-peer require policy.
4. Confirm the Hub sphere and all three owned provider nodes in both Alien Monitor deployments.

An announcement is intentionally not self-approval. This repository cannot grant itself federation trust.
