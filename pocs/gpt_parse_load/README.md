# GPT Parse/Load PoC

Standalone PDF parse/load lab for `specs/gpt-poc`. This code intentionally does
not import Frappe.

## Setup

From the app root:

```bash
cd pocs/gpt_parse_load
python -m pip install -r requirements.txt
```

The OpenRouter adapter reads `.env` from the app root (`apps/wikify/.env`) before
checking the environment. It accepts `OPENROUTER_API_KEY` and the existing
`OPENROUTER_KEY` name.

Optional parser dependencies:

```bash
python -m pip install pymupdf pymupdf4llm
python -m pip install docling
```

## CLI

Run commands from `pocs/gpt_parse_load`:

```bash
python -m pdfpoc.cli parse samples/input/sample.pdf --profile profiles/pymupdf_fast.yaml
python -m pdfpoc.cli parse ../../files/Obstetrics\ and\ Gynaecology.pdf --profile profiles/pymupdf_fast.yaml --pages 1-3
python -m pdfpoc.cli render runs/sample/pymupdf_fast/<run_id>/canonical.json --out output.md
python -m pdfpoc.cli load runs/sample/pymupdf_fast/<run_id>/canonical.json --db runs/index.sqlite
python -m pdfpoc.cli inspect --db runs/index.sqlite --document sample.pdf
python -m pdfpoc.cli eval runs/sample/pymupdf_fast/<run_id>/canonical.json
python -m pdfpoc.cli compare samples/input/sample.pdf --profiles pymupdf_fast,docling_local,openrouter_vlm
python -m pdfpoc.cli hybrid ../../files/Nephrology.pdf --cloud-profile openrouter_gemini_flash --pages 6-15 --db runs/index.sqlite
python -m pdfpoc.cli ui --db runs/index.sqlite
```

Artifacts are written below `runs/<pdf-stem>/<profile>/<run-id>/`.

Use `--pages` for large documents while tuning profiles. The canonical
`document.page_count` remains the full PDF page count; `pages` contains only the
parsed subset.

## Review UI

The UI is a local read-only review surface for comparing parser/model outputs
page by page:

- run scoreboard with metrics, cost, ingest state, and tag state
- page image plus selectable source text
- generated canonical Markdown per run
- ingested SQLite node Markdown per run
- page warnings and observations

Tagging is not implemented yet. The current database only records warning
observations, so the UI reports semantic tags as `none`.
