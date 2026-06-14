"""Render finale-report-<doc>.md for each doc in storage/benchmark.json (reproducible)."""

from __future__ import annotations

import json
from pathlib import Path

ALL = json.loads(Path("storage/benchmark.json").read_text())


def pct(v):
    return f"{v * 100:.1f}%" if v is not None else "n/a"


def usd(v):
    return f"${v:.3f}"


def render(D: dict) -> str:
    a, b, sp, st = D["all_vlm"], D["local_first"], D.get("structure_prep"), D.get("structure")
    L = []
    w = L.append
    w(f"# Finale Benchmark — All-VLM vs Local-first\n")
    w(f"**Document:** {D['filename']} ({D['pages']} pages)  ")
    w(f"**Models:** parse VLM = `{D['vlm_model']}` · cleanup = `{D['cleanup_model']}` · judge = `{D['judge_model']}`  ")
    w(f"**Quality:** judged on a {D['sample_size']}-page sample (same pages for both strategies).\n")
    w("- **All-VLM** — every page parsed by the cloud VLM.")
    w("- **Local-first** — free local baseline (`pymupdf4llm`), escalate **only** flagged pages "
      "(mangled text → cheap cleanup; visual/diagram or low-recall → VLM re-parse).\n")
    w("## Head to head\n")
    w("| Metric | All-VLM | Local-first |")
    w("|---|---|---|")
    w(f"| Parse wall time | {a['wall_seconds']} s | **{b['wall_seconds']} s** |")
    w(f"| Parse / remediation cost | {usd(a['parse_cost'])} | **{usd(b['parse_cost'])}** |")
    w(f"| Cloud parse calls | {a['by_label'].get('vlm_parse',{}).get('calls',0)} VLM | "
      f"**{b['escalated']['vlm']} VLM + {b['escalated']['cleanup']} cleanup** |")
    w(f"| Mean judge score (sample) | **{pct(a['mean_judge'])}** | {pct(b['mean_judge'])} |\n")
    if a["mean_judge"] is None or b["mean_judge"] is None:
        w("> ⏳ **Quality (judge) pending** — the judge phase hit an OpenRouter credit limit; "
          "scores will be backfilled after a top-up.\n")
    if sp:
        w("## Full pipeline cost (incl. remediation + structure prep)\n")
        w(f"Structure prep = classifying {sp['sections']} sections (`{sp['model']}`), shared by both: "
          f"{usd(sp['cost'])}. Baseline local parse in local-first is $0 (ran at ingest).\n")
        w("| | Parse / remediation | Structure prep | **Total pipeline** |")
        w("|---|---|---|---|")
        w(f"| All-VLM | {usd(a['parse_cost'])} | {usd(sp['cost'])} | **{usd(a['pipeline_cost'])}** |")
        w(f"| Local-first | {usd(b['parse_cost'])} | {usd(sp['cost'])} | **{usd(b['pipeline_cost'])}** |\n")
        w(f"Judge evaluation overhead (run on both, sample): {usd(D['judge_eval_cost'])} — measurement, not production cost.\n")
        w("## Section types\n")
        w("| type | count |")
        w("|---|---|")
        for t, c in sorted(sp["by_type"].items(), key=lambda x: -x[1]):
            w(f"| {t} | {c} |")
        w("")
    if st:
        w(f"## Generated structure ({st['wiki_pages']} wiki pages)\n")
        w("Derived from the section hierarchy; a heading-validation pass demotes numbered "
          "list-items mis-read as chapters. Internal page references are rewritten as wiki links.\n")
        w("| Wiki page | PDF pages | links |")
        w("|---|---|---|")
        for t in st["tree"]:
            rng = f"{t['page_start']}" if t["page_start"] == t["page_end"] else f"{t['page_start']}–{t['page_end']}"
            w(f"| {t['title']} | {rng} | {t['ref_links'] or ''} |")
        w("")
    w("---")
    w("*Generated from `storage/benchmark.json` via `gen_report.py`. View live at `/report`.*")
    return "\n".join(L)


for doc_id, D in ALL.items():
    out = Path(f"finale-report-{doc_id}.md")
    out.write_text(render(D), encoding="utf-8")
    print("wrote", out)
