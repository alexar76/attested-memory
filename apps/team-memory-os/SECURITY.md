# Security policy

Report suspected vulnerabilities privately to the maintainers with
reproduction steps, affected version and impact. Do not include live keys or
private data in an issue.

Every protected request requires a scoped `X-SaaS-Key`, actor headers and a
team assertion issued only to an active member. The service must run behind
TLS and an edge rate limiter. Never send wallet private keys to the service.
