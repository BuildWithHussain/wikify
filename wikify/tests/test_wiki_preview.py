# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

"""Slice 15 — wiki rendered preview.

Drives `api.wiki.render_section_preview` over a small known tree, asserting it renders
with the wiki app's renderer (markdown-it → `<pre class="mermaid">`, real tables), builds
the Project > Document > ... breadcrumb, dry-resolves internal page refs to preview links,
and flags excluded sections.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from wikify.api import wiki as api
from wikify.engine import store
from wikify.engine.loader.sectionizer import Section
from wikify.seed import seed_uncategorized_project


def _sec(title, level, path, p_start, p_end, markdown):
	return Section(
		title=title,
		level=level,
		hierarchy_path=path,
		page_start=p_start,
		page_end=p_end,
		markdown=markdown,
	)


class TestWikiPreview(FrappeTestCase):
	def setUp(self):
		self.project = seed_uncategorized_project()
		self.sd = frappe.get_doc(
			{
				"doctype": "Source Document",
				"title": "Preview Manual",
				"project": self.project,
				"page_count": 10,
			}
		).insert(ignore_permissions=True)
		store.replace_sections(
			self.sd.name,
			[
				_sec(
					"1. Intro",
					1,
					["1. Intro"],
					1,
					2,
					"Welcome. For details see Page No. 5 of the manual.",
				),
				_sec(
					"2. Diagrams",
					1,
					["2. Diagrams"],
					5,
					6,
					"## Flow\n\n```mermaid\ngraph TD; A-->B;\n```\n\n| Col | Val |\n| --- | --- |\n| a | 1 |",
				),
				_sec("3. Appendix", 1, ["3. Appendix"], 7, 8, "Extra notes."),
			],
		)
		self.by_title = {
			r.title: r.name
			for r in frappe.get_all(
				"Source Section",
				filters={"source_document": self.sd.name},
				fields=["name", "title"],
			)
		}

	def test_breadcrumb_and_title(self):
		out = api.render_section_preview(self.by_title["1. Intro"])
		self.assertEqual(out["title"], "1. Intro")
		# Project > Document > hierarchy_path (root section == its own title here).
		self.assertEqual(out["breadcrumb"], ["Uncategorized", "Preview Manual", "1. Intro"])

	def test_renders_with_wiki_renderer(self):
		out = api.render_section_preview(self.by_title["2. Diagrams"])
		# markdown-it emits a bare <pre class="mermaid"> (not <code class="language-...">).
		self.assertIn('<pre class="mermaid">', out["html"])
		# Real GFM table, not a dropped paragraph.
		self.assertIn("<table>", out["html"])
		self.assertIn("<h2", out["html"])

	def test_page_ref_resolves_to_preview_link(self):
		out = api.render_section_preview(self.by_title["1. Intro"])
		# "Page No. 5" → the section covering page 5 (2. Diagrams).
		self.assertEqual(out["page_refs_resolved"], 1)
		target = self.by_title["2. Diagrams"]
		self.assertIn(f"section-preview/{target}", out["html"])

	def test_excluded_section_flagged(self):
		name = self.by_title["3. Appendix"]
		frappe.db.set_value("Source Section", name, "include_in_wiki", 0)
		out = api.render_section_preview(name)
		self.assertFalse(out["include_in_wiki"])

	def test_markdown_passthrough_for_source_toggle(self):
		out = api.render_section_preview(self.by_title["3. Appendix"])
		self.assertIn("Extra notes.", out["markdown"])
		self.assertEqual(out["page_refs_resolved"], 0)
