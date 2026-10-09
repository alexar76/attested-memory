# Architecture

```text
client / agent
      │ SaaS key + actor proof + team_id
      ▼
Team Memory shell :9420
      │ membership + five-minute HMAC assertion
      ├── SaaS Gateway   (teams, members, entitlement)
      └── Memory Market  (team:<id> namespace, Truth, Provenance)
```

The shell adds the `team:<id>` tag to writes and forwards the verified boundary
to the Hub for reads and writes.
