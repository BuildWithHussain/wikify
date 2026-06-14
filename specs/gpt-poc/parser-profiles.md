# Parser Profiles

Profiles make parser behavior controllable and repeatable. A profile is the
effective configuration for one parser run.

The current implementation reads profiles from `pocs/gpt_parse_load/profiles/`.
CLI `--pages` overrides `page_range` without editing the profile file. Every run
stores the effective profile config in `parse_run.config`.

## Common fields

```yaml
name: docling_local
provider: docling
model: default
mode: local

page_range: all
ocr: auto
extract_images: true
extract_tables: true
table_format: html
include_bboxes: true
include_confidence: true
remove_headers_footers: true
build_sections: true
markdown_style: commonmark

store_raw_output: true
store_page_images: true
timeout_seconds: 600
```

## Local baseline: PyMuPDF

```yaml
name: pymupdf_fast
provider: pymupdf4llm
model: default
mode: local

page_range: all
ocr: false
extract_images: false
extract_tables: basic
table_format: markdown
include_bboxes: true
include_confidence: false
remove_headers_footers: false
build_sections: true
markdown_style: commonmark

store_raw_output: true
store_page_images: true
timeout_seconds: 300
```

Purpose:

- fast floor to beat
- useful for digital-native PDFs
- useful source for selectable text checks

## Local structured parser: Docling

```yaml
name: docling_local
provider: docling
model: default
mode: local

page_range: all
ocr: auto
extract_images: true
extract_tables: true
table_format: html
include_bboxes: true
include_confidence: true
remove_headers_footers: true
build_sections: true
markdown_style: commonmark

store_raw_output: true
store_page_images: true
timeout_seconds: 900
```

Purpose:

- stronger local structure extraction
- good candidate for privacy-sensitive documents
- good baseline before paying for cloud parsing

## Cloud VLM parser: OpenRouter

```yaml
name: openrouter_vlm
provider: openrouter
model: google/gemini-2.5-flash
mode: cloud

api_key_env: OPENROUTER_API_KEY
page_range: all
ocr: model
extract_images: true
extract_tables: true
table_format: html
include_bboxes: true
include_confidence: model_reported
remove_headers_footers: prompt_controlled
build_sections: true
markdown_style: commonmark

store_raw_output: true
store_page_images: true
timeout_seconds: 1200

provider_options:
  render_dpi: 200
  prompt_name: pdf_page_to_markdown_v1
  max_pages_per_request: 1
  temperature: 0
  require_json_response: true
  fallback_on_error: true
  fallback_render_dpi: 120
  fallback_prompt_name: pdf_page_to_markdown_plain_v1
  fallback_require_json_response: false
```

Purpose:

- OpenRouter-backed cloud model baseline
- compare VLM page-image parsing against local parsers
- switch cloud models without changing downstream normalization/load code

Notes:

- The adapter should render pages to images before sending them to the model.
- Use one page per request initially for simpler provenance and retry behavior.
- Models can be changed by editing `model`; the rest of the profile stays stable.
- If a model cannot produce reliable bboxes, set `include_bboxes: false` for that
  profile and let evaluation report the grounding gap.
- The app root `.env` currently contains `OPENROUTER_KEY`; the implementation
  accepts that as a fallback after the profile's `api_key_env` and
  `OPENROUTER_API_KEY`.
- A one-page smoke test with `google/gemini-2.5-flash` completed successfully at
  200 DPI and recorded cost of 0.0048702 USD.
- Dense pages that time out with the JSON/bbox prompt fall back to a lower-DPI
  markdown-only prompt. This preserves text/table quality but loses bboxes for
  fallback-derived blocks.

## Current runtime findings

`pymupdf_fast`:

- Works against both PDFs in `files/`.
- Fast enough for sampled runs: page 1 of `Nephrology.pdf` completed in 2029 ms;
  pages 1-3 of `Obstetrics and Gynaecology.pdf` completed in 6322 ms.
- Current canonical output has no block bboxes, so bbox coverage is 0 and
  `missing_bbox` warnings are expected.
- It emits useful markdown quickly, but table and heading fidelity still need
  deterministic and human review scoring.

`openrouter_vlm`:

- Works with the root `.env` key fallback.
- Uses `google/gemini-2.5-flash`; keep it for backward compatibility with
  earlier runs, but prefer the explicit `openrouter_gemini_flash` name for new
  bakeoffs.
- Page 1 of `Obstetrics and Gynaecology.pdf` completed in 9410 ms with 11
  canonical blocks, 3 sections, 1 table, and no warnings.
- The first output looked materially cleaner for the revision-history table, but
  model-reported bboxes and section boundaries still need spot checks.
- Page 2 of `Obstetrics and Gynaecology.pdf` is the first fallback case: primary
  JSON/bbox timed out, plain markdown at 120 DPI completed in roughly 6 seconds.

`openrouter_gemini_flash`:

- Explicit model profile for `google/gemini-2.5-flash`.
- Current best default cloud model from the 2026-06-14 pages 6-15 bakeoff:
  lower cost, stronger recall, cleaner extra-text behavior, and better bbox
  coverage than Mistral on the sampled pages.

`openrouter_mistral_medium`:

- Explicit model profile for `mistralai/mistral-medium-3-5`.
- Useful challenger for pages where Gemini is unstable, especially diagram-like
  pages.
- Current prompt yields weak bbox coverage, so treat it as a text/structure
  fallback until bbox behavior is improved.

`docling_local`:

- Adapter and profile are installed and verified.
- Page 1 of `Obstetrics and Gynaecology.pdf` produced strong text recall but
  took 227907 ms. Keep Docling to targeted single-page checks until runtime is
  tuned.

## Future profiles

Add later only when the harness works:

```text
marker_local
mineru_local
azure_document_intelligence
google_document_ai_layout
amazon_textract
mistral_ocr_native
llamaparse_native
```

## Profile rules

- Every run stores the effective profile config.
- OpenRouter is currently configured through the root `.env` `OPENROUTER_KEY`.
  If credentials are absent in another environment, OpenRouter profiles should
  skip rather than fail the whole bakeoff. Accepted key names are the profile's
  `api_key_env`, `OPENROUTER_API_KEY`, and `OPENROUTER_KEY`.
- Provider-specific options go under `provider_options`.
- Defaults must be resolved before the parse starts.
- Profile changes should produce a new parse run, never mutate old results.
