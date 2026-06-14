from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pdfpoc.models import content_sha256, document_id_for_sha, new_run_id, utc_now, warning
from pdfpoc.normalize.markdown_renderer import render_blocks
from pdfpoc.normalize.section_builder import build_sections

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def canonicalize_raw(
    raw: dict[str, Any],
    pdf_path: str | Path,
    profile: dict[str, Any],
    *,
    run_id: str | None = None,
    started_at: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    sha256 = content_sha256(pdf_path)
    doc_id = document_id_for_sha(sha256)
    parse_run_id = run_id or new_run_id(profile["name"])
    pages: list[dict[str, Any]] = []
    warnings = list(raw.get("warnings") or [])
    block_counter = 0

    for page_index, raw_page in enumerate(raw.get("pages") or [], start=1):
        page_number = int(raw_page.get("page_number") or page_index)
        page_id = f"page_{page_number:03d}"
        page = {
            "id": page_id,
            "page_number": page_number,
            "width": raw_page.get("width"),
            "height": raw_page.get("height"),
            "rotation": raw_page.get("rotation", 0),
            "metadata": {
                "source_text": raw_page.get("source_text") or "",
            },
            "blocks": [],
        }

        raw_blocks = raw_page.get("blocks") or []
        if raw_blocks:
            blocks, block_counter = _normalize_raw_blocks(
                raw_blocks,
                page_id,
                page_number,
                raw.get("provider") or profile["provider"],
                block_counter,
                warnings,
            )
        else:
            blocks, block_counter = _blocks_from_markdown(
                raw_page.get("markdown") or raw_page.get("text") or "",
                page_id,
                page_number,
                raw.get("provider") or profile["provider"],
                block_counter,
                warnings,
            )
        page["blocks"] = blocks
        pages.append(page)

    if not pages:
        warnings.append(warning("no_pages", "Parser returned no pages.", severity="error"))

    sections = build_sections(pages) if profile.get("build_sections", True) else []
    assets = _normalize_assets(raw.get("assets") or [], pages)
    page_count = int((raw.get("metadata") or {}).get("total_page_count") or len(pages))
    cost_usd = (raw.get("metadata") or {}).get("cost_usd")

    canonical = {
        "schema_version": "0.1",
        "document": {
            "id": doc_id,
            "filename": Path(pdf_path).name,
            "sha256": sha256,
            "page_count": page_count,
            "metadata": raw.get("document_metadata") or {},
        },
        "parse_run": {
            "id": parse_run_id,
            "profile_name": profile["name"],
            "provider": raw.get("provider") or profile["provider"],
            "model": raw.get("model") or profile.get("model"),
            "started_at": started_at or utc_now(),
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
            "config": _profile_for_storage(profile),
        },
        "pages": pages,
        "sections": sections,
        "assets": assets,
        "warnings": warnings,
    }
    return canonical


def _profile_for_storage(profile: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in profile.items() if not key.startswith("_")}


def _normalize_raw_blocks(
    raw_blocks: list[dict[str, Any]],
    page_id: str,
    page_number: int,
    provider: str,
    block_counter: int,
    warnings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    blocks: list[dict[str, Any]] = []
    for index, raw_block in enumerate(raw_blocks, start=1):
        block_counter += 1
        block_id = f"block_{block_counter:06d}"
        block_type = str(raw_block.get("type") or "paragraph")
        text = str(raw_block.get("text") or _markdown_to_text(str(raw_block.get("markdown") or ""))).strip()
        markdown = str(raw_block.get("markdown") or _markdown_for_block(block_type, text, raw_block.get("level")))
        bbox = raw_block.get("bbox")
        if bbox is None:
            warnings.append(
                warning(
                    "missing_bbox",
                    f"Provider did not return a bounding box for {block_type} block.",
                    page_number=page_number,
                    block_id=block_id,
                )
            )
        blocks.append(
            {
                "id": block_id,
                "page_id": page_id,
                "type": block_type,
                "text": text,
                "markdown": markdown,
                "level": raw_block.get("level"),
                "bbox": bbox,
                "confidence": raw_block.get("confidence"),
                "reading_order": raw_block.get("reading_order", index),
                "source": {"provider": provider, "raw_id": raw_block.get("id")},
                "metadata": raw_block.get("metadata") or {},
                **({"table": raw_block["table"]} if "table" in raw_block else {}),
            }
        )
    return blocks, block_counter


def _blocks_from_markdown(
    markdown: str,
    page_id: str,
    page_number: int,
    provider: str,
    block_counter: int,
    warnings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    blocks: list[dict[str, Any]] = []
    order = 0
    paragraphs: list[str] = []
    table_lines: list[str] = []
    list_lines: list[str] = []

    def add_block(block_type: str, lines: list[str], level: int | None = None) -> None:
        nonlocal block_counter, order
        if not lines:
            return
        text_markdown = "\n".join(lines).strip()
        if not text_markdown:
            return
        block_counter += 1
        order += 1
        block_id = f"block_{block_counter:06d}"
        block = {
            "id": block_id,
            "page_id": page_id,
            "type": block_type,
            "text": _markdown_to_text(text_markdown),
            "markdown": text_markdown,
            "level": level,
            "bbox": None,
            "confidence": None,
            "reading_order": order,
            "source": {"provider": provider, "raw_id": None},
            "metadata": {},
        }
        if block_type == "table":
            block["table"] = _table_metadata(text_markdown)
        blocks.append(block)
        warnings.append(
            warning(
                "missing_bbox",
                f"Provider did not return a bounding box for {block_type} block.",
                page_number=page_number,
                block_id=block_id,
            )
        )

    def flush_text() -> None:
        nonlocal paragraphs, list_lines, table_lines
        if table_lines:
            add_block("table", table_lines)
            table_lines = []
        if list_lines:
            add_block("list", list_lines)
            list_lines = []
        if paragraphs:
            add_block("paragraph", paragraphs)
            paragraphs = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        heading = _HEADING_RE.match(line)
        if heading:
            flush_text()
            add_block("heading", [line], level=len(heading.group(1)))
            continue
        if _is_table_line(line):
            if paragraphs or list_lines:
                flush_text()
            table_lines.append(line)
            continue
        if _LIST_RE.match(line):
            if paragraphs or table_lines:
                flush_text()
            list_lines.append(line)
            continue
        if not line.strip():
            flush_text()
            continue
        if table_lines or list_lines:
            flush_text()
        paragraphs.append(line)
    flush_text()
    return blocks, block_counter


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _markdown_to_text(markdown: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markdown)
    text = re.sub(r"[#*_`>|-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _markdown_for_block(block_type: str, text: str, level: int | None) -> str:
    if block_type == "heading":
        return f"{'#' * int(level or 1)} {text}".strip()
    return text


def _table_metadata(markdown: str) -> dict[str, Any]:
    rows = [line for line in markdown.splitlines() if _is_table_line(line)]
    data_rows = [line for line in rows if not re.match(r"^\s*\|[\s:|-]+\|\s*$", line)]
    columns = 0
    if data_rows:
        columns = max(len(line.strip().strip("|").split("|")) for line in data_rows)
    cells = []
    for row_index, row in enumerate(data_rows):
        for column_index, value in enumerate(row.strip().strip("|").split("|")):
            cells.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": value.strip(),
                    "bbox": None,
                }
            )
    return {"format": "markdown", "rows": len(data_rows), "columns": columns, "cells": cells}


def _normalize_assets(raw_assets: list[dict[str, Any]], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    page_id_by_number = {page["page_number"]: page["id"] for page in pages}
    assets: list[dict[str, Any]] = []
    for index, asset in enumerate(raw_assets, start=1):
        page_number = asset.get("page_number")
        assets.append(
            {
                "id": asset.get("id") or f"asset_{index:03d}",
                "type": asset.get("type") or "unknown",
                "page_id": asset.get("page_id") or page_id_by_number.get(page_number),
                "path": asset.get("path"),
                "mime_type": asset.get("mime_type"),
                "bbox": asset.get("bbox"),
                "metadata": asset.get("metadata") or {},
            }
        )
    return assets
