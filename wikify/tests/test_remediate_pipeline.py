# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from wikify.engine import parse_pdf, remediate_pdf
from wikify.tests.test_parse_pipeline import _make_sample_pdf

# Sentinel: a remediation output the fake judge rates 5/5 (vs 2/5 for anything else),
# so we can deterministically drive the "vlm improves → adopt" branch.
_MERMAID = "```mermaid\nflowchart TD\n  A[\"Start\"] --> B[\"End\"]\n```\nMERMAID_OK"


def _fake_chat(model, messages, label="", **kw):
	"""Offline stand-in for OpenRouter. Only the judge is exercised here (cleanup /
	vlm are patched at the engine seam); it scores 5 when the markdown carries the
	sentinel, else 2 — making adoption decisions deterministic."""
	overall = 2
	if label == "judge":
		md = messages[0]["content"][-1].get("text", "")
		overall = 5 if "MERMAID_OK" in md else 2
	content = json.dumps(
		{"overall": overall, "completeness": overall, "structure": overall, "no_hallucination": 5, "note": "t"}
	)
	return {"choices": [{"message": {"content": content}}], "usage": {}}


class TestRemediatePipeline(FrappeTestCase):
	def _parse(self):
		path = Path(tempfile.mkdtemp()) / "sample.pdf"
		_make_sample_pdf(str(path))
		# has_openrouter True (so the visual page is judged at parse → flagged) + a
		# fake judge; text pages are not judged (judge_all off) so stay deterministic.
		with (
			patch("wikify.engine.llm.has_openrouter", return_value=True),
			patch("wikify.engine.llm.chat_completion", side_effect=_fake_chat),
		):
			sd = parse_pdf(str(path), title="Remediate Test")
		return sd, str(path)

	def test_remediate_all_routes_adopts_and_writes_canonical(self):
		sd, path = self._parse()
		mean_before = frappe.db.get_value("Source Document", sd, "mean_score")
		# Visual page (3) is judged 2/5 at parse → flagged for review.
		self.assertEqual(frappe.db.get_value("Source Page", {"source_document": sd, "page_no": 3}, "verdict"), "review")

		with (
			patch("wikify.engine.llm.has_openrouter", return_value=True),
			patch("wikify.engine.llm.chat_completion", side_effect=_fake_chat),
			# Text cleanup is content-preserving (identity) → recall held → adopted.
			patch("wikify.engine.remediate.clean_markdown", side_effect=lambda md, model=None: md),
			# VLM re-parse yields a mermaid-bearing transcription the judge rates 5/5.
			patch("wikify.engine.remediate.vlm.parse_page_image", return_value=_MERMAID),
		):
			result = remediate_pdf(sd, path, scope="all")

		pages = {
			p.page_no: p
			for p in frappe.get_all(
				"Source Page",
				filters={"source_document": sd},
				fields=[
					"page_no", "kind", "remediation_method", "remediation_adopted",
					"canonical_source", "canonical_markdown", "canonical_composite",
				],
				order_by="page_no asc",
			)
		}

		# Every page got a canonical markdown + provenance, even non-adopted ones.
		for p in pages.values():
			self.assertIsNotNone(p.canonical_markdown)
			self.assertIn(p.canonical_source, ("baseline", "cleanup", "vlm"))

		# Text page → routed to cleanup, content preserved → adopted as canonical.
		text_page = pages[1]
		self.assertEqual(text_page.kind, "text")
		self.assertEqual(text_page.remediation_method, "cleanup")
		self.assertTrue(text_page.remediation_adopted)
		self.assertEqual(text_page.canonical_source, "cleanup")

		# Visual page → routed to vlm; mermaid output beats the baseline → adopted,
		# and the mermaid survives into the canonical markdown.
		visual_page = pages[3]
		self.assertEqual(visual_page.kind, "visual")
		self.assertEqual(visual_page.remediation_method, "vlm")
		self.assertTrue(visual_page.remediation_adopted)
		self.assertEqual(visual_page.canonical_source, "vlm")
		self.assertIn("mermaid", visual_page.canonical_markdown)

		# Adopting the improved visual page lifts the canonical mean above baseline.
		canonical_mean = frappe.db.get_value("Source Document", sd, "canonical_mean")
		self.assertEqual(canonical_mean, result["canonical_mean"])
		self.assertGreater(canonical_mean, mean_before)
		self.assertGreaterEqual(result["adopted"], 1)

	def test_remediate_flagged_scope_skips_passing_pages(self):
		sd, path = self._parse()
		with (
			patch("wikify.engine.llm.has_openrouter", return_value=True),
			patch("wikify.engine.llm.chat_completion", side_effect=_fake_chat),
			patch("wikify.engine.remediate.clean_markdown", side_effect=lambda md, model=None: md),
			patch("wikify.engine.remediate.vlm.parse_page_image", return_value=_MERMAID),
		):
			remediate_pdf(sd, path, scope="flagged")

		pages = {
			p.page_no: p
			for p in frappe.get_all(
				"Source Page",
				filters={"source_document": sd},
				fields=["page_no", "verdict", "remediation_method", "canonical_source"],
				order_by="page_no asc",
			)
		}
		# Passing text pages are untouched (no remediation attempt) but still get a
		# canonical = baseline; only the flagged visual page is remediated.
		self.assertFalse(pages[1].remediation_method)  # unset Select → "" (no attempt)
		self.assertEqual(pages[1].canonical_source, "baseline")
		self.assertEqual(pages[3].remediation_method, "vlm")
		self.assertEqual(pages[3].canonical_source, "vlm")
