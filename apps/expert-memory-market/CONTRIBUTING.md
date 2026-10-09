# Contributing

Use a focused branch, add tests for changed behavior, and run:

```bash
python -m pytest
python -m compileall src
docker build -t expert-memory-market .
```

Keep payment, entitlement and provenance behavior documented. Never commit
`.env`, API keys, wallet secrets or generated data.
