"""Parser bake-off on flagged pages.

Re-parses a sample of flagged (non-pass) pages with several VLM models, scores each
with the (independent) harness judge, and prints a scorecard vs the pymupdf4llm
baseline so you can pick a parse model on evidence.

Usage:  .venv/bin/python bakeoff.py [n_per_doc]
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

import fitz

from config import PAGES_DIR
from loader import graph
from parsers.vlm_parser import VLMParser
from verify.harness import score_page

CANDIDATES = [
    "google/gemini-2.5-flash",
    "google/gemini-2.5-pro",
    "mistralai/mistral-medium-3.1",
]

DOCS = {
    "obg": "../../files/Obstetrics and Gynaecology.pdf",
    "neph": "../../files/Nephrology.pdf",
}


def pick_pages(n_per_doc: int):
    items = []
    for doc_id, pdf in DOCS.items():
        flagged = [s for s in graph.get_page_scores(doc_id) if s["verdict"] != "pass"]
        flagged.sort(key=lambda s: s["composite"])  # worst first
        for s in flagged[:n_per_doc]:
            items.append((doc_id, pdf, s["page_no"], s["composite"]))
    return items


def run(n_per_doc: int = 3):
    pages = pick_pages(n_per_doc)
    tasks = [(d, pdf, p, base, m) for (d, pdf, p, base) in pages for m in CANDIDATES]

    def work(t):
        doc_id, pdf, pno, base, model = t
        img = str(PAGES_DIR / doc_id / f"page-{pno:04d}.png")
        md = VLMParser(model=model).parse_page(pdf, pno, image_path=img)
        with fitz.open(pdf) as d:
            gt = d[pno - 1].get_text("text")
        ps = score_page(pno, md, gt, image_path=img, use_judge=True)
        return (doc_id, pno, model, ps.composite, ps.text_recall, ps.judge_score)

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(work, tasks))

    # index results: (doc,page,model) -> composite
    cell = {(d, p, m): (c, r, j) for (d, p, m, c, r, j) in results}
    baseline = {(d, p): base for (d, pdf, p, base) in pages}

    short = [m.split("/")[-1] for m in CANDIDATES]
    out = ["BAKE-OFF — composite (recall / judge)  •  judge = independent claude-sonnet-4.6", ""]
    out.append(f"{'page':14} {'baseline':>9}  " + "  ".join(f"{s:>26}" for s in short))
    sums = {m: [] for m in CANDIDATES}
    bwins = 0
    for (d, pdf, p, base) in pages:
        row = f"{d+':'+str(p):14} {base:>9.2f}  "
        best_m, best_c = None, base
        cells = []
        for m in CANDIDATES:
            c, r, j = cell.get((d, p, m), (0, 0, None))
            sums[m].append(c)
            js = f"{j:.2f}" if j is not None else "-"
            cells.append(f"{c:>5.2f} ({r:.2f}/{js})".rjust(26))
            if c > best_c:
                best_c, best_m = c, m
        if best_m is None:
            bwins += 1
        out.append(row + "  ".join(cells) + ("   <- baseline best" if best_m is None else f"   <- {best_m.split('/')[-1]}"))

    out.append("")
    out.append(f"{'AVERAGE':14} {'':>9}  " + "  ".join(
        f"{(sum(v)/len(v) if v else 0):>26.2f}" for v in (sums[m] for m in CANDIDATES)))
    out.append(f"\nbaseline already best on {bwins}/{len(pages)} flagged pages")
    text = "\n".join(out)
    print(text)
    with open("/tmp/bakeoff.txt", "w") as f:
        f.write(text)


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
