# Architecture

```text
client / agent
      │ X-SaaS-Key + actor proof
      ▼
Personal Memory shell :9410
      │ scoped service calls
      ├── SaaS Gateway   (entitlement)
      └── Memory Market  (memory, Truth, Provenance)
```

The shell does not persist memory content. The Hub remains the system of record.
