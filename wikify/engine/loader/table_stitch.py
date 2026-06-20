"""Merge tables that pymupdf split across a page boundary.

If page N ends with a Markdown table and page N+1 begins with one of the same
column count, the rows are joined into a single table (a repeated header on the
continuation page is dropped). Heuristic, but cheap and reversible.

Ported verbatim from the POC `loader/table_stitch.py` (no I/O — pure markdown).
"""

from __future__ import annotations

import re

_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _ncols(row: str) -> int:
	return len(row.strip().strip("|").split("|"))


def _trailing_table(md: str):
	lines = md.rstrip().splitlines()
	i = len(lines)
	while i > 0 and _ROW.match(lines[i - 1]):
		i -= 1
	if i == len(lines):  # nothing trailing
		return None
	return lines[:i], lines[i:]  # (before, table_lines)


def _leading_table(md: str):
	lines = md.lstrip("\n").splitlines()
	j = 0
	while j < len(lines) and _ROW.match(lines[j]):
		j += 1
	if j == 0:
		return None
	return lines[:j], lines[j:]  # (table_lines, after)


def stitch_cross_page_tables(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
	out = [[pno, md] for pno, md in pages]
	for k in range(len(out) - 1):
		a = _trailing_table(out[k][1])
		b = _leading_table(out[k + 1][1])
		if not a or not b:
			continue
		a_before, a_tbl = a
		b_tbl, b_after = b
		if not a_tbl or not b_tbl or _ncols(a_tbl[0]) != _ncols(b_tbl[0]):
			continue
		# Drop a repeated header+separator at the start of the continuation table.
		cont = b_tbl[2:] if len(b_tbl) >= 2 and _SEP.match(b_tbl[1]) else b_tbl
		out[k][1] = "\n".join(a_before + a_tbl + cont).strip()
		out[k + 1][1] = "\n".join(b_after).strip()
	return [(pno, md) for pno, md in out]
