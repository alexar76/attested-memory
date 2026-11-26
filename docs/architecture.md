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
  |        +-- durable memory, grants, ratings --> PostgreSQL (SQLite in development)
  |        +-- finalized USDC Transfer ----------> access grant
  |                    ^
  |                    +---- Base RPC (read-only; funds go to operator wallet)
  |
  +---------------------------------------------> provenance-ledger :8812
                  content hash + source refs          (3 capabilities)
```

Cross-service calls use HTTP. Memory writes can still succeed during a trust service outage and keep the record `unverified` or `unattested`. Hub reads of a pack tied to a Memory Market memory require a current access decision from the market.

REST writes and `memory.write@v1` submit units for operator review. Approved units become eligible for a `created` receipt. `python -m memory_market.reconcile_provenance` looks for a creation receipt in the owner's name and requests one if needed. `--count` reports approved units awaiting attestation.

`--check` requires the receipt and root kept by Memory Market to appear in the ledger chain and verifies the available chain from genesis through its current head. The bundled services share one PostgreSQL database and one role. A writer to that database can alter the ledger and the market's reference together. An independently retained head export lets the operator check an older observation against the current chain.

Search and catalog omit memories the Truth Layer labels `rejected` unless the caller asks for that status or `truth=any`. The operator's review decision is an independent admission control. Operator-rejected values stay withheld on all retrieval paths, including historical requests and `truth=any`.

## Review and temporal retrieval

The operator reviews proposals from a privileged interactive terminal on the Compose host. Keep Docker administrative access with human operators. The agent-facing API and Hub capabilities expose submission and retrieval. Pending proposals stay out of the catalogue, direct reads, evidence retrieval, payment checkout and provenance publication. The migration preserves existing memories as approved.

```sh
docker compose exec memory-market python -m memory_market.review list
docker compose exec memory-market python -m memory_market.review show "$memory_id"
docker compose exec memory-market python -m memory_market.review approve "$memory_id"
```

`reject` records a durable rejection for the producer and the normalized content. The key uses Unicode NFC and collapsed whitespace, with case preserved. The same producer cannot resubmit the value under another title or visibility. Existing copies from that producer are withheld. Other producers keep independent records. Truth Layer evidence scores stay separate from operator decisions. Previously issued purchase orders and payment history remain in billing.

Operators can inspect a memory's access history from the same terminal:

```sh
docker compose exec memory-market python -m memory_market.review grant-history "$memory_id"
```

The history records owner grants and revocations, payment settlements, and payment rollbacks.
Payment events retain the order ID, transaction hash and grant ID when a rollback clears them
from the order. A rollback leaves access available when a separate confirmed payment or a
recorded owner grant still supports it. History covers events written by versions that record
them.

Optional `valid_from` and `valid_until` on a write describe when the fact held. Bounds use timezone-aware RFC 3339. The start is inclusive and the end is exclusive. Omitted bounds are open. The operator can record a correction while retaining the previously recorded interval.

```sh
docker compose exec memory-market python -m memory_market.review validity "$memory_id" \
  --from 2026-01-01T00:00:00Z --until 2026-03-01T00:00:00Z
```

Read and search accept `valid_at` (when the fact applied) and `known_at` (which version of the validity interval the system had recorded by then). Each defaults to the current time. Historical reads still enforce current visibility, access grants and operator rejections. A proposal appears in a historical read only if it had already been approved at `known_at`.

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
3. Durable verification jobs.
4. Optional Hub-level x402/escrow integration and publisher revenue splitting; direct Base USDC settlement is already implemented in Memory Market.
5. Encrypted content storage and per-grant key wrapping.
6. Automated rotation and pinning workflow for Ed25519 and ML-DSA-65 federation identity.
