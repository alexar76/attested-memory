# Contributing

Use a focused branch, add tests for changed behavior, and run:

```bash
python -m pytest
python -m compileall src
docker build -t personal-attested-memory .
```

Never commit `.env`, API keys, actor private keys or generated runtime data.
