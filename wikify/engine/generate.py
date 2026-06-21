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


def _unique_slug(base: str, taken: set[str]) -> str:
	"""Sibling-unique slug → globally-unique leaf route (paths diverge at the parent)."""
	slug, k = base, 2
	while slug in taken:
		slug, k = f"{base}-{k}", k + 1
	taken.add(slug)
	return slug


class _WikiGenerator:
	"""Projects one approved Source Document tree into a Wiki Space (see module doc)."""

	def __init__(
		self,
		source_document: str,
		*,
		wiki_space: str | None,
		new_space: dict | None,
		progress_cb: Callable[[int, int], None] | None,
		stage_cb: Callable[[str], None] | None,
	):
		self.sd = frappe.get_doc("Source Document", source_document)
		self.space = _resolve_or_create_space(wiki_space, new_space)
		self.progress_cb = progress_cb
		self.stage_cb = stage_cb
		self.sections = store.get_sections_for_wiki(source_document)
		self.by_name = {s["name"]: s for s in self.sections}
		self.included = [s for s in self.sections if s["include_in_wiki"]]
		self.wiki_name: dict[str, str] = {}  # section name → wiki document name
		self.wiki_route: dict[str, str] = {}  # section name → wiki route
		self.content: dict[str, str] = {}  # section name → content written
		self.deleted = 0
		self.links = 0

	def run(self) -> dict:
		self._stage("Preparing wiki space")
		self._ensure_root_group()
		self._sweep_stale()
		self._stage("Building wiki pages")
		self._build_structure()
		self._stage("Resolving page references")
		self._rewrite_links()
		store.set_document_wiki(self.sd.name, self.space.name, self.root_group.name, status="Wiki-Generated")
		return self._summary()

	def _stage(self, label: str) -> None:
		if self.stage_cb:
			self.stage_cb(label)

	def _ensure_root_group(self) -> None:
		# Per-document root group — namespaces routes (<space>/<doc>/…) so a space can hold
		# many imports tidily, and gives the cross-document corpus a stable home.
		doc_slug = slugify(self.sd.title)
		self.root_group = _upsert_wiki_document(
			self.sd.wiki_root_group,
			title=self.sd.title,
			content="",
			is_group=True,
			parent=self.space.root_group,
			route=f"{self.space.route}/{doc_slug}",
			slug=doc_slug,
		)

	def _sweep_stale(self) -> None:
		"""Delete leftover pages BEFORE building (so renamed/recreated routes don't collide).

		Keep the root group + every page an included section still links to; delete the
		rest under the root group deepest-first (NestedSet needs leaves gone first).
		"""
		kept = {self.root_group.name}
		kept |= {s["wiki_document"] for s in self.included if s["wiki_document"]}
		descendants = get_descendants_of("Wiki Document", self.root_group.name, ignore_permissions=True)
		stale = (
			frappe.get_all(
				"Wiki Document",
				filters={"name": ["in", [d for d in descendants if d not in kept]]},
				order_by="lft desc",
				pluck="name",
			)
			if descendants
			else []
		)
		for name in stale:
			frappe.delete_doc("Wiki Document", name, ignore_permissions=True, force=True)
		# Clear wiki_document on sections no longer included (their page was swept).
		for s in self.sections:
			if not s["include_in_wiki"] and s["wiki_document"]:
				store.set_section_wiki_document(s["name"], None)
		self.deleted = len(stale)

	def _parent_for(self, section: dict) -> tuple[str, str]:
		"""(wiki name, route) of the nearest already-built ancestor, else the root group."""
		parent = section["parent_source_section"]
		anc = self.by_name.get(parent) if parent else None
		while anc is not None:
			if anc["name"] in self.wiki_name:
				return self.wiki_name[anc["name"]], self.wiki_route[anc["name"]]
			anc = self.by_name.get(anc["parent_source_section"]) if anc["parent_source_section"] else None
		return self.root_group.name, self.root_group.route

	@staticmethod
	def _content_for(section: dict) -> str:
		md = (section["markdown"] or "").strip()
		if md:
			return md
		return "" if section["is_group"] else f"# {section['title']}\n"

	def _build_structure(self) -> None:
		"""Pass 1: walk included sections (parents precede children by lft) into pages."""
		used_slugs: dict[str, set[str]] = {}  # parent wiki name → slugs taken
		sort_counter: dict[str, int] = {}  # parent wiki name → next sort_order
		total = len(self.included)
		for i, s in enumerate(self.included):
			parent_name, parent_route = self._parent_for(s)
			slug = _unique_slug(slugify(s["title"]), used_slugs.setdefault(parent_name, set()))
			order = sort_counter.get(parent_name, 0)
			sort_counter[parent_name] = order + 1
			content = self._content_for(s)
			doc = _upsert_wiki_document(
				s["wiki_document"],
				title=s["title"],
				content=content,
				is_group=bool(s["is_group"]),
				parent=parent_name,
				route=f"{parent_route}/{slug}",
				slug=slug,
				sort_order=order,
			)
			self.wiki_name[s["name"]] = doc.name
			self.wiki_route[s["name"]] = doc.route
			self.content[s["name"]] = content
			store.set_section_wiki_document(s["name"], doc.name)
			if self.progress_cb:
				self.progress_cb(i + 1, total)

	def _route_for_page(self, n: int) -> str | None:
		"""Smallest-span included section whose PDF page range contains n → its route."""
		best = None
		for s in self.included:
			ps, pe = s["page_start"], s["page_end"]
			if ps and pe and ps <= n <= pe and (best is None or pe - ps < best[1]):
				best = (self.wiki_route[s["name"]], pe - ps)
		return best[0] if best else None

	def _rewrite_links(self) -> None:
		"""Pass 2: every target exists now, so "page N" refs resolve to wiki links."""
		page_count = self.sd.page_count or 10**9
		for s in self.included:
			new_md, links = rewrite_page_refs(
				self.content[s["name"]],
				page_count,
				self._route_for_page,
				current_route=self.wiki_route[s["name"]],
			)
			if links:
				frappe.db.set_value(
					"Wiki Document", self.wiki_name[s["name"]], "content", new_md, update_modified=False
				)
				self.links += links

	def _summary(self) -> dict:
		return {
			"space": self.space.name,
			"space_route": self.space.route,
			"root_group": self.root_group.name,
			"pages": sum(1 for s in self.included if not s["is_group"]),
			"groups": sum(1 for s in self.included if s["is_group"]),
			"deleted": self.deleted,
			"links": self.links,
		}


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
	return _WikiGenerator(
		source_document,
		wiki_space=wiki_space,
		new_space=new_space,
		progress_cb=progress_cb,
		stage_cb=stage_cb,
	).run()


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
