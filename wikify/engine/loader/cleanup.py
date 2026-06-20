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


def strip_boilerplate(
	pages: list[tuple[int, str]], boilerplate: set[str]
) -> list[tuple[int, str]]:
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
