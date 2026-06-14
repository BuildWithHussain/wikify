# Finale Benchmark — All-VLM vs Local-first

**Document:** Nephrology.pdf (398 pages)  
**Models:** parse VLM = `mistralai/mistral-medium-3.1` · cleanup = `google/gemini-2.5-flash` · judge = `anthropic/claude-sonnet-4.6`  
**Quality:** judged on a 45-page sample (same pages for both strategies).

- **All-VLM** — every page parsed by the cloud VLM.
- **Local-first** — free local baseline (`pymupdf4llm`), escalate **only** flagged pages (mangled text → cheap cleanup; visual/diagram or low-recall → VLM re-parse).

## Head to head

| Metric | All-VLM | Local-first |
|---|---|---|
| Parse wall time | 275.5 s | **6.4 s** |
| Parse / remediation cost | $0.236 | **$0.000** |
| Cloud parse calls | 126 VLM | **0 VLM + 0 cleanup** |
| Mean judge score (sample) | **n/a** | n/a |

> ⏳ **Quality (judge) pending** — the judge phase hit an OpenRouter credit limit; scores will be backfilled after a top-up.

## Generated structure (15 wiki pages)

Derived from the section hierarchy; a heading-validation pass demotes numbered list-items mis-read as chapters. Internal page references are rewritten as wiki links.

| Wiki page | PDF pages | links |
|---|---|---|
| CHRISTIAN MEDICAL COLLEGE VELLORE-RANIPET CAMPUS | 1 |  |
| PROCEDURE MANUAL - NEPHROLOGY | 1–392 |  |
| 5 Procedures for access of the patients | 4–105 |  |
| 6. Teaching | 68 |  |
| 7. Maintenance of records | 68–69 |  |
| 8. Maintenance of stocks and payments | 69 |  |
| 9. Receiving stocks | 69 |  |
| 10. Issuing stock | 69 |  |
| 11. Administration | 69–275 |  |
| NEPHROLOGY MANUAL | 210 |  |
| CHRISTIAN MEDICAL COLLEGE DEPARTMENT OF NEPHROLOGY CONSENT FOR CAPD CATHETER INSERTION | 210–257 |  |
| CHRISTIAN MEDICAL COLLEGE DEPARTMENT OF NEPHROLOGY | 257–265 |  |
| Peritonitis treatment (ISPD Guidelines and Recommendations 2016) | 266–374 |  |
| 12. INFORMATION MANAGEMENT SYSTEM | 392–396 |  |
| 13. DOCUMENTATION CONTROL | 397–398 |  |

---
*Generated from `storage/benchmark.json` via `gen_report.py`. View live at `/report`.*