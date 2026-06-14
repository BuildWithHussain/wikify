from __future__ import annotations

import re
from collections import Counter
from statistics import mean
from typing import Any

from pdfpoc.normalize.markdown_renderer import render_blocks

_WORD_RE = re.compile(r"[a-z0-9]+")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def evaluate_canonical(canonical: dict[str, Any]) -> dict[str, Any]:
    pages = canonical.get("pages") or []
    blocks = [block for page in pages for block in page.get("blocks") or []]
    sections = canonical.get("sections") or []
    table_count = sum(1 for block in blocks if block.get("type") == "table")
    warnings = canonical.get("warnings") or []
    page_quality = [_page_quality(page) for page in pages]
    text_pages = [item for item in page_quality if item["text_recall"] is not None]
    table_pages = [item for item in page_quality if item["table_score"] is not None]
    heading_pages = [item for item in page_quality if item["heading_score"] is not None]

    block_ids = [block["id"] for block in blocks]
    page_ids = {page["id"] for page in pages}
    section_block_ids = [block_id for section in sections for block_id in section.get("block_ids") or []]
    missing_page_blocks = [block["id"] for block in blocks if block.get("page_id") not in page_ids]
    dangling_section_blocks = [block_id for block_id in section_block_ids if block_id not in set(block_ids)]
    bbox_blocks = [block for block in blocks if block.get("bbox") is not None]

    block_page_coverage = _ratio(len(blocks) - len(missing_page_blocks), len(blocks))
    bbox_coverage = _ratio(len(bbox_blocks), len(blocks))
    section_block_coverage = _ratio(
        len(section_block_ids) - len(dangling_section_blocks),
        len(section_block_ids),
    )

    errors: list[str] = []
    if len(block_ids) != len(set(block_ids)):
        errors.append("Block ids are not unique.")
    if missing_page_blocks:
        errors.append(f"{len(missing_page_blocks)} blocks point to missing pages.")
    if dangling_section_blocks:
        errors.append(f"{len(dangling_section_blocks)} section block refs are dangling.")

    return {
        "document": canonical.get("document", {}).get("filename"),
        "profile": canonical.get("parse_run", {}).get("profile_name"),
        "provider": canonical.get("parse_run", {}).get("provider"),
        "duration_ms": canonical.get("parse_run", {}).get("duration_ms"),
        "cost_usd": canonical.get("parse_run", {}).get("cost_usd"),
        "page_count": len(pages),
        "block_count": len(blocks),
        "section_count": len(sections),
        "table_count": table_count,
        "text_recall_avg": _rounded_mean(item["text_recall"] for item in text_pages),
        "text_recall_min": _rounded_min(item["text_recall"] for item in text_pages),
        "extra_text_ratio_avg": _rounded_mean(item["extra_text_ratio"] for item in text_pages),
        "table_score": _rounded_mean(item["table_score"] for item in table_pages),
        "heading_score": _rounded_mean(item["heading_score"] for item in heading_pages),
        "reading_order_score": None,
        "block_page_coverage": round(block_page_coverage, 3),
        "bbox_coverage": round(bbox_coverage, 3),
        "section_block_coverage": round(section_block_coverage, 3),
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "errors": errors,
        "page_scores": page_quality,
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _page_quality(page: dict[str, Any]) -> dict[str, Any]:
    source_text = str((page.get("metadata") or {}).get("source_text") or "")
    blocks = sorted(page.get("blocks") or [], key=lambda item: item.get("reading_order") or 0)
    parsed_markdown = render_blocks(blocks)
    text_recall = None
    extra_text_ratio = None
    if source_text.strip():
        text_recall = _text_recall(source_text, parsed_markdown)
        extra_text_ratio = _extra_text_ratio(source_text, parsed_markdown)

    has_source_table = _source_has_table(source_text)
    parsed_table_count = sum(1 for block in blocks if block.get("type") == "table")
    table_score = None
    if has_source_table:
        table_score = 1.0 if parsed_table_count else 0.0

    expected_headings = _expected_heading_lines(source_text)
    parsed_headings = sum(1 for block in blocks if block.get("type") == "heading")
    heading_score = None
    if expected_headings:
        heading_score = min(1.0, parsed_headings / expected_headings)

    return {
        "page_number": page.get("page_number"),
        "text_recall": _round_or_none(text_recall),
        "extra_text_ratio": _round_or_none(extra_text_ratio),
        "table_score": _round_or_none(table_score),
        "heading_score": _round_or_none(heading_score),
        "source_table_detected": has_source_table,
        "parsed_table_count": parsed_table_count,
        "expected_heading_count": expected_headings,
        "parsed_heading_count": parsed_headings,
    }


def _tokens(text: str) -> Counter:
    cleaned = re.sub(r"<[^>]+>", " ", text.lower())
    cleaned = re.sub(r"[#*_`>|-]+", " ", cleaned)
    return Counter(_WORD_RE.findall(cleaned))


def _text_recall(source_text: str, parsed_text: str) -> float:
    source = _tokens(source_text)
    if not source:
        return 1.0
    parsed = _tokens(parsed_text)
    overlap = sum(min(count, parsed.get(token, 0)) for token, count in source.items())
    return overlap / sum(source.values())


def _extra_text_ratio(source_text: str, parsed_text: str) -> float:
    parsed = _tokens(parsed_text)
    if not parsed:
        return 0.0
    source = _tokens(source_text)
    extra = sum(max(0, count - source.get(token, 0)) for token, count in parsed.items())
    return extra / sum(parsed.values())


def _source_has_table(source_text: str) -> bool:
    table_like_lines = 0
    for line in source_text.splitlines():
        if _TABLE_ROW_RE.match(line):
            table_like_lines += 1
        elif len(re.findall(r"\S\s{2,}\S", line)) >= 2:
            table_like_lines += 1
    if table_like_lines >= 3:
        return True

    lowered = source_text.lower()
    header_terms = ["revision", "description", "initiated by", "approved by", "page", "issue"]
    header_hits = sum(1 for term in header_terms if term in lowered)
    date_rows = len(re.findall(r"\b\d{1,2}/\d{4}\b", source_text))
    numeric_rows = len(re.findall(r"(?m)^\s*\d+\s*$", source_text))
    return header_hits >= 3 and (date_rows >= 3 or numeric_rows >= 4)


def _expected_heading_lines(source_text: str) -> int:
    headings = 0
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 100:
            continue
        letters = [char for char in line if char.isalpha()]
        if len(letters) < 4:
            continue
        upper_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
        if upper_ratio >= 0.75:
            headings += 1
    return headings


def _rounded_mean(values) -> float | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return round(mean(valid), 3)


def _rounded_min(values) -> float | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return round(min(valid), 3)


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)
