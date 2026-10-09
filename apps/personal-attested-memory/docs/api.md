# API guide

All memory routes require a product-scoped `X-SaaS-Key` plus the actor proof
headers `X-Actor-ID`, `X-Actor-Public-Key` and `X-Actor-Signature`.

## Write

`POST /api/memories` accepts JSON with `title`, `content`, `tags`,
`visibility`, optional `source_refs`, `price_usdc` and `parent_memory_ids`.

## Search and read

- `GET /api/search?q=incident&limit=30` searches visible catalog metadata;
- `GET /api/memories/{memory_id}` reads one memory subject to Hub policy.

The shell forwards the request to Memory Market, which attaches Truth and
Provenance state where available.
