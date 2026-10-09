# API guide

Expert Memory Market 2.0 has two access contracts. The public and metered
`/v1` contract is for discovery, publisher attribution and pay-per-read. The
backward-compatible `/api` contract is for holders of the flat Expert Pass.

## Public discovery

No buyer credential is required. Paid content is removed from detail responses.

```http
GET /market/v1/listings?q=observability&limit=30
GET /market/v1/listings/{memory_id}
GET /market/v1/publishers/{publisher_id}
GET /market/v1/publishing
GET /market/v1/stats
```

Each listing adds `rank_score`, a complete `rank_reasons` breakdown,
`operation`, `price_usdc`, `publisher_id`, `purchasable` and
`pays_publisher`. Ranking uses only public Truth, provenance, reader-score and
freshness fields.

## Metered read

The buyer supplies their own Attested Meter account key. The Market reserves
the listing price, fetches the memory, then captures only after content was
returned. An upstream refusal or missing content releases the reservation.

```http
POST /market/v1/read
x-meter-key: amk_...
content-type: application/json

{"memory_id":"mem_..."}
```

Successful response:

```json
{
  "memory": {"id": "mem_...", "content": "..."},
  "charge": {"charged_usdc": "2.000000", "publisher_usdc": "1.400000"},
  "operation": "expert.read:mem_..."
}
```

The standard split is 70% publisher / 30% platform. Publisher Pro changes it
to 85% / 15%. The Market does not store the account key, balance or payout
ledger; Attested Meter owns those concerns.

## Flat Expert Pass

These compatibility routes require a live product-scoped `X-SaaS-Key` issued
by the SaaS Gateway after a trial or exact canonical-USDC settlement:

```http
GET /market/api/listings?q=observability&limit=30
GET /market/api/listings/{memory_id}
X-SaaS-Key: ask_...
```

The flat seven-day pass buys storefront access and does not accrue a publisher
share. Use the metered contract whenever exact author attribution matters.

Actor proof headers (`X-Actor-ID`, `X-Actor-Public-Key` and
`X-Actor-Signature`) are forwarded to the Hub when supplied. Never place a
private key in a request.
