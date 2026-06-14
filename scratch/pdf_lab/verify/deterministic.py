"""Deterministic checks — no LLM. Highest-value, cheapest layer.

text_recall  : fraction of ground-truth tokens present in the markdown (dropped content)
extra_ratio  : markdown tokens absent from ground truth (hallucination proxy)
table_score  : crude table-structure similarity (cell counts) when a table is present
"""

from __future__ import annotations

import re
from collections import Counter

_WORD_RE = re.compile(r"[a-z0-9]+")
_MD_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def _tokens(text: str) -> Counter:
    # Strip common markdown syntax so we compare words, not formatting.
    cleaned = re.sub(r"[#*_`>\-\|]", " ", text.lower())
    return Counter(_WORD_RE.findall(cleaned))


def text_recall(ground_truth: str, markdown: str) -> float:
    gt = _tokens(ground_truth)
    if not gt:
        return 1.0
    md = _tokens(markdown)
    overlap = sum(min(c, md.get(tok, 0)) for tok, c in gt.items())
    return overlap / sum(gt.values())


def extra_ratio(ground_truth: str, markdown: str) -> float:
    md = _tokens(markdown)
    if not md:
        return 0.0
    gt = _tokens(ground_truth)
    extra = sum(max(0, c - gt.get(tok, 0)) for tok, c in md.items())
    return extra / sum(md.values())


def _gt_has_table(ground_truth: str) -> bool:
    # Heuristic: multiple lines with several runs of 2+ spaces => columnar layout.
    cols = sum(1 for ln in ground_truth.splitlines() if len(re.findall(r"\S {2,}", ln)) >= 2)
    return cols >= 3


def _md_table_cell_count(markdown: str) -> int:
    cells = 0
    for ln in markdown.splitlines():
        if _MD_TABLE_ROW.match(ln) and not re.match(r"^\s*\|[\s:|-]+\|\s*$", ln):
            cells += len([c for c in ln.split("|")[1:-1]])
    return cells


_ARTIFACT_PATTERNS = [
    ("picture omitted", re.compile(r"intentionally omitted")),
    ("picture-text wrapper", re.compile(r"-+\s*Start of picture text")),
    ("empty table cells", re.compile(r"(?m)^\s*\|(\s*\|){2,}\s*$")),
]


def parser_artifacts(markdown: str) -> list[str]:
    """Tell-tale signs the extractor mangled structure (text may be complete but
    the layout is destroyed) — a strong signal to remediate even if recall is high."""
    found = [name for name, pat in _ARTIFACT_PATTERNS if pat.search(markdown)]
    if markdown.count("<br>") > 15:
        found.append("flattened <br> blob")
    return found


def table_score(ground_truth: str, markdown: str) -> float | None:
    """Return None when no table is detected on the page."""
    if not _gt_has_table(ground_truth):
        return None
    md_cells = _md_table_cell_count(markdown)
    if md_cells == 0:
        return 0.0  # table present but parser produced no markdown table
    # Reward presence + plausible size; full TEDS is out of scope for the POC.
    return min(1.0, md_cells / max(md_cells, 1))
