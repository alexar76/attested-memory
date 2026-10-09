import hashlib

from memory_market.models import MemoryCreate
from memory_market.store import MemoryStore
from provenance_ledger.crypto import Signer
from provenance_ledger.models import AttestationCreate
from provenance_ledger.store import Ledger
from truth_layer.engine import verify
from truth_layer.models import Evidence, VerifyRequest


def test_memory_truth_and_provenance_share_one_object(tmp_path):
    market = MemoryStore(str(tmp_path / "market.sqlite3"))
    provenance = Ledger(str(tmp_path / "provenance.sqlite3"), Signer(str(tmp_path / "signing.pem")))

    memory = market.create(MemoryCreate(
        title="Deployment continuity",
        content="The signed snapshot can restore the agent after a restart.",
        visibility="shared",
        tags=["continuity", "operations"],
        source_refs=["urn:runbook:restore:v3"],
    ), "agent:operator")

    created_receipt = provenance.append(AttestationCreate(
        memory_id=memory.id, event_type="created", content_hash=memory.content_hash,
        actor_id=memory.owner_id, source_refs=memory.source_refs,
    ))
    market.set_provenance(memory.id, created_receipt.id, created_receipt.chain_root)

    excerpt_hash = "sha256:" + hashlib.sha256(b"restore test passed").hexdigest()
    pack = verify(VerifyRequest(
        memory_id=memory.id,
        claim="The signed snapshot can restore the agent after a restart.",
        evidence=[Evidence(
            source_uri="urn:test:restore:2026-09-06", excerpt_hash=excerpt_hash,
            stance="supports", quality=0.95,
        )],
    ))
    market.set_truth(memory.id, pack.result.status, pack.result.confidence, pack.id)
    verified_receipt = provenance.append(AttestationCreate(
        memory_id=memory.id, event_type="verified", content_hash=memory.content_hash,
        actor_id="truth-layer", metadata={"evidence_pack_id": pack.id, "status": pack.result.status},
    ))
    market.set_provenance(memory.id, verified_receipt.id, verified_receipt.chain_root)

    final = market.get_unchecked(memory.id)
    assert final.truth.status == "supported"
    assert final.provenance.receipt_id == verified_receipt.id
    assert verified_receipt.previous_root == created_receipt.chain_root
    assert provenance.verify(verified_receipt.id).valid is True
