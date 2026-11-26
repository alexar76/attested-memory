"""Both services evaluate a stored evidence pack against the current grant."""
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

import memory_market.app as market_app
import truth_layer.app as truth_app
from memory_market.models import MemoryCreate
from memory_market.store import MemoryStore
from truth_layer.engine import verify
from truth_layer.models import VerifyRequest
from truth_layer.store import TruthStore


def test_hub_evidence_pack_respects_current_memory_readers(approved_memory, tmp_path, monkeypatch):
    market = MemoryStore(str(tmp_path / "market.sqlite3"))
    truth = TruthStore(str(tmp_path / "truth.sqlite3"))
    buyer = "bref-" + "a" * 32
    reader = "bref-" + "b" * 32
    owner = "aimarket:" + buyer
    token = "synthetic-internal-capability-secret-" + "x" * 32
    monkeypatch.setenv("MEMORY_MARKET_URL", "http://memory-market.test")
    monkeypatch.setenv("AIMARKET_CAPABILITY_TOKEN", token)
    monkeypatch.setattr(market_app, "store", lambda: market)
    monkeypatch.setattr(truth_app, "store", lambda: truth)
    monkeypatch.setattr(market_app, "production_mode", lambda: True)
    monkeypatch.setattr(truth_app, "production_mode", lambda: True)
    monkeypatch.setattr(truth_app, "provider_signer",
                        lambda: SimpleNamespace(response_headers=lambda *args: {}, pq_public_key=None))
    market_client, truth_client = TestClient(market_app.app), TestClient(truth_app.app)

    def routed_get(url, *, headers, timeout, follow_redirects):
        assert url.startswith("http://memory-market.test/internal/evidence-access/")
        assert not follow_redirects
        return market_client.get(httpx.URL(url).path, headers=headers)

    monkeypatch.setattr(truth_app.httpx, "get", routed_get)
    unit = approved_memory(market, MemoryCreate(title="private note", content="reviewed claim"), owner)
    public = approved_memory(market, MemoryCreate(title="public note", content="public claim", visibility="public"), owner)
    private_pack, public_pack, standalone = [
        verify(VerifyRequest(memory_id=memory_id, claim=claim))
        for memory_id, claim in ((unit.id, unit.content), (public.id, public.content), (None, "standalone claim"))
    ]
    for pack in (private_pack, public_pack, standalone):
        truth.save(pack)

    route = "/capabilities/evidence-pack/evidence.pack@v1/invoke"

    def retrieve(pack, ref=""):
        return truth_client.post(route, json={"input": {"pack_id": pack.id}},
                                 headers={"X-AIMarket-Internal-Token": token, "X-AIMarket-Buyer-Ref": ref})

    assert retrieve(private_pack, buyer).json()["result"]["claim"] == unit.content
    assert retrieve(private_pack, reader).status_code == retrieve(private_pack).status_code == 404
    market.grant(unit.id, "aimarket:" + reader, owner)
    assert retrieve(private_pack, reader).status_code == 200
    market.revoke(unit.id, "aimarket:" + reader, owner)
    assert retrieve(private_pack, reader).status_code == 404
    assert retrieve(public_pack).json()["result"]["claim"] == public.content
    assert retrieve(standalone).status_code == 200
    monkeypatch.delenv("MEMORY_MARKET_URL")
    assert retrieve(private_pack, buyer).status_code == 503
