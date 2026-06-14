# OpenRouter Model Bakeoff

Date: 2026-06-14

## What model were we using?

The existing OpenRouter profile was already using:

- `google/gemini-2.5-flash`
- profile file: `pocs/gpt_parse_load/profiles/openrouter_vlm.yaml`

For this bakeoff, explicit model profiles were added:

- `openrouter_gemini_flash`: `google/gemini-2.5-flash`
- `openrouter_mistral_medium`: `mistralai/mistral-medium-3-5`

`mistralai/mistral-medium-3-5` was selected because OpenRouter's model catalog
reported it as image-capable on 2026-06-14.

## Sample

Same sampled page band as the previous broader run:

- `files/Obstetrics and Gynaecology.pdf`, pages 6-15
- `files/Nephrology.pdf`, pages 6-15
- timeout: 20 seconds per cloud page request

Score caveat: these are automated ranking signals. `text_recall` and
`extra_text_ratio` are token comparisons against selectable PyMuPDF text.
`heading_score` is heuristic. `bbox_coverage` is provider/model reported and
still needs visual spot-checking.

## Independent Cloud-Only Runs

| PDF | Profile | Model | Cost | Duration | Avg Recall | Min Recall | Avg Extra | Heading | BBox | Warnings |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Obstetrics | `openrouter_gemini_flash` | `google/gemini-2.5-flash` | $0.044792 | 90465 ms | 0.994 | 0.963 | 0.003 | 0.000 | 1.000 | 0 |
| Obstetrics | `openrouter_mistral_medium` | `mistralai/mistral-medium-3-5` | $0.0919995 | 82567 ms | 0.979 | 0.900 | 0.019 | 0.453 | 0.198 | 85 |
| Nephrology | `openrouter_gemini_flash` | `google/gemini-2.5-flash` | $0.0429012 | 129345 ms | 1.000 | 1.000 | 0.000 | 0.000 | 0.780 | 13 |
| Nephrology | `openrouter_mistral_medium` | `mistralai/mistral-medium-3-5` | $0.0912225 | 81599 ms | 0.997 | 0.990 | 0.014 | 0.550 | 0.200 | 40 |

Independent totals:

- Gemini: $0.0876932 for 20 pages
- Mistral: $0.183222 for 20 pages

Independent read:

- Gemini is currently the better default: lower cost, stronger recall, cleaner
  extra-text behavior, and much better bbox coverage.
- Mistral produces more heading-shaped Markdown according to the current
  heuristic, and it was faster on these two independent runs.
- Mistral's bbox behavior is weak with the current JSON/block prompt. Most of
  its warnings are missing bbox warnings after normalization.
- Gemini fell back to the plain Markdown prompt on Nephrology pages 12 and 13,
  which reduced bbox coverage there. Mistral completed those pages without
  fallback.

## Local-First Hybrid Runs

Hybrid command added:

```bash
.venv/bin/python -m pdfpoc.cli hybrid PDF --cloud-profile PROFILE --pages 6-15 --timeout-seconds 20 --db runs/index.sqlite
```

The prototype runs below used local PyMuPDF first, then sent only low-scoring
pages to the cloud model. The pages selected for escalation were:

- Obstetrics: 10, 13, 14, 15
- Nephrology: 6, 7, 8, 9, 10, 14

The four recorded hybrid rows below were produced before the acceptance guard
was added, so cloud replacements were unconditional. The code now defaults to
score-gated acceptance: a cloud page is only stitched into the hybrid canonical
when it improves the local page score. Use `--accept-worse-cloud` to reproduce
the older unconditional behavior.

| PDF | Profile | Cloud Cost | Duration | Avg Recall | Min Recall | Avg Extra | Heading | BBox | Warnings |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Obstetrics | `pymupdf_fast` local baseline | n/a | 6596 ms | 0.974 | 0.750 | 0.083 | 0.438 | 0.000 | 78 |
| Obstetrics | `hybrid_pymupdf_fast_openrouter_gemini_flash` | $0.0143854 | 55587 ms | 0.938 | 0.429 | 0.009 | 0.374 | 0.171 | 73 |
| Obstetrics | `hybrid_pymupdf_fast_openrouter_mistral_medium` | $0.0317595 | 48765 ms | 0.994 | 0.963 | 0.018 | 0.527 | 0.000 | 96 |
| Nephrology | `pymupdf_fast` local baseline | n/a | 9829 ms | 0.964 | 0.900 | 0.131 | 0.217 | 0.000 | 41 |
| Nephrology | `hybrid_pymupdf_fast_openrouter_gemini_flash` | $0.0314212 | 67648 ms | 0.998 | 0.985 | 0.003 | 0.117 | 0.540 | 29 |
| Nephrology | `hybrid_pymupdf_fast_openrouter_mistral_medium` | $0.0570300 | 80558 ms | 0.996 | 0.985 | 0.012 | 0.417 | 0.073 | 57 |

Hybrid cloud-cost totals:

- Gemini escalations: $0.0458066
- Mistral escalations: $0.0887895

Hybrid read:

- The local-first strategy is useful. It cut cloud pages from 20 to 10 across
  both PDFs for each cloud model.
- Nephrology is a clean win for Gemini hybrid: better recall/extra text, better
  bbox coverage, lower warnings, and lower cost than Mistral hybrid.
- Obstetrics exposed a policy bug in the first hybrid implementation. Gemini's
  cloud parse for page 13 scored `0.429` recall in the hybrid run, while local
  had kept the page text and Mistral scored `0.990` on the same page.
- Gemini page 13 is not stable across runs. In the independent Gemini run it
  scored `0.990`; in the hybrid escalation run it scored `0.429`; in the prior
  broader batch it also scored `0.429`. Treat diagram/organogram pages as a
  special case.

## Recommendation

Default path:

1. Run `pymupdf_fast` first.
2. Score pages locally.
3. Escalate low-recall or high-extra-text pages to `openrouter_gemini_flash`.
4. Accept the cloud replacement only if it improves the local page score.
5. Route diagram/organogram pages to a special prompt or to Mistral as a second
   opinion when Gemini's score is low.

Model choice:

- Use Gemini 2.5 Flash as the default cloud model.
- Keep Mistral Medium as a diagram/heading-oriented challenger, not as the
  default. It costs about 2x more on this sample and has poor bbox coverage
  with the current prompt, but it handled the Obstetrics organogram page more
  consistently in this run.

Next implementation step:

- Add page-type detection for diagram/organogram/table-heavy pages.
- Add a diagram-specific prompt that explicitly asks for every visible label
  and edge/relationship text.
- Re-run only flagged pages with Gemini and Mistral, then accept the best page
  output by score.
