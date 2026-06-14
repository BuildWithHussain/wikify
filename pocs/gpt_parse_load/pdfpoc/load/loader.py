from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pdfpoc.load.sqlite_graph import connect, init_db
from pdfpoc.models import utc_now


def load_canonical(canonical: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    document = canonical["document"]
    run = canonical["parse_run"]
    document_id = document["id"]
    run_id = run["id"]

    with connect(db_path) as con:
        init_db(con)
        con.execute(
            """
            INSERT OR REPLACE INTO documents
            (id, filename, sha256, page_count, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM documents WHERE id = ?), ?))
            """,
            (
                document_id,
                document["filename"],
                document["sha256"],
                document.get("page_count"),
                _json(document.get("metadata") or {}),
                document_id,
                utc_now(),
            ),
        )
        con.execute(
            """
            INSERT OR REPLACE INTO parse_runs
            (id, document_id, profile_name, provider, model, config_json, started_at,
             completed_at, duration_ms, cost_usd, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                document_id,
                run["profile_name"],
                run["provider"],
                run.get("model"),
                _json(run.get("config") or {}),
                run["started_at"],
                utc_now(),
                run.get("duration_ms"),
                run.get("cost_usd"),
                "completed",
                None,
            ),
        )

        node_ids: dict[str, str] = {}
        document_node_id = _node_id(run_id, "document")
        node_ids[document_id] = document_node_id
        _insert_node(
            con,
            document_node_id,
            run_id,
            document_id,
            "document",
            label=document["filename"],
            text=None,
            markdown=None,
            page_number=None,
            bbox=None,
            confidence=None,
            metadata=document.get("metadata") or {},
        )

        for page in canonical.get("pages") or []:
            page_node_id = _node_id(run_id, page["id"])
            node_ids[page["id"]] = page_node_id
            _insert_node(
                con,
                page_node_id,
                run_id,
                document_id,
                "page",
                label=f"Page {page['page_number']}",
                text=None,
                markdown=None,
                page_number=page["page_number"],
                bbox=None,
                confidence=None,
                metadata={
                    "width": page.get("width"),
                    "height": page.get("height"),
                    "rotation": page.get("rotation", 0),
                },
            )
            _insert_edge(
                con,
                run_id,
                document_id,
                document_node_id,
                page_node_id,
                "DOCUMENT_HAS_PAGE",
                evidence={"page_number": page["page_number"]},
            )

            for block in page.get("blocks") or []:
                block_node_id = _node_id(run_id, block["id"])
                node_ids[block["id"]] = block_node_id
                _insert_node(
                    con,
                    block_node_id,
                    run_id,
                    document_id,
                    "table" if block.get("type") == "table" else "block",
                    label=_label_for_block(block),
                    text=block.get("text"),
                    markdown=block.get("markdown"),
                    page_number=page["page_number"],
                    bbox=block.get("bbox"),
                    confidence=block.get("confidence"),
                    metadata={
                        **(block.get("metadata") or {}),
                        "block_type": block.get("type"),
                        "reading_order": block.get("reading_order"),
                        "source": block.get("source"),
                        **({"table": block["table"]} if "table" in block else {}),
                    },
                )
                _insert_edge(
                    con,
                    run_id,
                    document_id,
                    page_node_id,
                    block_node_id,
                    "PAGE_HAS_BLOCK",
                    confidence=block.get("confidence"),
                    evidence={"page_number": page["page_number"], "bbox": block.get("bbox")},
                )

        for section in canonical.get("sections") or []:
            section_node_id = _node_id(run_id, section["id"])
            node_ids[section["id"]] = section_node_id
            _insert_node(
                con,
                section_node_id,
                run_id,
                document_id,
                "section",
                label=section.get("title"),
                text=None,
                markdown=section.get("markdown"),
                page_number=section.get("page_start"),
                bbox=None,
                confidence=section.get("confidence"),
                metadata={
                    **(section.get("metadata") or {}),
                    "heading_path": section.get("heading_path"),
                    "level": section.get("level"),
                    "page_end": section.get("page_end"),
                },
            )
            for block_id in section.get("block_ids") or []:
                block_node_id = node_ids.get(block_id)
                if not block_node_id:
                    continue
                _insert_edge(
                    con,
                    run_id,
                    document_id,
                    block_node_id,
                    section_node_id,
                    "BLOCK_PART_OF_SECTION",
                    confidence=section.get("confidence"),
                    evidence={"section_id": section["id"], "block_id": block_id},
                )

        for section in canonical.get("sections") or []:
            section_node_id = node_ids.get(section["id"])
            if not section_node_id:
                continue
            for block_id in section.get("block_ids") or []:
                block = _find_block(canonical, block_id)
                if not block or block.get("type") not in {"table", "image"}:
                    continue
                edge_type = "SECTION_HAS_TABLE" if block["type"] == "table" else "SECTION_HAS_IMAGE"
                _insert_edge(
                    con,
                    run_id,
                    document_id,
                    section_node_id,
                    node_ids[block_id],
                    edge_type,
                    evidence={"section_id": section["id"], "block_id": block_id},
                )

        for index, item in enumerate(canonical.get("warnings") or [], start=1):
            con.execute(
                """
                INSERT OR REPLACE INTO observations
                (id, parse_run_id, document_id, provider, subject_id, observation_type,
                 payload_json, confidence, page_number, bbox_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{run_id}:warning:{index:04d}",
                    run_id,
                    document_id,
                    run["provider"],
                    item.get("block_id"),
                    "warning",
                    _json(item),
                    None,
                    item.get("page_number"),
                    None,
                    utc_now(),
                ),
            )

        for asset in canonical.get("assets") or []:
            page_number = _page_number_for_page_id(canonical, asset.get("page_id"))
            con.execute(
                """
                INSERT OR REPLACE INTO assets
                (id, parse_run_id, document_id, node_id, type, path, mime_type,
                 page_number, bbox_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _node_id(run_id, asset["id"]),
                    run_id,
                    document_id,
                    node_ids.get(asset.get("page_id")),
                    asset.get("type") or "unknown",
                    asset.get("path") or "",
                    asset.get("mime_type"),
                    page_number,
                    _json(asset.get("bbox")),
                    _json(asset.get("metadata") or {}),
                ),
            )

        counts = {
            "documents": con.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"],
            "parse_runs": con.execute("SELECT COUNT(*) AS c FROM parse_runs").fetchone()["c"],
            "nodes_loaded": con.execute(
                "SELECT COUNT(*) AS c FROM nodes WHERE parse_run_id = ?",
                (run_id,),
            ).fetchone()["c"],
            "edges_loaded": con.execute(
                "SELECT COUNT(*) AS c FROM edges WHERE parse_run_id = ?",
                (run_id,),
            ).fetchone()["c"],
        }
    return {"document_id": document_id, "parse_run_id": run_id, **counts}


def _insert_node(
    con,
    node_id: str,
    run_id: str,
    document_id: str,
    node_type: str,
    *,
    label: str | None,
    text: str | None,
    markdown: str | None,
    page_number: int | None,
    bbox: Any,
    confidence: float | None,
    metadata: dict[str, Any],
) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO nodes
        (id, parse_run_id, document_id, type, label, text, markdown, page_number,
         bbox_json, confidence, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            run_id,
            document_id,
            node_type,
            label,
            text,
            markdown,
            page_number,
            _json(bbox),
            confidence,
            _json(metadata),
        ),
    )


def _insert_edge(
    con,
    run_id: str,
    document_id: str,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    *,
    confidence: float | None = None,
    evidence: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    edge_id = f"{run_id}:edge:{edge_type}:{source_node_id}:{target_node_id}"
    con.execute(
        """
        INSERT OR REPLACE INTO edges
        (id, parse_run_id, document_id, source_node_id, target_node_id, type,
         confidence, evidence_json, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            edge_id,
            run_id,
            document_id,
            source_node_id,
            target_node_id,
            edge_type,
            confidence,
            _json(evidence or {}),
            _json(metadata or {}),
        ),
    )


def _node_id(run_id: str, local_id: str) -> str:
    return f"{run_id}:{local_id}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _label_for_block(block: dict[str, Any]) -> str:
    if block.get("type") == "heading":
        return str(block.get("text") or "Heading")
    if block.get("type") == "table":
        return "Table"
    text = str(block.get("text") or "")
    return text[:80] if text else str(block.get("type") or "Block")


def _find_block(canonical: dict[str, Any], block_id: str) -> dict[str, Any] | None:
    for page in canonical.get("pages") or []:
        for block in page.get("blocks") or []:
            if block["id"] == block_id:
                return block
    return None


def _page_number_for_page_id(canonical: dict[str, Any], page_id: str | None) -> int | None:
    for page in canonical.get("pages") or []:
        if page["id"] == page_id:
            return int(page["page_number"])
    return None

