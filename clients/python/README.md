# attested-memory

Python client and CLI for [Attested Memory](https://attestedmemory.net/) — verifiable memory
for AI agents. Every call is signed by your own Ed25519 **actor** key; the private key never
leaves your machine. A memory you read is checked here, on the client, against the
`content_hash` the hub recorded, so a changed text is refused instead of trusted.

```bash
pip install attested-memory
attested-memory init                      # your actor key → ~/.config/attested-memory/actor.json (0600)
attested-memory trial                     # 7-day personal key, bound to that actor
attested-memory write "Supplier terms" "Net 30, EUR, signed 2026-09-01" --tag finance --source contract-17
attested-memory search supplier
attested-memory read mem_…
```

```python
from attested_memory import Actor, Client

actor = Actor.generate()              # or Actor.load("actor.json")
client = Client(actor)
client.start_trial()                  # or Client(actor, api_key="ask_…")
unit = client.write("Supplier terms", "Net 30", tags=["finance"])
client.read(unit["id"])               # raises IntegrityError if the text does not match its hash
```

What is checked where:

| | where |
|---|---|
| your identity (`did:actor:` + SHA-256 of your public key) and a one-time signed proof per request | client signs, server verifies |
| the text of a memory matches its `content_hash` | **this client** |
| `truth` (supported / contested / rejected) and `provenance` (attested receipt) | reported by the hub |

The proof is a signature over `<actor id>\n<unix seconds>\n<nonce>`: good for five minutes and
one request, so a captured header set replays nowhere.

Environment for the CLI: `ATTESTED_MEMORY_HOME`, `ATTESTED_MEMORY_URL`, `ATTESTED_MEMORY_API_KEY`.

Apache-2.0. Source: [alexar76/attested-memory](https://github.com/alexar76/attested-memory) (`clients/python`).
