from pathlib import Path

from memory_market.aimarket import CAPABILITIES as MARKET_CAPABILITIES
from memory_market.aimarket import signed_protocol_manifest as market_manifest
from memory_market.signing import ProviderSigner as MarketSigner
from provenance_ledger.aimarket import CAPABILITIES as LEDGER_CAPABILITIES
from provenance_ledger.aimarket import signed_protocol_manifest as ledger_manifest
from provenance_ledger.crypto import Signer as LedgerSigner
from truth_layer.aimarket import CAPABILITIES as TRUTH_CAPABILITIES
from truth_layer.aimarket import signed_protocol_manifest as truth_manifest
from truth_layer.signing import ProviderSigner as TruthSigner


def test_hub_surface_has_twelve_unique_capabilities():
    capabilities = (*MARKET_CAPABILITIES, *TRUTH_CAPABILITIES, *LEDGER_CAPABILITIES)
    identifiers = [item.capability_id for item in capabilities]
    assert len(identifiers) == 12
    assert len(set(identifiers)) == 12
    assert identifiers[0] == "memory.write@v1"


def test_each_provider_exposes_a_signed_v2_manifest(tmp_path, monkeypatch):
    monkeypatch.delenv("ATTESTED_PQC_ENABLED", raising=False)
    documents = (
        market_manifest(MarketSigner(str(tmp_path / "market.pem"))),
        truth_manifest(TruthSigner(str(tmp_path / "truth.pem"))),
        ledger_manifest(LedgerSigner(str(tmp_path / "ledger.pem"))),
    )
    assert [document["capabilities_count"] for document in documents] == [5, 4, 3]
    assert all(document["protocol_version"] == "v2" for document in documents)
    assert all(document["signature"]["algorithm"] == "ed25519" for document in documents)
    assert all(document["signature"]["value"] for document in documents)


def test_production_hub_both_emits_and_requires_pq_signatures():
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text()
    assert 'AIMARKET_PQC: "1"' in compose
    assert 'AIMARKET_PQC_REQUIRE: "1"' in compose
    assert "require_pq=False" not in compose
