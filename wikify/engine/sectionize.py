"""Sectionize pass (Slice 4) — build a doc's Source Section tree from its pages.

Ported from the POC `pipeline._store_sections`: take each page's canonical markdown,
strip cross-page boilerplate (running headers/footers that would read as fake
headings), split into hierarchical sections honoring the embedded PDF outline, and
rebuild the `Source Section` NestedSet tree.

Run at the end of both parse (canonical == baseline there) and remediate (canonical ==
adopted output), so the tree always reflects the best available markdown — the
remediate rebuild never reverts to empty/pre-cleanup text.
"""

from __future__ import annotations

from collections.abc import Callable

from wikify.engine import store
from wikify.engine.classify import classify_document
from wikify.engine.loader.cleanup import clean_pages
from wikify.engine.loader.sectionizer import sectionize
from wikify.engine.loader.toc import toc_level_map


def sectionize_document(source_document: str, pdf_path: str) -> int:
	"""Rebuild the Source Section tree from the doc's canonical pages. Returns the count."""
	level_map = toc_level_map(str(pdf_path))
	pages = clean_pages(store.get_canonical_pages(source_document))
	sections = sectionize(pages, level_map)
	return store.replace_sections(source_document, sections)


def rebuild_and_classify(
	source_document: str,
	pdf_path: str,
	stage_cb: Callable[[str], None] | None = None,
) -> int:
	"""Rebuild the section tree, then classify each fresh section. Returns the count.

	Shared tail of the parse and remediate passes (the rebuild assigns new section
	names, so types are always re-derived). `stage_cb` streams the two post-page-loop
	phase labels so the progress bar doesn't look pinned at the last page.
	"""
	if stage_cb:
		stage_cb("Building section tree")
	count = sectionize_document(source_document, pdf_path)
	if stage_cb:
		stage_cb("Classifying sections")
	classify_document(
		source_document,
		progress_cb=(lambda done, total, title, type_: stage_cb(f"Classifying sections ({done}/{total})"))
		if stage_cb
		else None,
	)
	return count
