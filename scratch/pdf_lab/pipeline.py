"""End-to-end: PDF -> per-page parse -> verify -> stitch -> sections -> graph."""

from __future__ import annotations

from config import PAGES_DIR
from loader import graph
from loader.classifier import classify_section
from loader.cleanup import clean_pages
from loader.cleanup_llm import clean_markdown
from loader.sectionizer import sectionize
from loader.table_stitch import stitch_cross_page_tables
from loader.toc import toc_level_map
from parsers.registry import get_parser
from pdf_utils import classify_page, render_and_extract
from verify import deterministic as det
from verify.harness import score_page


def _store_sections(doc_id, pages, level_map, classify) -> int:
    """(Re)build a doc's section nodes from per-page markdown. Replaces existing."""
    graph.clear_sections(doc_id)
    pages = clean_pages(pages)
    sections = sectionize(pages, level_map)
    path_to_id: dict[tuple[str, ...], str] = {}
    for idx, sec in enumerate(sections):
        if classify:
            sec.section_type = classify_section(sec.title, sec.markdown)
        node_id = f"{doc_id}:s{idx}"
        parent_id = path_to_id.get(tuple(sec.hierarchy_path[:-1]))
        graph.add_section(node_id, doc_id, sec, parent_id)
        path_to_id[tuple(sec.hierarchy_path)] = node_id
    return len(sections)


def process_document(
    doc_id: str,
    pdf_path: str,
    parser_name: str,
    use_judge: bool = False,
    classify: bool = True,
) -> dict:
    parser = get_parser(parser_name)
    assets = render_and_extract(pdf_path, doc_id)
    level_map = toc_level_map(pdf_path)

    pages: list[tuple[int, str]] = []
    for a in assets:
        markdown = parser.parse_page(pdf_path, a.page_no, image_path=str(a.image_path))
        # Persist per-page markdown next to the rendered PNG for the preview view.
        a.image_path.with_suffix(".md").write_text(markdown, encoding="utf-8")
        # Visual pages must be judged (text GT is unreliable), even if use_judge is off.
        ps = score_page(
            a.page_no, markdown, a.ground_truth_text,
            image_path=str(a.image_path),
            use_judge=use_judge or a.kind == "visual",
            page_kind=a.kind,
        )
        graph.add_page_score(doc_id, ps)
        pages.append((a.page_no, markdown))

    n_sections = _store_sections(doc_id, pages, level_map, classify)
    mean_score = graph.mean_composite(doc_id)
    graph.finish_document(doc_id, "done", mean_score)
    return {"pages": len(assets), "sections": n_sections, "mean_score": mean_score}


def _canonical_pages(doc_id, page_numbers, prefer: dict[int, str]) -> list[tuple[int, str]]:
    """Read per-page markdown from disk; for pages in `prefer` use that parser's file."""
    page_dir = PAGES_DIR / doc_id
    pages: list[tuple[int, str]] = []
    for p in page_numbers:
        suffix = f".{prefer[p]}.md" if p in prefer else ".md"
        f = page_dir / f"page-{p:04d}{suffix}"
        pages.append((p, f.read_text(encoding="utf-8") if f.exists() else ""))
    return pages


def escalate_document(
    doc_id: str,
    pdf_path: str,
    parser_name: str = "vlm",
    keep_best: bool = True,
    reclassify: bool = True,
) -> dict:
    """Re-parse flagged (non-pass) pages with a stronger parser and re-score.

    With keep_best, pages where the new parser scores higher become canonical:
    their page score is updated and the doc's sections are rebuilt from the
    improved markdown. Before/after is always stored for the UI.
    """
    from concurrent.futures import ThreadPoolExecutor

    import fitz

    import config

    parser = get_parser(parser_name)
    all_scores = graph.get_page_scores(doc_id)
    flagged = [s for s in all_scores if s["verdict"] != "pass"]
    page_dir = PAGES_DIR / doc_id
    improved_pages: dict[int, str] = {}

    judge = config.has_openrouter()

    def work(s):
        p = s["page_no"]
        image_path = str(page_dir / f"page-{p:04d}.png")
        with fitz.open(pdf_path) as doc:  # one Document per thread (not shared)
            page = doc[p - 1]
            gt = page.get_text("text")
            kind = classify_page(page)
        # Re-score the baseline WITH the judge so it's comparable to the escalation
        # (both judge-inclusive, same page kind) — otherwise keep-best is unfair.
        base_md = (page_dir / f"page-{p:04d}.md").read_text(encoding="utf-8")
        base_ps = score_page(p, base_md, gt, image_path=image_path, use_judge=judge, page_kind=kind)
        esc_md = parser.parse_page(pdf_path, p, image_path=image_path)
        esc_ps = score_page(p, esc_md, gt, image_path=image_path, use_judge=judge, page_kind=kind)
        return base_ps, esc_md, esc_ps

    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(work, flagged))

    for base_ps, esc_md, esc_ps in rows:  # graph writes sequential (SQLite)
        p = esc_ps.page_no
        graph.update_page_score(doc_id, base_ps)  # baseline now judge-inclusive
        (page_dir / f"page-{p:04d}.{parser_name}.md").write_text(esc_md, encoding="utf-8")
        graph.add_escalation(doc_id, parser_name, esc_ps)
        if esc_ps.composite > base_ps.composite:
            improved_pages[p] = parser_name

    if keep_best and improved_pages:
        # Keep page_scores as the original baseline; "best-per-page" is computed at
        # read time (graph.canonical_mean / the document view). Rebuild sections
        # from the canonical (best) markdown so the graph reflects the improvement.
        page_numbers = [s["page_no"] for s in all_scores]
        pages = _canonical_pages(doc_id, page_numbers, improved_pages)
        level_map = toc_level_map(pdf_path)
        _store_sections(doc_id, pages, level_map, classify=reclassify)
        graph.finish_document(doc_id, "done", graph.canonical_mean(doc_id))

    return {
        "flagged": len(flagged),
        "escalated_with": parser_name,
        "improved": len(improved_pages),
        "adopted": bool(keep_best and improved_pages),
    }


