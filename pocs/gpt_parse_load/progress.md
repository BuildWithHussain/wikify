# GPT Parse/Load PoC Progress

Last updated: 2026-06-14

## Current state

- Standalone PoC lives under `pocs/gpt_parse_load/` and does not import Frappe.
- CLI supports `parse`, `render`, `load`, `inspect`, `eval`, `compare`,
  `hybrid`, and `ui`.
- Root `.env` loading works with the existing `OPENROUTER_KEY`.
- Profiles exist for:
  - `pymupdf_fast`
  - `docling_local`
  - `openrouter_vlm`
  - `openrouter_gemini_flash`
  - `openrouter_mistral_medium`
- Sample PDFs in use:
  - `files/Obstetrics and Gynaecology.pdf`
  - `files/Nephrology.pdf`
- Generated runs and SQLite graph load live under `pocs/gpt_parse_load/runs/`.

## Findings so far

- Existing OpenRouter baseline was already `google/gemini-2.5-flash`.
- Gemini 2.5 Flash is the current best default cloud model by automated score:
  lower cost, stronger recall, lower extra text, and better bbox coverage on the
  sampled pages.
- Mistral Medium is useful as a challenger for diagram/heading-heavy pages, but
  current bbox coverage is weak and cost is higher.
- Local-first hybrid parsing is useful, but blind cloud replacement is unsafe.
  The `hybrid` command now only accepts cloud output when it improves the local
  page score unless `--accept-worse-cloud` is passed.
- Obstetrics page 13 remains the key instability case: Gemini can miss
  organogram labels depending on run/prompt path.
- Diagram/organogram-specific parsing is intentionally deferred for now. The
  current workflow is to use the review UI to inspect flagged pages and let the
  user manually choose winners/rejections or fix downstream content.
- Full local `pymupdf_fast` end-to-end parses completed for both PDFs:
  - Obstetrics: 180 pages, 447 sections, 35 tables, average recall `0.995`,
    minimum recall `0.75`.
  - Nephrology: 398 pages, 1131 sections, 118 tables, average recall `0.989`,
    minimum recall `0.722`.
- The local score gate flagged 12 Obstetrics pages and 47 Nephrology pages for
  Gemini escalation. This confirms the guarded hybrid approach is practical:
  Gemini is needed for a small subset, not all 578 pages.
- Gemini escalation can be slow on specific pages. Obstetrics page 2 and
  Nephrology pages 174/230 triggered slow primary requests; fallback plain
  prompt recovered page 2 and page 174. Batch 2 was interrupted while page 230
  was still in progress, and no parse process was left running.

## UI status

- Review UI has been added and is served by:

```bash
cd pocs/gpt_parse_load
.venv/bin/python -m pdfpoc.cli ui --host 127.0.0.1 --port 8765 --runs-dir runs --db runs/index.sqlite
```

- Current local URL for the updated review UI:

```text
http://127.0.0.1:8766
```

- UI currently shows:
  - document/run/page selectors
  - run scorecard comparison
  - ingest status from SQLite
  - current tag/observation status
  - page-level review controls
  - page image
  - selectable source text
  - generated Markdown per run
  - ingested SQLite node Markdown per run
  - page warnings
- UI review actions can now save:
  - review status
  - page type
  - winning run
  - rejected runs
  - rejection reason
  - reviewer notes

## Tagging and ingest status

- Ingesting is implemented for canonical JSON into SQLite graph tables.
- Many sampled runs have been loaded into `runs/index.sqlite`.
- Lightweight review annotations are stored in `page_reviews`.
- Full local runs have been loaded into `runs/index.sqlite`; generated artifacts
  remain under ignored `pocs/gpt_parse_load/runs/`.
- Partial Gemini escalation runs have been loaded for:
  - Obstetrics pages `1,2,4,10,13,14,15,39,125,130,153,162`
  - Nephrology batch 1 pages `1,2,3,4,5,6,7,8,9,10,14,25`
- Semantic tagging is not implemented yet.
- The only observations currently loaded are warnings, so the UI reports
  semantic tags as `none`.

## Verification

- `.venv/bin/python -m unittest discover -s tests -v` passes with 8 tests.
- `.venv/bin/python -m compileall -q pdfpoc` passes.
- `git diff --check` passes.
- UI API was checked against the current run set and indexed 40 canonical runs.
- Page compare smoke checked a page-matched run selection and returned review
  status `unreviewed`.

## Next steps

1. Resume Nephrology Gemini escalation from remaining flagged pages:
   `28,30,31,32,81,121,174,203,208,230,231,235,238,239,246,260,264,265,266,272,273,285,286,290,321,328,330,333,334,335,337,339,340,375,389`.
   Keep batches small and use bounded timeouts; if one page blocks, skip it and
   keep the local page.
2. Compose final guarded hybrid runs from the full local runs plus Gemini pages,
   accepting Gemini only when the page score improves.
3. Update the UI to expose a page list, section list, and tag/review summary for
   the selected run/document.
4. Add semantic tagging observations after the page-level review loop is stable.
5. Revisit diagram/organogram detection and diagram-specific prompts only if
   manual review proves too slow or error-prone.
