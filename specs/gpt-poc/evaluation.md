# Parse/Load Evaluation

This phase evaluates parsing quality only.

No chatbot quality, embedding quality, vector recall, or answer synthesis is
evaluated here.

## Sample set

Use a small but diverse set first:

| Type | Count | Why |
|---|---:|---|
| clean digital PDFs | 3 | baseline text and headings |
| table-heavy PDFs | 3 | structure fidelity |
| multi-column PDFs | 2 | reading order |
| scanned PDFs | 2 | OCR quality |
| form/contract PDFs | 2 | labels, clauses, field-like layout |
| long PDFs around 100 pages | 1-2 | performance and stitching |

Current available sample PDFs:

| File | Pages | Current Use |
|---|---:|---|
| `files/Obstetrics and Gynaecology.pdf` | 180 | Local pages 1-3, OpenRouter page 1 |
| `files/Nephrology.pdf` | 398 | Local page 1 compare/load smoke test |

Use `--pages` for early evaluation. For sampled runs,
`document.page_count` remains the full PDF page count while canonical `pages`
contains only the parsed subset.

## Parse quality checks

### Text completeness

For digital-native PDFs:

- extract selectable text with PyMuPDF
- normalize whitespace and punctuation
- compare parser markdown text to source text
- flag pages with missing text or large extra text

Metrics:

```text
text_recall
extra_text_ratio
empty_page_false_positive
empty_page_false_negative
```

### Heading quality

Check:

- detected heading text
- heading levels
- heading order
- section nesting
- page ranges

Metrics:

```text
heading_precision
heading_recall
heading_level_accuracy
section_boundary_accuracy
```

### Table quality

Check:

- table detection
- row count
- column count
- merged cells
- header rows
- cell text
- table split/merge across pages

Metrics:

```text
table_detection_recall
table_structure_score
cell_text_recall
```

### Reading order

Check:

- multi-column text order
- sidebars
- captions
- footnotes
- headers/footers

Metrics:

```text
reading_order_score
header_footer_noise_score
```

### Source grounding

Check:

- page number exists for every block
- bbox exists where provider supports it
- section maps to block ids
- markdown maps back to block ids

Metrics:

```text
block_page_coverage
bbox_coverage
section_block_coverage
```

## Load quality checks

After loading canonical JSON into SQLite:

- document row exists
- parse run row exists
- page node count matches parsed canonical pages
- document `page_count` stores the full PDF page count when the adapter can
  inspect the PDF
- block node count matches canonical block count
- section node count matches canonical section count
- required edges exist
- no dangling edges
- observations are queryable
- assets point to existing files

## Scorecard

Each parser/profile should produce:

```text
document
profile
provider
duration_ms
cost_usd
page_count
block_count
section_count
table_count
text_recall_avg
text_recall_min
heading_score
table_score
reading_order_score
bbox_coverage
warnings_count
errors_count
```

Current implemented scorecard fields:

```text
document
profile
provider
duration_ms
cost_usd
page_count
block_count
section_count
table_count
block_page_coverage
bbox_coverage
section_block_coverage
warnings_count
errors_count
errors
```

Target fields still pending:

```text
text_recall_avg
text_recall_min
extra_text_ratio
heading_score
table_score
reading_order_score
```

## Current Findings

Smoke tests completed on 2026-06-14:

| PDF | Profile | Pages Parsed | Failed Pages | Duration | Cost | Avg Text Recall | Avg Extra Text | Result |
|---|---|---:|---|---:|---:|---:|---:|---|
| Obstetrics and Gynaecology | `pymupdf_fast` | 1-5 | none | 5073 ms | n/a | 0.995 | 0.166 | Loaded into SQLite; 16 bbox warnings |
| Obstetrics and Gynaecology | `openrouter_vlm` | 1-5 | none; page 2 fallback | 68572 ms | 0.0274681 USD | 0.999 | 0.003 | Loaded into SQLite; fallback warnings for page 2 |
| Obstetrics and Gynaecology | `docling_local` | 1 | not batched | 227907 ms | n/a | 1.0 | 0.013 | Loaded into SQLite; 13 bbox warnings |
| Nephrology | `pymupdf_fast` | 1-5 | none | 8443 ms | n/a | 0.918 | 0.316 | Loaded into SQLite; 8 bbox warnings |
| Nephrology | `openrouter_vlm` | 1-5 | none | 54872 ms | 0.028151 USD | 1.0 | 0.0 | Loaded into SQLite; no warnings |

Initial interpretation:

- The canonical and graph contracts are viable for local and OpenRouter outputs.
- Missing bboxes are the dominant warning for the local baseline.
- OpenRouter output appears more structured on the sampled cover/revision pages,
  but one page per document is not enough to select a default parser.
- Docling has promising text/heading output but is currently too slow for
  multi-page runs without tuning.
- OpenRouter timed out on Obstetrics page 2 with the primary JSON/bbox prompt.
  Provider calls now have per-page deadlines and automatic lower-DPI
  plain-markdown fallback for reliable bakeoffs.
- Large PDFs make page-range testing essential during profile tuning.

## Human review loop

Pick representative pages and label expected behavior:

- 10 good pages
- 10 hard pages
- 5 table-heavy pages
- 5 scanned pages, if scans matter

Keep the labels small but stable. The goal is to catch regressions and rank
profiles consistently.

## Pass/fail target for the PoC

The PoC is successful when:

- at least three parser profiles run through the same CLI
- all outputs normalize to canonical JSON
- all outputs load into SQLite graph tables
- markdown renders from canonical JSON
- comparison scorecards are generated
- failures are visible by page and provider
- there is a clear recommendation for the next build phase
