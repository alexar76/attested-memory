# Security policy

Report suspected vulnerabilities privately to the maintainers with
reproduction steps, affected version and impact. Do not include live keys or
private data in an issue.

The service requires a valid scoped `X-SaaS-Key` and a complete actor proof:
`X-Actor-ID`, `X-Actor-Public-Key` and `X-Actor-Signature`. Never send a wallet
seed phrase or private signing key to this service. Put it behind TLS and an
edge rate limiter in production.
