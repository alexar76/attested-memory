# Security policy

Report suspected vulnerabilities privately to the maintainers with
reproduction steps, affected version and impact. Do not include live keys or
private data in an issue.

Public listing discovery is intentionally keyless and must never include paid
content. Flat-pass routes require a valid product-scoped `X-SaaS-Key`; metered
reads require the buyer's `x-meter-key`. Actor signatures are forwarded when
present for protected Hub operations.

The service never needs a wallet private key and does not persist SaaS, Meter or
publisher credentials. Keep those keys in server-side secret storage, remove
them from logs and traces, and rotate them after suspected exposure. Use TLS, an
authenticated edge, rate limits and private service networks in production.

For per-read access, reserve happens before the Hub fetch and capture happens
only after content is delivered. Every upstream error, refusal or body-less
response must release the reservation. Changes to that ordering are
security-sensitive because they can charge a buyer for failed delivery.
