"""Five gaps our own Agent-Memory-Atlas-style reading found after the 2026-11-25 re-read.

* A payment or verification receipt made an unattested unit ``attested``; reconcile_provenance
  then never added its ``created`` receipt. Only a ``created`` receipt sets ``attested`` now.
* lineage.get@v1 is open to any hub caller, and the payment receipt named the buyer and the
  transaction: anyone could list who bought a paid memory. It now carries a commitment.
* Public lineage omits source references, parent ids and evidence pack identifiers from non-public units.
* The catalogue exposes the evidence pack id only to callers who may read its memory.
* An owner could share a memory but never take the access back. They can now, except access that
  was paid for.
"""
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

import memory_market.app as app_module
import memory_market.clients as clients_module
from memory_market.clients import TrustClients, receipt_refs
from memory_market.models import MemoryCreate, VerifyMemory
from memory_market.store import MemoryStore

ALICE = "bref-" + "a" * 32
BOB = "bref-" + "b" * 32


def sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture()
def market(tmp_path, monkeypatch):
    store = MemoryStore(str(tmp_path / "privacy.sqlite3"))
    monkeypatch.setattr(app_module, "store", lambda: store)
    signer = SimpleNamespace(response_headers=lambda *a, **k: {}, pq_public_key=None)
    monkeypatch.setattr(app_module, "provider_signer", lambda: signer)
    return store


class Recorder:
    """TrustClients' attest and verify, recording what would be sent to the ledger."""

    sent: list = []

    def __init__(self, settings=None):
        pass

    def attest(self, unit, event_type, actor_id, metadata=None):
        Recorder.sent.append({"memory_id": unit.id, "event_type": event_type, "actor_id": actor_id,
                              "source_refs": receipt_refs(unit), "metadata": metadata or {}})
        return {"id": f"rcpt_{len(Recorder.sent)}", "chain_root": sha(str(len(Recorder.sent)))}

    def verify(self, unit, request):
        return {"status": "supported", "confidence": 0.9, "evidence_pack_id": "pack_" + "c" * 24}


@pytest.fixture()
def recorder(monkeypatch):
    Recorder.sent = []
    monkeypatch.setattr(app_module, "TrustClients", Recorder)
    return Recorder


def _invoke(capability_id, payload, headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    product_id = app_module.BY_CAPABILITY[capability_id].product_id
    return app_module.invoke_capability(
        product_id, capability_id, {"input": payload}, Request({"type": "http", "headers": raw}), Response())["result"]


def _paid(approved_memory, store, owner="agent:owner", refs=("https://example.org/private-source",)):
    return approved_memory(store, MemoryCreate(title="paid note", content="the paid part", visibility="paid",
                                     price_usdc="1.00", source_refs=list(refs)), owner)


def test_only_a_created_receipt_marks_a_unit_attested(approved_memory, market, recorder):
    unit = _paid(approved_memory, market)
    order = SimpleNamespace(order_id="ord_1", tx_hash="0xABC", grantee_id="agent:buyer", memory_id=unit.id)
    app_module._attest_payment(order)
    stored = market.get_unchecked(unit.id).provenance
    assert stored.status == "unattested" and stored.receipt_id == "rcpt_1"
    assert [u.id for u in market.unattested()] == [unit.id]
    market.set_provenance(unit.id, "rcpt_2", sha("2"), created=True)
    assert market.get_unchecked(unit.id).provenance.status == "attested"
    # A later non-creation receipt moves the recorded root but keeps the status.
    market.set_provenance(unit.id, "rcpt_3", sha("3"), created=False)
    assert market.get_unchecked(unit.id).provenance.status == "attested"


def test_the_payment_receipt_names_neither_buyer_nor_transaction(approved_memory, market, recorder):
    unit = _paid(approved_memory, market)
    order = SimpleNamespace(order_id="ord_1", tx_hash="0xABC", grantee_id="agent:buyer", memory_id=unit.id)
    app_module._attest_payment(order)
    sent = recorder.sent[0]
    assert sent["actor_id"] == "memory-market:payment"
    flat = repr(sent)
    for secret in ("agent:buyer", "0xabc", "0xABC", "ord_1"):
        assert secret not in flat
    # The buyer, who knows all three, can open the commitment.
    assert sent["metadata"]["settlement"] == sha("ord_1|0xabc|agent:buyer")


def test_receipts_only_include_public_sources_and_parents(approved_memory, market, monkeypatch):
    posted = []

    def fake_post(url, json, headers, timeout):
        posted.append(json)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"id": "r", "chain_root": "x"})

    monkeypatch.setattr(clients_module.httpx, "post", fake_post)
    clients = TrustClients(SimpleNamespace(provenance_url="http://ledger", provenance_token="t"))
    ref = "https://example.org/private-source"
    for visibility in ("public", "paid", "private", "shared"):
        parent = "mem_" + "d" * 24
        unit = approved_memory(market, MemoryCreate(title=visibility, content="body", visibility=visibility,
                                          price_usdc="1.00" if visibility == "paid" else None,
                                          source_refs=[ref], parent_memory_ids=[parent]), "agent:owner")
        clients.attest(unit, "created", "agent:owner")
        assert posted[-1]["source_refs"] == ([ref] if visibility == "public" else []), visibility
        assert posted[-1]["parent_memory_ids"] == ([parent] if visibility == "public" else [])


