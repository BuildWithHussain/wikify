# Parser Smoke Report: 2026-06-14

This report captures the first scored parser smoke tests against the PDFs in
`files/`. These are not final bakeoff results; they are a checkpoint to decide
what to run next.

## Environment

- Implementation: `pocs/gpt_parse_load/`
- Python: PoC virtualenv at `pocs/gpt_parse_load/.venv/`
- OpenRouter key source: app-root `.env`, using `OPENROUTER_KEY` fallback
- Local parser deps installed: PyMuPDF, pymupdf4llm, Docling
- Generated artifacts: `pocs/gpt_parse_load/runs/`

## Runs

| PDF | Profile | Pages | Duration | Cost | Text Recall | Extra Text | Heading Score | Table Score | BBox Coverage | Warnings |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Obstetrics and Gynaecology | `pymupdf_fast` | 1 | 1548 ms | n/a | 0.974 | 0.238 | 0.6 | 1.0 | 0.0 | 6 |
| Obstetrics and Gynaecology | `openrouter_vlm` | 1 | 10021 ms | 0.0048702 USD | 0.993 | 0.013 | 0.4 | 1.0 | 1.0 | 0 |
| Obstetrics and Gynaecology | `docling_local` | 1 | 227907 ms | n/a | 1.0 | 0.013 | 0.8 | 1.0 | 0.0 | 13 |
| Nephrology | `pymupdf_fast` | 1 | 2033 ms | n/a | 0.846 | 0.202 | 0.0 | 1.0 | 0.0 | 2 |
| Nephrology | `openrouter_vlm` | 1 | 10959 ms | 0.0055402 USD | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0 |

## Pages 1-5 Aggregate

After the single-page smoke tests, PyMuPDF and OpenRouter were run over pages
1-5. OpenRouter originally stalled on Obstetrics page 2 with the JSON/bbox
prompt. The adapter now falls back to a lower-DPI plain-markdown prompt when a
primary OpenRouter request times out or errors.

| PDF | Profile | Pages Completed | Missing/Failed Pages | Duration | Cost | Avg Text Recall | Min Text Recall | Avg Extra Text | Heading Score | Table Score | BBox Coverage | Warnings |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Obstetrics and Gynaecology | `pymupdf_fast` | 1-5 | none | 5073 ms | n/a | 0.995 | 0.974 | 0.166 | 0.219 | 1.0 | 0.0 | 16 |
| Obstetrics and Gynaecology | `openrouter_vlm` | 1-5 | none; page 2 used fallback | 68572 ms | 0.0274681 USD | 0.999 | 0.993 | 0.003 | 0.119 | 1.0 | 0.923 | 5 |
| Nephrology | `pymupdf_fast` | 1-5 | none | 8443 ms | n/a | 0.918 | 0.846 | 0.316 | 0.0 | 1.0 | 0.0 | 8 |
| Nephrology | `openrouter_vlm` | 1-5 | none | 54872 ms | 0.028151 USD | 1.0 | 1.0 | 0.0 | 0.1 | 1.0 | 1.0 | 0 |

## Findings

- The canonical JSON and SQLite graph path works for all three configured
  profiles.
- OpenRouter is consistently cleaner on the sampled cover/revision pages:
  higher text recall, lower extra text, no warnings, and model-reported bboxes.
- OpenRouter page 2 of `Obstetrics and Gynaecology.pdf` times out with the
  JSON/bbox prompt but succeeds with the plain-markdown fallback at 120 DPI. The
  tradeoff is expected: text and table quality stay high, but bbox coverage drops
  for fallback-derived blocks.
- PyMuPDF remains the speed baseline. It is useful for cheap scanning and source
  text checks, but sampled outputs show more extra text and no bboxes.
- Docling produced strong text and heading scores on the Obstetrics page, but
  first-run page conversion took nearly 4 minutes. It should not be included in
  multi-page bakeoffs until the adapter/profile is tuned.
- Current heading score is a heuristic based on uppercase-looking source lines
  and parsed heading blocks. Treat it as a coarse signal, not a final heading
  quality metric.
- Current table score is table-presence detection, not structural fidelity.

## Next Run

Use a small, fixed page set before full-document parsing. OpenRouter now has
timeout control and automatic fallback:

```bash
cd pocs/gpt_parse_load
.venv/bin/python -m pdfpoc.cli compare ../../files/Obstetrics\ and\ Gynaecology.pdf --profiles pymupdf_fast,openrouter_vlm --pages 1-5 --timeout-seconds 20 --db runs/index.sqlite
.venv/bin/python -m pdfpoc.cli compare ../../files/Nephrology.pdf --profiles pymupdf_fast --pages 1-5 --db runs/index.sqlite
.venv/bin/python -m pdfpoc.cli compare ../../files/Nephrology.pdf --profiles openrouter_vlm --pages 2 --timeout-seconds 90 --db runs/index.sqlite
```

Keep Docling to single-page targeted checks until its runtime is understood.
