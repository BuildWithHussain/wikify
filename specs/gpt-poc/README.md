# GPT PDF Parse/Load PoC

Status: implementation checkpoint, 2026-06-14. The PoC is intentionally
standalone and does not touch Frappe, chatbot flows, embeddings, or vector
search.

The first implementation lives in `pocs/gpt_parse_load/`. It is CLI-first and
artifact-first: parse runs write raw output, canonical JSON, rendered markdown,
assets, and optional SQLite graph rows under `pocs/gpt_parse_load/runs/`.

## Goal

Build a controllable PDF parse/load lab that can run the same PDF through
multiple local parsers and OpenRouter-backed cloud models, normalize the
results, load them into a simple graph-shaped SQLite store, and compare parse
quality.

The output of this phase is not a production app. It is evidence:

- which parsers preserve text, headings, tables, page references, and layout
- which parameters materially improve quality
- whether a simple graph index can represent the parsed document cleanly
- which parser/provider path is worth building around later

## Explicit scope

In scope:

- PDF ingestion from local files
- switchable parser profiles
- local parser adapters
- OpenRouter cloud model adapters
- canonical document JSON
- markdown rendering
- Beagle-style graph load into SQLite
- parser comparison reports
- parse quality evaluation

Out of scope:

- Frappe DocTypes or Frappe UI
- chatbot UI
- embeddings
- vector search
- multi-user permissions
- production deployment

## Pipeline

```text
PDF
  -> parse profile
  -> parser adapter
  -> raw parser output
  -> canonical document JSON
  -> markdown render
  -> SQLite graph load
  -> inspect / compare / evaluate
```

## Recommended first providers

Start small enough that the harness ships quickly:

| Profile | Type | Purpose |
|---|---|---|
| `pymupdf_fast` | local | fast digital-PDF baseline |
| `docling_local` | local | structured open-source parser baseline |
| `openrouter_vlm` | cloud | VLM page-image to markdown baseline |
| `openrouter_gemini_flash` | cloud | explicit Gemini 2.5 Flash VLM profile |
| `openrouter_mistral_medium` | cloud | explicit Mistral Medium VLM challenger |

Add Marker, MinerU, Azure Document Intelligence, Google Document AI, or Amazon
Textract only after the adapter interface and scorecard are stable. Native
cloud parser APIs are optional later paths; this PoC uses OpenRouter for cloud
model calls.

## Current checkpoint

Implemented:

- standalone Python package under `pocs/gpt_parse_load/`
- profiles for `pymupdf_fast`, `docling_local`, `openrouter_vlm`,
  `openrouter_gemini_flash`, and `openrouter_mistral_medium`
- root `.env` loading with support for both `OPENROUTER_API_KEY` and the
  existing `OPENROUTER_KEY`
- lazy parser adapters so missing optional dependencies skip cleanly
- canonical JSON normalization
- markdown rendering from canonical blocks and sections
- SQLite graph schema and loader
- CLI commands: `parse`, `render`, `load`, `inspect`, `eval`, `compare`,
  `hybrid`, `ui`
- `--pages` override for sampled runs against large PDFs
- local-first `hybrid` command for cloud escalation of low-scoring pages
- read-only review UI for cross-model page comparison, generated Markdown,
  ingested SQLite nodes, warnings, and current tag/observation status
- unit tests for core canonicalization, loading, `.env`, and page range logic

Sample PDFs currently available in `files/`:

| File | Pages | Notes |
|---|---:|---|
| `Obstetrics and Gynaecology.pdf` | 180 | Used for local and OpenRouter smoke tests |
| `Nephrology.pdf` | 398 | Used for local compare/load smoke test |

Observed scored smoke-test runs:

| PDF | Profile | Pages Parsed | Failed Pages | Duration | Cost | Avg Text Recall | Avg Extra Text | BBox Coverage | Warnings |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| Obstetrics and Gynaecology | `pymupdf_fast` | 1-5 | none | 5073 ms | n/a | 0.995 | 0.166 | 0.0 | 16 |
| Obstetrics and Gynaecology | `openrouter_vlm` | 1-5 | none; page 2 fallback | 68572 ms | 0.0274681 USD | 0.999 | 0.003 | 0.923 | 5 |
| Obstetrics and Gynaecology | `docling_local` | 1 | not batched | 227907 ms | n/a | 1.0 | 0.013 | 0.0 | 13 |
| Nephrology | `pymupdf_fast` | 1-5 | none | 8443 ms | n/a | 0.918 | 0.316 | 0.0 | 8 |
| Nephrology | `openrouter_vlm` | 1-5 | none | 54872 ms | 0.028151 USD | 1.0 | 0.0 | 1.0 | 0 |

Current gaps:

- Docling is installed and verified, but first-run single-page conversion took
  nearly 4 minutes and needs profile/adapter tuning before multi-page bakeoffs.
- Deterministic text recall and table-presence scoring exist; detailed table
  structure fidelity scoring is still target work.
- PyMuPDF-derived canonical blocks currently lack bboxes, so bbox coverage is
  expected to be 0 for that profile.
- OpenRouter bbox quality is model-reported and needs human spot checking before
  it is treated as reliable grounding.
- `Obstetrics and Gynaecology.pdf` page 2 times out through the primary
  OpenRouter JSON/bbox prompt but succeeds through the plain-markdown fallback.

## Spec files

| File | Purpose |
|---|---|
| [implementation-plan.md](implementation-plan.md) | milestones, CLI, repo layout |
| [canonical-schema.md](canonical-schema.md) | normalized parser output contract |
| [sqlite-graph.md](sqlite-graph.md) | Beagle-style graph/index model |
| [parser-profiles.md](parser-profiles.md) | controllable profile parameters and examples |
| [evaluation.md](evaluation.md) | quality checks and scorecard |
| [scratch/](scratch/) | temporary notes and experimental outputs |

Recent scratch reports:

- [2026-06-14 parser smoke report](scratch/2026-06-14-parser-smoke-report.md)
- [2026-06-14 parser analysis report](scratch/2026-06-14-parser-analysis-report.md)
- [2026-06-14 OpenRouter model bakeoff](scratch/2026-06-14-openrouter-model-bakeoff.md)

## Design principle

Markdown is an output, not the source of truth. The durable artifact is the
canonical document JSON plus graph records with page numbers, bounding boxes,
parser metadata, and confidence where available.
