from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def inspect_database(db_path: str | Path, document: str | None = None) -> dict:
    with connect(db_path) as con:
        init_db(con)
        params: list[str] = []
        doc_filter = ""
        if document:
            doc_filter = " WHERE id = ? OR filename = ?"
            params = [document, document]
        docs = [dict(row) for row in con.execute(f"SELECT * FROM documents{doc_filter}", params)]
        result = {"documents": docs, "parse_runs": [], "node_counts": [], "warning_count": 0}
        if not docs:
            return result
        doc_ids = [doc["id"] for doc in docs]
        placeholders = ",".join("?" for _ in doc_ids)
        result["parse_runs"] = [
            dict(row)
            for row in con.execute(
                f"SELECT * FROM parse_runs WHERE document_id IN ({placeholders}) ORDER BY started_at DESC",
                doc_ids,
            )
        ]
        result["node_counts"] = [
            dict(row)
            for row in con.execute(
                f"""
                SELECT document_id, parse_run_id, type, COUNT(*) AS count
                FROM nodes
                WHERE document_id IN ({placeholders})
                GROUP BY document_id, parse_run_id, type
                ORDER BY document_id, parse_run_id, type
                """,
                doc_ids,
            )
        ]
        result["warning_count"] = con.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM observations
            WHERE document_id IN ({placeholders}) AND observation_type = 'warning'
            """,
            doc_ids,
        ).fetchone()["count"]
        return result

