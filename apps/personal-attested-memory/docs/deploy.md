# Deployment

The product shell is stateless. Run it behind the SaaS edge or another TLS
reverse proxy and point it at the private Memory Market and Gateway services.

Required variables:

- `MEMORY_MARKET_URL`;
- `MEMORY_MARKET_API_KEY`;
- `SAAS_GATEWAY_URL`;
- `SAAS_GATEWAY_API_KEY`.

Production uses the Hub's PostgreSQL profile. Keep actor signing keys in the
client or agent runtime and keep service credentials in a secret manager.
