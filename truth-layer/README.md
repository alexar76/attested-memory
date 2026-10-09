# Truth Layer

Deterministic evidence packaging and contradiction indicators for Memory Units.

The service reports what the submitted evidence supports; it does not claim to independently establish real-world truth. Evidence packs are content-addressed and reproducible.

```bash
pip install -e '.[dev]'
uvicorn truth_layer.app:app --port 8811
pytest
```
