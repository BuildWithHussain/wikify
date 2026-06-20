"""Whitelisted APIs for the Source Section tree.

Slice 4 added the read seam (`get_tree`); Slice 5 adds the HITL tree-review
mutations (reparent / reorder / rename / include-toggle / delete) and the
`build_graph` approval gate. The tree is a Frappe NestedSet, so `lft`/`rgt` plus
the denormalized `level` / `hierarchy_path` / `is_group` fields must be kept
consistent after every structural change — `_rebuild_tree` does that in one DFS.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Coalesce


@frappe.whitelist()
def get_tree(source_document: str) -> list[dict]:
	"""Nested section tree for a Source Document, ordered by tree position (`lft`).

	Returns the root sections, each with a recursive `children` list — the shape the
	frappe-ui `Tree` consumes.
	"""
	rows = frappe.get_all(
		"Source Section",
		filters={"source_document": source_document},
		fields=[
			"name",
			"parent_source_section",
			"title",
			"is_group",
			"level",
			"section_type",
			"hierarchy_path",
			"page_start",
			"page_end",
			"sort_order",
			"markdown",
		],
		order_by="lft asc",
	)

	by_name = {r["name"]: {**r, "children": []} for r in rows}
	roots: list[dict] = []
	for r in rows:
		node = by_name[r["name"]]
		parent = r["parent_source_section"]
		if parent and parent in by_name:
			by_name[parent]["children"].append(node)
		else:
			roots.append(node)
	return roots


# --- Slice 5: tree-review mutations ---------------------------------------------------


def _rebuild_tree(source_document: str) -> None:
	"""Re-walk a doc's section tree, re-deriving every position field in one DFS.

	Mirrors the wiki app's NestedSet rebuild (siblings ordered by `sort_order`, then
	`name`), but also re-derives the Wikify-specific denorm fields so a reparent or
	rename can't leave them stale:
	  - `lft`/`rgt` — tree numbering (depth-first interval),
	  - `level`     — 1-based depth (roots are level 1, matching the sectionizer),
	  - `hierarchy_path` — " > "-joined titles from root to the node,
	  - `is_group`  — set iff the node actually has children now.
	Each Source Document is an independent NestedSet number-space, so only this doc's
	tree is rebuilt (no global rebuild).
	"""
	table = frappe.qb.DocType("Source Section")

	def children_of(parent: str | None) -> list[str]:
		q = frappe.qb.from_(table).where(table.source_document == source_document)
		if parent is None:
			q = q.where((table.parent_source_section == "") | table.parent_source_section.isnull())
		else:
			q = q.where(table.parent_source_section == parent)
		return (
			q.orderby(Coalesce(table.sort_order, 0), order=Order.asc)
			.orderby(table.name, order=Order.asc)
			.select(table.name)
		).run(pluck="name")

	def walk(name: str, left: int, level: int, ancestry: list[str]) -> int:
		title = frappe.db.get_value("Source Section", name, "title") or ""
		path = [*ancestry, title]
		kids = children_of(name)
		right = left + 1
		for kid in kids:
			right = walk(kid, right, level + 1, path)
		frappe.db.set_value(
			"Source Section",
			name,
			{
				"lft": left,
				"rgt": right,
				"level": level,
				"hierarchy_path": " > ".join(path),
				"is_group": 1 if kids else 0,
			},
			update_modified=False,
		)
		return right + 1

	right = 1
	for root in children_of(None):
		right = walk(root, right, 1, [])


def _subtree_names(name: str) -> tuple[str, list[str]]:
	"""(source_document, [names in the subtree rooted at `name`]) via lft/rgt range."""
	sec = frappe.db.get_value(
		"Source Section", name, ["source_document", "lft", "rgt"], as_dict=True
	)
	if not sec:
		frappe.throw(_("Section {0} not found.").format(name))
	names = frappe.get_all(
		"Source Section",
		filters={
			"source_document": sec.source_document,
			"lft": [">=", sec.lft],
			"rgt": ["<=", sec.rgt],
		},
		pluck="name",
	)
	return sec.source_document, names


@frappe.whitelist()
def reorder_section(
	name: str, new_parent: str | None = None, new_index: int = 0, siblings: str | list | None = None
) -> dict:
	"""Move a section under `new_parent` and re-order it among `siblings`.

	`siblings` is the full ordered list of names at the destination (the client sends
	the post-drop order); their `sort_order` is rewritten to match, then the whole
	doc tree is rebuilt so `lft`/`level`/`hierarchy_path`/`is_group` stay consistent.
	`new_index` is accepted for parity with the client call but ordering is driven by
	`siblings`.
	"""
	new_parent = new_parent or None
	sec = frappe.db.get_value(
		"Source Section", name, ["source_document", "lft", "rgt"], as_dict=True
	)
	if not sec:
		frappe.throw(_("Section {0} not found.").format(name))

	# Guard against cycles: the new parent must not be the node itself or a descendant.
	if new_parent:
		parent = frappe.db.get_value(
			"Source Section", new_parent, ["source_document", "lft"], as_dict=True
		)
		if not parent or parent.source_document != sec.source_document:
			frappe.throw(_("New parent must belong to the same document."))
		if sec.lft <= parent.lft <= sec.rgt:
			frappe.throw(_("Can't move a section into its own subtree."))

	frappe.db.set_value("Source Section", name, "parent_source_section", new_parent)

	if isinstance(siblings, str):
		siblings = json.loads(siblings)
	for idx, sib in enumerate(siblings or []):
		frappe.db.set_value("Source Section", sib, "sort_order", idx, update_modified=False)

	_rebuild_tree(sec.source_document)
	return {"ok": True}


@frappe.whitelist()
def rename_section(name: str, title: str) -> dict:
	"""Rename a section. Recomputes `hierarchy_path` for it and its descendants."""
	title = (title or "").strip()
	if not title:
		frappe.throw(_("Title can't be empty."))
	source_document = frappe.db.get_value("Source Section", name, "source_document")
	frappe.db.set_value("Source Section", name, "title", title)
	_rebuild_tree(source_document)
	return {"ok": True}


@frappe.whitelist()
def toggle_include(name: str, include: bool | int | str) -> dict:
	"""Set `include_in_wiki` on a section and its whole subtree (cascade)."""
	include = 1 if frappe.parse_json(include) else 0
	_, names = _subtree_names(name)
	frappe.db.set_value(
		"Source Section", {"name": ["in", names]}, "include_in_wiki", include, update_modified=False
	)
	return {"ok": True, "count": len(names)}


@frappe.whitelist()
def delete_section(name: str) -> dict:
	"""Delete a section and its entire subtree, then rebuild the doc tree."""
	source_document, names = _subtree_names(name)
	# Raw-delete the subtree (the same wholesale approach store.replace_sections uses);
	# _rebuild_tree re-numbers what remains, so NestedSet stays consistent.
	frappe.db.delete("Source Section", {"name": ["in", names]})
	_rebuild_tree(source_document)
	return {"ok": True, "deleted": len(names)}


@frappe.whitelist()
def build_graph(import_name: str) -> dict:
	"""Approve the reviewed tree — advance the import + document to `Graphed`.

	The structure stays editable afterward (re-running this re-approves), so this is a
	milestone, not a freeze. It unlocks the downstream Explore (Slice 6) and Wiki
	(Slice 7) steps.
	"""
	imp = frappe.get_doc("Wikify Import", import_name)
	if not imp.source_document:
		frappe.throw(_("Nothing to graph — parse hasn't produced a document yet."))
	imp.db_set("status", "Graphed")
	frappe.db.set_value("Source Document", imp.source_document, "status", "Graphed")
	return {"status": "Graphed"}
