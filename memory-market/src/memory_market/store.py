from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import (
    Grant, HubStats, MemoryCreate, MemorySummary, MemoryUnit, ProvenanceState, ScoreResult,
    TruthState, ValidityVersion, ValidityWindow, utc_timestamp,
)
from .db import Database


def now() -> str:
    return utc_timestamp(datetime.now(timezone.utc))


def content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def value_digest(content: str) -> str:
    return content_hash(" ".join(unicodedata.normalize("NFC", content).split()))


class RejectedValue(ValueError):
    """A reviewer rejected this value for this owner."""


_ADMITTED = """memories.review_state = 'approved' AND NOT EXISTS (
    SELECT 1 FROM memory_value_controls vc WHERE vc.owner_id = memories.owner_id
    AND vc.value_digest = memories.value_digest AND vc.rejected_at IS NOT NULL
)"""
_VALIDITY_FIELDS = "v.valid_from, v.valid_until, v.recorded_at AS validity_recorded_at"
_VALIDITY_JOIN = """LEFT JOIN memory_validity v ON v.memory_id = memories.id AND v.revision = (
    SELECT MAX(previous.revision) FROM memory_validity previous
    WHERE previous.memory_id = memories.id AND previous.recorded_at <= ?
)"""
_VISIBLE_AT = f"""{_ADMITTED} AND memories.created_at <= ?
    AND (memories.reviewed_at IS NULL OR memories.reviewed_at <= ?)
    AND (v.valid_from IS NULL OR v.valid_from <= ?)
    AND (v.valid_until IS NULL OR v.valid_until > ?)"""


def _time_values(valid_at: datetime | None, known_at: datetime | None) -> tuple[str, ...]:
    current = now()
    recorded = utc_timestamp(known_at) if known_at is not None else current
    valid = utc_timestamp(valid_at) if valid_at is not None else current
    return (recorded, recorded, recorded, valid, valid)

# Truth Layer statuses a catalog or search offers unless the caller asks otherwise: everything but a
# memory the evidence rejected. TruthStatus in models.py lists all four.
DEFAULT_TRUTH: tuple[str, ...] = ("unverified", "supported", "contested")

