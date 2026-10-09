#!/usr/bin/env python3
"""One-shot SQLite -> PostgreSQL migration for the Attested Memory Hub.

The source is never modified.  Existing PostgreSQL tables are left intact and
records are inserted with ``ON CONFLICT DO NOTHING`` so the command is safe to
resume after an interrupted copy.  Run once per SQLite database/table owner.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql as pg_sql


def _pg_schema(sql: str) -> str:
    sql = re.sub(
        r"^\s*CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\b)",
        "CREATE TABLE IF NOT EXISTS ", sql, count=1, flags=re.I,
    )
    sql = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", sql, flags=re.I)
    sql = re.sub(r"\bAUTOINCREMENT\b", "", sql, flags=re.I)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.I)
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql, flags=re.I)
    return sql


def migrate(source: Path, dsn: str) -> tuple[int, int]:
    if not source.is_file():
        raise FileNotFoundError(source)
    with sqlite3.connect(source) as src, psycopg.connect(dsn) as dst:
        src.row_factory = sqlite3.Row
        tables = [row["name"] for row in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        copied_tables = copied_rows = 0
        with dst.cursor() as cur:
            for table in tables:
                ddl = src.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                if not ddl:
                    continue
                cur.execute(_pg_schema(ddl))
                column_info = list(src.execute(f'PRAGMA table_info("{table}")'))
                columns = [row["name"] for row in column_info]
                quoted_table = '"' + table.replace('"', '""') + '"'
                quoted_cols = ", ".join('"' + col.replace('"', '""') + '"' for col in columns)
                placeholders = ", ".join(f"%s" for _ in columns)
                rows = src.execute(f'SELECT * FROM "{table.replace(chr(34), chr(34) * 2)}"')
                for row in rows:
                    cur.execute(
                        f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({placeholders}) "
                        "ON CONFLICT DO NOTHING",
                        tuple(row[col] for col in columns),
                    )
                    copied_rows += max(cur.rowcount, 0)
                for column in column_info:
                    if not column["pk"] or "INT" not in str(column["type"]).upper():
                        continue
                    cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, column["name"]))
                    sequence = cur.fetchone()[0]
                    if sequence:
                        cur.execute(
                            pg_sql.SQL(
                                "SELECT setval(%s, COALESCE(MAX({column}), 1), COUNT(*) > 0) "
                                "FROM {table}"
                            ).format(
                                column=pg_sql.Identifier(column["name"]),
                                table=pg_sql.Identifier(table),
                            ),
                            (sequence,),
                        )
                copied_tables += 1
            # Recreate user indexes after data copy. SQLite's autoindexes and indexes
            # already present in the destination are harmlessly skipped.
            for row in src.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                "AND name NOT LIKE 'sqlite_%'"
            ):
                index_sql = _pg_schema(row[0])
                index_sql = re.sub(r"^\s*CREATE\s+(UNIQUE\s+)?INDEX\s+", r"CREATE \1INDEX IF NOT EXISTS ", index_sql, flags=re.I)
                cur.execute(index_sql)
        dst.commit()
    return copied_tables, copied_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, type=Path, help="source SQLite database")
    parser.add_argument("--dsn", required=True, help="target PostgreSQL DSN")
    args = parser.parse_args()
    tables, rows = migrate(args.sqlite, args.dsn)
    print(f"migrated {rows} rows across {tables} tables")


if __name__ == "__main__":
    main()
