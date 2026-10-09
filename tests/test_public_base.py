"""Where a provider says it lives, versus where the hub dials it.

`AIMARKET_INVOKE_BASE` is the address the co-located hub calls — a container hostname on a
single-host deploy. All three providers used it to describe THEMSELVES too, so every reader
of `hub.attestedmemory.net`'s ecosystem, and anyone who fetched a provider's own
well-known, was handed `http://memory-market:8810/ai-market/v2/manifest`: a URL that
resolves on exactly one machine in the world.

One variable cannot answer both questions. `AIMARKET_PUBLIC_BASE` answers "where are you"
and falls back to the invoke base, so a deployment that sets nothing is unchanged — which
is the property most of these tests are about, because a silent behaviour change here would
repoint live manifests.

The invoke base must stay INTERNAL: the signed manifest's `base_url` and every capability's
invoke URL come from it, and those are where the hub actually sends paid traffic. Publishing
a public address there would route hub→provider calls out through nginx and back.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from memory_market.aimarket import signed_protocol_manifest as market_manifest
from memory_market.signing import ProviderSigner as MarketSigner
from provenance_ledger.aimarket import signed_protocol_manifest as ledger_manifest
from provenance_ledger.crypto import Signer as LedgerSigner
from truth_layer.aimarket import signed_protocol_manifest as truth_manifest
from truth_layer.signing import ProviderSigner as TruthSigner

PROVIDERS = (
    ("memory_market.app", 8810, "Memory Market", "http://memory-market:8810"),
    ("truth_layer.app", 8811, "Truth Layer", "http://truth-layer:8811"),
    ("provenance_ledger.app", 8812, "Provenance Ledger", "http://provenance-ledger:8812"),
)


def _well_known(module_name: str) -> dict:
    import importlib

    module = importlib.import_module(module_name)
    with TestClient(module.app) as client:
        response = client.get("/.well-known/ai-market.json")
        assert response.status_code == 200
        return response.json()


@pytest.mark.parametrize("module_name,port,name,invoke", PROVIDERS)
def test_public_base_is_what_the_provider_publishes(monkeypatch, module_name, port, name, invoke):
    monkeypatch.setenv("AIMARKET_INVOKE_BASE", invoke)
    monkeypatch.setenv("AIMARKET_PUBLIC_BASE", "https://public.example/")
    document = _well_known(module_name)
    assert document["name"] == name
    assert document["manifest_url"] == "https://public.example/ai-market/v2/manifest"


@pytest.mark.parametrize("module_name,port,name,invoke", PROVIDERS)
def test_without_a_public_base_nothing_changes(monkeypatch, module_name, port, name, invoke):
    """The property that makes this safe to ship to a running deployment."""
    monkeypatch.setenv("AIMARKET_INVOKE_BASE", invoke)
    monkeypatch.delenv("AIMARKET_PUBLIC_BASE", raising=False)
    document = _well_known(module_name)
    assert document["manifest_url"] == f"{invoke}/ai-market/v2/manifest"


@pytest.mark.parametrize("module_name,port,name,invoke", PROVIDERS)
def test_neither_set_falls_back_to_localhost(monkeypatch, module_name, port, name, invoke):
    monkeypatch.delenv("AIMARKET_INVOKE_BASE", raising=False)
    monkeypatch.delenv("AIMARKET_PUBLIC_BASE", raising=False)
    document = _well_known(module_name)
    assert document["manifest_url"] == f"http://localhost:{port}/ai-market/v2/manifest"


@pytest.mark.parametrize("module_name,port,name,invoke", PROVIDERS)
def test_a_public_base_that_is_not_a_url_is_ignored(monkeypatch, module_name, port, name, invoke):
    """A half-set variable must not produce a half-formed URL in a signed document."""
    monkeypatch.setenv("AIMARKET_INVOKE_BASE", invoke)
    for bad in ("memory.attestedmemory.net", "  ", "javascript:alert(1)", "ftp://x.example"):
        monkeypatch.setenv("AIMARKET_PUBLIC_BASE", bad)
        assert _well_known(module_name)["manifest_url"] == f"{invoke}/ai-market/v2/manifest"


@pytest.mark.parametrize("module_name,invoke,manifest,signer_factory", (
    ("memory_market", "http://memory-market:8810", market_manifest, MarketSigner),
    ("truth_layer", "http://truth-layer:8811", truth_manifest, TruthSigner),
    ("provenance_ledger", "http://provenance-ledger:8812", ledger_manifest, LedgerSigner),
))
def test_the_public_base_never_touches_the_invoke_path(
    monkeypatch, tmp_path, module_name, invoke, manifest, signer_factory,
):
    """The signed manifest routes PAID traffic. It must keep dialling the container.

    If `AIMARKET_PUBLIC_BASE` leaked into the manifest, every hub->provider call on this
    host would leave through nginx and come back — slower, and dependent on TLS for a call
    that never left the machine.
    """
    monkeypatch.setenv("AIMARKET_INVOKE_BASE", invoke)
    monkeypatch.setenv("AIMARKET_PUBLIC_BASE", "https://public.example")
    monkeypatch.delenv("ATTESTED_PQC_ENABLED", raising=False)
    document = manifest(signer_factory(str(tmp_path / f"{module_name}.pem")))
    assert document["base_url"] == invoke, "the invoke base must stay internal"
    assert "public.example" not in str(document)
