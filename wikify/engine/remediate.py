"""Remediation pass — ported from the POC `pipeline.remediate_document`.

For each target page, route to the cheaper fix that fits and re-score:
  - **cleanup** (cheap text model): text present + decent recall → restructure the
    baseline markdown + strip page furniture, WITHOUT the image.
  - **vlm** (image): visual/diagram page or low recall → re-parse from the page image.
Adoption: cleanup is kept when it preserves content (recall within tolerance — a small
drop is the intended furniture removal); vlm is kept when it scores higher. The adopted
(or baseline) markdown becomes each page's **canonical** markdown; cross-page tables are
then stitched, and the doc's canonical mean is recomputed.

I/O-boundary changes vs the POC: persistence goes through `store` (the Frappe ORM seam)
instead of `loader/graph`; pages are re-rendered from the PDF via `pdf_utils` instead of
read off disk. The routing + adoption rules are unchanged. **Sequential** (not the POC's
ThreadPoolExecutor) — the Frappe ORM writes are not thread-safe; a dev-tool remediate
over a manual is fast enough serial.
"""

from __future__ import annotations

from collections.abc import Callable

import fitz  # PyMuPDF

from wikify.engine import llm, pdf_utils, settings, store
from wikify.engine.loader.cleanup_llm import clean_markdown
from wikify.engine.loader.table_stitch import stitch_cross_page_tables
from wikify.engine.parsers import vlm
from wikify.engine.sectionize import rebuild_and_classify
from wikify.engine.verify import deterministic as det
from wikify.engine.verify import score_page

# Below this baseline recall a text page has likely dropped content — route to the
# image-based VLM rather than a text-only cleanup that can't recover what's missing.
_LOW_RECALL = 0.85


def remediate_pdf(
	source_document: str,
	pdf_path: str,
	scope: str = "all",
	progress_cb: Callable[[int, int], None] | None = None,
	page_cb: Callable[..., None] | None = None,
	stage_cb: Callable[[str], None] | None = None,
) -> dict:
	"""Route + re-score + adopt per page → write canonical markdown + canonical mean.

	`scope='all'` cleans every page (uniform, furniture-free markdown); `scope='flagged'`
	only touches non-`pass` pages. Returns a summary dict. `progress_cb(done, total)` and
	`page_cb(page_no, total, method, adopted, base_composite, new_composite, metrics)` are
	optional streaming hooks the remediate job uses for live progress + log lines.
	"""
	if not llm.has_openrouter():
		raise RuntimeError("OpenRouter key not set — remediation needs cloud models.")

	pdf_path = str(pdf_path)
	judge_all = bool(settings.get("judge_all_pages"))
	recall_tol = float(settings.get("cleanup_recall_tolerance"))
	dpi = int(settings.get("render_dpi"))

	pages = store.get_pages(source_document)
	targets = pages if scope == "all" else [p for p in pages if p["verdict"] != "pass"]
	total = len(targets)

	# Canonical defaults to each page's baseline; adopted remediations override below.
	canon_md = {p["page_no"]: p["baseline_markdown"] or "" for p in pages}
	canon_comp = {p["page_no"]: p["composite"] for p in pages}
	canon_src = {p["page_no"]: "baseline" for p in pages}

	with fitz.open(pdf_path) as doc:
		for i, p in enumerate(targets):
			page = doc[p["page_no"] - 1]
			gt = page.get_text("text")
			kind = p["kind"]
			base_md = p["baseline_markdown"] or ""
			data_url = pdf_utils.png_to_data_url(pdf_utils.render_png(page, dpi=dpi))

			# Route: visual/diagram or low recall → vlm (needs image); else text cleanup.
			method = "vlm" if (kind == "visual" or det.text_recall(gt, base_md) < _LOW_RECALL) else "cleanup"
			use_judge = judge_all or kind == "visual"
			img = data_url if use_judge else None
			llm.reset_metrics()
			base_ps = score_page(
				p["page_no"], base_md, gt, image_data_url=img, use_judge=use_judge, page_kind=kind
			)

			# A single page's model call failing (rate limit, billing, transient) must not
			# abort the whole pass — log it, keep the baseline for that page, move on.
			try:
				new_md = vlm.parse_page_image(data_url) if method == "vlm" else clean_markdown(base_md)
				new_ps = score_page(
					p["page_no"], new_md, gt, image_data_url=img, use_judge=use_judge, page_kind=kind
				)
				if method == "cleanup":
					# Adopt unless content was lost (a small recall drop = furniture removal).
					adopted = new_ps.text_recall >= base_ps.text_recall - recall_tol
				else:
					adopted = new_ps.composite > base_ps.composite
				notes = "; ".join(new_ps.notes) if new_ps.notes else None
				store.set_remediation(p["name"], method, new_md, new_ps, adopted, notes)
				new_composite = new_ps.composite
			except Exception as e:
				adopted, new_composite = False, base_ps.composite
				store.set_remediation(p["name"], method, "", base_ps, False, f"{method} failed: {e}")

			if adopted:
				canon_md[p["page_no"]] = new_md
				canon_comp[p["page_no"]] = new_composite
				canon_src[p["page_no"]] = method

			if page_cb:
				page_cb(
					p["page_no"],
					total,
					method,
					adopted,
					base_ps.composite,
					new_composite,
					llm.get_metrics(),
				)
			if progress_cb:
				progress_cb(i + 1, total)

	# Stitch cross-page tables over the canonical set, then persist canonical per page.
	stitched = dict(stitch_cross_page_tables([(p["page_no"], canon_md[p["page_no"]]) for p in pages]))
	for p in pages:
		pno = p["page_no"]
		store.set_canonical(p["name"], stitched[pno], canon_comp[pno], canon_src[pno])

	comps = [c for c in canon_comp.values() if c is not None]
	canonical_mean = round(sum(comps) / len(comps), 3) if comps else None
	store.set_canonical_mean(source_document, canonical_mean)

	# Rebuild the section tree over the now-canonical (adopted) markdown, then re-tag.
	n_sections = rebuild_and_classify(source_document, pdf_path, stage_cb)

	adopted_count = sum(1 for src in canon_src.values() if src != "baseline")
	return {
		"targets": total,
		"adopted": adopted_count,
		"canonical_mean": canonical_mean,
		"sections": n_sections,
	}
