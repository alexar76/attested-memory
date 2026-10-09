"""Expert Market 2.0 — ranking, metered reads and the publisher's share.

Version 1 had a storefront and no author side at all. These tests pin the three
things that make the difference real: what the ranking is computed from, that a
read the market refuses is never billed, and that this service holds no ledger of
its own.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from expert_market import app as module


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(module, "METER", "http://meter.test")
    return TestClient(module.app)


def item(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "mem_1", "title": "A memory", "owner_id": "did:actor:" + "0" * 64,
        "content_hash": "h", "tags": [], "visibility": "discoverable", "price_usdc": None,
        "truth": {"status": "unverified", "confidence": 0.0, "evidence_pack_id": None},
        "provenance": {"status": "unattested", "receipt_id": None, "lineage_root": None},
        "average_score": None, "score_count": 0,
        "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z",
    }
    base.update(overrides)
    return base


# ───────────────────────────── ranking ───────────────────────────────────────

def test_a_supported_claim_outranks_an_unverified_one():
    supported = module.rank(item(truth={"status": "supported", "confidence": 0.9}))
    unverified = module.rank(item())
    assert supported["rank_score"] > unverified["rank_score"]


def test_being_wrong_ranks_below_being_unproven():
    """A rejected claim must not merely lose its bonus — it has to cost."""
    rejected = module.rank(item(truth={"status": "rejected", "confidence": 0.9}))
    contested = module.rank(item(truth={"status": "contested", "confidence": 0.9}))
    unverified = module.rank(item())
    assert rejected["rank_score"] < contested["rank_score"] < unverified["rank_score"]


def test_attestation_and_lineage_both_count():
    plain = module.rank(item())
    attested = module.rank(item(provenance={"status": "attested", "receipt_id": "r", "lineage_root": None}))
    lineage = module.rank(item(provenance={"status": "attested", "receipt_id": "r", "lineage_root": "root"}))
    assert plain["rank_score"] < attested["rank_score"] < lineage["rank_score"]


def test_one_five_star_rating_is_not_evidence():
    """Confidence weighting: a single rating moves the score far less than ten.

    Asserted on the ratings TERM, not the total — the total also carries
    freshness, and comparing totals would pass even if the weighting were gone.
    """
    def ratings_term(row):
        return next(r["points"] for r in row["rank_reasons"] if r["signal"] == "ratings")

    one = module.rank(item(average_score=5.0, score_count=1))
    ten = module.rank(item(average_score=5.0, score_count=10))
    assert 0 < ratings_term(one) < ratings_term(ten)
    assert ratings_term(one) == pytest.approx(ratings_term(ten) / 10)
    assert one["rank_score"] < ten["rank_score"]


def test_every_listing_shows_its_own_working():
    reasons = module.rank(item())["rank_reasons"]
    assert [r["signal"] for r in reasons] == ["truth", "provenance", "ratings", "freshness"]


def test_a_malformed_timestamp_does_not_break_ranking():
    assert module.rank(item(updated_at="not-a-date", created_at="also-not"))["rank_score"] == 0.0


# ───────────────────────── listings and pricing ──────────────────────────────

def test_listings_are_ranked_and_carry_their_price(client, monkeypatch):
    catalog = {"items": [item(id="low"), item(id="high", truth={"status": "supported", "confidence": 1.0},
                                              provenance={"status": "attested", "receipt_id": "r",
                                                          "lineage_root": "x"})],
               "total": 2, "query": ""}
    monkeypatch.setattr(module, "_catalog", lambda *a, **k: catalog)
    monkeypatch.setattr(module, "_prices", lambda: {
        "expert.read:high": {"operation": "expert.read:high", "price_usdc": "2.000000",
                             "publisher_id": "pub_1"}})

    body = client.get("/v1/listings").json()
    assert [row["id"] for row in body["items"]] == ["high", "low"]
    assert body["items"][0]["purchasable"] is True
    assert body["items"][0]["price_usdc"] == "2.000000"
    assert body["items"][0]["pays_publisher"] is True
    assert body["items"][1]["purchasable"] is False
    assert body["items"][1]["pays_publisher"] is False


def test_a_listing_page_does_not_leak_the_content_it_sells(client, monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return item(content="the paid text")

    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: Response())
    monkeypatch.setattr(module, "_prices", lambda: {})
    body = client.get("/v1/listings/mem_1").json()
    assert "content" not in body
    assert "rank_score" in body and body["rank_reasons"]


# ───────────────────────────── metered read ──────────────────────────────────

def _meter_recorder(calls: list[tuple[str, str, dict[str, Any] | None]]):
    def fake(method: str, path: str, key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((method, path, payload))
        if path.endswith("/authorize"):
            return {"authorization_id": "op_1", "reserved_usdc": "2.000000"}
        if path.endswith("/capture"):
            return {"charged_usdc": "2.000000", "publisher_usdc": "1.400000"}
        return {"returned_usdc": "2.000000"}

    return fake


def test_a_read_is_reserved_before_the_fetch_and_captured_after(client, monkeypatch):
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    monkeypatch.setattr(module, "_meter", _meter_recorder(calls))

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return item(content="the paid text")

    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: Response())
    body = client.post("/v1/read", json={"memory_id": "mem_1"},
                       headers={"x-meter-key": "a" * 44}).json()
    assert [c[1] for c in calls] == ["/v1/meter/authorize", "/v1/meter/capture"]
    assert body["memory"]["content"] == "the paid text"
    assert body["charge"]["publisher_usdc"] == "1.400000"


def test_a_read_the_market_refuses_is_released_not_billed(client, monkeypatch):
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    monkeypatch.setattr(module, "_meter", _meter_recorder(calls))

    class Response:
        status_code = 402

        @staticmethod
        def json():
            return {"detail": "memory requires an access grant"}

    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: Response())
    response = client.post("/v1/read", json={"memory_id": "mem_1"}, headers={"x-meter-key": "a" * 44})
    assert response.status_code == 402
    assert [c[1] for c in calls] == ["/v1/meter/authorize", "/v1/meter/release"]
    assert "nothing was charged" in response.json()["detail"]


def test_a_200_without_content_is_still_not_a_delivery(client, monkeypatch):
    """The market answers 200 with a payment hint for a paid memory. Capturing on
    the status code alone would bill the buyer for a paywall notice."""
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    monkeypatch.setattr(module, "_meter", _meter_recorder(calls))

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"memory_id": "mem_1", "price_usdc": "5.00", "payment_required": True}

    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: Response())
    assert client.post("/v1/read", json={"memory_id": "mem_1"},
                       headers={"x-meter-key": "a" * 44}).status_code == 402
    assert [c[1] for c in calls] == ["/v1/meter/authorize", "/v1/meter/release"]


def test_a_read_needs_the_buyers_own_meter_key(client):
    assert client.post("/v1/read", json={"memory_id": "mem_1"}).status_code == 401


def test_publishing_instructions_are_in_the_order_you_do_them(client):
    steps = client.get("/v1/publishing").json()["steps"]
    assert [s["step"] for s in steps] == [1, 2, 3, 4]
    assert "70%" in client.get("/v1/publishing").json()["split"]


def test_the_v1_pass_surface_still_requires_its_key(client):
    assert client.get("/api/listings").status_code == 401
