"""Two gaps an outside review of the pinned revision named (Agent Memory Atlas, 2026-11-24).

* truth.status filtered no read: a memory the Truth Layer rejected came back from search like any
  other. Catalog and memory.search@v1 now leave rejected memories out unless ``truth`` asks for them.
* Reconciliation attests approved hub and REST memories and retries failures without doubling a receipt.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response
from fastapi.testclient import TestClient

import memory_market.app as app_module
from memory_market.models import MemoryCreate
from memory_market.reconcile_provenance import reconcile
from memory_market.store import MemoryStore

ALICE = "bref-" + "a" * 32


@pytest.fixture()
def market(tmp_path, monkeypatch):
    store = MemoryStore(str(tmp_path / "truth.sqlite3"))
    monkeypatch.setattr(app_module, "store", lambda: store)
    signer = SimpleNamespace(response_headers=lambda *a, **k: {}, pq_public_key=None)
    monkeypatch.setattr(app_module, "provider_signer", lambda: signer)
    return store


def _public(approved_memory, store, title, status):
    unit = approved_memory(store, MemoryCreate(title=title, content=title + " body", visibility="public"), "agent:owner")
    if status != "unverified":
        store.set_truth(unit.id, status, 0.9, "pack_" + status)
    return unit


def _invoke(capability_id, payload, headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    product_id = app_module.BY_CAPABILITY[capability_id].product_id
    return app_module.invoke_capability(
        product_id, capability_id, {"input": payload}, Request({"type": "http", "headers": raw}), Response())["result"]


def test_search_leaves_out_rejected_memories_unless_asked(approved_memory, market):
    units = {s: _public(approved_memory, market, f"note {s}", s) for s in ("unverified", "supported", "contested", "rejected")}

    _, default_total = market.catalog("note", None, 20, 0)
    assert default_total == 3
    items, _ = market.catalog("note", None, 20, 0, truth=("supported",))
    assert [i.id for i in items] == [units["supported"].id]
    _, everything = market.catalog("note", None, 20, 0, truth=None)
    assert everything == 4

    hub = _invoke("memory.search@v1", {"query": "note"})
    assert units["rejected"].id not in {i["id"] for i in hub["items"]}
    hub_rejected = _invoke("memory.search@v1", {"query": "note", "truth": "rejected"})
    assert [i["id"] for i in hub_rejected["items"]] == [units["rejected"].id]

    # A rejected memory is still readable by id, with its status, so nothing is hidden from audit.
    read = _invoke("memory.read@v1", {"memory_id": units["rejected"].id})
    assert read["truth"]["status"] == "rejected"


def test_rest_catalog_takes_truth_and_refuses_an_unknown_status(approved_memory, market):
    _public(approved_memory, market, "note a", "supported")
    _public(approved_memory, market, "note b", "rejected")
    client = TestClient(app_module.app)
    assert client.get("/v1/catalog", params={"q": "note"}).json()["total"] == 1
    assert client.get("/v1/catalog", params={"q": "note", "truth": "any"}).json()["total"] == 2
    assert client.get("/v1/catalog", params={"q": "note", "truth": "supported,rejected"}).json()["total"] == 2
    assert client.get("/v1/catalog", params={"q": "note", "truth": "true"}).status_code == 422


def test_hub_write_is_attested_only_after_approval(market):
    calls = []

    class Clients:
        def created_receipt(self, unit):
            return None

        def attest(self, unit, event_type, actor_id, metadata=None):
            calls.append((unit.id, event_type, actor_id))
            return {"id": "rcpt_hub", "chain_root": "a" * 64}

    result = _invoke("memory.write@v1", {"title": "hub note", "content": "written via the hub"},
                     {"X-AIMarket-Buyer-Ref": ALICE})
    assert result["review_state"] == "pending"
    assert reconcile(market, Clients())["unattested"] == 0
    assert calls == []
    market.review(result["id"], "approved", "operator:fixture")
    assert reconcile(market, Clients())["attested"] == 1
    assert calls == [(result["id"], "created", "aimarket:" + ALICE)]
    assert market.get_unchecked(result["id"]).provenance.receipt_id == "rcpt_hub"


def test_reconcile_links_a_landed_receipt_and_attests_the_rest_once(approved_memory, market):
    landed = approved_memory(market, MemoryCreate(title="landed", content="x"), "agent:one")
    missing = approved_memory(market, MemoryCreate(title="missing", content="y"), "agent:two")
    down = approved_memory(market, MemoryCreate(title="down", content="z"), "agent:three")

    class Ledger:
        attested: list = []

        def created_receipt(self, unit):
            return {"id": "rcpt_old", "chain_root": "b" * 64} if unit.id == landed.id else None

        def attest(self, unit, event_type, actor_id, metadata=None):
            if unit.id == down.id:
                return None
            self.attested.append((unit.id, actor_id))
            return {"id": "rcpt_new", "chain_root": "c" * 64}

    ledger = Ledger()
    assert reconcile(market, ledger, write=False) == {"unattested": 3, "linked": 0, "attested": 0, "failed": 0}
    assert reconcile(market, ledger) == {"unattested": 3, "linked": 1, "attested": 1, "failed": 1}
    assert ledger.attested == [(missing.id, "agent:two")]
    assert market.get_unchecked(landed.id).provenance.receipt_id == "rcpt_old"
    assert market.get_unchecked(down.id).provenance.status == "unattested"
    # Run again: only the one the ledger still refuses is left, nothing is attested twice.
    assert reconcile(market, ledger) == {"unattested": 1, "linked": 0, "attested": 0, "failed": 1}
    assert ledger.attested == [(missing.id, "agent:two")]
