import contextvars
from types import SimpleNamespace

from truth_layer.db import Database
from fastapi import Response
import truth_layer.app as app_module


def test_postgres_transaction_executes_on_checked_out_connection():
    calls = []

    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            return "cursor"

    db = object.__new__(Database)
    db._pool = object()
    db._tx = contextvars.ContextVar("truth_layer_test_tx", default=None)
    db._tx.set((object(), Connection()))

    assert db.execute("SELECT ?", (7,)) == "cursor"
    assert calls == [("SELECT %s", (7,))]


def test_health_fails_with_503_when_database_is_down(monkeypatch):
    class Connection:
        is_postgres = True

        def execute(self, *_args):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(app_module, "store", lambda: SimpleNamespace(connection=Connection()))
    monkeypatch.setattr(app_module, "provider_signer", lambda: SimpleNamespace(pq_public_key="pq"))
    response = Response()
    payload = app_module.health(response)
    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == {"backend": "postgresql", "healthy": False}
