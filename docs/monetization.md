# Monetization

The commercial primitive is access to a Memory Unit, not raw storage.

Supported and planned rails:

- subscription for private and team memory;
- direct Base USDC pay-per-read for licensed expert memory (implemented);
- x402 authorization through the bundled Hub (separate, disabled until contracts and verifier are deployed);
- publisher split on marketplace reads;
- verification and evidence-pack fees for high-cost truth workflows.

Paid reads return HTTP `402` unless the caller has an explicit or payment-issued grant. Memory Market implements a non-custodial exact-transfer rail: funds go straight to the operator wallet from `PAYMENT_RECIPIENT`, while the service watches canonical Circle USDC on Base and atomically issues a grant after finality. It validates chain, token, recipient, amount, successful receipt, order age, transaction uniqueness and confirmation depth. Invoice creation and client-submitted tx hashes are never treated as settlement.

The small raw-unit suffix on every quote makes its exact amount an invoice identifier. See [direct payments](payments.md) for setup, API flow, threat model and operational limits.
