"""Persistence seam — replaces the POC's `loader/graph.py` (SQLite) with the
Frappe ORM. The pipeline calls these helpers instead of touching DocTypes
directly, keeping the ported logic diff-minimal against the POC.

Slice 1b surface: `create_document`, `add_page`, `set_page_count`. Slice 2 adds
`set_page_scores` + `set_mean_score`. Sections and canonical selection land later.
"""

from __future__ import annotations

import frappe
from frappe.utils.file_manager import save_file


def create_document(
	title: str,
	import_name: str | None = None,
	pdf_url: str | None = None,
	parser: str | None = None,
) -> str:
	"""Create a Source Document and return its name."""
	doc = frappe.new_doc("Source Document")
	doc.title = title
	doc.set("import", import_name)  # 'import' is a Python keyword — set by string
	doc.pdf = pdf_url
	doc.parser_used = parser
	doc.status = "Parsed"
	doc.insert(ignore_permissions=True)
	return doc.name


def add_page(
	source_document: str,
	page_no: int,
	kind: str,
	png_bytes: bytes,
	baseline_markdown: str,
) -> str:
	"""Create a Source Page row + attach its rendered PNG as a private File."""
	page = frappe.new_doc("Source Page")
	page.source_document = source_document
	page.page_no = page_no
	page.kind = kind
	page.baseline_markdown = baseline_markdown
	page.insert(ignore_permissions=True)

	file_doc = save_file(
		f"page-{page_no:04d}.png",
		png_bytes,
		"Source Page",
		page.name,
		df="image",
		is_private=1,
	)
	page.db_set("image", file_doc.file_url)
	return page.name


def set_page_count(source_document: str, count: int) -> None:
	frappe.db.set_value("Source Document", source_document, "page_count", count)


def set_page_scores(page_name: str, score) -> None:
	"""Write a `PageScore` (verify.harness) onto a Source Page row.

	`table_score` / `judge_score` are `None` when there's no table / the page wasn't
	judged. Frappe Float columns are NOT NULL (default 0), so those keys are omitted
	rather than written — the row keeps 0.0 and the UI reads 0 as "n/a" (the harness
	`notes` carry a genuine table-miss). Rows are recreated on every parse, so 0.0
	never lingers as a stale value.
	"""
	values = {
		"text_recall": score.text_recall,
		"extra_ratio": score.extra_ratio,
		"composite": score.composite,
		"verdict": score.verdict,
		"notes": "; ".join(score.notes) if score.notes else None,
	}
	if score.table_score is not None:
		values["table_score"] = score.table_score
	if score.judge_score is not None:
		values["judge_score"] = score.judge_score
	frappe.db.set_value("Source Page", page_name, values)


def set_mean_score(source_document: str, mean: float | None) -> None:
	frappe.db.set_value("Source Document", source_document, "mean_score", mean)


# --- Slice 3: remediation + canonical selection ---


def get_pages(source_document: str) -> list[dict]:
	"""Pages of a doc (ordered) with the fields remediation needs to route + re-score."""
	return frappe.get_all(
		"Source Page",
		filters={"source_document": source_document},
		fields=["name", "page_no", "kind", "baseline_markdown", "verdict", "composite"],
		order_by="page_no asc",
	)


def set_remediation(
	page_name: str,
	method: str,
	markdown: str,
	score,
	adopted: bool,
	notes: str | None = None,
) -> None:
	"""Record a page's remediation attempt + its score + whether it was adopted."""
	frappe.db.set_value(
		"Source Page",
		page_name,
		{
			"remediation_method": method,
			"remediation_markdown": markdown,
			"remediation_composite": score.composite,
			"remediation_adopted": 1 if adopted else 0,
			"remediation_notes": notes,
		},
	)


def set_canonical(
	page_name: str, markdown: str, composite: float | None, source: str
) -> None:
	"""Write a page's canonical (best-per-page) markdown + its composite + provenance."""
	values = {"canonical_markdown": markdown, "canonical_source": source}
	if composite is not None:
		values["canonical_composite"] = composite
	frappe.db.set_value("Source Page", page_name, values)


def set_canonical_mean(source_document: str, mean: float | None) -> None:
	frappe.db.set_value("Source Document", source_document, "canonical_mean", mean)


