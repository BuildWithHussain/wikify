# POC-0 — Verification Harness

**Purpose:** a reusable "ruler" that scores how faithfully a parser turned a PDF
page into markdown. It is the scoring engine for POC-1 and, later, a production
quality gate. Build this **first** — everything downstream is measured by it.

## Inputs / outputs

**Input** (per page):
- `page_image: PIL.Image` — rendered page (for the LLM judge).
- `parsed_markdown: str` — a parser's output for that page.
- `ground_truth_text: str` — selectable text from `PyMuPDF` (digital-native ⇒ reliable).

**Output** (per page): a `PageScore`:
```python
@dataclass
class PageScore:
    text_recall: float        # 0..1, fraction of GT tokens present in markdown
    extra_ratio: float        # markdown tokens not in GT (hallucination proxy)
    table_score: float | None # 0..1 structure score if page has table(s), else None
    judge_score: float        # 0..1 from LLM-as-judge rubric
    composite: float          # weighted blend
    verdict: str              # "pass" | "escalate" | "review"
    notes: list[str]          # human-readable failures
```
Document-level: aggregate (mean/min composite, count of escalate/review pages).

## Three layers (cheap → expensive)

### 1. Deterministic — text recall (no LLM, highest value)
- Tokenize GT and markdown (normalize: lowercase, strip markdown syntax, collapse whitespace).
- `text_recall = |GT ∩ MD| / |GT|` → catches **dropped content**.
- `extra_ratio = |MD \ GT| / |MD|` → catches **hallucinated/invented content**.
- Char-count ratio sanity check; flag suspiciously empty pages.

### 2. Deterministic — table structure
- Detect table presence via GT layout / parser metadata.
- Compare cell/row/column counts between parser output and a reference
  (`pdfplumber`/`camelot` extraction). Lightweight TEDS-style structure similarity
  if feasible. Tables are the main adversary for digital-native docs.

### 3. LLM-as-judge — semantic fidelity
- Prompt = page image + parsed markdown + rubric. Score each 1–5:
  - **completeness** (nothing missing/added)
  - **heading correctness** (right levels, right order)
  - **table fidelity** (structure + values)
  - **reading order** (multi-column / sidebars handled)
  - **no hallucination**
- Return per-criterion scores + one-line justifications.
- Research backing: semantic LLM judges ≈0.78 Pearson / ~90% human agreement vs
  ~0.34 for rule-based metrics — but only when **calibrated**.

## Calibration (required, do once)
- Hand-label ~10–20 pages across the samples (good/medium/bad parses).
- Tune composite weights + verdict thresholds so harness ranking matches human ranking.
- Store the labeled set as a regression fixture.

## Composite & verdicts (initial, tune in calibration)
- `composite = 0.4*text_recall + 0.15*(1-extra_ratio) + 0.15*table_score + 0.3*judge_score`
  (drop table term and renormalize when no table on page).
- `pass` ≥ 0.9, `escalate` 0.7–0.9, `review` < 0.7.

## Public interface
```python
def score_page(page_image, parsed_markdown, ground_truth_text, *, judge=True) -> PageScore: ...
def score_document(pages: list[PageInputs], *, judge=True) -> DocumentScore: ...
```
- `judge=False` runs deterministic-only (fast, free) for tight loops.

## Dependencies
`pymupdf` (render + GT text), `pdfplumber`/`camelot` (table reference), an LLM
client for the judge (model selectable; default a cheap-but-strong vision model).

## Success criteria
- Harness ranking agrees with human ranking on the calibration set.
- Deterministic layer alone flags every injected-error fixture (drop a paragraph,
  duplicate a line, mangle a table) without the LLM.
- Runs per page in a few seconds with judge, sub-second deterministic-only.

## Out of scope
- Cross-page heading consistency (handled at stitch stage in POC-1).
- Anything Frappe.
