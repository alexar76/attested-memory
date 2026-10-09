# Deployment

Run the shell behind TLS and an edge rate limiter. Keep the Gateway and Memory
Market private; only the product edge should be reachable by clients.

Required variables:

- `MEMORY_MARKET_URL`;
- `MEMORY_MARKET_API_KEY`;
- `SAAS_GATEWAY_URL`;
- `SAAS_GATEWAY_API_KEY`.

The Gateway stores PostgreSQL membership state. The Hub production profile uses
PostgreSQL for memory, Truth and Provenance stores. Share the team assertion
secret only between the Gateway and Hub.
