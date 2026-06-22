"""Read / context tools — reuse the existing whitelisted `api/` read seams.

Slice 12 shipped `read_tree`; slice 13 adds `read_section`, `read_page`,
`list_section_types`, and `search_sections`. Handlers default `source_document` to the
attached document (`ctx.default_document`) so the user rarely names ids.
"""

from __future__ import annotations

import frappe
from frappe import _

from wikify.agent.context import Ctx
from wikify.agent.registry import Tool

# Keep tool results bounded — the model can ask for a narrower slice if it needs more.
_BODY_LIMIT = 6000


def _truncate(text: str) -> str:
	text = text or ""
	return text if len(text) <= _BODY_LIMIT else text[:_BODY_LIMIT] + "\n… (truncated)"


def render_tree(source_document: str) -> str:
	"""The Source Section tree as compact, indented text (shared with context.py)."""
	from wikify.api.sections import get_tree

	roots = get_tree(source_document)
	if not roots:
		return _("Document {0} has no sections yet.").format(source_document)

	lines: list[str] = []

	def walk(node: dict, depth: int) -> None:
		indent = "  " * depth
		pages = ""
		start, end = node.get("page_start"), node.get("page_end")
		if start:
			pages = f" [p.{start}]" if not end or end == start else f" [p.{start}-{end}]"
		stype = f" ({node['section_type']})" if node.get("section_type") else ""
		lines.append(f"{indent}- {node.get('title') or '(untitled)'}{stype}{pages} <{node['name']}>")
		for child in node.get("children", []):
			walk(child, depth + 1)

	for root in roots:
		walk(root, 1)
	return "\n".join(lines)


def _read_tree(ctx: Ctx, args: dict) -> str:
	"""Return the Source Section tree as compact, indented text."""
	source_document = ctx.default_document(args.get("source_document"))
	if not source_document:
		return _(
			"No document specified. Ask the user which Source Document to read, or have "
			"them open one (its tree will be attached automatically)."
		)
	return f"Section tree of {source_document}:\n{render_tree(source_document)}"


def _read_section(ctx: Ctx, args: dict) -> str:
	"""A section's markdown + metadata."""
	name = args.get("name")
	if not name:
		return _("Provide the section `name` (the id shown in <angle brackets> in the tree).")
	row = frappe.db.get_value(
		"Source Section",
		name,
		["title", "section_type", "hierarchy_path", "page_start", "page_end", "include_in_wiki", "markdown"],
		as_dict=True,
	)
	if not row:
		return _("Section {0} not found.").format(name)
	pages = (
		f"{row.page_start}-{row.page_end}"
		if row.page_end and row.page_end != row.page_start
		else row.page_start
	)
	meta = [
		f"Title: {row.title}",
		f"Type: {row.section_type or '(untagged)'}",
		f"Path: {row.hierarchy_path or row.title}",
		f"Pages: {pages or '—'}",
		f"Included in wiki: {'yes' if row.include_in_wiki else 'no'}",
	]
	return "\n".join(meta) + "\n\n" + _truncate(row.markdown or "(no body)")


def _read_page(ctx: Ctx, args: dict) -> str:
	"""A page's canonical markdown + verdict + scores."""
	source_document = ctx.default_document(args.get("source_document"))
	page_no = args.get("page_no")
	if not source_document:
		return _("No document specified. Open a document or pass `source_document`.")
	if page_no is None:
		return _("Provide the `page_no` to read.")
	row = frappe.db.get_value(
		"Source Page",
		{"source_document": source_document, "page_no": int(page_no)},
		["kind", "verdict", "composite", "canonical_source", "canonical_markdown", "baseline_markdown"],
		as_dict=True,
	)
	if not row:
		return _("Page {0} of {1} not found.").format(page_no, source_document)
	body = row.canonical_markdown or row.baseline_markdown or "(no markdown yet)"
	meta = [
		f"Page {page_no} of {source_document}",
		f"Kind: {row.kind or '—'}",
		f"Verdict: {row.verdict or '—'}  Composite: {row.composite if row.composite is not None else '—'}",
		f"Canonical source: {row.canonical_source or 'baseline'}",
	]
	return "\n".join(meta) + "\n\n" + _truncate(body)


