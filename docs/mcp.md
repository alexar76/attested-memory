# MCP access

Attested Memory Hub exposes the AIMarket gateway as a streamable HTTP MCP server:

```text
https://hub.attestedmemory.net/mcp
```

The server provides two tools:

- `market_search` discovers Memory Market, Truth Layer, Provenance Ledger and
  federated capabilities.
- `market_invoke` routes one selected capability and returns its signed receipt.

## Safe paid-call flow

1. Call `market_search` with a short intent.
2. Select a result and copy its `product_id`, `capability_id`, `source_hub`, and
   `max_price_usd` unchanged.
3. Call `market_invoke` once. The Hub checks `max_price_usd` atomically before
   provider work or payment. If the route price increased, the call fails with
   `price_limit_exceeded` and MCP `isError: true`; the client should search again
   instead of retrying. Payment walls and other rejected invokes use the same
   tool-error signal while keeping their structured details in the text payload.
4. Verify both Ed25519 and ML-DSA-65 layers of the returned receipt when the
   selected provider advertises a post-quantum identity.

Never send an EVM private key or seed phrase to MCP. Payment credentials are
scoped authorizations; the receiving wallet is configured by the operator via
environment variables.

## JSON-RPC smoke test

```bash
curl -sS https://hub.attestedmemory.net/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}'
```

List tools:

```bash
curl -sS https://hub.attestedmemory.net/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

The registry-ready descriptor lives at [`../server.json`](../server.json): the remote
MCP URL and the source repository,
[`alexar76/attested-memory`](https://github.com/alexar76/attested-memory).
