# Capability catalogue

| Capability | Owner | MVP behavior |
| --- | --- | --- |
| `memory.write@v1` | memory-market | Submits a Memory Unit for operator review. Optional `valid_from` and `valid_until` record fact validity |
| `memory.read@v1` | memory-market | Enforces admission, visibility and grants. Accepts `valid_at` and `known_at` |
| `memory.search@v1` | memory-market | Searches admitted, visible records using `valid_at` and `known_at`. Truth Layer rejections are hidden by default. `truth=any` still enforces operator decisions |
| `memory.share@v1` | memory-market | Creates a read grant; with `revoke: true` the owner withdraws it (REST: `DELETE /v1/memories/{id}/grants/{grantee}`). Access a buyer paid for cannot be revoked by the owner |
| `memory.score@v1` | memory-market | One caller score per memory, aggregated without rewriting history |
| `memory.verify@v1` | truth-layer | Scores supplied evidence and records the result |
| `claim.check@v1` | truth-layer | Alias of the verification contract for standalone claims |
| `contradiction.scan@v1` | truth-layer | Deterministic conflict indicators; not semantic proof |
| `evidence.pack@v1` | truth-layer | Returns a portable content-addressed evidence pack. For a pack tied to a Memory Market id, the Truth Layer checks the caller's current read access with Memory Market before returning the pack |
| `memory.attest@v1` | provenance-ledger | Adds a signed, attributed event to a memory lineage. A named Hub buyer may extend only a chain they started. Memory Market starts the chains for its own ids. Event labels on buyer-started chains express the buyer's assertions |
| `lineage.get@v1` | provenance-ledger | Returns the ordered chain and current root to any caller. For non-public units, new receipts omit source references, parent ids and evidence pack ids. Payment receipts carry a commitment to the order, transaction and buyer |
| `receipt.verify@v1` | provenance-ledger | Verifies canonical payload hash, chain link and hybrid Ed25519 + ML-DSA-65 signatures, that the signing keys are the ledger's own (or listed in `PROVENANCE_TRUSTED_PUBLIC_KEYS` / `PROVENANCE_TRUSTED_PQ_PUBLIC_KEYS` after a rotation), and that the memory's newest stored receipt is the recorded chain head |

Each row is registered as an independent AI Market v2 offer in the bundled Hub. Versioned direct HTTP endpoints are documented by each service at `/docs`; provider manifests are exposed at `/ai-market/v2/manifest`.

Personal and Team users can read the current pack through their product's memory
`/evidence-pack` route. Sign the corresponding Market path
`GET /v1/memories/{memory_id}/evidence-pack` with the same actor proof as a
memory read. Python clients can use `Client.read_evidence(memory_id)` on Personal.

## Automatic publication and promotion

Each provider registers its capabilities with the bundled Hub at startup and
retries while the Hub is unavailable. The Hub then exposes the signed catalog,
includes owned providers in `ecosystem.nodes`, records invocation metrics and
announces its public identity to the configured federation roots.

This is automatic distribution, not automatic trust. Registration requires an
operator-issued scoped publisher token, and every external federation root keeps
a new peer pending until its operator verifies and pins the signing identity.
Social publishing, commercial directories and paid campaigns remain explicit
operator choices; a provider cannot approve itself or spend a marketing budget.

The public integration and manifest-builder workflow is documented at
`https://attestedmemory.net/developers` and in the localized
`attested/docs/i18n/*/DEVELOPER_GUIDE.md` files.