def _list_section_types(ctx: Ctx, args: dict) -> str:
	"""The taxonomy (Section Types: name, label, description, color)."""
	types = frappe.get_all(
		"Section Type",
		fields=["type_name", "label", "description", "color", "is_other"],
		order_by="is_other asc, creation asc",
	)
	if not types:
		return _("No Section Types defined yet.")
	lines = ["Section Types (taxonomy):"]
	for t in types:
		desc = f" — {t.description}" if t.description else ""
		lines.append(f"- {t.type_name} ({t.label or t.type_name}){desc}")
	return "\n".join(lines)


def _search_sections(ctx: Ctx, args: dict) -> str:
	"""Explore-style cross-document lookup, reusing `api.explore.sections_by_type`.

	With `section_type`, returns the matching sections grouped by document (optionally
	scoped to `project` / the attached `source_document`, and filtered by a `query`
	substring on title/path). Without a type, lists the taxonomy counts so the model can
	pick a type to drill into.
	"""
	from wikify.api.explore import sections_by_type, type_summary

	section_type = args.get("section_type")
	project = args.get("project") or ctx.project
	source_document = ctx.default_document(args.get("source_document"))
	query = (args.get("query") or "").strip().lower()

	if not section_type:
		summary = type_summary(source_document=source_document, project=project)
		lines = ["Available section types (pass `section_type` to drill in):"]
		lines += [f"- {s['type_name']}: {s['count']}" for s in summary if s["count"]]
		return "\n".join(lines) if len(lines) > 1 else _("No tagged sections in this scope yet.")

	groups = sections_by_type(section_type, source_document=source_document, project=project)
	lines: list[str] = []
	total = 0
	for g in groups:
		secs = g["sections"]
		if query:
			secs = [
				s
				for s in secs
				if query in (s.get("title") or "").lower() or query in (s.get("hierarchy_path") or "").lower()
			]
		if not secs:
			continue
		lines.append(f"# {g['doc_title']} ({g['source_document']})")
		for s in secs:
			pages = f" [p.{s['page_start']}-{s['page_end']}]" if s.get("page_start") else ""
			lines.append(f"  - {s['hierarchy_path'] or s['title']}{pages} <{s['name']}>")
			total += 1
	if not lines:
		return _("No sections of type {0} match.").format(section_type)
	return f"{total} section(s) of type {section_type}:\n" + "\n".join(lines)


TOOLS = [
	Tool(
		name="read_tree",
		side="server",
		description=(
			"Read the Source Section tree (titles, section types, page ranges, hierarchy, "
			"and each section's id) of a document. Defaults to the document the user is "
			"currently looking at."
		),
		parameters={
			"type": "object",
			"properties": {
				"source_document": {
					"type": "string",
					"description": "Source Document name. Omit to use the attached document.",
				}
			},
		},
		handler=_read_tree,
	),
	Tool(
		name="read_section",
		side="server",
		description="Read one section's markdown body and metadata. Pass the section id (shown in <angle brackets> in the tree).",
		parameters={
			"type": "object",
			"properties": {
				"name": {"type": "string", "description": "Source Section id."},
			},
			"required": ["name"],
		},
		handler=_read_section,
	),
	Tool(
		name="read_page",
		side="server",
		description="Read a page's canonical markdown, verdict, and scores. Defaults to the attached document.",
		parameters={
			"type": "object",
			"properties": {
				"source_document": {
					"type": "string",
					"description": "Source Document name. Omit to use the attached document.",
				},
				"page_no": {"type": "integer", "description": "1-based page number."},
			},
			"required": ["page_no"],
		},
		handler=_read_page,
	),
	Tool(
		name="list_section_types",
		side="server",
		description="List the Section Type taxonomy (the available tags) with labels and descriptions.",
		parameters={"type": "object", "properties": {}},
		handler=_list_section_types,
	),
	Tool(
		name="search_sections",
		side="server",
		description=(
			"Find sections across documents by Section Type (Explore-style). Optionally scope "
			"to a project or the attached document, and filter by a title/path substring. "
			"Omit section_type to list the available types with counts."
		),
		parameters={
			"type": "object",
			"properties": {
				"section_type": {"type": "string", "description": "Section Type to filter by."},
				"query": {"type": "string", "description": "Optional substring filter on title/path."},
				"project": {"type": "string", "description": "Optional Wikify Project to scope to."},
				"source_document": {"type": "string", "description": "Optional single-document scope."},
			},
		},
		handler=_search_sections,
	),
]
