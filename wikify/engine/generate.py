"""Wiki generation (Slice 7) — project an approved Source Section tree into a Frappe
Wiki Space as a 1:1 mirror of `Wiki Document` rows, then rewrite internal page-number
references into wiki links.

Two boundary changes from the POC `loader/wiki.build_wiki`:

  - **Structure-preserving, not the L1 collapse.** The POC had no user-arranged tree, so
    it folded everything under each L1 ancestor into one page. We now have an approved,
    editable Source Section tree, so we mirror it node-for-node — groups → sidebar
    folders, leaves → pages — using the structure the user curated.
  - **Target is `Wiki Document`** (the live NestedSet model), created the way the wiki app
    itself does (`is_group`/`content`/`parent_wiki_document`/`sort_order`). Legacy
    `Wiki Page` is hard-deprecated.

The job is idempotent: each Source Section tracks its `wiki_document`, so regeneration
**updates** existing pages, **creates** newly-included ones, and **deletes** sections
now excluded or removed from the tree — never blind-duplicates. Run order:

  resolve/create space → ensure per-document root group → sweep stale pages →
  pass 1 (structure) → pass 2 (link rewrite) → status Wiki-Generated.
"""

from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe.utils.nestedset import get_descendants_of

from wikify.engine import store
from wikify.engine.loader.wiki import rewrite_page_refs, slugify


def _upsert_wiki_document(
	existing: str | None,
	*,
	title: str,
	content: str,
	is_group: bool,
	parent: str | None,
	route: str,
	slug: str,
	sort_order: int | None = None,
):
	"""Create or update a Wiki Document, returning the saved doc.

	`route`/`slug` are set explicitly (the wiki controller only auto-derives them when
	empty), so renames and reparents recompute deterministically. `is_published=1` keeps
	the page visible in the sidebar."""
	if existing and frappe.db.exists("Wiki Document", existing):
		doc = frappe.get_doc("Wiki Document", existing)
	else:
		doc = frappe.new_doc("Wiki Document")
	doc.title = title
	doc.is_group = 1 if is_group else 0
	doc.is_published = 1
	doc.parent_wiki_document = parent
	doc.content = content
	doc.slug = slug
	doc.route = route
	if sort_order is not None:
		doc.sort_order = sort_order
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	return doc


def _resolve_or_create_space(wiki_space: str | None, new_space: dict | None):
	"""Return a Wiki Space doc — an existing one by name, or a freshly created one
	(its `root_group` auto-creates on insert)."""
	if wiki_space:
		return frappe.get_doc("Wiki Space", wiki_space)
	if not new_space or not (new_space.get("space_name") and new_space.get("route")):
		frappe.throw("Provide an existing wiki_space or a new_space with space_name + route.")
	space = frappe.new_doc("Wiki Space")
	space.space_name = new_space["space_name"]
	space.route = new_space["route"].strip().strip("/")
	space.is_published = 1
	space.insert(ignore_permissions=True)
	return space


