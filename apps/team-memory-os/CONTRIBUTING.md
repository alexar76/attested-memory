# Contributing

Use a focused branch, add tests for changed behavior, and run:

```bash
python -m pytest
python -m compileall src
docker build -t team-memory-os .
```

Changes to membership, assertions or namespaces must include a security
regression test. Never commit `.env`, API keys or actor private keys.
