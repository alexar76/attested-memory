"""The client's actor proof against the Memory Market's own verifier, not a copy of it."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from fastapi import Request
import memory_market.app as market_app
from memory_market.store import MemoryStore

import pytest

HUB_SRC = Path(__file__).resolve().parents[3] / "memory-market" / "src"
sys.path.insert(0, str(HUB_SRC))
pytest.importorskip("fastapi")
app = pytest.importorskip("memory_market.app")
from fastapi import HTTPException  # noqa: E402

from attested_memory import Actor  # noqa: E402

SETTINGS = SimpleNamespace(api_key="test-key")


@pytest.fixture(autouse=True)
def nonce_store(tmp_path, monkeypatch):
    market = MemoryStore(str(tmp_path / "nonces.sqlite3"))
    monkeypatch.setattr(app, "store", lambda: market)


def proof(actor, **kwargs):
    return actor.proof_headers(audience="memory-market", path="/v1/catalog", **kwargs)


def verify(headers: dict[str, str]) -> str:
    request = Request({"type": "http", "method": "GET", "path": "/v1/catalog", "query_string": b"",
                       "headers": [(k.lower().encode(), v.encode()) for k, v in
                                   {**headers, "Authorization": "Bearer test-key"}.items()]})
    return app._production_actor(request, SETTINGS)


def test_the_server_accepts_the_clients_proof():
    actor = Actor.generate()
    assert verify(proof(actor)) == actor.actor_id
    assert len(actor.actor_id) == 74 and actor.actor_id.startswith("did:actor:")


def test_a_proof_is_good_for_one_request():
    headers = proof(Actor.generate())
    verify(headers)
    with pytest.raises(HTTPException, match="already used"):
        verify(headers)


def test_every_request_gets_a_fresh_nonce():
    actor = Actor.generate()
    assert proof(actor)["X-Actor-Nonce"] != proof(actor)["X-Actor-Nonce"]


def test_someone_elses_id_with_my_key_is_refused():
    mine, theirs = Actor.generate(), Actor.generate()
    headers = {**proof(mine), "X-Actor-ID": theirs.actor_id}
    with pytest.raises(HTTPException):
        verify(headers)


def test_a_stale_proof_is_refused():
    import time
    with pytest.raises(HTTPException, match="stale"):
        verify(proof(Actor.generate(), now=time.time() - 3600))