# --- Slice 4: sectionize → Source Section tree ---


def get_canonical_pages(source_document: str) -> list[tuple[int, str]]:
	"""(page_no, markdown) for sectionizing — canonical markdown where remediation
	adopted something, else the baseline. At parse time canonical is unset, so this
	falls back to baseline; after a remediate pass it reflects the adopted output
	(so the rebuilt tree never reverts to empty/pre-cleanup text)."""
	pages = frappe.get_all(
		"Source Page",
		filters={"source_document": source_document},
		fields=["page_no", "canonical_markdown", "baseline_markdown"],
		order_by="page_no asc",
	)
	return [(p["page_no"], p["canonical_markdown"] or p["baseline_markdown"] or "") for p in pages]


# --- Slice 6: classification ---


def get_section_taxonomy() -> list[str]:
	"""Ordered `type_name`s from the Section Type master (the classifier's label set)."""
	return frappe.get_all("Section Type", pluck="type_name", order_by="is_other asc, creation asc")


def get_sections_to_classify(source_document: str) -> list[dict]:
	"""Each section's (name, title, markdown) — the input the classifier needs."""
	return frappe.get_all(
		"Source Section",
		filters={"source_document": source_document},
		fields=["name", "title", "markdown"],
		order_by="lft asc",
	)


def set_section_type(name: str, section_type: str | None) -> None:
	frappe.db.set_value("Source Section", name, "section_type", section_type, update_modified=False)


def replace_sections(source_document: str, sections) -> int:
	"""Rebuild a doc's Source Section tree from ordered `sectionizer.Section`s.

	Replaces the existing tree wholesale (mirrors the POC's `_store_sections`):
	clear, then insert in document order, resolving each section's parent by its
	hierarchy path (the parent always precedes it). NestedSet manages `lft`/`rgt`;
	`is_group` is set for any section another section nests under. Returns the count.
	"""
	# Full rebuild: raw-delete this doc's sections (other docs' subtrees are
	# independent number-spaces, so NestedSet stays consistent without a global rebuild).
	frappe.db.delete("Source Section", {"source_document": source_document})

	parent_paths = {tuple(s.hierarchy_path[:-1]) for s in sections if len(s.hierarchy_path) > 1}
	path_to_name: dict[tuple[str, ...], str] = {}
	for idx, sec in enumerate(sections):
		doc = frappe.new_doc("Source Section")
		doc.source_document = source_document
		doc.parent_source_section = path_to_name.get(tuple(sec.hierarchy_path[:-1]))
		doc.is_group = 1 if tuple(sec.hierarchy_path) in parent_paths else 0
		doc.title = sec.title
		doc.section_type = sec.section_type
		doc.level = sec.level
		doc.hierarchy_path = " > ".join(sec.hierarchy_path)
		doc.page_start = sec.page_start
		doc.page_end = sec.page_end
		doc.sort_order = idx
		doc.markdown = sec.markdown
		doc.insert(ignore_permissions=True)
		path_to_name[tuple(sec.hierarchy_path)] = doc.name
	return len(sections)


# --- Slice 7: wiki generation ---


def get_sections_for_wiki(source_document: str) -> list[dict]:
	"""Every Source Section (ordered by tree position) with the fields wiki generation
	needs. Returns all rows — the caller filters on `include_in_wiki` and resolves
	parents — so excluded/removed sections can also be cleaned up on regeneration."""
	return frappe.get_all(
		"Source Section",
		filters={"source_document": source_document},
		fields=[
			"name",
			"parent_source_section",
			"title",
			"is_group",
			"markdown",
			"page_start",
			"page_end",
			"sort_order",
			"include_in_wiki",
			"wiki_document",
		],
		order_by="lft asc",
	)


def set_section_wiki_document(name: str, wiki_document: str | None) -> None:
	frappe.db.set_value(
		"Source Section", name, "wiki_document", wiki_document, update_modified=False
	)


def set_document_wiki(
	source_document: str, wiki_space: str, wiki_root_group: str, status: str | None = None
) -> None:
	values = {"wiki_space": wiki_space, "wiki_root_group": wiki_root_group}
	if status:
		values["status"] = status
	frappe.db.set_value("Source Document", source_document, values)
