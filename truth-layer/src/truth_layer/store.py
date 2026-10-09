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
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_packs (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT,
                    claim_hash TEXT NOT NULL,
                    pack_hash TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_packs_memory
                ON evidence_packs(memory_id, created_at);
                """
            )

    def save(self, pack: EvidencePack) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO evidence_packs (id, memory_id, claim_hash, pack_hash, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pack.id, pack.memory_id, pack.claim_hash, pack.pack_hash, pack.model_dump_json(), pack.result.created_at),
            )

    def get(self, pack_id: str) -> EvidencePack:
        row = self.connection.execute("SELECT payload FROM evidence_packs WHERE id = ?", (pack_id,)).fetchone()
        if row is None:
            raise KeyError(pack_id)
        return EvidencePack.model_validate(json.loads(row["payload"]))
