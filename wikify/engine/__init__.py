"""Wikify pipeline package — ported from the POC (`scratch/pdf_lab/`).

No Flask, no SQLite: persistence goes through `store.py` (the Frappe ORM seam).
The POC logic is preserved; only the I/O boundaries change.

`parse_pdf` is the headless entry point: render + baseline-parse every page of a PDF
into Source Document + Source Page rows, **score each page** (deterministic always;
LLM judge for visual / opted-in pages), and mirror the mean composite onto the doc.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import fitz  # PyMuPDF

from wikify.engine import llm, pdf_utils, settings, store
from wikify.engine.parsers import pymupdf as baseline
from wikify.engine.remediate import remediate_pdf
from wikify.engine.verify import score_page

__all__ = ["parse_pdf", "remediate_pdf"]


def parse_pdf(
	pdf_path: str,
	title: str | None = None,
	import_name: str | None = None,
	pdf_url: str | None = None,
	progress_cb: Callable[[int, int], None] | None = None,
	page_cb: Callable[..., None] | None = None,
) -> str:
	"""Render + baseline-parse + score every page → Source Document (+ pages).

	Returns the Source Document name. `progress_cb(done, total)` and
	`page_cb(page_no, total, kind, score, metrics)` are optional hooks the parse job
	uses to stream progress + per-page log lines (with cost); the headless
	`bench execute` path passes neither and still scores + persists everything.
	"""
	pdf_path = str(pdf_path)
	title = title or Path(pdf_path).stem

	# Resolve tunables once (visual classification + whether to judge text pages).
	min_chars = int(settings.get("visual_min_chars"))
	min_drawings = int(settings.get("visual_min_drawings"))
	dpi = int(settings.get("render_dpi"))
	judge_all = bool(settings.get("judge_all_pages"))

	composites: list[float] = []

	with fitz.open(pdf_path) as doc:
		total = doc.page_count
		sd = store.create_document(
			title=title, import_name=import_name, pdf_url=pdf_url, parser=baseline.NAME
		)
		for i, page in enumerate(doc):
			page_no = i + 1
			png = pdf_utils.render_png(page, dpi=dpi)
			kind = pdf_utils.classify_page(page, min_chars, min_drawings)
			markdown = baseline.parse_page(pdf_path, page_no)
			page_name = store.add_page(sd, page_no, kind, png, markdown)

			# Visual pages MUST be judged (text GT is unreliable on diagrams); text
			# pages are judged only when the operator opted in (cost/latency).
			use_judge = judge_all or kind == "visual"
			image_data_url = pdf_utils.png_to_data_url(png) if use_judge else None
			llm.reset_metrics()
			score = score_page(
				page_no,
				markdown,
				page.get_text("text"),
				image_data_url=image_data_url,
				use_judge=use_judge,
				page_kind=kind,
			)
			store.set_page_scores(page_name, score)
			composites.append(score.composite)

			if page_cb:
				page_cb(page_no, total, kind, score, llm.get_metrics())
			if progress_cb:
				progress_cb(page_no, total)
		store.set_page_count(sd, total)
		store.set_mean_score(sd, round(sum(composites) / len(composites), 3) if composites else None)

	return sd
