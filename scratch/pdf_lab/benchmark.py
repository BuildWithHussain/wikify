"""Finale benchmark: All-VLM vs Local-first(+escalate-when-needed).

- Strategy A (all_vlm): every page parsed by the cloud VLM (Mistral).
- Strategy B (local_first): free local baseline (pymupdf4llm), escalate only the
  pages the harness flags — visual/low-recall -> VLM, mangled text -> cheap cleanup.

Parse cost + wall time are measured on the FULL document. Quality is measured by
the judge model on a fixed sample of pages (same pages for both) to bound judge cost.

Usage:  .venv/bin/python benchmark.py <doc_id> <pdf_path> [sample_size]
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import fitz

import config
from config import PAGES_DIR, STORAGE_DIR
from loader.cleanup_llm import clean_markdown
from parsers.pymupdf_parser import PyMuPDFParser
from parsers.vlm_parser import VLMParser
from pdf_utils import classify_page
from verify import deterministic as det
from verify.harness import score_page

RESULT_PATH = STORAGE_DIR / "benchmark.json"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _summary(metrics, wall):
    by = {}
    cost_known = True
    for m in metrics:
        b = by.setdefault(m["label"], {"calls": 0, "seconds": 0.0, "cost": 0.0})
        b["calls"] += 1
        b["seconds"] += m["seconds"]
        if m["cost"] is None:
            cost_known = False
        else:
            b["cost"] += m["cost"]
    for b in by.values():
        b["seconds"] = round(b["seconds"], 1)
        b["cost"] = round(b["cost"], 5)
    return {
        "wall_seconds": round(wall, 1),
        "by_label": by,
        "parse_cost": round(sum(v["cost"] for k, v in by.items() if k != "judge"), 5),
        "cost_known": cost_known,
    }


def run(doc_id: str, pdf: str, sample_size: int = 40) -> dict:
    with fitz.open(pdf) as d:
        n = d.page_count
    page_nums = list(range(1, n + 1))
    pdir = PAGES_DIR / doc_id
    bp = PyMuPDFParser()

    def meta(p):
        with fitz.open(pdf) as d:
            page = d[p - 1]
            return page.get_text("text"), classify_page(page)

    def log(msg):
        print(msg, flush=True)

    # ---- Strategy A: all-vlm (parse every page; write to disk, memory-light) ----
    config.reset_metrics()
    t0 = time.time()

    def work_a(p):
        try:
            img = str(pdir / f"page-{p:04d}.png")
            md = VLMParser().parse_page(pdf, p, image_path=img)
        except Exception as e:
            md = f"[parse error: {e}]"
        (pdir / f"page-{p:04d}.allvlm.md").write_text(md, encoding="utf-8")
        return p

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work_a, page_nums))
    A = _summary(config.get_metrics(), time.time() - t0)
    log(f"[A] all-vlm done: {A['wall_seconds']}s, parse_cost={A['parse_cost']}")

    # ---- Strategy B: local-first + escalate when needed (baseline read from disk) ----
    config.reset_metrics()
    t0 = time.time()
    escalated = {"cleanup": 0, "vlm": 0}

    def work_b(p):
        method = None
        try:
            img = str(pdir / f"page-{p:04d}.png")
            gt, kind = meta(p)
            base_md = (pdir / f"page-{p:04d}.md").read_text(encoding="utf-8")  # free, from ingest
            base_ps = score_page(p, base_md, gt, page_kind=kind, use_judge=False)
            if base_ps.verdict == "pass":
                canon = base_md
            elif kind == "visual" or det.text_recall(gt, base_md) < 0.85:
                canon, method = VLMParser().parse_page(pdf, p, image_path=img), "vlm"
            else:
                canon, method = clean_markdown(base_md), "cleanup"
        except Exception as e:
            canon = f"[error: {e}]"
        (pdir / f"page-{p:04d}.localfirst.md").write_text(canon, encoding="utf-8")
        return p, method

    with ThreadPoolExecutor(max_workers=4) as ex:
        for p, method in ex.map(work_b, page_nums):
            if method:
                escalated[method] += 1
    B = _summary(config.get_metrics(), time.time() - t0)
    B["escalated"] = escalated
    log(f"[B] local-first done: {B['wall_seconds']}s, parse_cost={B['parse_cost']}, escalated={escalated}")

    # ---- Quality: judge a fixed sample of pages for both strategies (read from disk) ----
    step = max(1, n // sample_size)
    sample = sorted(set(page_nums[::step]))
    config.reset_metrics()

    def judge_pair(p):
        try:
            img = str(pdir / f"page-{p:04d}.png")
            gt, kind = meta(p)
            amd = (pdir / f"page-{p:04d}.allvlm.md").read_text(encoding="utf-8")
            bmd = (pdir / f"page-{p:04d}.localfirst.md").read_text(encoding="utf-8")
            ja = score_page(p, amd, gt, image_path=img, use_judge=True, page_kind=kind).judge_score
            jb = score_page(p, bmd, gt, image_path=img, use_judge=True, page_kind=kind).judge_score
            return ja, jb
        except Exception:
            return None, None

    with ThreadPoolExecutor(max_workers=4) as ex:
        pairs = list(ex.map(judge_pair, sample))
    log(f"[Q] judged {len(sample)} sample pages")
    judge_cost = round(sum(m["cost"] or 0 for m in config.get_metrics()), 5)

    A["mean_judge"] = _mean([a for a, _ in pairs])
    B["mean_judge"] = _mean([b for _, b in pairs])

    return {
        "doc_id": doc_id,
        "filename": (pdf.split("/")[-1]),
        "pages": n,
        "sample_size": len(sample),
        "judge_model": config.JUDGE_MODEL,
        "vlm_model": config.VLM_MODEL,
        "cleanup_model": config.CLEANUP_MODEL,
        "all_vlm": A,
        "local_first": B,
        "judge_eval_cost": judge_cost,
    }


def _load_all() -> dict:
    if not RESULT_PATH.exists():
        return {}
    data = json.loads(RESULT_PATH.read_text())
    if "doc_id" in data:  # migrate old single-doc flat format -> {doc_id: result}
        data = {data["doc_id"]: data}
    return data


if __name__ == "__main__":
    doc_id, pdf = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    res = run(doc_id, pdf, size)
    alld = _load_all()
    alld[doc_id] = res
    RESULT_PATH.write_text(json.dumps(alld, indent=2))
    print(f"saved benchmark for {doc_id}: {len(alld)} doc(s) total")
