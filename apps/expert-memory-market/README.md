# Expert Memory Market

<p align="center">
  <img src="docs/gallery/hero.svg" alt="Expert Memory Market — buy insight and keep provenance" width="100%">
</p>

<p align="center">
  <img src="docs/badges/ci.svg" alt="CI configured">
  <img src="docs/badges/docker.svg" alt="Docker ready">
  <img src="docs/badges/license.svg" alt="License">
</p>

**Knowledge an agent can verify — and the expert actually gets paid.**

[Live product](https://attestedmemory.net/market) ·
[Implementation guide](https://attestedmemory.net/market/guide) ·
[Use cases](https://attestedmemory.net/market/use-cases) ·
[API contract](docs/api.md) ·
[Deployment](docs/deploy.md)

Version 1 was a storefront with no author side: no publisher, no wallet, no take
rate, no payout. Version 2 adds all of it and writes none of the machinery — that
already exists in [Attested Meter](../attested/attested-meter/), which registers
publishers, splits every captured charge and issues signed payout instructions.

So this service holds **no ledger, no balance and no admin token**. It does three
things.

## Public launch surface

The product is presented as three deliberate journeys rather than one generic
catalog page:

| Audience | Start here | Outcome |
|---|---|---|
| Buyer | [Market landing](https://attestedmemory.net/market) | Inspect public evidence, then choose a pass or a metered read |
| Publisher | [Implementation guide](https://attestedmemory.net/market/guide) | Register in Meter, price owned memory and track the publisher split |
| Integrator | [Use cases](https://attestedmemory.net/market/use-cases) | Add governed expert context to a human or autonomous-agent workflow |

All three surfaces switch between English, Russian, Spanish, Brazilian
Portuguese, German, French, Japanese, Korean, Simplified Chinese and Turkish.
The catalog itself remains keyless; paid content does not.

## 1. Ranks by what the network knows

Listings are ordered by a score built only from fields the catalogue already
publishes, and every listing carries its own `rank_reasons` breakdown:

| Signal | Weight |
|---|---|
| Truth state | `supported` scales with confidence; `contested` costs; `rejected` costs more |
| Provenance | attested, plus a little more for a lineage root |
| Ratings | confidence-weighted — one five-star rating is not evidence, ten are some |
| Freshness | small, decaying over 180 days |

A refuted claim ranks **below** an unverified one. Being wrong is worse than being
unproven, and popularity is not a signal here at all — it is the one a seller can
manufacture.

## 2. Meters reads, so the split is exact

```
POST /v1/read      x-meter-key: amk_…
```

The charge is **reserved before the fetch and captured only if the Memory Market
actually served the content** — including the case where it answers `200` with a
paywall notice instead of a body. A read that was refused is released, not billed.
That ordering is the whole contract: charge after delivery and an upstream `503`
becomes someone's money.

The buyer's own Meter key does the paying, so this service never holds a balance.

## 3. Tells an expert how to get paid, in the order they do it

```
GET /v1/publishing
```

```bash
# 1. register with your own signed identity — no operator involved
POST https://meter.attestedmemory.net/v1/publishers
     {"label": "your desk", "payout_address": "0x… on Base"}

# 2. price your memory with the key you were just given
POST https://meter.attestedmemory.net/v1/publishers/me/prices
     {"operation": "expert.read:<memory_id>", "price_usdc": "2.00"}

# 3. it is purchasable here; every capture accrues your share
POST https://attestedmemory.net/market/v1/read

# 4. watch what you earned
GET  https://meter.attestedmemory.net/v1/publishers/me
```

70 / 30 by default, 85 / 15 with a Publisher Pro key. Above the minimum the
operator issues a signed `attested.payout/v1` instruction and records the payout
transaction hash against it.

**A publisher key can only price its own operations.** An operation owned by
another publisher, or by the platform (`memory.read` has no publisher at all), is
refused — otherwise one key could reprice a competitor or divert the platform's
own metered reads.

## What the flat pass does and does not do

The 7-day pass keeps working exactly as before, and it **does not split to
publishers**. A flat fee cannot be attributed to an author without inventing the
attribution. It buys access to the storefront; the per-read path is what pays the
author, and `/v1/listings` says which is which per item (`pays_publisher`).

## Surfaces

| Route | Auth | Purpose |
|---|---|---|
| `GET /v1/listings` | none | ranked, priced, with the ranking's own working |
| `GET /v1/listings/{id}` | none | one listing; never returns the content it sells |
| `POST /v1/read` | buyer's Meter key | metered read, reserve → fetch → capture/release |
| `GET /v1/publishers/{id}` | none | a publisher's public earnings, proxied from Meter |
| `GET /v1/publishing` | none | the four steps |
| `GET /api/listings` | SaaS pass key | the v1 surface, unchanged |

## Run it

```bash
python -m venv .venv && ./.venv/bin/pip install -e .
MEMORY_MARKET_URL=… METER_URL=https://meter.attestedmemory.net \
  ./.venv/bin/uvicorn expert_market.app:app --port 9430
./.venv/bin/python -m pytest -q        # 16 tests, no network
```

`METER_URL` unset means the storefront still lists and ranks, but nothing is
purchasable per read — which is exactly what `/v1/listings` then reports, per item.
