# Architecture

```text
buyer / agent
      │ public discovery · Meter key per read · or SaaS pass key
      ▼
Expert Market shell :9430
      ├── Memory Market  listing, Truth, Provenance and paid content
      ├── Attested Meter price, reserve, capture/release and publisher split
      └── SaaS Gateway   trial/pass-key introspection

flat pass checkout only
      │ exact canonical USDC
      └── KOVA verifies settlement for the SaaS Gateway
```

The shell is intentionally not a truth oracle. Listings should carry scope,
date, sources and evidence before publication.

Discovery, money and proof stay separate. The Market never stores buyer Meter
keys, publisher keys, balances or payout ledgers. Public detail responses strip
the paid body. A metered charge is reserved before the Hub fetch and captured
only after the Hub returned content; every refused path releases the reserve.

The flat seven-day pass is a storefront entitlement and has no honest
per-publisher attribution. Per-read capture is the publisher-paying path.
