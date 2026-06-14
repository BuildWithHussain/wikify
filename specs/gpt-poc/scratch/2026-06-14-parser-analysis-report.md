# Parser Analysis Report: 2026-06-14

This report summarizes the GPT PDF parse/load PoC status, parser runs, metrics,
and findings through the pages 6-15 sampled batch.

## Scope

Implementation under test:

- `pocs/gpt_parse_load/`
- SQLite DB: `pocs/gpt_parse_load/runs/index.sqlite`
- Input PDFs:
  - `files/Obstetrics and Gynaecology.pdf` - 180 pages
  - `files/Nephrology.pdf` - 398 pages

Profiles tested:

- `pymupdf_fast`: local baseline using PyMuPDF/pymupdf4llm
- `openrouter_vlm`: OpenRouter VLM using `google/gemini-2.5-flash`
- `docling_local`: Docling local parser, single-page smoke only

OpenRouter behavior:

- Primary request: JSON/bbox prompt at 200 DPI
- Fallback request: plain-markdown prompt at 120 DPI
- Fallback is triggered on timeout/error

## Metric Caveats

These are useful ranking signals, not final quality scores.

- `text_recall` compares tokens from selectable PyMuPDF source text to rendered
  parser markdown.
- `extra_text_ratio` estimates parser text not present in the selectable source.
- `table_score` is table-presence only, not structural fidelity.
- `heading_score` is a rough uppercase-line heuristic and is weak for forms,
  diagrams, table-heavy pages, and pages where models emit tables instead of
  markdown headings.
- Bbox coverage for OpenRouter is model-reported and still needs spot checking.

## Batch Results

### Pages 1-5

| PDF | Profile | Pages | Duration | Cost | Avg Recall | Min Recall | Avg Extra | Heading | BBox | Warnings | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Obstetrics | `pymupdf_fast` | 1-5 | 5073 ms | n/a | 0.995 | 0.974 | 0.166 | 0.219 | 0.0 | 16 | Fast, but extra text and no bboxes |
| Obstetrics | `openrouter_vlm` | 1-5 | 68572 ms | 0.0274681 USD | 0.999 | 0.993 | 0.003 | 0.119 | 0.923 | 5 | Page 2 used fallback |
| Nephrology | `pymupdf_fast` | 1-5 | 8443 ms | n/a | 0.918 | 0.846 | 0.316 | 0.0 | 0.0 | 8 | Fast but noisy |
| Nephrology | `openrouter_vlm` | 1-5 | 54872 ms | 0.028151 USD | 1.0 | 1.0 | 0.0 | 0.1 | 1.0 | 0 | Cleanest output |

### Pages 6-15

| PDF | Profile | Pages | Duration | Cost | Avg Recall | Min Recall | Avg Extra | Heading | BBox | Warnings | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Obstetrics | `pymupdf_fast` | 6-15 | 7683 ms | n/a | 0.974 | 0.75 | 0.083 | 0.438 | 0.0 | 78 | Better than OpenRouter on organogram page by recall |
| Obstetrics | `openrouter_vlm` | 6-15 | 87996 ms | 0.044067 USD | 0.938 | 0.429 | 0.004 | 0.0 | 1.0 | 0 | Missed organogram labels on page 13 |
| Nephrology | `pymupdf_fast` | 6-15 | 11162 ms | n/a | 0.964 | 0.9 | 0.131 | 0.217 | 0.0 | 41 | Still noisy, no bboxes |
| Nephrology | `openrouter_vlm` | 6-15 | 94800 ms | 0.050242 USD | 1.0 | 1.0 | 0.0 | 0.05 | 1.0 | 0 | Strongest result |

### Combined Pages 1-15

| PDF | Profile | Pages | Duration | Cost | Avg Recall | Min Recall | Avg Extra | Heading | BBox | Warnings |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Obstetrics | `pymupdf_fast` | 1-15 | 12756 ms | n/a | 0.981 | 0.75 | 0.110 | 0.365 | 0.0 | 94 |
| Obstetrics | `openrouter_vlm` | 1-15 | 156568 ms | 0.0715351 USD | 0.958 | 0.429 | 0.003 | 0.040 | 0.962 | 5 |
| Nephrology | `pymupdf_fast` | 1-15 | 19605 ms | n/a | 0.949 | 0.846 | 0.193 | 0.144 | 0.0 | 49 |
| Nephrology | `openrouter_vlm` | 1-15 | 149672 ms | 0.078393 USD | 1.0 | 1.0 | 0.0 | 0.067 | 1.0 | 0 |

