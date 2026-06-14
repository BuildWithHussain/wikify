from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pdfpoc.config import RUNS_DIR
from pdfpoc.eval.checks import evaluate_canonical
from pdfpoc.load.sqlite_graph import connect, init_db
from pdfpoc.models import utc_now
from pdfpoc.normalize.markdown_renderer import render_blocks

REVIEW_STATUSES = {"unreviewed", "needs_review", "reviewed"}


def build_overview(runs_dir: str | Path = RUNS_DIR, db_path: str | Path | None = None) -> dict[str, Any]:
    runs = [_run_summary(path, db_path) for path in _canonical_paths(runs_dir)]
    documents: dict[str, dict[str, Any]] = {}
    for run in runs:
        document = documents.setdefault(
            run["document_id"],
            {
                "id": run["document_id"],
                "filename": run["document_filename"],
                "page_count": run["document_page_count"],
                "runs": [],
                "pages": set(),
                "review": _review_counts(db_path, run["document_id"]),
            },
        )
        document["runs"].append(run)
        document["pages"].update(run["pages"])

    docs = []
    for document in documents.values():
        document["pages"] = sorted(document["pages"])
        document["runs"].sort(key=lambda row: row.get("started_at") or "", reverse=True)
        docs.append(document)
    docs.sort(key=lambda row: row["filename"])
    return {
        "documents": docs,
        "run_count": len(runs),
        "db_path": str(db_path) if db_path else None,
        "runs_dir": str(runs_dir),
    }


