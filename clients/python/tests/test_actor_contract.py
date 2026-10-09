"""The client's actor proof against the Memory Market's own verifier, not a copy of it."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HUB_SRC = Path(__file__).resolve().parents[3] / "memory-market" / "src"
sys.path.insert(0, str(HUB_SRC))
pytest.importorskip("fastapi")
app = pytest.importorskip("memory_market.app")
from fastapi import HTTPException  # noqa: E402

from attested_memory import Actor  # noqa: E402

SETTINGS = SimpleNamespace(api_key="test-key")


def verify(headers: dict[str, str]) -> str:
    return app._production_actor(
        headers["X-Actor-ID"], "Bearer test-key", headers["X-Actor-Signature"],
        headers["X-Actor-Public-Key"], SETTINGS, headers["X-Actor-Timestamp"], headers["X-Actor-Nonce"],
    )


def test_the_server_accepts_the_clients_proof():
    actor = Actor.generate()
    assert verify(actor.proof_headers()) == actor.actor_id
    assert len(actor.actor_id) == 74 and actor.actor_id.startswith("did:actor:")


def test_a_proof_is_good_for_one_request():
    headers = Actor.generate().proof_headers()
    verify(headers)
    with pytest.raises(HTTPException, match="already used"):
        verify(headers)


def test_every_request_gets_a_fresh_nonce():
    actor = Actor.generate()
    assert actor.proof_headers()["X-Actor-Nonce"] != actor.proof_headers()["X-Actor-Nonce"]


def test_someone_elses_id_with_my_key_is_refused():
    mine, theirs = Actor.generate(), Actor.generate()
    headers = {**mine.proof_headers(), "X-Actor-ID": theirs.actor_id}
    with pytest.raises(HTTPException):
        verify(headers)


def test_a_stale_proof_is_refused():
    import time
    with pytest.raises(HTTPException, match="stale"):
        verify(Actor.generate().proof_headers(now=time.time() - 3600))