def generate_wiki(
	source_document: str,
	*,
	wiki_space: str | None = None,
	new_space: dict | None = None,
	progress_cb: Callable[[int, int], None] | None = None,
	stage_cb: Callable[[str], None] | None = None,
) -> dict:
	"""Generate (or regenerate) a Source Document's wiki under the chosen space.

	Returns `{space, space_route, root_group, pages, groups, deleted, links}`.
	"""
	sd = frappe.get_doc("Source Document", source_document)
	space = _resolve_or_create_space(wiki_space, new_space)
	space_route = space.route

	# Per-document root group — namespaces routes (<space>/<doc>/…) so a space can hold
	# many imports tidily, and gives the cross-document corpus a stable home.
	if stage_cb:
		stage_cb("Preparing wiki space")
	doc_slug = slugify(sd.title)
	root_group = _upsert_wiki_document(
		sd.wiki_root_group,
		title=sd.title,
		content="",
		is_group=True,
		parent=space.root_group,
		route=f"{space_route}/{doc_slug}",
		slug=doc_slug,
	)

	sections = store.get_sections_for_wiki(source_document)
	by_name = {s["name"]: s for s in sections}
	included = [s for s in sections if s["include_in_wiki"]]

	# --- Sweep stale pages BEFORE building (so renamed/recreated routes don't collide
	# with leftovers). Keep the root group + every page an included section still links to;
	# delete everything else under the root group, deepest-first (NestedSet needs leaves
	# gone before their parents).
	kept = {root_group.name}
	kept |= {s["wiki_document"] for s in included if s["wiki_document"]}
	descendants = get_descendants_of("Wiki Document", root_group.name, ignore_permissions=True)
	stale = frappe.get_all(
		"Wiki Document",
		filters={"name": ["in", [d for d in descendants if d not in kept]]},
		order_by="lft desc",
		pluck="name",
	) if descendants else []
	for name in stale:
		frappe.delete_doc("Wiki Document", name, ignore_permissions=True, force=True)
	# Clear wiki_document on sections that are no longer included (their page was swept).
	for s in sections:
		if not s["include_in_wiki"] and s["wiki_document"]:
			store.set_section_wiki_document(s["name"], None)

	# --- Pass 1: structure — walk included sections (parents precede children by lft).
	if stage_cb:
		stage_cb("Building wiki pages")
	wiki_name: dict[str, str] = {}  # section name → wiki document name
	wiki_route: dict[str, str] = {}  # section name → wiki route
	content_map: dict[str, str] = {}  # section name → content written
	used_slugs: dict[str, set[str]] = {}  # parent wiki name → slugs taken (sibling-unique)
	sort_counter: dict[str, int] = {}  # parent wiki name → next sort_order

	total = len(included)
	for i, s in enumerate(included):
		# Wiki parent = nearest included ancestor's page, else the per-document root group.
		parent_name = root_group.name
		parent_route = root_group.route
		anc = by_name.get(s["parent_source_section"]) if s["parent_source_section"] else None
		while anc is not None:
			if anc["name"] in wiki_name:
				parent_name = wiki_name[anc["name"]]
				parent_route = wiki_route[anc["name"]]
				break
			anc = by_name.get(anc["parent_source_section"]) if anc["parent_source_section"] else None

		# Sibling-unique slug → globally-unique leaf route (paths diverge at the parent).
		base = slugify(s["title"])
		taken = used_slugs.setdefault(parent_name, set())
		slug, k = base, 2
		while slug in taken:
			slug, k = f"{base}-{k}", k + 1
		taken.add(slug)
		route = f"{parent_route}/{slug}"

		is_group = bool(s["is_group"])
		md = (s["markdown"] or "").strip()
		content = md if md else ("" if is_group else f"# {s['title']}\n")
		order = sort_counter.get(parent_name, 0)
		sort_counter[parent_name] = order + 1

		doc = _upsert_wiki_document(
			s["wiki_document"],
			title=s["title"],
			content=content,
			is_group=is_group,
			parent=parent_name,
			route=route,
			slug=slug,
			sort_order=order,
		)
		wiki_name[s["name"]] = doc.name
		wiki_route[s["name"]] = doc.route
		content_map[s["name"]] = content
		store.set_section_wiki_document(s["name"], doc.name)
		if progress_cb:
			progress_cb(i + 1, total)

	# --- Pass 2: link rewrite — every target exists now, so "page N" refs resolve.
	if stage_cb:
		stage_cb("Resolving page references")
	page_count = sd.page_count or 10**9
	spans = [
		(s["page_start"], s["page_end"], wiki_route[s["name"]])
		for s in included
		if s["page_start"] and s["page_end"]
	]

	def route_for_page(n: int) -> str | None:
		"""Smallest-span included section whose PDF page range contains n → its route."""
		best = None
		for ps, pe, route in spans:
			if ps <= n <= pe:
				span = pe - ps
				if best is None or span < best[1]:
					best = (route, span)
		return best[0] if best else None

	total_links = 0
	for s in included:
		new_md, links = rewrite_page_refs(
			content_map[s["name"]], page_count, route_for_page, current_route=wiki_route[s["name"]]
		)
		if links:
			frappe.db.set_value(
				"Wiki Document", wiki_name[s["name"]], "content", new_md, update_modified=False
			)
			total_links += links

	store.set_document_wiki(
		source_document, space.name, root_group.name, status="Wiki-Generated"
	)
	return {
		"space": space.name,
		"space_route": space_route,
		"root_group": root_group.name,
		"pages": sum(1 for s in included if not s["is_group"]),
		"groups": sum(1 for s in included if s["is_group"]),
		"deleted": len(stale),
		"links": total_links,
	}


def preview_wiki(source_document: str) -> dict:
	"""Projected wiki structure without writes — the included Source Section tree as a
	nested list, plus counts. Drives the Wiki tab's pre-generation preview."""
	sections = store.get_sections_for_wiki(source_document)
	included = [s for s in sections if s["include_in_wiki"]]
	by_name = {s["name"]: {**s, "children": []} for s in included}
	roots: list[dict] = []
	for s in included:
		node = by_name[s["name"]]
		parent = s["parent_source_section"]
		# Attach to nearest included ancestor; else it's a root.
		anc = by_name.get(parent)
		if anc is None and parent:
			cur = next((x for x in sections if x["name"] == parent), None)
			while cur is not None and cur["name"] not in by_name:
				cur = next((x for x in sections if x["name"] == cur["parent_source_section"]), None)
			anc = by_name.get(cur["name"]) if cur else None
		(anc["children"] if anc else roots).append(node)
	return {
		"tree": roots,
		"pages": sum(1 for s in included if not s["is_group"]),
		"groups": sum(1 for s in included if s["is_group"]),
		"excluded": sum(1 for s in sections if not s["include_in_wiki"]),
	}
