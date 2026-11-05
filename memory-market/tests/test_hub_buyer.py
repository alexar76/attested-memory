"""Who owns a memory written through the hub (POST /capabilities/.../invoke).

The owner used to be sha256 of X-Payment-Channel. The hub sends that header empty for every
buyer on credits, x402 or a trial, so all of them were one owner and read each other's
private memories. Now the owner is the buyer the hub names in X-AIMarket-Buyer-Ref; without
one a caller reads public memories only and cannot write, share or score.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

import memory_market.app as app_module
from memory_market.models import MemoryCreate
from memory_market.store import MemoryStore

ALICE = "bref-" + "a" * 32
BOB = "bref-" + "b" * 32


@pytest.fixture()
def market(tmp_path, monkeypatch):
    store = MemoryStore(str(tmp_path / "hub-buyer.sqlite3"))
    monkeypatch.setattr(app_module, "store", lambda: store)
    signer = SimpleNamespace(response_headers=lambda *a, **k: {}, pq_public_key=None)
    monkeypatch.setattr(app_module, "provider_signer", lambda: signer)
    return store


def _req(headers: dict | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw})


def _invoke(capability_id: str, payload: dict, headers: dict | None = None) -> dict:
    product_id = app_module.BY_CAPABILITY[capability_id].product_id
    return app_module.invoke_capability(
        product_id, capability_id, {"input": payload}, _req(headers), Response())["result"]


def _as(ref: str) -> dict:
    return {"X-AIMarket-Buyer-Ref": ref}


def test_private_memory_belongs_to_the_named_buyer_only(market):
    unit = _invoke("memory.write@v1", {"title": "wzhik note", "content": "stars fell again",
                                       "visibility": "private"}, _as(ALICE))
    assert unit["owner_id"] == "aimarket:" + ALICE
    assert _invoke("memory.read@v1", {"memory_id": unit["id"]}, _as(ALICE))["id"] == unit["id"]
    found = _invoke("memory.search@v1", {"query": "stars"}, _as(ALICE))
    assert [item["id"] for item in found["items"]] == [unit["id"]]

    # Another buyer, and a caller the hub names nobody (trial, the old empty channel header).
    for headers in (_as(BOB), {}, {"X-Payment-Channel": ""}, {"X-Payment-Channel": "anonymous"}):
        with pytest.raises(HTTPException) as denied:
            _invoke("memory.read@v1", {"memory_id": unit["id"]}, headers)
        assert denied.value.status_code == 403
        assert _invoke("memory.search@v1", {"query": "stars"}, headers)["items"] == []


def test_anonymous_callers_cannot_write_share_or_score(market):
    owned = _invoke("memory.write@v1", {"title": "t", "content": "c"}, _as(ALICE))
    cases = (
        ("memory.write@v1", {"title": "t", "content": "c", "visibility": "public"}),
        ("memory.share@v1", {"memory_id": owned["id"], "grantee_id": "aimarket:x"}),
        ("memory.score@v1", {"memory_id": owned["id"], "score": 5}),
    )
    for headers in ({}, {"X-Payment-Channel": ""}, {"X-AIMarket-Buyer-Ref": "bref-short"},
                    {"X-AIMarket-Buyer-Ref": ALICE.upper()}, {"X-AIMarket-Buyer-Ref": ALICE + "0"}):
        for capability_id, payload in cases:
            with pytest.raises(HTTPException) as denied:
                _invoke(capability_id, payload, headers)
            assert denied.value.status_code == 403, (capability_id, headers)


def test_public_memories_stay_readable_without_a_buyer(market):
    public = market.create(MemoryCreate(title="public incident", content="open",
                                        visibility="public"), "someone")
    assert _invoke("memory.read@v1", {"memory_id": public.id})["id"] == public.id
    assert [i["id"] for i in _invoke("memory.search@v1", {"query": "incident"})["items"]] == [public.id]


def test_owner_can_share_with_another_named_buyer(market):
    unit = _invoke("memory.write@v1", {"title": "handoff", "content": "for bob"}, _as(ALICE))
    _invoke("memory.share@v1", {"memory_id": unit["id"], "grantee_id": "aimarket:" + BOB}, _as(ALICE))
    assert _invoke("memory.read@v1", {"memory_id": unit["id"]}, _as(BOB))["id"] == unit["id"]
