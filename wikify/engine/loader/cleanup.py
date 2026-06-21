"""Strip repeated page headers/footers before sectionizing.

Real manuals repeat a running header/footer on every page (doc title, doc code,
"Pg X of Y", version/date). Left in, each becomes a fake heading. We remove lines
that recur across many pages, plus a few varying-boilerplate patterns (page
numbers, doc codes) that won't match exactly page-to-page.

Ported verbatim from the POC `loader/cleanup.py` (pure markdown, no I/O). Wired into
the pipeline at sectionize time (Slice 4); shipped here per the Slice 3 cleanup port.
"""

from __future__ import annotations

import re
from collections import Counter

_NORM = re.compile(r"[#*_`>\-\s]+")
_VARYING = [
	re.compile(r"(?i)\bpg\.?\s*\d+\s*of\s*\d+"),
	re.compile(r"(?i)\bpage\s*\d+\s*of\s*\d+"),
	re.compile(r"(?i)^man/[a-z0-9/]+"),
	re.compile(r"(?i)\bver\.?\s*:"),
	re.compile(r"(?i)\bissue\s*:\s*\d"),
	re.compile(r"(?i)^\s*date\s*:"),
]


def _norm(line: str) -> str:
	return _NORM.sub(" ", line).strip().lower()


def find_boilerplate(pages: list[tuple[int, str]]) -> set[str]:
	"""Normalized lines that recur on a large fraction of pages."""
	counts: Counter[str] = Counter()
	for _, md in pages:
		for nl in {_norm(line) for line in md.splitlines() if _norm(line)}:
			counts[nl] += 1
	threshold = max(3, int(0.30 * len(pages)))
	return {line for line, c in counts.items() if c >= threshold and len(line) <= 90}


def _is_varying(line: str) -> bool:
	return any(p.search(line) for p in _VARYING)


def strip_boilerplate(pages: list[tuple[int, str]], boilerplate: set[str]) -> list[tuple[int, str]]:
	out: list[tuple[int, str]] = []
	for pno, md in pages:
		kept = [
			line
			for line in md.splitlines()
			if not (_norm(line) and _norm(line) in boilerplate) and not _is_varying(line)
		]
		out.append((pno, "\n".join(kept)))
	return out


def clean_pages(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
	return strip_boilerplate(pages, find_boilerplate(pages))


def strip_outer_markdown_fence(text: str) -> str:
	"""Unwrap a reply an LLM fenced as one ```markdown … ``` block (with optional
	commentary around it), returning just the inner markdown.

	Models sometimes ignore "no code fences" and fence the whole page — often adding a
	trailing "The table is part of…" note — so real tables/headings render as a literal
	code block. We unwrap only when the first non-blank line opens a markdown/md (or
	untagged) fence and the block has no nested fence, so a genuine ```mermaid diagram
	is left untouched.
	"""
	lines = text.strip().splitlines()
	start = next((i for i, line in enumerate(lines) if line.strip()), None)
	if start is None or not lines[start].startswith("```"):
		return text
	if lines[start][3:].strip().lower() not in ("", "markdown", "md"):
		return text
	close = next((i for i in range(start + 1, len(lines)) if set(lines[i].strip()) == {"`"}), None)
	if close is None:
		return text
	# A nested fence inside the block (e.g. ```mermaid) means unwrapping could corrupt it.
	if any(lines[i].lstrip().startswith("```") for i in range(start + 1, close)):
		return text
	return "\n".join(lines[start + 1 : close]).strip()
