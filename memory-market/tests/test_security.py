from types import SimpleNamespace
import contextvars
import json

import pytest
pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException, Response

from memory_market.app import _production_actor
from memory_market.db import Database
import base64
import hashlib
import os
import time
import memory_market.app as app_module


def test_catalog_entry_exposes_author_without_paid_content_or_private_metadata(tmp_path, monkeypatch):
    from memory_market.models import MemoryCreate
    from memory_market.store import MemoryStore

    market = MemoryStore(str(tmp_path / "summaries.sqlite3"))
    monkeypatch.setattr(app_module, "store", lambda: market)
    paid = market.create(MemoryCreate(title="Expert memory", content="paid-secret-content",
                                      visibility="paid", price_usdc="2"), "owner")
    summary = app_module.catalog_entry(paid.id, None, None).model_dump()
    assert summary["owner_id"] == "owner" and "content" not in summary
    private = market.create(MemoryCreate(title="Private", content="private-secret"), "owner")
    with pytest.raises(HTTPException) as error:
        app_module.catalog_entry(private.id, None, None)
    assert error.value.status_code == 404
    assert app_module.catalog_entry(private.id, "owner", None).id == private.id
    shared = market.create(MemoryCreate(title="Team only", content="team secret",
                                         visibility="shared", tags=["team:team_one"]), "owner")
    for actor, team in ((None, None), ("outsider", None), ("outsider", "team_two")):
        with pytest.raises(HTTPException) as denied:
            app_module.catalog_entry(shared.id, actor, team)
        assert denied.value.status_code == 404
    assert app_module.catalog_entry(shared.id, "member", "team_one").id == shared.id


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_production_actor_is_bound_to_request_destination_and_key(tmp_path, monkeypatch):
    from fastapi import Request
    from memory_market.store import MemoryStore
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    actor = "did:actor:" + hashlib.sha256(public).hexdigest()
    timestamp, nonce = str(int(time.time())), _b64(os.urandom(18))
    intent = _b64(json.dumps([{"audience": "memory-market", "method": "GET", "path": "/v1/catalog",
                             "query": [], "body_sha256": hashlib.sha256(b"").hexdigest()}]).encode())
    signature = _b64(private.sign(f"attested-actor/v2\n{actor}\n{timestamp}\n{nonce}\n{intent}".encode()))
    settings = SimpleNamespace(api_key="k" * 32)
    market = MemoryStore(str(tmp_path / "actor.sqlite3"))
    monkeypatch.setattr(app_module, "store", lambda: market)
    values = {"x-actor-version": "2", "x-actor-intent": intent, "x-actor-id": actor,
              "x-actor-public-key": _b64(public), "x-actor-timestamp": timestamp,
              "x-actor-nonce": nonce, "x-actor-signature": signature,
              "authorization": "Bearer " + settings.api_key}

    def request(**changes):
        return Request({"type": "http", "method": "GET", "path": "/v1/catalog", "query_string": b"",
                        "headers": [(k.encode(), v.encode()) for k, v in (values | changes).items()]})

    assert _production_actor(request(), settings) == actor
    with pytest.raises(HTTPException) as replay:
        _production_actor(request(), settings)
    assert "already used" in replay.value.detail
    for changes in ({"x-actor-version": "1"}, {"x-actor-id": "did:actor:" + "0" * 64},
                    {"x-actor-timestamp": str(int(time.time()) - 3600)}):
        with pytest.raises(HTTPException):
            _production_actor(request(**changes), settings)


def test_payment_ip_budget_is_atomic_and_bounded(tmp_path):
    db = Database(str(tmp_path / "market.sqlite3"), "MISSING_MEMORY_DSN")
    with db:
        db.executescript(
            """
            CREATE TABLE payment_rate_limits (
              ip TEXT PRIMARY KEY, minute_start INTEGER NOT NULL,
              minute_count INTEGER NOT NULL, hour_start INTEGER NOT NULL,
              hour_count INTEGER NOT NULL
            );
            """
        )
    assert [db.insert_or_update_rate_limit("127.0.0.1", 1) for _ in range(6)] == [True] * 5 + [False]
    assert db.insert_or_update_rate_limit("127.0.0.1", 3601)


def test_postgres_transaction_executes_on_checked_out_connection():
    calls = []

    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            return "cursor"

    db = object.__new__(Database)
    db._pool = object()
    db._tx = contextvars.ContextVar("memory_market_test_tx", default=None)
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
    payload = app_module.health(response, SimpleNamespace(
        truth_url="http://truth", provenance_url="http://provenance", payment_recipient="",
    ))
    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == {"backend": "postgresql", "healthy": False}



def test_production_gates_resolve_and_bite(monkeypatch):
    """The gates call production_mode() at REQUEST time, not import time — so a missing
    import passed every unit test here and crash-looped the container on the first
    lifespan (2026-09-11). Exercise the real code path under production."""
    from fastapi import Request

    monkeypatch.setenv("AIFACTORY_PROD", "1")
    monkeypatch.delenv("AIFACTORY_DEV", raising=False)
    monkeypatch.setenv("AIMARKET_CAPABILITY_TOKEN", "t" * 64)
    assert app_module.production_mode() is True

    def req(headers: dict) -> Request:
        scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
        return Request(scope)

    app_module.require_capability_access(req({"X-AIMarket-Internal-Token": "t" * 64}))
    with pytest.raises(HTTPException):
        app_module.require_capability_access(req({}))
    monkeypatch.setenv("AIFACTORY_DEV", "1")
    monkeypatch.delenv("AIFACTORY_PROD", raising=False)
    assert app_module.production_mode() is False
    app_module.require_capability_access(req({}))   # dev mode: open, by explicit choice
