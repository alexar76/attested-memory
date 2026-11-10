# Actor request proofs v2

Identity-only proofs are refused on protected operations. The old signature over
`actor ID / timestamp / nonce` could be replayed from one product to another to
recover an account key or perform a different operation. Existing Ed25519 actor
identities, paid balances, team memberships and API keys remain valid; clients
must create a new request-bound proof for each operation.

The Python `Client` and first-party Personal/Team browser interfaces generate v2
proofs automatically. Update the client and service together before reopening
protected traffic. There is no fallback accepting old identity signatures for
secret recovery, private reads or mutations.

## Wire contract

Carry the existing five actor headers plus `X-Actor-Version: 2` and
`X-Actor-Intent`. The latter is unpadded base64url of a UTF-8 JSON array containing
one to four explicit targets. Each target has exactly these fields:

```json
{"audience":"memory-market","method":"POST","path":"/v1/memories","query":[],"body_sha256":"<64 lowercase hex characters>"}
```

`path` is the final destination's decoded service path, without its public proxy
prefix. `query` contains decoded `[name, value]` pairs **in request order**,
including repeated names and blank values. Reordering repeated names changes an
operation. `body_sha256` hashes the exact HTTP body bytes, including JSON
whitespace; an empty body hashes the empty byte string. Proxies must preserve the
body or receive an explicit target for the exact transformed bytes. The signature
is Ed25519 over these UTF-8 bytes, with no final newline:

```text
attested-actor/v2\n<actor ID>\n<Unix seconds>\n<nonce>\n<X-Actor-Intent>
```

The actor ID remains `did:actor:` plus the SHA-256 hex digest of its raw public
key. Signatures and public keys are unpadded base64url. Nonces contain 16–64
URL-safe characters. The maximum clock skew is 300 seconds. Each audience may
appear only once in an intent.

## Routing and storage

Default audiences are `attested-deal`, `attested-meter`, `attested-prove`,
`attested-saas-gateway` and `memory-market`. Independently trusted deployments
must set unique `DEAL_ACTOR_AUDIENCE`, `METER_ACTOR_AUDIENCE`,
`PROVE_ACTOR_AUDIENCE`, `SAAS_ACTOR_AUDIENCE` and
`MEMORY_MARKET_ACTOR_AUDIENCE` values and configure their clients accordingly.
The Python `Client` accepts `memory_audience` and `gateway_audience`; direct
`Actor.proof_headers` callers pass their configured audience. Browser deployments
set `window.ATTESTED_ACTOR_AUDIENCES` before loading `actor.js`, mapping default
product names to their deployment audiences.

An audience identifies the recipient deployment, not the caller's chosen Host
header. Never reuse an audience across production and an untrusted test server.

A Personal proxy relays only the final Memory target. A Team operation explicitly
signs two targets: a Gateway membership assertion for one team, and the exact
Memory operation. Neither proxy holds an actor private key or gains authority
to recover keys on another product. A Meter request carrying a Memory intent
cannot authorize Meter account recovery.

Services automatically create `actor_proof_nonces_v2`. Its primary key is
`(audience, actor_id, nonce)`. A unique insert commits before accepting the proof;
expired rows are removed only after the signed timestamp is no longer accepted.
This works across worker processes, restarts and replicas sharing PostgreSQL.
All replicas of one audience must share the same database. The audience column
also permits narrowly signed multi-product flows when products share a database.
No cache eviction or process-local nonce fallback is used.

## Direct Python usage

```python
import json
from attested_memory import Actor

actor = Actor.generate()  # load the existing private identity in production
body = json.dumps({"title": "Context", "content": "Example"},
                  ensure_ascii=False, separators=(",", ":")).encode()
headers = actor.proof_headers(audience="memory-market", method="POST",
                              path="/v1/memories", body=body)
# Send exactly `body`, plus the authorized product/API credential.
```

Tests include cross-product/method/path/body/query replay, reordered duplicate
query parameters, invalid-signature nonce burning, concurrent SQLite and
PostgreSQL workers, restart persistence, real Personal/Team proxy flows, and
browser WebCrypto signatures verified by the Python server. All credentials in
these tests are synthetic. No wallet transaction or external publication is
needed for the migration.
