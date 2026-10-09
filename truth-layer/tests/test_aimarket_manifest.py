"""What the truth layer registers on the hub."""
from truth_layer.aimarket import BY_CAPABILITY, manifest
from truth_layer.signing import ProviderSigner

WALLET = "0xB73d8Bc93B791510C4733C5C5Ac2015a3c2930Ec"


def test_a_payout_address_lets_the_checks_be_bought_per_call_in_usdc(tmp_path, monkeypatch):
    monkeypatch.setenv("AIMARKET_PAYOUT_ADDRESS", WALLET)
    body = manifest(BY_CAPABILITY["claim.check@v1"], ProviderSigner(str(tmp_path / "key.pem")))
    assert body["payout_address"] == WALLET


def test_no_or_malformed_payout_address_is_left_out(tmp_path, monkeypatch):
    signer = ProviderSigner(str(tmp_path / "key.pem"))
    monkeypatch.delenv("AIMARKET_PAYOUT_ADDRESS", raising=False)
    assert "payout_address" not in manifest(BY_CAPABILITY["claim.check@v1"], signer)
    monkeypatch.setenv("AIMARKET_PAYOUT_ADDRESS", "not-a-wallet")
    assert "payout_address" not in manifest(BY_CAPABILITY["claim.check@v1"], signer)
