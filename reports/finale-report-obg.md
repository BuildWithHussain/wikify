# Finale Benchmark — All-VLM vs Local-first

**Document:** Obstetrics and Gynaecology.pdf (180 pages)  
**Models:** parse VLM = `mistralai/mistral-medium-3.1` · cleanup = `google/gemini-2.5-flash` · judge = `anthropic/claude-sonnet-4.6`  
**Quality:** judged on a 45-page sample (same pages for both strategies).

- **All-VLM** — every page parsed by the cloud VLM.
- **Local-first** — free local baseline (`pymupdf4llm`), escalate **only** flagged pages (mangled text → cheap cleanup; visual/diagram or low-recall → VLM re-parse).

## Head to head

| Metric | All-VLM | Local-first |
|---|---|---|
| Parse wall time | 366.2 s | **23.4 s** |
| Parse / remediation cost | $0.347 | **$0.019** |
| Cloud parse calls | 180 VLM | **3 VLM + 13 cleanup** |
| Mean judge score (sample) | **97.3%** | 88.4% |

## Full pipeline cost (incl. remediation + structure prep)

Structure prep = classifying 372 sections (`google/gemini-2.5-flash`), shared by both: $0.033. Baseline local parse in local-first is $0 (ran at ingest).

| | Parse / remediation | Structure prep | **Total pipeline** |
|---|---|---|---|
| All-VLM | $0.347 | $0.033 | **$0.380** |
| Local-first | $0.019 | $0.033 | **$0.052** |

Judge evaluation overhead (run on both, sample): $0.662 — measurement, not production cost.

## Section types

| type | count |
|---|---|
| patient_management | 106 |
| clinical_protocols | 75 |
| medication_management | 44 |
| surgical_procedures | 36 |
| administrative_policies | 27 |
| staff_roles_and_responsibilities | 24 |
| emergency_procedures | 19 |
| training_and_audits | 17 |
| other | 10 |
| research_and_documentation | 10 |
| equipment_and_facilities | 4 |

## Generated structure (19 wiki pages)

Derived from the section hierarchy; a heading-validation pass demotes numbered list-items mis-read as chapters. Internal page references are rewritten as wiki links.

| Wiki page | PDF pages | links |
|---|---|---|
| CHRISTIAN MEDICAL COLLEGE, VELLORE | 1 |  |
| REVISION HISTORY | 1–6 |  |
| 1. DEPARTMENTAL PROFILE | 7–16 |  |
| 3. RESPONSIBILITIES AND JOB DESCRIPTION | 16–37 |  |
| 4. RECORDS MAINTAINED | 37–38 |  |
| 5. PROCEDURE FOLLOWED FOR THE ACCESS OF THE PATIENT | 39–87 |  |
| 6. CLINICAL PROTOCOLS | 87–110 |  |
| MISOPROSTOL-ONLY RECOMMENDED REGIMENS 2017 | 110–134 | 1 |
| FIGO recommendations | 130–161 |  |
| 7. PROCEDURES IN PLACE FOR COMPLIANCE TO PATIENT RIGHTS AND RESPONSIBITIES | 161–165 |  |
| 8. PROCEDURES IN PLACE FOR MANAGING MEDICATION | 165–169 |  |
| 9. PROCEDURES IN PLACE FOR MONITORING QUALITY OF SERVICES | 169–170 |  |
| 10. PROCEDURES FOLLOWED FOR THE PATIENT/STAFF SAFETY | 170–174 |  |
| 11. LEGAL REQUIREMENTS | 174–175 |  |
| 12. CONTINUOUS LEARNING /TRAINING INITIATIVES | 175–176 |  |
| 13. INFORMATION MANAGEMENT SYSTEM | 176–177 |  |
| 14. KEY PERFORMANCE INDICATORS | 177–178 |  |
| 15. CLINICAL AUDITS | 178–179 |  |
| 16. DOCUMENTATION CONTROL | 179–180 |  |

---
*Generated from `storage/benchmark.json` via `gen_report.py`. View live at `/report`.*