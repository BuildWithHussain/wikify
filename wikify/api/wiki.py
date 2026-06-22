"""Whitelisted API for the in-app wiki preview (Slice 15).

`render_section_preview` renders a single `Source Section` to **the same HTML the wiki
would produce**, so the preview matches the eventual generated `Wiki Document` page.

**Renderer decision (Slice 15):** the wiki app renders `Wiki Document.content`
server-side via `wiki.wiki.markdown.render_markdown` (markdown-it-py + callout/video/pdf
plugins; a ```mermaid fence becomes `<pre class="mermaid">`, hydrated client-side). We
reuse that exact function here — true fidelity — rather than the browser-side `marked`
in `MarkdownPreview.vue`. The frontend runs the same wiki mermaid loader over the result
(see `utils/mermaid.renderMermaidIn`, extended to also handle `<pre class="mermaid">`).

Page references ("refer Page No. 130") are resolved in **dry** mode with the same pass-2
logic wiki generation uses (`engine.loader.wiki.rewrite_page_refs`): the smallest-span
included section whose PDF page range contains N is the target. Since nothing is
generated yet, links point at a preview sentinel route (`/section-preview/<name>`) that
the frontend intercepts to navigate the tree, and we report how many refs resolved.
"""

from __future__ import annotations

import frappe
from frappe import _
from wiki.wiki.markdown import render_markdown

from wikify.engine.loader.wiki import rewrite_page_refs

_PREVIEW_ROUTE_PREFIX = "section-preview"


def _content_for(markdown: str, *, is_group: bool, title: str) -> str:
	"""The content wiki generation would write for this section (mirror of
	`engine.generate._WikiGenerator._content_for`), so preview ≈ result."""
	md = (markdown or "").strip()
	if md:
		return md
	return "" if is_group else f"# {title}\n"


@frappe.whitelist()
def render_section_preview(section: str) -> dict:
	"""Render one `Source Section` as a wiki-fidelity page.

	Returns `{title, breadcrumb, html, markdown, include_in_wiki, page_refs_resolved}`:
	  - `breadcrumb` — Project > Document > ancestors > Title (from `hierarchy_path`).
	  - `html` — the wiki renderer's output over the section's content, with internal
	    page refs rewritten to preview links.
	  - `markdown` — the raw source (drives the Rendered ⇄ Source toggle).
	  - `page_refs_resolved` — count of "page N" refs that resolved to a target section.
	"""
	sec = frappe.get_doc("Source Section", section)
	sd = frappe.get_doc("Source Document", sec.source_document)

	content = _content_for(sec.markdown, is_group=bool(sec.is_group), title=sec.title)

	# Dry pass-2: resolve "page N" → the smallest-span included section covering N.
	included = frappe.get_all(
		"Source Section",
		filters={"source_document": sec.source_document, "include_in_wiki": 1},
		fields=["name", "title", "page_start", "page_end"],
	)

	def route_for_page(n: int) -> str | None:
		best = None
		for s in included:
			ps, pe = s["page_start"], s["page_end"]
			if ps and pe and ps <= n <= pe and (best is None or pe - ps < best[1]):
				best = (f"{_PREVIEW_ROUTE_PREFIX}/{s['name']}", pe - ps)
		return best[0] if best else None

	current_route = f"{_PREVIEW_ROUTE_PREFIX}/{sec.name}"
	rewritten, resolved = rewrite_page_refs(
		content,
		sd.page_count or 10**9,
		route_for_page,
		current_route=current_route,
	)

	html = render_markdown(rewritten)

	# Breadcrumb: Project > Document > <hierarchy_path ancestors + self>.
	project_name = (
		frappe.db.get_value("Wikify Project", sd.project, "project_name") if sd.project else None
	)
	crumbs = [project_name or _("Project"), sd.title]
	if sec.hierarchy_path:
		crumbs.extend(p for p in sec.hierarchy_path.split(" > ") if p)
	else:
		crumbs.append(sec.title)

	return {
		"title": sec.title,
		"breadcrumb": crumbs,
		"html": html,
		"markdown": content,
		"include_in_wiki": bool(sec.include_in_wiki),
		"page_refs_resolved": resolved,
	}