class MemoryStore:
    def __init__(self, db_path: str):
        import os
        if not (os.getenv("MEMORY_MARKET_DATABASE_URL") or os.getenv("DATABASE_URL")):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = Database(db_path, "MEMORY_MARKET_DATABASE_URL")
        self.lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self.connection:
            if self.connection.is_postgres:
                self.connection.execute("SELECT pg_advisory_xact_lock(8840113083)")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS actor_proof_nonces_v2 (
                    audience TEXT NOT NULL, actor_id TEXT NOT NULL, nonce TEXT NOT NULL, expires_at BIGINT NOT NULL,
                    PRIMARY KEY (audience, actor_id, nonce)
                );
                CREATE INDEX IF NOT EXISTS idx_actor_proof_expiry ON actor_proof_nonces_v2(expires_at);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    visibility TEXT NOT NULL CHECK (visibility IN ('private','shared','public','paid')),
                    price_usdc TEXT,
                    source_refs TEXT NOT NULL,
                    parent_memory_ids TEXT NOT NULL,
                    truth_status TEXT NOT NULL DEFAULT 'unverified',
                    truth_confidence REAL NOT NULL DEFAULT 0,
                    evidence_pack_id TEXT,
                    provenance_status TEXT NOT NULL DEFAULT 'unattested',
                    receipt_id TEXT,
                    lineage_root TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS grants (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    grantee_id TEXT NOT NULL,
                    granted_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    UNIQUE(memory_id, grantee_id)
                );
                CREATE TABLE IF NOT EXISTS memory_grant_events (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    grant_id TEXT NOT NULL,
                    grantee_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (event_type IN ('granted','revoked')),
                    occurred_at TEXT NOT NULL,
                    payment_order_id TEXT,
                    payment_tx_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_memory_grant_events_memory
                ON memory_grant_events(memory_id, occurred_at, id);
                CREATE TABLE IF NOT EXISTS memory_value_controls (
                    owner_id TEXT NOT NULL,
                    value_digest TEXT NOT NULL,
                    rejected_at TEXT,
                    rejected_by TEXT,
                    decision_memory_id TEXT,
                    PRIMARY KEY (owner_id, value_digest)
                );
                CREATE TABLE IF NOT EXISTS memory_review_events (
                    memory_id TEXT NOT NULL REFERENCES memories(id),
                    decision TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
                    reviewer TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (memory_id, decision)
                );
                CREATE TABLE IF NOT EXISTS memory_validity (
                    memory_id TEXT NOT NULL REFERENCES memories(id),
                    revision INTEGER NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT,
                    recorded_at TEXT NOT NULL,
                    recorded_by TEXT NOT NULL,
                    CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until),
                    PRIMARY KEY (memory_id, revision)
                );
                CREATE TABLE IF NOT EXISTS ratings (
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    actor_id TEXT NOT NULL,
                    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(memory_id, actor_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_visibility_created
                ON memories(visibility, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_owner_created
                ON memories(owner_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_grants_grantee_active
                ON grants(grantee_id, memory_id) WHERE revoked_at IS NULL;
                CREATE TABLE IF NOT EXISTS payment_orders (
                    order_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL REFERENCES memories(id),
                    grantee_id TEXT NOT NULL,
                    price_usdc TEXT NOT NULL,
                    amount_usdc TEXT NOT NULL,
                    amount_raw TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_unix INTEGER NOT NULL,
                    expires_unix INTEGER NOT NULL,
                    created_block INTEGER NOT NULL,
                    last_scanned_block INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','expired','confirmed')),
                    tx_hash TEXT,
                    payer TEXT,
                    paid_block INTEGER,
                    paid_block_hash TEXT,
                    paid_at TEXT,
                    paid_unix INTEGER,
                    late INTEGER NOT NULL DEFAULT 0,
                    grant_id TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_payment_orders_open
                ON payment_orders(state, expires_unix);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_orders_tx
                ON payment_orders(tx_hash) WHERE tx_hash IS NOT NULL;
                CREATE TABLE IF NOT EXISTS payment_rate_limits (
                    ip TEXT PRIMARY KEY,
                    minute_start INTEGER NOT NULL,
                    minute_count INTEGER NOT NULL,
                    hour_start INTEGER NOT NULL,
                    hour_count INTEGER NOT NULL
                );
                """
            )
            if not self.connection.is_postgres:
                # sqlite3.executescript commits first; serialize the following schema changes.
                self.connection.execute("BEGIN IMMEDIATE")
            if "paid_block_hash" not in self._columns("payment_orders"):
                self.connection.execute("ALTER TABLE payment_orders ADD COLUMN paid_block_hash TEXT")
            grant_event_columns = self._columns("memory_grant_events")
            for column in ("payment_order_id", "payment_tx_hash"):
                if column not in grant_event_columns:
                    self.connection.execute(f"ALTER TABLE memory_grant_events ADD COLUMN {column} TEXT")
            columns = self._columns("memories")
            if "review_state" not in columns:
                self.connection.execute("ALTER TABLE memories ADD COLUMN review_state TEXT NOT NULL DEFAULT 'approved' "
                                        "CHECK (review_state IN ('pending','approved','rejected'))")
            if "reviewed_at" not in columns:
                self.connection.execute("ALTER TABLE memories ADD COLUMN reviewed_at TEXT")
            if "value_digest" not in columns:
                self.connection.execute("ALTER TABLE memories ADD COLUMN value_digest TEXT")
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_without_value "
                                    "ON memories(id) WHERE value_digest IS NULL")
            while rows := self.connection.execute(
                "SELECT id, content FROM memories WHERE value_digest IS NULL ORDER BY id LIMIT 200"
            ).fetchall():
                for row in rows:
                    self.connection.execute("UPDATE memories SET value_digest = ? WHERE id = ?",
                                            (value_digest(row["content"]), row["id"]))
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_review_queue "
                                    "ON memories(created_at, id) WHERE review_state = 'pending'")

    def _columns(self, table: str) -> set[str]:
        if self.connection.is_postgres:
            return {row["column_name"] for row in self.connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?", (table,))}
        return {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}

    def create(self, request: MemoryCreate, owner_id: str) -> MemoryUnit:
        """Submit a unit for operator review."""
        memory_id = "mem_" + uuid4().hex[:24]
        digest = value_digest(request.content)
        with self.lock, self.connection:
            if self._lock_value(owner_id, digest)["rejected_at"] is not None:
                raise RejectedValue("this value was rejected for this owner")
            created_at = now()
            self.connection.execute(
                """INSERT INTO memories (
                id, title, content, content_hash, owner_id, tags, visibility, price_usdc,
                source_refs, parent_memory_ids, created_at, updated_at, value_digest, review_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (memory_id, request.title, request.content, content_hash(request.content), owner_id,
                 json.dumps(request.tags), request.visibility, request.price_usdc,
                 json.dumps(request.source_refs), json.dumps(request.parent_memory_ids), created_at, created_at,
                 digest),
            )
            self._insert_validity(memory_id, request, 1, created_at, owner_id)
        return self.get_unchecked(memory_id)

    def _lock_value(self, owner_id: str, digest: str):
        self.connection.execute(
            "INSERT INTO memory_value_controls (owner_id, value_digest) VALUES (?, ?) "
            "ON CONFLICT (owner_id, value_digest) DO NOTHING", (owner_id, digest),
        )
        lock = " FOR UPDATE" if self.connection.is_postgres else ""
        return self.connection.execute(
            "SELECT rejected_at FROM memory_value_controls WHERE owner_id = ? AND value_digest = ?" + lock,
            (owner_id, digest),
        ).fetchone()

    def pending_reviews(self, limit: int = 30, offset: int = 0) -> list[dict]:
        rows = self.connection.execute(
            """SELECT id, title, owner_id, created_at FROM memories WHERE review_state = 'pending'
               AND NOT EXISTS (SELECT 1 FROM memory_value_controls vc WHERE vc.owner_id = memories.owner_id
               AND vc.value_digest = memories.value_digest AND vc.rejected_at IS NOT NULL)
               ORDER BY created_at, id LIMIT ? OFFSET ?""", (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    def review(self, memory_id: str, decision: str, reviewer: str) -> MemoryUnit:
        if decision not in {"approved", "rejected"} or not reviewer.strip():
            raise ValueError("a review requires an approval or rejection and a reviewer")
        with self.lock, self.connection:
            row = self.connection.execute("SELECT owner_id, value_digest FROM memories WHERE id = ?",
                                          (memory_id,)).fetchone()
            if row is None:
                raise KeyError(memory_id)
            if reviewer == row["owner_id"]:
                raise PermissionError("the producer cannot review its own memory")
            control = self._lock_value(row["owner_id"], row["value_digest"])
            if decision == "approved" and control["rejected_at"] is not None:
                raise RejectedValue("this value was rejected for this owner")
            recorded_at = now()
            changed = self.connection.execute(
                "UPDATE memories SET review_state = ?, reviewed_at = ?, updated_at = ? "
                "WHERE id = ? AND review_state NOT IN (?, 'rejected')",
                (decision, recorded_at, recorded_at, memory_id, decision),
            ).rowcount
            if changed:
                self.connection.execute(
                    "INSERT INTO memory_review_events (memory_id, decision, reviewer, recorded_at) VALUES (?, ?, ?, ?)",
                    (memory_id, decision, reviewer, recorded_at),
                )
                if decision == "rejected":
                    self.connection.execute(
                        "UPDATE memory_value_controls SET rejected_at = ?, rejected_by = ?, decision_memory_id = ? "
                        "WHERE owner_id = ? AND value_digest = ? AND rejected_at IS NULL",
                        (recorded_at, reviewer, memory_id, row["owner_id"], row["value_digest"]),
                    )
        return self.get_unchecked(memory_id)

    def _insert_validity(self, memory_id: str, window: ValidityWindow, revision: int,
                         recorded_at: str, recorded_by: str) -> None:
        start = utc_timestamp(window.valid_from) if window.valid_from is not None else None
        end = utc_timestamp(window.valid_until) if window.valid_until is not None else None
        self.connection.execute(
            "INSERT INTO memory_validity (memory_id, revision, valid_from, valid_until, recorded_at, recorded_by) "
            "VALUES (?, ?, ?, ?, ?, ?)", (memory_id, revision, start, end, recorded_at, recorded_by),
        )

    def correct_validity(self, memory_id: str, window: ValidityWindow, reviewer: str) -> MemoryUnit:
        with self.lock, self.connection:
            row = self.connection.execute("SELECT owner_id, value_digest FROM memories WHERE id = ?",
                                          (memory_id,)).fetchone()
            if row is None:
                raise KeyError(memory_id)
            if reviewer == row["owner_id"]:
                raise PermissionError("the producer cannot correct its own memory")
            control = self._lock_value(row["owner_id"], row["value_digest"])
            if control["rejected_at"] is not None:
                raise RejectedValue("this value was rejected for this owner")
            current = self.get_unchecked(memory_id)
            if current.review_state != "approved":
                raise ValueError("approve the memory before correcting its validity")
            if (current.validity is not None and window.valid_from == current.validity.valid_from
                    and window.valid_until == current.validity.valid_until):
                return current
            latest = self.connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM memory_validity WHERE memory_id = ?", (memory_id,)
            ).fetchone()["revision"]
            if latest == 0:
                self._insert_validity(memory_id, ValidityWindow(), 1, current.created_at, current.owner_id)
                latest = 1
            self._insert_validity(memory_id, window, latest + 1, now(), reviewer)
        return self.get_unchecked(memory_id)

    def _rating(self, memory_id: str) -> tuple[float | None, int]:
        row = self.connection.execute(
            "SELECT AVG(score) average, COUNT(*) count FROM ratings WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        return (round(row["average"], 2) if row["average"] is not None else None, row["count"])

    def _unit(self, row: sqlite3.Row) -> MemoryUnit:
        average, count = self._rating(row["id"])
        validity = None
        if "validity_recorded_at" in row.keys() and row["validity_recorded_at"] is not None:
            validity = ValidityVersion(valid_from=row["valid_from"], valid_until=row["valid_until"],
                                       recorded_at=row["validity_recorded_at"])
        return MemoryUnit(
            id=row["id"], title=row["title"], content=row["content"], content_hash=row["content_hash"],
            owner_id=row["owner_id"], tags=json.loads(row["tags"]), visibility=row["visibility"],
            price_usdc=row["price_usdc"], source_refs=json.loads(row["source_refs"]),
            parent_memory_ids=json.loads(row["parent_memory_ids"]),
            truth=TruthState(status=row["truth_status"], confidence=row["truth_confidence"], evidence_pack_id=row["evidence_pack_id"]),
            provenance=ProvenanceState(status=row["provenance_status"], receipt_id=row["receipt_id"], lineage_root=row["lineage_root"]),
            average_score=average, score_count=count, created_at=row["created_at"], updated_at=row["updated_at"],
            review_state=row["review_state"], validity=validity,
        )

    @staticmethod
    def summary(unit: MemoryUnit) -> MemorySummary:
        return MemorySummary(**unit.model_dump(exclude={"content", "source_refs", "parent_memory_ids"}))

    def get_unchecked(self, memory_id: str) -> MemoryUnit:
        row = self.connection.execute(
            f"SELECT memories.*, {_VALIDITY_FIELDS} FROM memories {_VALIDITY_JOIN} WHERE memories.id = ?",
            (now(), memory_id),
        ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return self._unit(row)

    def get_available(self, memory_id: str, *, valid_at: datetime | None = None,
                      known_at: datetime | None = None) -> MemoryUnit:
        row = self.connection.execute(
            f"SELECT memories.*, {_VALIDITY_FIELDS} FROM memories {_VALIDITY_JOIN} "
            f"WHERE {_VISIBLE_AT} AND memories.id = ?", (*_time_values(valid_at, known_at), memory_id),
        ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return self._unit(row)

    def has_grant(self, memory_id: str, actor_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM grants WHERE memory_id = ? AND grantee_id = ? AND revoked_at IS NULL",
            (memory_id, actor_id),
        ).fetchone() is not None

    def payment_order(self, order_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT payment_orders.*, memories.title AS memory_title FROM payment_orders "
            "JOIN memories ON memories.id = payment_orders.memory_id WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise KeyError(order_id)
        return row

    def claimable_payment_orders(self, grace_floor: int, limit: int = 200) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT payment_orders.*, memories.title AS memory_title FROM payment_orders "
            "JOIN memories ON memories.id = payment_orders.memory_id "
            "WHERE state='pending' OR (state='expired' AND expires_unix > ?) "
            "ORDER BY created_unix LIMIT ?",
            (grace_floor, limit),
        ).fetchall()

    def open_payment_orders_for_grantee(self, grantee_id: str, grace_floor: int) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM payment_orders WHERE grantee_id = ? "
            "AND (state='pending' OR (state='expired' AND expires_unix > ?))",
            (grantee_id, grace_floor),
        ).fetchone()
        return int(row["count"])

    def confirmed_payment_orders(self, limit: int = 200):
        return self.connection.execute(
            "SELECT * FROM payment_orders WHERE state='confirmed' "
            "AND paid_block IS NOT NULL AND paid_block_hash IS NOT NULL "
            "ORDER BY paid_unix DESC LIMIT ?", (limit,)
        ).fetchall()

    def open_payment_amounts(self, grace_floor: int) -> set[int]:
        rows = self.connection.execute(
            "SELECT amount_raw FROM payment_orders WHERE state='pending' "
            "OR (state='expired' AND expires_unix > ?)", (grace_floor,),
        ).fetchall()
        return {int(row["amount_raw"]) for row in rows}

    def insert_payment_order(self, values: tuple[object, ...]) -> None:
        with self.lock, self.connection:
            memory_id = values[1]
            row = self.connection.execute("SELECT owner_id, value_digest FROM memories WHERE id = ?",
                                          (memory_id,)).fetchone()
            if row is None:
                raise KeyError(memory_id)
            self._lock_value(row["owner_id"], row["value_digest"])
            self.get_available(memory_id)
            self.connection.execute(
                """INSERT INTO payment_orders (
                order_id, memory_id, grantee_id, price_usdc, amount_usdc, amount_raw,
                recipient, created_at, created_unix, expires_unix, created_block,
                last_scanned_block, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                values,
            )

    def expire_payment_orders(self, timestamp: int) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE payment_orders SET state='expired' WHERE state='pending' AND expires_unix < ?",
                (timestamp,),
            )

    def advance_payment_scan(self, end_block: int, grace_floor: int) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE payment_orders SET last_scanned_block=MAX(last_scanned_block, ?) "
                "WHERE state='pending' OR (state='expired' AND expires_unix > ?)",
                (end_block, grace_floor),
            )

    def settle_payment(
        self, order_id: str, tx_hash: str, payer: str, paid_block: int,
        paid_block_hash: str | None, paid_at: str, paid_unix: int, late: bool,
    ) -> bool:
        """Record one settlement, its access grant and audit event atomically."""
        with self.lock:
            try:
                with self.connection:
                    row = self.connection.execute(
                        "SELECT memory_id, grantee_id FROM payment_orders "
                        "WHERE order_id=? AND state IN ('pending','expired')", (order_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    claimed = self.connection.execute(
                        "UPDATE payment_orders SET tx_hash=?, payer=?, paid_block=?, paid_block_hash=?, paid_at=?, "
                        "paid_unix=?, late=? WHERE order_id=? AND state IN ('pending','expired')",
                        (tx_hash.lower(), payer.lower(), paid_block, paid_block_hash, paid_at, paid_unix, int(late), order_id),
                    ).rowcount
                    if claimed != 1:
                        return False
                    owner = self.connection.execute(
                        "SELECT owner_id FROM memories WHERE id=?", (row["memory_id"],),
                    ).fetchone()
                    if owner is None:
                        raise RuntimeError("paid memory disappeared before settlement")
                    grant_id = "grant_" + uuid4().hex[:24]
                    granted_at = now()
                    self.connection.execute(
                        """INSERT INTO grants (id, memory_id, grantee_id, granted_by, created_at, revoked_at)
                        VALUES (?, ?, ?, ?, ?, NULL)
                        ON CONFLICT(memory_id, grantee_id) DO UPDATE SET
                        revoked_at=NULL, granted_by=excluded.granted_by, created_at=excluded.created_at""",
                        (grant_id, row["memory_id"], row["grantee_id"], owner["owner_id"], granted_at),
                    )
                    persisted = self.connection.execute(
                        "SELECT id FROM grants WHERE memory_id=? AND grantee_id=?",
                        (row["memory_id"], row["grantee_id"]),
                    ).fetchone()
                    self.connection.execute(
                        "UPDATE payment_orders SET state='confirmed', grant_id=?, last_error=NULL WHERE order_id=?",
                        (persisted["id"], order_id),
                    )
                    self._record_grant_event(
                        row["memory_id"], persisted["id"], row["grantee_id"], "system:payment", "granted",
                        granted_at, payment_order_id=order_id, payment_tx_hash=tx_hash.lower(),
                    )
                return True
            except Exception as error:
                # sqlite3 and psycopg expose different exception classes; SQLSTATE
                # 23xxx is the portable integrity/unique-constraint family.
                if isinstance(error, sqlite3.IntegrityError) or getattr(error, "sqlstate", "").startswith("23"):
                    return False
                raise

    def reorg_payment(self, order_id: str, paid_block_hash: str) -> bool:
        """Record the rollback of the specific settlement that was checked against the chain."""
        with self.lock, self.connection:
            if not self.connection.is_postgres:
                self.connection.execute("BEGIN IMMEDIATE")
            lock = " FOR UPDATE" if self.connection.is_postgres else ""
            row = self.connection.execute(
                "SELECT grant_id, memory_id, grantee_id, tx_hash FROM payment_orders "
                "WHERE order_id = ? AND state = 'confirmed' AND paid_block_hash = ?" + lock,
                (order_id, paid_block_hash),
            ).fetchone()
            if row is None:
                return False
            grant_id = row["grant_id"]
            if grant_id:
                self.connection.execute("SELECT id FROM grants WHERE id = ?" + lock, (grant_id,)).fetchone()
            self.connection.execute(
                "UPDATE payment_orders SET state='expired', tx_hash=NULL, payer=NULL, "
                "paid_block=NULL, paid_block_hash=NULL, paid_at=NULL, paid_unix=NULL, late=0, grant_id=NULL, "
                "last_error='payment block reorged' WHERE order_id = ?",
                (order_id,),
            )
            if grant_id:
                revoked_at = now()
                self.connection.execute(
                    """UPDATE grants SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL
                       AND NOT EXISTS (SELECT 1 FROM payment_orders WHERE grant_id = ? AND state = 'confirmed')
                       AND COALESCE((SELECT event_type FROM memory_grant_events
                           WHERE grant_id = ? AND payment_order_id IS NULL
                           ORDER BY occurred_at DESC, id DESC LIMIT 1), 'revoked') = 'revoked'""",
                    (revoked_at, grant_id, grant_id, grant_id),
                )
                self._record_grant_event(
                    row["memory_id"], grant_id, row["grantee_id"], "system:payment", "revoked", revoked_at,
                    payment_order_id=order_id, payment_tx_hash=row["tx_hash"],
                )
            return True

    def can_read(self, unit: MemoryUnit, actor_id: str | None, team_id: str | None = None) -> bool:
        if not self.connection.execute(f"SELECT 1 FROM memories WHERE id = ? AND {_ADMITTED}",
                                       (unit.id,)).fetchone():
            return False
        if team_id and f"team:{team_id}" in unit.tags and unit.visibility in {"shared", "public", "paid"}:
            return True
        if unit.visibility == "public":
            return True
        if actor_id is None:
            return False
        return actor_id == unit.owner_id or self.has_grant(unit.id, actor_id)

    def catalog(self, query: str, actor_id: str | None, limit: int, offset: int, team_id: str | None = None,
                truth: tuple[str, ...] | None = DEFAULT_TRUTH, *, valid_at: datetime | None = None,
                known_at: datetime | None = None) -> tuple[list[MemorySummary], int]:
        """Discoverable memories, newest first. ``truth`` keeps only those whose Truth Layer status is
        listed; by default a memory the evidence rejected is not offered as an answer (it can still be
        read by id, with its status). ``None`` applies no truth filter."""
        params: list[object] = list(_time_values(valid_at, known_at))
        access = "(visibility IN ('public','paid'))"
        team_tag = None
        if team_id:
            # LIKE metacharacters in team IDs are data, never other teams.
            escaped_team = team_id.casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            team_tag = f'%"team:{escaped_team}"%'
            access = "(lower(tags) LIKE ? ESCAPE '!' AND visibility IN ('shared','public','paid'))"
            params.append(team_tag)
        elif actor_id:
            access = "(visibility IN ('public','paid') OR owner_id = ? OR id IN (SELECT memory_id FROM grants WHERE grantee_id = ? AND revoked_at IS NULL))"
            params.extend([actor_id, actor_id])
        search = ""
        if query:
            needle = f"%{query.casefold()}%"
            # A catalog may advertise paid memories, but searching their hidden
            # content would let an unpaid caller test arbitrary secret substrings.
            readable = "visibility = 'public'"
            content_params: list[object] = []
            if actor_id:
                readable += " OR owner_id = ? OR id IN (SELECT memory_id FROM grants WHERE grantee_id = ? AND revoked_at IS NULL)"
                content_params.extend([actor_id, actor_id])
            if team_tag is not None:
                readable += " OR (lower(tags) LIKE ? ESCAPE '!' AND visibility IN ('shared','paid'))"
                content_params.append(team_tag)
            search = f" AND (lower(title) LIKE ? OR lower(tags) LIKE ? OR (lower(content) LIKE ? AND ({readable})))"
            params.extend([needle, needle, needle])
            params.extend(content_params)
        if truth is not None:
            search += (" AND truth_status IN (" + ",".join("?" * len(truth)) + ")") if truth else " AND 1=0"
            params.extend(truth)
        selection = f"FROM memories {_VALIDITY_JOIN} WHERE {_VISIBLE_AT} AND {access}{search}"
        count = self.connection.execute(f"SELECT COUNT(*) count {selection}", params).fetchone()["count"]
        rows = self.connection.execute(
            f"SELECT memories.*, {_VALIDITY_FIELDS} {selection} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [self.listing(self._unit(row), actor_id, team_id) for row in rows], count

    def listing(self, unit: MemoryUnit, actor_id: str | None, team_id: str | None = None) -> MemorySummary:
        """A catalogue entry for this caller. The evidence pack holds the verified claim, which for a
        paid or private unit can repeat its content, so only a caller who may read the unit gets the
        pack id; everyone sees the truth status and confidence."""
        summary = self.summary(unit)
        if summary.truth.evidence_pack_id and not self.can_read(unit, actor_id, team_id):
            summary = summary.model_copy(update={"truth": summary.truth.model_copy(update={"evidence_pack_id": None})})
        return summary

    def grant(self, memory_id: str, grantee_id: str, actor_id: str) -> Grant:
        unit = self.get_available(memory_id)
        if unit.owner_id != actor_id:
            raise PermissionError("only the owner can grant access")
        grant_id = "grant_" + uuid4().hex[:24]
        created_at = now()
        with self.lock, self.connection:
            row = self.connection.execute(
                """INSERT INTO grants (id, memory_id, grantee_id, granted_by, created_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(memory_id, grantee_id) DO UPDATE SET revoked_at = NULL, granted_by = excluded.granted_by, created_at = excluded.created_at
                RETURNING id, memory_id, grantee_id, granted_by, created_at""",
                (grant_id, memory_id, grantee_id, actor_id, created_at),
            ).fetchone()
            self._record_grant_event(memory_id, row["id"], grantee_id, actor_id, "granted", created_at)
        return Grant(**dict(row))

    def revoke(self, memory_id: str, grantee_id: str, actor_id: str) -> Grant:
        """The owner withdraws access they gave. Access a buyer paid for is not the owner's to take
        back (a reorged payment removes its own grant, see reorg_payment)."""
        unit = self.get_unchecked(memory_id)
        if unit.owner_id != actor_id:
            raise PermissionError("only the owner can revoke access")
        with self.lock, self.connection:
            lock = " FOR UPDATE" if self.connection.is_postgres else ""
            row = self.connection.execute(
                "SELECT id, memory_id, grantee_id, granted_by, created_at, revoked_at FROM grants "
                "WHERE memory_id = ? AND grantee_id = ?" + lock, (memory_id, grantee_id),
            ).fetchone()
            if row is None:
                raise LookupError("no grant for this grantee")
            if self.connection.execute(
                "SELECT 1 FROM payment_orders WHERE grant_id = ? AND state = 'confirmed'", (row["id"],)
            ).fetchone() is not None:
                raise PermissionError("this access was paid for; the owner cannot revoke it")
            if row["revoked_at"] is None:
                revoked_at = now()
                self.connection.execute(
                    "UPDATE grants SET revoked_at = ? WHERE id = ?", (revoked_at, row["id"]))
                self._record_grant_event(memory_id, row["id"], grantee_id, actor_id, "revoked", revoked_at)
                return Grant(**(dict(row) | {"revoked_at": revoked_at}))
            return Grant(**dict(row))

    def grant_history(self, memory_id: str, limit: int = 30, offset: int = 0) -> list[dict]:
        rows = self.connection.execute(
            "SELECT id, memory_id, grant_id, grantee_id, actor_id, event_type, occurred_at, "
            "payment_order_id, payment_tx_hash FROM memory_grant_events WHERE memory_id = ? "
            "ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
            (memory_id, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    def _record_grant_event(self, memory_id: str, grant_id: str, grantee_id: str, actor_id: str,
                            event_type: str, occurred_at: str, *, payment_order_id: str | None = None,
                            payment_tx_hash: str | None = None) -> None:
        self.connection.execute(
            "INSERT INTO memory_grant_events (id, memory_id, grant_id, grantee_id, actor_id, event_type, "
            "occurred_at, payment_order_id, payment_tx_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid4().hex, memory_id, grant_id, grantee_id, actor_id, event_type, occurred_at,
             payment_order_id, payment_tx_hash),
        )

    def score(self, memory_id: str, actor_id: str, score: int) -> ScoreResult:
        self.get_available(memory_id)
        timestamp = now()
        with self.connection:
            self.connection.execute(
                """INSERT INTO ratings (memory_id, actor_id, score, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(memory_id, actor_id) DO UPDATE SET score = excluded.score, updated_at = excluded.updated_at""",
                (memory_id, actor_id, score, timestamp, timestamp),
            )
        average, count = self._rating(memory_id)
        return ScoreResult(memory_id=memory_id, average_score=average or 0, score_count=count)

    def set_provenance(self, memory_id: str, receipt_id: str, lineage_root: str, *, created: bool) -> None:
        """Record the newest ledger receipt of a unit. Only its ``created`` receipt makes the unit
        ``attested``: a payment or verification receipt that lands while the creation receipt is
        still missing keeps it ``unattested``, so reconcile_provenance still adds the creation."""
        with self.connection:
            self.connection.execute(
                "UPDATE memories SET provenance_status=CASE WHEN ? THEN 'attested' ELSE provenance_status END, "
                "receipt_id=?, lineage_root=?, updated_at=? WHERE id=?",
                (bool(created), receipt_id, lineage_root, now(), memory_id),
            )

    def unattested(self, limit: int = 200, after_id: str = "") -> list[MemoryUnit]:
        """Units the ledger never confirmed (``provenance_status='unattested'``), oldest id first."""
        rows = self.connection.execute(
            f"SELECT * FROM memories WHERE provenance_status='unattested' AND {_ADMITTED} AND id > ? ORDER BY id LIMIT ?",
            (after_id, limit),
        ).fetchall()
        return [self._unit(row) for row in rows]

    def attested(self, limit: int = 200, after_id: str = "") -> list[MemoryUnit]:
        """Units with a ledger receipt recorded here, oldest id first."""
        rows = self.connection.execute(
            "SELECT * FROM memories WHERE provenance_status='attested' AND id > ? ORDER BY id LIMIT ?",
            (after_id, limit),
        ).fetchall()
        return [self._unit(row) for row in rows]

    def set_truth(self, memory_id: str, status: str, confidence: float, pack_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE memories SET truth_status=?, truth_confidence=?, evidence_pack_id=?, updated_at=? WHERE id=?",
                (status, confidence, pack_id, now(), memory_id),
            )

    def stats(self, actor_id: str | None, payment_enabled: bool) -> HubStats:
        _, discoverable = self.catalog("", actor_id, 1, 0)
        row = self.connection.execute(
            f"""SELECT
            SUM(CASE WHEN provenance_status='attested' THEN 1 ELSE 0 END) attested,
            SUM(CASE WHEN truth_status!='unverified' THEN 1 ELSE 0 END) verified,
            SUM(CASE WHEN visibility='paid' THEN 1 ELSE 0 END) paid
            FROM memories WHERE {_ADMITTED}"""
        ).fetchone()
        return HubStats(
            discoverable_memories=discoverable, attested_memories=row["attested"] or 0,
            verified_memories=row["verified"] or 0, paid_memories=row["paid"] or 0,
            payment_enabled=payment_enabled,
        )
