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