def test_the_evidence_pack_id_reaches_only_readers(approved_memory, market, recorder):
    paid = _paid(approved_memory, market)
    public = approved_memory(market, MemoryCreate(title="public note", content="open", visibility="public"), "agent:owner")
    for unit in (paid, public):
        app_module.verify_memory(unit.id, VerifyMemory(claim="the paid part is true"), actor_id="agent:owner",
                                 settings=SimpleNamespace())
    pack = "pack_" + "c" * 24

    def pack_seen(actor, unit):
        items, _ = market.catalog("note", actor, 20, 0)
        listed = {item.id: item.truth.evidence_pack_id for item in items}
        entry = app_module.catalog_entry(unit.id, actor_id=actor, team_id=None).truth.evidence_pack_id
        assert listed[unit.id] == entry
        return entry

    assert pack_seen(None, paid) is None and pack_seen("agent:stranger", paid) is None
    assert pack_seen("agent:owner", paid) == pack
    market.grant(paid.id, "agent:reader", "agent:owner")
    assert pack_seen("agent:reader", paid) == pack
    assert pack_seen(None, public) == pack
    # Only the public receipt can identify its evidence pack.
    verified = {s["memory_id"]: s["metadata"] for s in recorder.sent if s["event_type"] == "verified"}
    assert verified[public.id]["evidence_pack_id"] == pack
    assert verified[paid.id] == {"status": "supported", "confidence": 0.9}


def test_an_owner_revokes_access_they_gave_but_not_access_that_was_paid_for(approved_memory, market):
    unit = approved_memory(market, MemoryCreate(title="private", content="body", visibility="private"), "aimarket:" + ALICE)
    _invoke("memory.share@v1", {"memory_id": unit.id, "grantee_id": "aimarket:" + BOB}, {"X-AIMarket-Buyer-Ref": ALICE})
    assert market.can_read(unit, "aimarket:" + BOB)

    with pytest.raises(HTTPException) as denied:  # only the owner
        _invoke("memory.share@v1", {"memory_id": unit.id, "grantee_id": "aimarket:" + BOB, "revoke": True},
                {"X-AIMarket-Buyer-Ref": BOB})
    assert denied.value.status_code == 422 and market.can_read(unit, "aimarket:" + BOB)

    revoked = _invoke("memory.share@v1", {"memory_id": unit.id, "grantee_id": "aimarket:" + BOB, "revoke": True},
                      {"X-AIMarket-Buyer-Ref": ALICE})
    assert revoked["revoked_at"] and not market.can_read(unit, "aimarket:" + BOB)
    market.revoke(unit.id, "aimarket:" + BOB, "aimarket:" + ALICE)
    with pytest.raises(HTTPException) as missing:
        _invoke("memory.share@v1", {"memory_id": unit.id, "grantee_id": "aimarket:nobody", "revoke": True},
                {"X-AIMarket-Buyer-Ref": ALICE})
    assert missing.value.status_code == 404
    # Sharing again restores it.
    _invoke("memory.share@v1", {"memory_id": unit.id, "grantee_id": "aimarket:" + BOB}, {"X-AIMarket-Buyer-Ref": ALICE})
    assert market.can_read(unit, "aimarket:" + BOB)
    events = market.connection.execute(
        "SELECT * FROM memory_grant_events WHERE memory_id = ? ORDER BY occurred_at, id", (unit.id,)
    ).fetchall()
    assert [event["event_type"] for event in events] == ["granted", "revoked", "granted"]
    assert all(event["grant_id"] == revoked["id"] and event["actor_id"] == "aimarket:" + ALICE for event in events)

    # REST, and a grant that a confirmed payment issued.
    paid = _paid(approved_memory, market)
    grant = market.grant(paid.id, "agent:buyer", "agent:owner")
    with market.connection:
        market.connection.execute(
            "INSERT INTO payment_orders (order_id, memory_id, grantee_id, price_usdc, amount_usdc, amount_raw, "
            "recipient, created_at, created_unix, expires_unix, created_block, last_scanned_block, state, grant_id) "
            "VALUES ('ord_p', ?, 'agent:buyer', '1.00', '1.000001', '1000001', '0x0', 'now', 0, 0, 0, 0, 'confirmed', ?)",
            (paid.id, grant.id))
    with pytest.raises(HTTPException) as kept:
        app_module.revoke_memory_grant(paid.id, "agent:buyer", actor_id="agent:owner")
    assert kept.value.status_code == 403 and "paid for" in kept.value.detail
    assert market.can_read(paid, "agent:buyer")
