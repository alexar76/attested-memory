# Security model

This MVP binds published Compose ports to loopback and is not ready for direct Internet exposure.

## Trust boundaries

- Memory content stays in the market database. Provenance stores only hashes and caller-provided source references.
- An attestation proves that this node signed a specific event in a specific chain. It does not prove the underlying claim is true.
- Truth scores are deterministic summaries of submitted evidence. They are not independent fact checking and must not be marketed as such.
- Paid access fails closed while `PAYMENT_RECIPIENT` is empty. No endpoint treats invoice creation or a client-provided transaction hash as settlement.
- Payment settlement is non-custodial: only a public receiving address is configured. An exact canonical USDC `Transfer` on Base must match recipient and order amount, postdate the order, survive the confirmation threshold and have an unused transaction hash. The tx claim and access grant share one database transaction.
- RPC failure fails closed. Late transfers are accepted only within the configured grace window; automated refunds are outside the service boundary.
- Operator endpoints use bearer tokens in the MVP. Put the services behind TLS and an identity-aware gateway before public use.
- Health endpoints execute `SELECT 1` and return HTTP 503 when their database is unavailable; container health no longer reports a false positive.
- Provenance appends lock a per-memory chain head in PostgreSQL, preventing two workers from creating competing successors.

## Post-quantum policy

- Provider manifests, provider invoke responses and provenance receipts are hybrid-signed with Ed25519 and ML-DSA-65 when the Compose stack runs.
- `ATTESTED_PQC_ENABLED=1` and `ATTESTED_PQC_REQUIRE=1` are the local policy: a missing PQ library prevents startup, and receipt verification rejects a stripped PQ signature.
- The bundled AIMarket Hub installs its PQ verifier and fails closed on any PQ signature it receives.
- Production Compose and startup guards force `AIMARKET_PQC_REQUIRE=1`; local development may still use the classical-only federation mode when `AIFACTORY_PROD` is unset.

## Production checklist

- Replace default tokens and keep `.env` out of source control.
- Put both classical and ML-DSA signing keys in a managed secret store or HSM; back them up separately from the ledger.
- Encrypt memory content at rest and isolate tenants.
- Add audit logs, deletion/retention policy and abuse handling.
- Production actor IDs are Ed25519 public-key-bound and payment-order creation has a PostgreSQL-backed per-IP budget in addition to per-actor order caps. Keep an edge WAF/rate limiter as a second layer.
- Use authenticated redundant Base RPC endpoints and alert on scanner lag or repeated range failures.
- Pin outbound trust-service origins and add mTLS or signed service requests.
- Review privacy, data licensing and right-to-delete requirements for every memory source.

The latest code-level review and remaining deployment controls are recorded in
[the security audit](security-audit-2026-09-06.md).
