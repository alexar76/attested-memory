from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import EvidencePack
from .db import Database


class TruthStore:
    def __init__(self, db_path: str):
        import os
        if not (os.getenv("TRUTH_LAYER_DATABASE_URL") or os.getenv("DATABASE_URL")):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = Database(db_path, "TRUTH_LAYER_DATABASE_URL")
        with self.connection:
            if self.connection.is_postgres:
                self.connection.execute("SELECT pg_advisory_xact_lock(8840113084)")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_packs (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT,
                    claim_hash TEXT NOT NULL,
                    pack_hash TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    buyer_ref_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_packs_memory
                ON evidence_packs(memory_id, created_at);
                """
            )
            if self.connection.is_postgres:
                self.connection.execute("ALTER TABLE evidence_packs ADD COLUMN IF NOT EXISTS buyer_ref_hash TEXT")
            else:
                self.connection.execute("BEGIN IMMEDIATE")
                columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(evidence_packs)")}
                if "buyer_ref_hash" not in columns:
                    self.connection.execute("ALTER TABLE evidence_packs ADD COLUMN buyer_ref_hash TEXT")

    def save(self, pack: EvidencePack, *, buyer_ref_hash: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO evidence_packs (id, memory_id, claim_hash, pack_hash, payload, created_at, buyer_ref_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pack.id, pack.memory_id, pack.claim_hash, pack.pack_hash, pack.model_dump_json(),
                 pack.result.created_at, buyer_ref_hash),
            )

    def get(self, pack_id: str) -> EvidencePack:
        return self.get_with_buyer(pack_id)[0]

    def get_with_buyer(self, pack_id: str) -> tuple[EvidencePack, str | None]:
        row = self.connection.execute(
            "SELECT payload, buyer_ref_hash FROM evidence_packs WHERE id = ?", (pack_id,),
        ).fetchone()
        if row is None:
            raise KeyError(pack_id)
        return EvidencePack.model_validate(json.loads(row["payload"])), row["buyer_ref_hash"]
