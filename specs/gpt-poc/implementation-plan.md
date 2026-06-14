# Implementation Plan

## Checkpoint Summary

As of 2026-06-14, Milestones 0 through 5 are implemented enough for smoke tests
against real PDFs. Milestone 6 is partially implemented through basic scorecards.
Milestone 7 has not started.

The implementation is under `pocs/gpt_parse_load/`. Run commands from that
directory using:

```bash
python -m pdfpoc.cli ...
```

The local PoC virtualenv used for verification is `pocs/gpt_parse_load/.venv/`.
Generated run artifacts live under `pocs/gpt_parse_load/runs/` and are ignored
by git.

## Milestone 0: PoC skeleton

Create a standalone Python package or script directory outside the Frappe app
runtime. It can live in this repo for now, but it should not import Frappe.

Proposed layout:

```text
pocs/gpt_parse_load/
  pdfpoc/
    cli.py
    config.py
    models.py
    parsers/
      base.py
      pymupdf_adapter.py
      docling_adapter.py
      openrouter_vlm_adapter.py
    normalize/
      canonical.py
      section_builder.py
      markdown_renderer.py
    load/
      schema.sql
      sqlite_graph.py
      loader.py
    eval/
      checks.py
      compare_runs.py
  profiles/
    pymupdf_fast.yaml
    docling_local.yaml
    openrouter_vlm.yaml
  samples/
    input/
  runs/
```

Status: implemented with this layout. The sample PDFs are currently in repo root
`files/`, not `pocs/gpt_parse_load/samples/input/`.

## Milestone 1: parser adapter contract

All parsers implement the same interface:

```python
class ParserAdapter:
    provider: str
    profile_name: str

    def parse_document(self, pdf_path: str, profile: dict) -> dict:
        """Return raw provider output plus basic run metadata."""
```

Each adapter is responsible for provider calls only. It should not decide
sectioning, graph loading, or evaluation.

Cloud model calls go through OpenRouter. The OpenRouter adapter should render
PDF pages to images, send them to the selected VLM with the parsing prompt, and
return raw model output for normalization.

Status: implemented. OpenRouter is configured through the root `.env`
`OPENROUTER_KEY` fallback and has been used for scored Gemini/Mistral runs.
Adapters still expose availability checks so future optional providers can skip
cleanly when their dependencies or credentials are not configured.

## Milestone 2: canonical normalization

Convert every raw parser output into the canonical schema described in
[canonical-schema.md](canonical-schema.md).

This is the most important layer. If the canonical schema is good, providers
can change without breaking downstream evaluation or loading.

Status: implemented for markdown/text-shaped raw outputs and OpenRouter JSON
responses. Sectioning is currently derived from canonical heading blocks.

## Milestone 3: markdown rendering

Generate markdown from canonical sections and blocks.

Rules:

- headings come from canonical section hierarchy
- tables should prefer HTML if markdown would lose merged-cell structure
- every rendered block should be traceable to source page and block id
- preserve page breaks as comments or metadata, not noisy visible text by default

Status: implemented. Optional source comments are available through `render
--source-comments`.

## Milestone 4: SQLite graph load

Load documents, parse runs, nodes, edges, observations, and assets into SQLite.

The initial graph does not need semantic tags, embeddings, or chunks. It only
needs to represent parsed document structure and provenance.

Status: implemented. The loader writes documents, parse runs, nodes, edges,
warnings as observations, and assets. FTS is still optional and not implemented.

## Milestone 5: CLI

Initial CLI commands:

```bash
python -m pdfpoc.cli parse ../../files/Obstetrics\ and\ Gynaecology.pdf --profile profiles/pymupdf_fast.yaml --pages 1-3
python -m pdfpoc.cli render runs/<doc>/<profile>/<run_id>/canonical.json --out runs/<doc>/<profile>/<run_id>/output.md
python -m pdfpoc.cli load runs/<doc>/<profile>/<run_id>/canonical.json --db runs/index.sqlite
python -m pdfpoc.cli inspect --db runs/index.sqlite --document sample.pdf
python -m pdfpoc.cli compare ../../files/Nephrology.pdf --profiles pymupdf_fast,docling_local --pages 1 --db runs/index.sqlite
python -m pdfpoc.cli eval runs/<doc>/<profile>/<run_id>/canonical.json
```

Status: implemented. `--pages` overrides profile `page_range` and should be used
for early tests on large PDFs to control runtime and OpenRouter cost.
`--timeout-seconds` overrides provider timeout settings for exploratory runs.
OpenRouter profiles can also fall back from JSON/bbox parsing to lower-DPI
plain markdown when a page times out.

## Milestone 6: comparison report

For each PDF/profile pair, produce:

- canonical JSON
- rendered markdown
- raw provider output, if license/terms allow local storage
- timing data
- page/block/section counts
- missing-text checks
- table count and structure checks
- heading hierarchy report
- warnings and parser errors

Status: partial. Current scorecards include document, profile, provider,
duration, cost, page count, block count, section count, table count, bbox
coverage, warning count, and error count. Missing-text checks, heading scoring,
and detailed table structure scoring remain to be built.

## Milestone 7: decision report

After running the sample set, produce a short recommendation:

- best local parser
- best OpenRouter cloud model/profile
- default parser candidate
- fallback parser candidate
- parameter settings that improved quality
- document types that still fail

Status: not started. Need a broader labeled sample run first.

## Non-goals

- no Frappe migration
- no DocTypes
- no UI
- no chatbot
- no vector store
- no production queueing