def rescore_document(doc_id: str, pdf_path: str, workers: int = 6) -> dict:
    """Re-score existing baseline pages with the current (page-kind-aware) harness.

    Re-detects visual pages and judges them (text GT is unreliable there); text
    pages keep fast deterministic scoring. No re-parsing. Run before escalation so
    visual pages that were falsely 'passed' get correctly flagged.
    """
    from concurrent.futures import ThreadPoolExecutor

    import fitz

    import config

    judge = config.has_openrouter()
    page_dir = PAGES_DIR / doc_id
    scores = graph.get_page_scores(doc_id)

    def work(s):
        p = s["page_no"]
        img = str(page_dir / f"page-{p:04d}.png")
        with fitz.open(pdf_path) as doc:
            page = doc[p - 1]
            gt = page.get_text("text")
            kind = classify_page(page)
        md = (page_dir / f"page-{p:04d}.md").read_text(encoding="utf-8")
        return score_page(p, md, gt, image_path=img, use_judge=(judge and kind == "visual"), page_kind=kind)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(work, scores))
    for ps in rows:
        graph.update_page_score(doc_id, ps)
    graph.finish_document(doc_id, "done", graph.canonical_mean(doc_id))
    return {"pages": len(rows), "visual": sum(1 for ps in rows if ps.kind == "visual")}


def remediate_document(doc_id: str, pdf_path: str, reclassify: bool = True, scope: str = "all") -> dict:
    """Run the model cleanup pass over pages and adopt per-page improvements.

    scope='all' (default) cleans EVERY page for uniform, furniture-free markdown;
    scope='flagged' only touches pages the harness flagged. Routing per page:
      - cleanup (cheap text model): text present → restructure + strip header/footer
      - vlm (image): visual/diagram page or low recall → re-parse from the image
    Adoption: cleanup is kept when it preserves content (recall within tolerance —
    a small drop is the intended furniture removal); vlm is kept when it scores
    higher. Then cross-page tables are stitched and sections rebuilt.
    """
    from concurrent.futures import ThreadPoolExecutor

    import fitz

    import config

    page_dir = PAGES_DIR / doc_id
    all_scores = graph.get_page_scores(doc_id)
    targets = all_scores if scope == "all" else [s for s in all_scores if s["verdict"] != "pass"]

    def work(s):
        p = s["page_no"]
        img = str(page_dir / f"page-{p:04d}.png")
        base_md = (page_dir / f"page-{p:04d}.md").read_text(encoding="utf-8")
        with fitz.open(pdf_path) as doc:
            page = doc[p - 1]
            gt = page.get_text("text")
            kind = classify_page(page)
        # Route: visual/diagram or low recall → vlm (needs image); else → text cleanup.
        if kind == "visual" or det.text_recall(gt, base_md) < 0.85:
            method, new_md, jb = "vlm", get_parser("vlm").parse_page(pdf_path, p, image_path=img), config.has_openrouter()
        else:
            method, new_md, jb = "cleanup", clean_markdown(base_md), False
        base_ps = score_page(p, base_md, gt, image_path=img, use_judge=jb, page_kind=kind)
        new_ps = score_page(p, new_md, gt, image_path=img, use_judge=jb, page_kind=kind)
        if method == "cleanup":
            # Adopt unless content was lost (a small recall drop = furniture removal).
            adopted = new_ps.text_recall >= base_ps.text_recall - config.CLEANUP_RECALL_TOLERANCE
        else:
            adopted = new_ps.composite > base_ps.composite
        return method, new_md, base_ps, new_ps, adopted

    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(work, targets))

    improved: dict[int, str] = {}
    counts = {"cleanup": 0, "vlm": 0}
    adopted_by = {"cleanup": 0, "vlm": 0}
    for method, new_md, base_ps, new_ps, adopted in rows:
        p = base_ps.page_no
        counts[method] += 1
        graph.update_page_score(doc_id, base_ps)
        (page_dir / f"page-{p:04d}.{method}.md").write_text(new_md, encoding="utf-8")
        graph.add_escalation(doc_id, method, new_ps, adopted=adopted)
        if adopted:
            improved[p] = method
            adopted_by[method] += 1

    # Canonical (adopted) markdown per page → stitch cross-page tables → rebuild sections.
    page_numbers = [s["page_no"] for s in all_scores]
    canon = _canonical_pages(doc_id, page_numbers, improved)
    canon = stitch_cross_page_tables(canon)
    _store_sections(doc_id, canon, toc_level_map(pdf_path), classify=reclassify)
    graph.finish_document(doc_id, "done", graph.canonical_mean(doc_id))

    return {"targets": len(targets), "routed": counts, "adopted": len(improved), "adopted_by": adopted_by}


def classify_document(doc_id: str, workers: int = 8) -> dict:
    """Tag every section of a doc with the current taxonomy.

    LLM calls run concurrently (read-only); graph writes happen after, sequentially,
    to avoid SQLite write contention.
    """
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    sections = graph.get_sections(doc_id)

    def work(s):
        return s["id"], classify_section(s["title"], s["markdown"])

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(work, sections))

    counts: Counter[str] = Counter()
    for node_id, t in results:
        graph.set_section_type(node_id, t)
        counts[t] += 1
    return {"sections": len(results), "by_type": dict(counts)}
