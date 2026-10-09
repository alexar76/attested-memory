import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "migrate_sqlite_to_postgres.py"
SPEC = importlib.util.spec_from_file_location("migrate_sqlite_to_postgres", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_schema_translation_is_resumable_and_uses_postgres_types():
    translated = MODULE._pg_schema(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, score REAL, payload BLOB)"
    )
    assert translated.startswith("CREATE TABLE IF NOT EXISTS events")
    assert "BIGSERIAL PRIMARY KEY" in translated
    assert "DOUBLE PRECISION" in translated
    assert "BYTEA" in translated
