# POC-1 — Parser Bake-off

**Purpose:** run a shortlist of parsers over the real sample PDFs, score every
page with POC-0, and produce a ranked scorecard that picks a **default parser**
and a **fallback** for hard pages. Also validates the ToC-extraction and
consensus ideas.

## Depends on
POC-0 (the harness). Sample PDFs in `samples/` — ideally including: a table-heavy
page, a doc with a real embedded ToC, and one long (~100pp) doc.

## Candidates

| Tier | Parser | Notes |
|---|---|---|
| Baseline | `pymupdf4llm` | Fast, free; also the GT source. Floor to beat. |
| Self-host ML | **Docling** | Structured `DoclingDocument`, RAG-friendly hierarchy. |
| Self-host ML | **Marker** | Strong structure/tables; optional LLM on hard pages. |
| Cloud VLM | **Gemini (3 Flash)** | Top of 2026 leaderboards. |
| Cloud VLM | **Mistral OCR** | Cheap, strong on tables. |
| Optional | LlamaParse, MinerU | Add only if the above leave gaps. |

Each parser sits behind a uniform adapter so they're pluggable / skippable
(important: cloud ones may be gated on API keys).

```python
class ParserAdapter(Protocol):
    name: str
    requires_api_key: bool
    def parse_page(self, pdf_path: str, page_no: int) -> str: ...   # markdown
    def parse_document(self, pdf_path: str) -> list[str]: ...        # per-page md
```

## Pipeline

1. **Triage** each page (digital-text vs image) via PyMuPDF — expected all digital.
2. **ToC extraction** (run once per doc):
   - Prefer embedded outline `doc.get_toc()` → authoritative heading hierarchy.
   - Else detect a printed ToC page and parse it.
   - Else fall back to font-size/style heuristics.
   - Output: a heading map used to **correct** parser headings at stitch time.
3. **Parse** every page with every enabled adapter.
4. **Score** every (page, parser) with POC-0 → matrix of `PageScore`.
5. **Consensus signal:** where two cheap parsers disagree materially (low text
   overlap / different table shape), mark the page "hard" — a label-free predictor
   of which pages need escalation.
6. **Escalation simulation:** for the proposed default, route hard/low-score pages
   to a VLM fallback and re-score → measure accuracy gain vs added cost.
7. **Stitch** the default parser's pages into one markdown doc, applying the ToC
   heading map; score cross-page heading consistency.

## Outputs (`results/`)
- **Scorecard** (CSV + markdown): per parser — mean/min composite, text-recall,
  table-score, judge-score, %pass, cost estimate, latency, GPU need.
- **Per-page heatmap** of composite scores (parser × page) to see *where* each fails.
- **Recommendation:** default parser + fallback + escalation threshold, with the
  measured accuracy/cost tradeoff.
- **Hard-page report:** pages flagged by consensus vs pages flagged by low score
  (how well does disagreement predict difficulty?).

## Config
- `enabled_parsers` list; cloud parsers auto-skip if keys absent (logged, not failed).
- `judge_on` toggle for fast iteration (deterministic-only) vs full scoring.
- Cost/latency captured per parser call for the scorecard.

## Success criteria
- A clear, defensible default+fallback recommendation with numbers behind it.
- ToC extraction measurably improves heading correctness vs raw parser headings.
- Escalating only hard pages beats "run the VLM on everything" on cost at
  comparable accuracy (validates the router architecture).

## Open questions for user
- API keys for Gemini / Mistral available now, or start self-hosted-only and add cloud later?
- GPU available for Docling/Marker, or CPU-only (affects latency numbers)?
