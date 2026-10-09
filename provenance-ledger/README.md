# Provenance Ledger

Append-only, Ed25519-signed lineage for Memory Units. The service stores hashes, source references and transformation metadata; it does not need memory content.

```bash
pip install -e '.[dev]'
uvicorn provenance_ledger.app:app --port 8812
pytest
```

Set `PROVENANCE_ADMIN_TOKEN` before exposing write endpoints. The signing key is created at `PROVENANCE_KEY_FILE` with owner-only permissions when it does not exist.
