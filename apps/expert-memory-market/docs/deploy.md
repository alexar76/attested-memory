# Deployment

Run the shell behind TLS and an edge rate limiter. Keep the Gateway, KOVA and
Memory Market services on private networks.

Required variables:

- `MEMORY_MARKET_URL`;
- `MEMORY_MARKET_API_KEY`;
- `SAAS_GATEWAY_URL`;
- `SAAS_GATEWAY_API_KEY`;
- `METER_URL` — required for pricing, metered reads and publisher lookup;
- `EXPERT_PUBLIC_ORIGIN` — canonical public API origin, normally
  `https://attestedmemory.net/market`.

Production settlement is non-custodial: KOVA verifies canonical USDC on Base,
while the market receives only the scoped entitlement result.

## Production checks

1. `GET /healthz` reports `version: 2.0.0` and `metering: true`.
2. `GET /v1/listings` works without a buyer key and never exposes paid content.
3. A rejected test read releases its Meter reservation; it is not captured.
4. The pass routes reject a missing, expired or wrong-product `X-SaaS-Key`.
5. `/market`, `/market/guide` and `/market/use-cases` return `200` behind TLS.
6. `robots.txt`, `sitemap.xml`, canonical metadata and social preview images are
   reachable from the public origin.

Use `scripts/verify_live.py` from the SaaS Gateway package for a non-paying
end-to-end check. It creates short-lived trial fixtures and an unpaid invoice;
it never signs or broadcasts a wallet transaction.
