"""Read / context tools — reuse the existing whitelisted `api/` read seams.

Slice 12 ships only `read_tree` (the walking skeleton's one tool); slice 13 adds
`read_section`, `read_page`, `list_section_types`, `search_sections`.
"""

from __future__ import annotations

from frappe import _

from wikify.agent.context import Ctx
from wikify.agent.registry import Tool


def _read_tree(ctx: Ctx, args: dict) -> str:
	"""Return the Source Section tree as compact, indented YAML-ish text."""
	from wikify.api.sections import get_tree

	source_document = ctx.default_document(args.get("source_document"))
	if not source_document:
		return _(
			"No document specified. Ask the user which Source Document to read, or have "
			"them open one (its tree will be attached automatically)."
		)

	roots = get_tree(source_document)
	if not roots:
		return _("Document {0} has no sections yet.").format(source_document)

	lines: list[str] = [f"Section tree of {source_document}:"]

	def walk(node: dict, depth: int) -> None:
		indent = "  " * depth
		pages = ""
		start, end = node.get("page_start"), node.get("page_end")
		if start:
			pages = f" [p.{start}]" if not end or end == start else f" [p.{start}-{end}]"
		stype = f" ({node['section_type']})" if node.get("section_type") else ""
		lines.append(f"{indent}- {node.get('title') or '(untitled)'}{stype}{pages}")
		for child in node.get("children", []):
			walk(child, depth + 1)

	for root in roots:
		walk(root, 1)
	return "\n".join(lines)


TOOLS = [
	Tool(
		name="read_tree",
		side="server",
		description=(
			"Read the Source Section tree (titles, section types, page ranges, hierarchy) "
			"of a document. Defaults to the document the user is currently looking at."
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
]