Total recorded successful OpenRouter cost for the selected final sampled runs:
`0.1499281 USD`.

Total selected runtime:

- PyMuPDF final sampled runs: 32361 ms
- OpenRouter final sampled runs: 306240 ms

## Important Page-Level Findings

### Obstetrics Page 2

Problem:

- The primary OpenRouter JSON/bbox prompt timed out.
- The page is a dense contents-summary table with many rows.

Resolution:

- The lower-DPI plain-markdown fallback completed.
- Output preserved the header, table, and footer cleanly.
- Score: text recall `1.0`, extra text `0.0`, table score `1.0`.

Tradeoff:

- Fallback-derived blocks do not have bboxes.
- This reduced OpenRouter bbox coverage on Obstetrics pages 1-5 from a theoretical
  1.0 to 0.923.

### Obstetrics Page 13

Problem:

- OpenRouter scored text recall `0.429`.
- The page is an organogram/diagram page.
- PyMuPDF selectable text includes many diagram labels.
- OpenRouter captured the page title/header/footer but omitted most diagram
  labels.

Interpretation:

- This is a real parser failure for diagram/flowchart-style content.
- It is not just a scoring artifact.

Next action:

- Add a diagram-specific prompt path for pages with many images/drawings or many
  short labels.
- For organograms, output should preserve labels and relationships as a nested
  list or edge list, not just visible prose/table text.

### Nephrology Pages 1-15

OpenRouter was consistently strong:

- Avg recall `1.0`
- Min recall `1.0`
- Avg extra text `0.0`
- No warnings
- Bbox coverage `1.0`

PyMuPDF was faster but noisier:

- Avg recall `0.949`
- Avg extra text `0.193`
- No bboxes

## Parser Assessment

### OpenRouter VLM

Strengths:

- Best text completeness on Nephrology and most Obstetrics pages.
- Lowest extra text.
- Bboxes available on primary JSON/bbox runs.
- Fallback makes dense table pages recoverable.

Weaknesses:

- Slower and paid.
- Diagram/organogram content can be missed unless prompted directly.
- Fallback loses bboxes.

Current role:

- Best default candidate for high-quality parsing, with local fallback and
  diagram-specific prompt work still needed.

### PyMuPDF / pymupdf4llm

Strengths:

- Very fast.
- Cheap local baseline.
- Good source text extraction for selectable-text comparison.
- Preserved organogram labels better than OpenRouter on Obstetrics page 13.

Weaknesses:

- No bboxes in current canonical output.
- More extra text/noise.
- Tables can be over-expanded or malformed.

Current role:

- Fast baseline, source-text authority, and fallback for pages where VLM misses
  selectable diagram labels.

### Docling

Observed:

- Obstetrics page 1 score was strong: recall `1.0`, extra text `0.013`,
  heading score `0.8`.
- Single-page runtime was `227907 ms`.

Current role:

- Not viable for multi-page batches until profile/runtime is tuned.

## Current Recommendation

Use a hybrid strategy for the next PoC stage:

1. Run PyMuPDF on all sampled pages first.
2. Run OpenRouter VLM on sampled pages for high-quality markdown and bboxes.
3. Use OpenRouter fallback for dense table pages that time out.
4. Detect diagram/organogram pages and route them to a specialized prompt.
5. Compare OpenRouter output against PyMuPDF source text and flag low-recall
   pages automatically.

For now, OpenRouter is the best quality default, but PyMuPDF remains necessary
as a fast baseline and guardrail.

## Next Work

Highest-value next steps:

1. Add a diagram/organogram OpenRouter prompt.
2. Add automatic low-recall page retry using the diagram prompt.
3. Add a small UI for:
   - run list
   - score comparison
   - page image vs markdown
   - warnings/fallbacks
   - low-recall page review
4. Improve scoring:
   - structural table fidelity
   - heading matching against table of contents
   - diagram label recall
5. Keep Docling as an optional single-page experiment until runtime improves.

