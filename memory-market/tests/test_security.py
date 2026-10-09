from types import SimpleNamespace
import contextvars

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


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_production_actor_is_bound_to_ed25519_public_key():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    actor = "did:actor:" + hashlib.sha256(public).hexdigest()
    timestamp = str(int(time.time()))
    nonce = _b64(os.urandom(18))
    signature = _b64(private.sign(f"{actor}\n{timestamp}\n{nonce}".encode()))
    settings = SimpleNamespace(api_key="k" * 32)

    auth = "Bearer " + settings.api_key
    assert _production_actor(actor, auth, signature, _b64(public), settings, timestamp, nonce) == actor
    # the same proof a second time is a replay
    with pytest.raises(HTTPException) as replay:
        _production_actor(actor, auth, signature, _b64(public), settings, timestamp, nonce)
    assert "already used" in replay.value.detail
    # a proof without time/nonce is the old static bearer and is refused outright
    with pytest.raises(HTTPException):
        _production_actor(actor, auth, _b64(private.sign(actor.encode())), _b64(public), settings)
    # a stale proof is refused even though the signature is valid
    old_ts = str(int(time.time()) - 3600)
    stale = _b64(private.sign(f"{actor}\n{old_ts}\n{nonce}x".encode()))
    with pytest.raises(HTTPException):
        _production_actor(actor, auth, stale, _b64(public), settings, old_ts, nonce + "x")
    with pytest.raises(HTTPException):
        _production_actor("did:actor:" + "0" * 64, auth, signature, _b64(public), settings, timestamp, nonce)


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
