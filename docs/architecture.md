# Architecture

## Product boundary

`memory-market` owns the customer-facing object and access policy. It stores the actual memory content. `truth-layer` receives claims and explicit evidence supplied for verification. `provenance-ledger` receives hashes and lineage metadata, not private memory content.

```text
                           +---------------- AIMarket Alien Monitor
                           |
AIMarket Hub :9084 --------+---------------- Independent Alien Monitor
  | signed ecosystem.nodes
  |
  +-- memory-market :8810  ---- claim + evidence ----> truth-layer :8811
  |        |                                            (4 capabilities)
  |        +-- durable memory, grants, ratings --> SQLite
  |        +-- finalized USDC Transfer ----------> access grant
  |                    ^
  |                    +---- Base RPC (read-only; funds go to operator wallet)
  |
  +---------------------------------------------> provenance-ledger :8812
                  content hash + source refs          (3 capabilities)
```

All cross-service calls are HTTP and optional. A memory can still be written when a trust service is temporarily unavailable; its state remains `unverified` or `unattested` and can be reconciled later. The market never invents a successful verification or attestation.

## One object, three concerns

- Memory: content, metadata, access, price, retrieval and rating.
- Truth: claims, evidence, contradictions, confidence and reproducible evidence packs.
- Provenance: source references, parent memories, transformation steps, hash-chain position and signature.

Identifiers are opaque and service-scoped. Content integrity is SHA-256 over UTF-8 bytes. Provenance receipts are canonical JSON signed with both Ed25519 and ML-DSA-65 and linked through a per-memory append-only chain.

## Hub and federation

The bundled Hub comes from an exact pinned AIMarket Hub commit. Each service registers with a distinct publisher token and exposes an AI Market v2 manifest plus request-bound signed invoke responses. The Hub derives three owned child nodes from those publisher identities and publishes them in its signed discovery document.

The federation bootstrap announces the public Hub URL independently to the AIMarket and Independent roots. Announcement creates a pending peer; it never bypasses root-side approval or key pinning. Alien Monitor discovers the Hub and its service topology from federation data, so there are no static monitor-specific node definitions to drift.

## Deployment

The three folders are intentionally separate build contexts. They can be deployed together with the root Compose file or independently. No service imports source code from another service. The JSON contracts in `contracts/` are the integration boundary.

## Next production slices

1. Tenant identity and scoped API keys.
2. Embedding provider adapter and hybrid search.
3. Durable verification jobs and reconciliation queue.
4. Optional Hub-level x402/escrow integration and publisher revenue splitting; direct Base USDC settlement is already implemented in Memory Market.
5. Encrypted content storage and per-grant key wrapping.
6. Automated rotation and pinning workflow for Ed25519 and ML-DSA-65 federation identity.
