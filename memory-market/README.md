# Memory Market

The primary Attested Memory Hub service: durable Memory Units, search, access grants, ratings, trust state and provenance references.

```bash
pip install -e '.[dev]'
MEMORY_MARKET_API_KEY=dev-secret uvicorn memory_market.app:app --port 8810
pytest
```

Open <http://127.0.0.1:8810> for the operator console and `/docs` for the API. Paid records are discoverable but fail closed with `402` until an explicit grant or finalized direct payment exists.

## Direct USDC checkout

Set a public Base receiving address to enable non-custodial settlement:

```bash
PAYMENT_RECIPIENT=0xYourPublicAddress uvicorn memory_market.app:app --port 8810
```

The service creates an exact-amount quote, watches canonical Circle USDC `Transfer` events, waits for finality and atomically grants the quoted actor access. It never needs a wallet private key. The endpoints are under `/v1/billing`; complete configuration and security guidance lives in [the Hub payment guide](../docs/payments.md).