def page_compare(
    document_id: str,
    page_number: int,
    run_ids: list[str],
    *,
    runs_dir: str | Path = RUNS_DIR,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    source_text = ""
    image_asset: dict[str, Any] | None = None
    filename = ""
    page_numbers: set[int] = set()

    for canonical_path in _canonical_paths(runs_dir):
        canonical = _read_json(canonical_path)
        document = canonical.get("document") or {}
        run = canonical.get("parse_run") or {}
        run_id = str(run.get("id") or "")
        if document.get("id") != document_id or run_id not in run_ids:
            continue
        filename = str(document.get("filename") or filename)
        page = _page_by_number(canonical, page_number)
        if not page:
            continue
        page_numbers.update(int(item.get("page_number")) for item in canonical.get("pages") or [])
        if not source_text:
            source_text = str((page.get("metadata") or {}).get("source_text") or "")
        if image_asset is None:
            image_asset = _asset_for_page(canonical, page_number)
        scorecard = evaluate_canonical(canonical)
        selected.append(
            {
                "run": _run_summary_from_canonical(canonical, canonical_path, scorecard, db_path),
                "page": _page_payload(canonical, page, scorecard, db_path),
            }
        )

    selected.sort(key=lambda row: row["run"].get("started_at") or "", reverse=True)
    return {
        "document_id": document_id,
        "filename": filename,
        "page_number": page_number,
        "page_numbers": sorted(page_numbers),
        "source_text": source_text,
        "image_asset": image_asset,
        "review": _page_review(db_path, document_id, page_number),
        "runs": selected,
    }


def save_page_review(
    document_id: str,
    page_number: int,
    payload: dict[str, Any],
    *,
    db_path: str | Path | None,
) -> dict[str, Any]:
    if not db_path:
        raise ValueError("db_path is required to save reviews")

    status = _clean_text(payload.get("status") or "unreviewed") or "unreviewed"
    if status not in REVIEW_STATUSES:
        raise ValueError(f"Unsupported review status: {status}")

    rejected = payload.get("rejected_run_ids") or []
    if not isinstance(rejected, list):
        raise ValueError("rejected_run_ids must be a list")
    rejected_run_ids = sorted(_clean_text(item) for item in rejected if _clean_text(item))

    now = utc_now()
    review_id = f"{document_id}:page:{int(page_number):04d}"
    values = {
        "id": review_id,
        "document_id": _clean_text(document_id),
        "page_number": int(page_number),
        "page_type": _clean_text(payload.get("page_type")),
        "winning_parse_run_id": _clean_text(payload.get("winning_parse_run_id")) or None,
        "rejected_parse_run_ids_json": json.dumps(rejected_run_ids, sort_keys=True),
        "rejection_reason": _clean_text(payload.get("rejection_reason")),
        "status": status,
        "notes": _clean_text(payload.get("notes")),
        "created_at": now,
        "updated_at": now,
    }
    with connect(db_path) as con:
        init_db(con)
        existing = con.execute(
            """
            SELECT created_at
            FROM page_reviews
            WHERE document_id = ? AND page_number = ?
            """,
            (values["document_id"], values["page_number"]),
        ).fetchone()
        values["created_at"] = existing["created_at"] if existing else now
        con.execute(
            """
            INSERT OR REPLACE INTO page_reviews
            (id, document_id, page_number, page_type, winning_parse_run_id,
             rejected_parse_run_ids_json, rejection_reason, status, notes,
             created_at, updated_at)
            VALUES (:id, :document_id, :page_number, :page_type, :winning_parse_run_id,
                    :rejected_parse_run_ids_json, :rejection_reason, :status, :notes,
                    :created_at, :updated_at)
            """,
            values,
        )
    return _page_review(db_path, values["document_id"], values["page_number"])


def _canonical_paths(runs_dir: str | Path) -> list[Path]:
    return sorted(Path(runs_dir).glob("**/canonical.json"))


def _run_summary(canonical_path: Path, db_path: str | Path | None) -> dict[str, Any]:
    canonical = _read_json(canonical_path)
    return _run_summary_from_canonical(canonical, canonical_path, evaluate_canonical(canonical), db_path)


def _run_summary_from_canonical(
    canonical: dict[str, Any],
    canonical_path: Path,
    scorecard: dict[str, Any],
    db_path: str | Path | None,
) -> dict[str, Any]:
    document = canonical.get("document") or {}
    run = canonical.get("parse_run") or {}
    pages = [int(page.get("page_number")) for page in canonical.get("pages") or []]
    run_id = str(run.get("id") or "")
    return {
        "id": run_id,
        "document_id": document.get("id"),
        "document_filename": document.get("filename"),
        "document_page_count": document.get("page_count"),
        "profile": run.get("profile_name"),
        "provider": run.get("provider"),
        "model": run.get("model"),
        "started_at": run.get("started_at"),
        "duration_ms": run.get("duration_ms"),
        "cost_usd": run.get("cost_usd"),
        "pages": sorted(pages),
        "page_count": len(pages),
        "canonical_path": str(canonical_path),
        "run_dir": str(canonical_path.parent),
        "scorecard": {
            key: scorecard.get(key)
            for key in (
                "text_recall_avg",
                "text_recall_min",
                "extra_text_ratio_avg",
                "heading_score",
                "table_score",
                "bbox_coverage",
                "warnings_count",
                "errors_count",
                "block_count",
                "section_count",
                "table_count",
            )
        },
        "ingest": _ingest_summary(db_path, run_id),
        "tagging": _tagging_summary(db_path, run_id),
    }


def _page_payload(
    canonical: dict[str, Any],
    page: dict[str, Any],
    scorecard: dict[str, Any],
    db_path: str | Path | None,
) -> dict[str, Any]:
    run_id = str((canonical.get("parse_run") or {}).get("id") or "")
    page_number = int(page.get("page_number"))
    blocks = sorted(page.get("blocks") or [], key=lambda item: item.get("reading_order") or 0)
    warnings = [
        item
        for item in canonical.get("warnings") or []
        if item.get("page_number") in {None, page_number}
    ]
    return {
        "page_number": page_number,
        "metrics": _page_score(scorecard, page_number),
        "generated_markdown": render_blocks(blocks),
        "generated_blocks": [_block_payload(block) for block in blocks],
        "ingested": _ingested_page(db_path, run_id, page_number),
        "warnings": warnings,
        "asset": _asset_for_page(canonical, page_number),
        "metadata": page.get("metadata") or {},
    }


def _block_payload(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": block.get("id"),
        "type": block.get("type"),
        "text": block.get("text"),
        "markdown": block.get("markdown"),
        "bbox": block.get("bbox"),
        "confidence": block.get("confidence"),
        "reading_order": block.get("reading_order"),
    }


def _page_score(scorecard: dict[str, Any], page_number: int) -> dict[str, Any]:
    for page_score in scorecard.get("page_scores") or []:
        if int(page_score.get("page_number")) == page_number:
            return page_score
    return {}


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _page_by_number(canonical: dict[str, Any], page_number: int) -> dict[str, Any] | None:
    for page in canonical.get("pages") or []:
        if int(page.get("page_number")) == page_number:
            return page
    return None


def _asset_for_page(canonical: dict[str, Any], page_number: int) -> dict[str, Any] | None:
    page_id = f"page_{page_number:03d}"
    for asset in canonical.get("assets") or []:
        if asset.get("page_number") == page_number or asset.get("page_id") == page_id:
            return {
                "id": asset.get("id"),
                "path": asset.get("path"),
                "mime_type": asset.get("mime_type"),
                "metadata": asset.get("metadata") or {},
            }
    return None


def _connect_readonly(db_path: str | Path | None) -> sqlite3.Connection | None:
    if not db_path:
        return None
    path = Path(db_path)
    if not path.exists():
        return None
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    init_db(con)
    return con


def _ingest_summary(db_path: str | Path | None, run_id: str) -> dict[str, Any]:
    con = _connect_readonly(db_path)
    if con is None:
        return {"loaded": False, "status": "not_loaded", "node_count": 0, "edge_count": 0}
    try:
        run = con.execute("SELECT status, completed_at FROM parse_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return {"loaded": False, "status": "not_loaded", "node_count": 0, "edge_count": 0}
        node_count = con.execute("SELECT COUNT(*) AS c FROM nodes WHERE parse_run_id = ?", (run_id,)).fetchone()["c"]
        edge_count = con.execute("SELECT COUNT(*) AS c FROM edges WHERE parse_run_id = ?", (run_id,)).fetchone()["c"]
        node_types = [
            dict(row)
            for row in con.execute(
                """
                SELECT type, COUNT(*) AS count
                FROM nodes
                WHERE parse_run_id = ?
                GROUP BY type
                ORDER BY type
                """,
                (run_id,),
            )
        ]
        return {
            "loaded": True,
            "status": run["status"],
            "completed_at": run["completed_at"],
            "node_count": node_count,
            "edge_count": edge_count,
            "node_types": node_types,
        }
    finally:
        con.close()


def _tagging_summary(db_path: str | Path | None, run_id: str) -> dict[str, Any]:
    con = _connect_readonly(db_path)
    if con is None:
        return {"status": "not_started", "observation_count": 0, "types": []}
    try:
        rows = [
            dict(row)
            for row in con.execute(
                """
                SELECT observation_type AS type, COUNT(*) AS count
                FROM observations
                WHERE parse_run_id = ?
                GROUP BY observation_type
                ORDER BY observation_type
                """,
                (run_id,),
            )
        ]
        semantic = [row for row in rows if row["type"] not in {"warning"}]
        status = "not_started" if not semantic else "has_observations"
        return {
            "status": status,
            "observation_count": sum(row["count"] for row in rows),
            "semantic_observation_count": sum(row["count"] for row in semantic),
            "types": rows,
        }
    finally:
        con.close()


def _ingested_page(db_path: str | Path | None, run_id: str, page_number: int) -> dict[str, Any]:
    con = _connect_readonly(db_path)
    if con is None:
        return {"loaded": False, "nodes": [], "markdown": "", "warnings": []}
    try:
        run = con.execute("SELECT id FROM parse_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return {"loaded": False, "nodes": [], "markdown": "", "warnings": []}
        nodes = [
            {
                **dict(row),
                "metadata": _json_or_empty(row["metadata_json"]),
                "bbox": _json_or_none(row["bbox_json"]),
            }
            for row in con.execute(
                """
                SELECT id, type, label, text, markdown, page_number, bbox_json, confidence, metadata_json
                FROM nodes
                WHERE parse_run_id = ? AND page_number = ? AND type IN ('block', 'table', 'section')
                ORDER BY type = 'section', id
                """,
                (run_id, page_number),
            )
        ]
        warnings = [
            _json_or_empty(row["payload_json"])
            for row in con.execute(
                """
                SELECT payload_json
                FROM observations
                WHERE parse_run_id = ? AND observation_type = 'warning'
                  AND (page_number IS NULL OR page_number = ?)
                ORDER BY id
                """,
                (run_id, page_number),
            )
        ]
        markdown = "\n\n".join(
            str(node.get("markdown") or node.get("text") or "").strip()
            for node in nodes
            if node.get("type") in {"block", "table"}
        )
        return {"loaded": True, "nodes": nodes, "markdown": markdown.strip(), "warnings": warnings}
    finally:
        con.close()


def _review_counts(db_path: str | Path | None, document_id: str) -> dict[str, Any]:
    con = _connect_readonly(db_path)
    if con is None:
        return {"total": 0, "statuses": []}
    try:
        rows = [
            dict(row)
            for row in con.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM page_reviews
                WHERE document_id = ?
                GROUP BY status
                ORDER BY status
                """,
                (document_id,),
            )
        ]
        return {"total": sum(row["count"] for row in rows), "statuses": rows}
    finally:
        con.close()


def _page_review(db_path: str | Path | None, document_id: str, page_number: int) -> dict[str, Any]:
    empty = {
        "status": "unreviewed",
        "page_type": "",
        "winning_parse_run_id": "",
        "rejected_run_ids": [],
        "rejection_reason": "",
        "notes": "",
        "updated_at": None,
    }
    con = _connect_readonly(db_path)
    if con is None:
        return empty
    try:
        row = con.execute(
            """
            SELECT page_type, winning_parse_run_id, rejected_parse_run_ids_json,
                   rejection_reason, status, notes, updated_at
            FROM page_reviews
            WHERE document_id = ? AND page_number = ?
            """,
            (document_id, int(page_number)),
        ).fetchone()
        if not row:
            return empty
        return {
            "status": row["status"] or "unreviewed",
            "page_type": row["page_type"] or "",
            "winning_parse_run_id": row["winning_parse_run_id"] or "",
            "rejected_run_ids": _json_list(row["rejected_parse_run_ids_json"]),
            "rejection_reason": row["rejection_reason"] or "",
            "notes": row["notes"] or "",
            "updated_at": row["updated_at"],
        }
    finally:
        con.close()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item]


def _json_or_empty(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_or_none(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
