"""Split per-page markdown into hierarchical sections, tracking page ranges.

A section spans from one heading until the next heading of equal-or-higher level.
The embedded-ToC level map (if present) overrides parsed heading levels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from loader.toc import correct_level

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
# Numbered headings ("1.", "1.1", "1.1.1") encode their own level — recover it.
# Allow an optional trailing dot so top-level "1." is caught, not just "1.1".
_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")


def _clean_title(raw: str) -> str:
    return raw.strip().strip("*").strip()


def _infer_level(title: str, fallback: int) -> int:
    m = _NUM_RE.match(title)
    if m:
        return min(6, m.group(1).count(".") + 1)
    return fallback


@dataclass
class Section:
    title: str
    level: int
    hierarchy_path: list[str]
    page_start: int
    page_end: int
    markdown: str = ""
    section_type: str | None = None


def sectionize(pages: list[tuple[int, str]], level_map: dict[str, int] | None = None) -> list[Section]:
    """pages: list of (page_no, markdown). Returns ordered sections."""
    level_map = level_map or {}
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (level, title) for hierarchy path
    current: Section | None = None
    buf: list[str] = []

    def flush():
        if current is not None:
            current.markdown = "\n".join(buf).strip()
            sections.append(current)

    for page_no, md in pages:
        for line in md.splitlines():
            m = _HEADING_RE.match(line)
            if m:
                flush()
                buf = []
                title = _clean_title(m.group(2))
                # Embedded ToC wins; else numbering; else the parser's '#' depth.
                level = correct_level(title, _infer_level(title, len(m.group(1))), level_map)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                current = Section(
                    title=title,
                    level=level,
                    hierarchy_path=[t for _, t in stack],
                    page_start=page_no,
                    page_end=page_no,
                )
            else:
                if current is not None:
                    current.page_end = page_no
                buf.append(line)

    flush()

    # Collapse headings the parser re-emitted as per-page running titles.
    # Numbered headings (e.g. "3.", "3.1") should be unique, so merge ALL their
    # occurrences (running chapter headers span many pages). Non-numbered headings
    # only merge when consecutive (they may legitimately recur, e.g. "General").
    merged: list[Section] = []
    numbered: dict[str, Section] = {}
    for sec in sections:
        key = sec.title.lower()
        is_numbered = bool(_NUM_RE.match(sec.title))
        prev = merged[-1] if merged else None
        if is_numbered and key in numbered:
            tgt = numbered[key]
            tgt.page_end = max(tgt.page_end, sec.page_end)
            tgt.markdown = (tgt.markdown + "\n" + sec.markdown).strip()
        elif prev and prev.level == sec.level and prev.title.lower() == key:
            prev.page_end = max(prev.page_end, sec.page_end)
            prev.markdown = (prev.markdown + "\n" + sec.markdown).strip()
        else:
            merged.append(sec)
            if is_numbered:
                numbered[key] = sec
    sections = merged

    # Content before the first heading becomes a synthetic "Preamble" section.
    if not sections and pages:
        whole = "\n".join(md for _, md in pages).strip()
        if whole:
            sections.append(
                Section(
                    title="Preamble",
                    level=1,
                    hierarchy_path=["Preamble"],
                    page_start=pages[0][0],
                    page_end=pages[-1][0],
                    markdown=whole,
                )
            )
    return sections
