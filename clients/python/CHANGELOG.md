# Changelog

Notable changes to the `attested-memory` Python client. Earlier releases: the git history.

## 0.2.0 — 2026-11-03

### Security
- **Actor proof v2.** Every protected call now signs an explicit operation: the destination service, the HTTP
  method, path and query, and the SHA-256 of the exact request body (`X-Actor-Version: 2`, `X-Actor-Intent`). A
  captured header set cannot be replayed against another route or with another body, and a proxy relaying it gains
  no authority to change the operation. 0.1.0 signed only the actor id, timestamp and nonce.
- The client no longer follows redirects, so the actor proof and `X-SaaS-Key` never reach another host.

### Changed (breaking)
- `Actor.proof_headers()` needs `audience` and `path` (or explicit `targets`); `Actor.target()` builds one target.
  `Client` maps its product routes to the Memory Market and SaaS gateway audiences itself (`memory_audience`,
  `gateway_audience`), so code that only uses `Client` needs no change.
- Request bodies are sent as compact JSON, the same bytes that are signed.
