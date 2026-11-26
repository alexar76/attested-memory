"""Exercise the review gate and the two time axes through normal memory serving paths."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import memory_market.app as market_app
import memory_market.review as review_cli
import memory_market.store as store_module
from memory_market.models import MemoryCreate, ValidityWindow
from memory_market.store import MemoryStore, RejectedValue


OWNER = {"Authorization": "Bearer fixture-api-key", "X-Actor-ID": "agent:owner"}
BUYER = {"X-AIMarket-Buyer-Ref": "bref-" + "a" * 32}
REVIEWER = "operator:fixture"


@pytest.fixture(params=["sqlite", "postgres"])
def market(request, tmp_path, monkeypatch):
    dsn = os.environ.get("ATTESTED_TEST_POSTGRES_DSN")
    schema = None
    if request.param == "postgres":
        if not dsn:
            pytest.skip("no isolated PostgreSQL test DSN supplied")
        import psycopg
        from psycopg import sql

        schema = "memory_lifecycle_" + uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        separator = "&" if "?" in dsn else "?"
        monkeypatch.setenv("MEMORY_MARKET_DATABASE_URL", dsn + separator + "options=" + quote(f"-csearch_path={schema}"))
    else:
        monkeypatch.delenv("MEMORY_MARKET_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AIFACTORY_DEV", "1")
    monkeypatch.setenv("MEMORY_MARKET_API_KEY", "fixture-api-key")
    store = MemoryStore(str(tmp_path / "market.sqlite3"))
    monkeypatch.setattr(market_app, "store", lambda: store)
    monkeypatch.setattr(market_app, "provider_signer", lambda: SimpleNamespace(
        response_headers=lambda *args: {}, pq_public_key=None,
    ))
    try:
        yield store
    finally:
        store.connection.close()
        if schema is not None:
            with psycopg.connect(dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def invoke(client, capability, body, headers=None):
    product = market_app.BY_CAPABILITY[capability].product_id
    return client.post(f"/capabilities/{product}/{capability}/invoke", json={"input": body}, headers=headers)


def test_rest_and_hub_producers_cannot_admit_a_memory(approved_memory, market):
    client = TestClient(market_app.app)
    control = approved_memory(market, MemoryCreate(title="Visible control", content="control", visibility="public"), "control")
    body = {"title": "Waiting", "content": "pending material", "visibility": "public",
            "review_state": "approved", "reviewer": REVIEWER}
    response = client.post("/v1/memories", json=body, headers=OWNER)
    assert response.status_code == 201 and response.json()["review_state"] == "pending"
    rest_id = response.json()["id"]
    hub = invoke(client, "memory.write@v1", body, BUYER).json()["result"]
    assert hub["review_state"] == "pending"
    assert {unit.id for unit in market.unattested()} == {control.id}
    for memory_id in (rest_id, hub["id"]):
        for path in (f"/v1/catalog/{memory_id}", f"/v1/memories/{memory_id}",
                     f"/v1/memories/{memory_id}/evidence-pack", f"/internal/evidence-access/{memory_id}"):
            assert client.get(path, headers=OWNER).status_code == 404
        assert invoke(client, "memory.read@v1", {"memory_id": memory_id}, BUYER).status_code == 404
    assert client.post(f"/v1/memories/{rest_id}/approve", json={}, headers=OWNER).status_code in {404, 405}
    assert client.post(f"/v1/memories/{rest_id}/grants", json={"grantee_id": "buyer"}, headers=OWNER).status_code == 404
    assert client.put(f"/v1/memories/{rest_id}/score", json={"score": 5}, headers=OWNER).status_code == 404
    assert [row["id"] for row in client.get("/v1/catalog", params={"truth": "any"}).json()["items"]] == [control.id]
    assert [row["id"] for row in invoke(client, "memory.search@v1", {"truth": "any"}).json()["result"]["items"]] == [control.id]
    with pytest.raises(PermissionError):
        market.review(rest_id, "approved", OWNER["X-Actor-ID"])
    assert {row["id"] for row in market.pending_reviews()} == {rest_id, hub["id"]}
    for memory_id in (rest_id, hub["id"]):
        assert market.review(memory_id, "approved", REVIEWER).review_state == "approved"
        assert client.get(f"/v1/memories/{memory_id}").status_code == 200
    assert not market.pending_reviews()


def test_rejection_survives_reextraction_and_cannot_be_reviewed_away(approved_memory, market):
    client = TestClient(market_app.app)
    digest_owner = OWNER["X-Actor-ID"]
    kept = approved_memory(market, MemoryCreate(title="Independent", content="Café approved", visibility="public"), "other")
    duplicate = approved_memory(market, MemoryCreate(title="Earlier duplicate", content="Café approved", visibility="public"), digest_owner)
    pending = market.create(MemoryCreate(title="Review case", content="Cafe\u0301\n  approved"), digest_owner)
    market.review(pending.id, "rejected", REVIEWER)
    assert client.get(f"/v1/memories/{duplicate.id}").status_code == 404
    assert [row["id"] for row in client.get("/v1/catalog", params={"truth": "any"}).json()["items"]] == [kept.id]
    assert client.post("/v1/memories", headers=OWNER, json={
        "title": "Re-extracted title", "content": "  Café approved ", "visibility": "paid", "price_usdc": "1",
    }).status_code == 409
    with pytest.raises(RejectedValue):
        market.review(duplicate.id, "approved", REVIEWER)
    event = market.connection.execute("SELECT decision, reviewer FROM memory_review_events WHERE memory_id=?", (pending.id,)).fetchone()
    assert dict(event) == {"decision": "rejected", "reviewer": REVIEWER}


def test_bitemporal_reads_preserve_earlier_knowledge_across_interfaces(market, monkeypatch):
    client = TestClient(market_app.app)
    clock = ["2026-01-05T12:00:00.000000+00:00"]
    monkeypatch.setattr(store_module, "now", lambda: clock[0])
    record = client.post("/v1/memories", headers=OWNER, json={
        "title": "Contract", "content": "The terms applied", "visibility": "public",
        "valid_from": "2025-11-01T01:00:00+01:00", "valid_until": "2026-04-01T00:00:00Z",
    }).json()
    memory_id = record["id"]
    clock[0] = "2026-01-06T12:00:00.000000+00:00"
    market.review(memory_id, "approved", REVIEWER)
    clock[0] = "2026-02-10T12:00:00.000000+00:00"
    window = ValidityWindow(valid_from="2025-11-01T00:00:00Z", valid_until="2026-01-31T00:00:00Z")
    market.correct_validity(memory_id, window, REVIEWER)
    market.correct_validity(memory_id, window, REVIEWER)

    before_review = {"known_at": "2026-01-05T18:00:00Z", "valid_at": "2026-01-01T00:00:00Z"}
    earlier_view = {"known_at": "2026-01-20T00:00:00Z", "valid_at": "2026-02-01T00:00:00Z"}
    corrected_view = {"known_at": "2026-02-11T00:00:00Z", "valid_at": "2026-02-01T00:00:00Z"}
    assert client.get(f"/v1/memories/{memory_id}", params=before_review).status_code == 404
    assert client.get(f"/v1/memories/{memory_id}", params=earlier_view).json()["validity"]["valid_until"] == "2026-04-01T00:00:00Z"
    assert client.get(f"/v1/memories/{memory_id}", params=corrected_view).status_code == 404
    corrected_view["valid_at"] = "2026-01-30T00:00:00Z"
    result = invoke(client, "memory.read@v1", {"memory_id": memory_id, **corrected_view}).json()["result"]
    assert result["validity"]["valid_until"] == "2026-01-31T00:00:00Z"
    assert result["content_hash"] == record["content_hash"]
    assert client.get("/v1/catalog", params=earlier_view).json()["total"] == 1
    corrected_view["valid_at"] = "2026-01-31T00:00:00Z"
    assert invoke(client, "memory.search@v1", corrected_view).json()["result"]["total"] == 0
    assert client.get("/v1/catalog", params={"valid_at": "2026-01-30T00:00:00"}).status_code == 422
    assert market.connection.execute("SELECT COUNT(*) AS n FROM memory_validity WHERE memory_id=?", (memory_id,)).fetchone()["n"] == 2


def test_rejection_serializes_with_concurrent_submission(approved_memory, market):
    competitor = MemoryStore(market.connection.db_path)
    barrier = Barrier(2)
    original = approved_memory(market, MemoryCreate(title="Original", content="duplicate value"), "agent:owner")

    def submit():
        barrier.wait()
        try:
            return competitor.create(MemoryCreate(title="Again", content="duplicate value "), "agent:owner")
        except RejectedValue:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(submit)
            barrier.wait()
            market.review(original.id, "rejected", REVIEWER)
            duplicate = pending.result(timeout=10)
        if duplicate is not None:
            with pytest.raises(RejectedValue):
                competitor.review(duplicate.id, "approved", REVIEWER)
        assert market.catalog("", "agent:owner", 30, 0, truth=None)[1] == 0
        assert not market.pending_reviews()
    finally:
        competitor.connection.close()


def test_legacy_rows_are_backfilled_and_remain_readable(market):
    legacy = market.create(MemoryCreate(title="Legacy record", content="Old evidence", visibility="public"), "agent:owner")
    market.review(legacy.id, "approved", REVIEWER)
    previous_grant = market.grant(legacy.id, "agent:reader", "agent:owner")
    with market.connection:
        market.connection.execute("DELETE FROM memory_validity WHERE memory_id = ?", (legacy.id,))
        for column in ("payment_order_id", "payment_tx_hash"):
            market.connection.execute(f"ALTER TABLE memory_grant_events DROP COLUMN {column}")
        market.connection.execute("DROP INDEX idx_memories_review_queue")
        market.connection.execute("DROP INDEX idx_memories_without_value")
        for column in ("review_state", "reviewed_at", "value_digest"):
            market.connection.execute(f"ALTER TABLE memories DROP COLUMN {column}")
    reopened = MemoryStore(market.connection.db_path)
    try:
        assert reopened.get_available(legacy.id).review_state == "approved"
        assert reopened.get_available(legacy.id).validity is None
        previous_event, = reopened.grant_history(legacy.id)
        assert previous_event["grant_id"] == previous_grant.id
        assert previous_event["payment_order_id"] is None and previous_event["payment_tx_hash"] is None
        reopened.review(legacy.id, "rejected", REVIEWER)
        with pytest.raises(RejectedValue):
            reopened.create(MemoryCreate(title="Replayed legacy value", content=" Old evidence "), "agent:owner")
    finally:
        reopened.connection.close()


def test_review_cli_requires_terminal_and_records_the_operator_decision(market, monkeypatch):
    unit = market.create(MemoryCreate(title="Manual decision", content="operator reviews this"), "agent:owner")
    result = subprocess.run([sys.executable, "-m", "memory_market.review", "approve", unit.id],
                            capture_output=True, check=False, text=True, timeout=10)
    assert result.returncode == 2 and "operator terminal" in result.stderr
    assert market.get_unchecked(unit.id).review_state == "pending"
    monkeypatch.setattr(review_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(review_cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(review_cli, "get_settings", lambda: SimpleNamespace(db_path=market.connection.db_path))
    monkeypatch.setattr("builtins.input", lambda _: f"approve {unit.id}")
    assert review_cli.main(["approve", unit.id]) == 0
    assert market.get_available(unit.id).review_state == "approved"


def test_payment_audit_is_available_to_the_operator_after_a_reorg(approved_memory, market, monkeypatch, capsys):
    unit = approved_memory(market, MemoryCreate(title="Paid", content="Reviewed", visibility="paid", price_usdc="1"), "agent:owner")
    order_id = "pay_" + "a" * 32
    market.insert_payment_order((
        order_id, unit.id, "agent:buyer", "1", "1.000001", "1000001", "recipient",
        "2026-11-26T00:00:00Z", 0, 3600, 1, 0,
    ))
    assert market.settle_payment(order_id, "tx", "payer", 1, "hash", "2026-11-26T00:00:00Z", 1, False)
    assert not market.reorg_payment(order_id, "wrong-hash")
    assert market.reorg_payment(order_id, "hash")
    monkeypatch.setattr(review_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(review_cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(review_cli, "get_settings", lambda: SimpleNamespace(db_path=market.connection.db_path))
    assert review_cli.main(["grant-history", unit.id, "--limit", "1"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert len(events) == 1 and events[0]["event_type"] == "revoked"
    assert events[0]["payment_order_id"] == order_id and events[0]["payment_tx_hash"] == "tx"
