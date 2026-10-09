import hashlib
import contextvars
from types import SimpleNamespace

from provenance_ledger.crypto import Signer
from provenance_ledger.models import AttestationCreate
from provenance_ledger.store import Ledger
from provenance_ledger.db import Database
from fastapi import Response
import provenance_ledger.app as app_module


def test_append_chain_and_verify(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"), Signer(str(tmp_path / "key.pem")))
    content_hash = "sha256:" + hashlib.sha256(b"portable memory").hexdigest()
    first = ledger.append(AttestationCreate(
        memory_id="mem_1234567890abcdef12345678", event_type="created",
        content_hash=content_hash, actor_id="agent:test", source_refs=["https://example.test/source"],
    ))
    second = ledger.append(AttestationCreate(
        memory_id=first.memory_id, event_type="verified", content_hash=content_hash,
        actor_id="truth-layer", metadata={"status": "supported"},
    ))

    assert second.previous_root == first.chain_root
    assert ledger.verify(first.id).valid is True
    assert ledger.verify(second.id).valid is True
    assert ledger.lineage(first.memory_id).chain_root == second.chain_root
    assert len(ledger.lineage(first.memory_id).receipts) == 2
    head = ledger.connection.execute(
        "SELECT chain_root FROM receipt_heads WHERE memory_id = ?", (first.memory_id,)
    ).fetchone()
    assert head["chain_root"] == second.chain_root


def test_migration_backfills_chain_head(tmp_path):
    db_path = str(tmp_path / "ledger.sqlite3")
    key_path = str(tmp_path / "key.pem")
    ledger = Ledger(db_path, Signer(key_path))
    receipt = ledger.append(AttestationCreate(
        memory_id="mem_1234567890abcdef12345678", event_type="created",
        content_hash="sha256:" + "c" * 64, actor_id="agent:test",
    ))
    with ledger.connection:
        ledger.connection.execute("DELETE FROM receipt_heads")
    ledger.connection.close()

    reopened = Ledger(db_path, Signer(key_path))
    row = reopened.connection.execute(
        "SELECT chain_root FROM receipt_heads WHERE memory_id = ?", (receipt.memory_id,)
    ).fetchone()
    assert row["chain_root"] == receipt.chain_root


def test_tamper_is_detected(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"), Signer(str(tmp_path / "key.pem")))
    receipt = ledger.append(AttestationCreate(
        memory_id="mem_1234567890abcdef12345678", event_type="created",
        content_hash="sha256:" + "a" * 64, actor_id="agent:test",
    ))
    with ledger.connection:
        ledger.connection.execute("UPDATE receipts SET actor_id = 'attacker' WHERE id = ?", (receipt.id,))
    result = ledger.verify(receipt.id)
    assert result.valid is False
    assert result.checks["event_hash"] is False


def test_pq_requirement_fails_closed_for_classical_receipt(tmp_path, monkeypatch):
    monkeypatch.delenv("ATTESTED_PQC_ENABLED", raising=False)
    signer = Signer(str(tmp_path / "key.pem"))
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"), signer)
    receipt = ledger.append(AttestationCreate(
        memory_id="mem_1234567890abcdef12345678", event_type="created",
        content_hash="sha256:" + "b" * 64, actor_id="agent:test",
    ))
    monkeypatch.setenv("ATTESTED_PQC_REQUIRE", "1")
    result = ledger.verify(receipt.id)
    assert result.valid is False
    assert result.checks["pq_signature"] is False


def test_postgres_transaction_executes_on_checked_out_connection():
    calls = []

    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            return "cursor"

    db = object.__new__(Database)
    db._pool = object()
    db._tx = contextvars.ContextVar("provenance_test_tx", default=None)
    db._tx.set((object(), Connection()))

    assert db.execute("SELECT ?", (7,)) == "cursor"
    assert calls == [("SELECT %s", (7,))]


def test_health_fails_with_503_when_database_is_down(monkeypatch):
    class Connection:
        is_postgres = True

        def execute(self, *_args):
            raise RuntimeError("database unavailable")

    fake_ledger = SimpleNamespace(
        connection=Connection(), signer=SimpleNamespace(pq_public_key="pq"),
    )
    monkeypatch.setattr(app_module, "ledger", lambda: fake_ledger)
    response = Response()
    payload = app_module.health(response)
    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == {"backend": "postgresql", "healthy": False}
