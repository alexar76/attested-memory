# Security audit — 2026-09-06

Scope: bundled AIMarket Hub, Memory Market, Truth Layer, Provenance Ledger,
PostgreSQL profile, Base USDC settlement, migration, backup/restore and container
startup configuration.

## Fixed findings

| Severity | Finding | Resolution |
| --- | --- | --- |
| Critical | Service PostgreSQL adapters called `execute` on a transaction tuple, breaking transactional writes in production. | SQL now executes on the checked-out psycopg connection; regression tests cover all three adapters. |
| Critical | Production Hub changes existed only in ignored `.upstreams`, so a clean clone could build the unpatched runtime. | A tracked deterministic patch is applied to the pinned commit and verified by the test script. |
| High | Compose enabled relaxed supply security in production. | The flag is disabled and the startup guard rejects it and all known simulation/payment stubs. |
| High | Disabling relaxed mode also blocked the three bundled first-party providers because they had no external stake. | Exact operator-controlled publisher IDs now use per-publisher credentials and bypass only the collateral gate; all other publishers retain verified-stake enforcement. |
| High | Provenance used only a process-local lock and could fork one memory's chain under multiple workers. | A PostgreSQL row-locked `receipt_heads` table serializes each chain append and is backfilled during migration. |
| High | Health endpoints claimed the database was healthy without querying it. | Every service now probes the database and returns HTTP 503 on failure. |
| High | Restore verification compared DSN text only; two aliases could identify the same production database. | The script compares resolved server address, port and database before destructive restore. |
| Medium | SQLite migration was not safely resumable, over-counted skipped rows and left serial sequences behind imported IDs. | Table creation is idempotent, inserted-row counts are accurate and PostgreSQL sequences are advanced after copy. |
| Medium | Operator bearer comparisons were not consistently constant-time. | Memory Market and Provenance Ledger use constant-time comparison. |
| Medium | Upstream default advertised testnet payments when the production environment omitted the flag. | Compose explicitly selects mainnet semantics and startup rejects an omitted/enabled testnet flag. |

## Verified controls

- PostgreSQL 16 is selected for all production stores; SQLite remains a dev/test fallback.
- Required internal, admin, team and publisher secrets are checked at startup.
- PQ and provider response signatures fail closed in production.
- Base USDC settlement requires the canonical token, exact recipient and amount,
  sufficient confirmations and an unused transaction hash; settlement and grant issuance
  share one database transaction.
- Service ports bind to loopback, application containers are read-only, capabilities are
  dropped and `no-new-privileges` is enabled.
- Unit, service-contract and production-guard tests run from `scripts/check.sh`.

## Deployment controls still owned by the operator

The Compose profile is suitable as an internal application tier, not as a directly exposed
public edge. Before Internet publication, terminate TLS at the SaaS edge, enforce identity,
rate limits and request-size limits there, and keep ports 8810–8812 and 9084 private.

Store signing keys and secrets in a managed secret store or HSM, encrypt database volumes,
send audit logs and metrics to an external system, use authenticated redundant Base RPC
providers, and schedule backups plus restore drills for every distinct DSN. Tenant data
retention, deletion, privacy and abuse-response policies remain operational requirements.
