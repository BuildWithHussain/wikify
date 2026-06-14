# Finale Benchmark — All-VLM vs Local-first

**Document:** Obstetrics and Gynaecology.pdf (180 pages)
**Models:** parse VLM = `mistral-medium-3.1` · cleanup = `gemini-2.5-flash` · judge = `claude-sonnet-4.6`
**Quality:** judged by the judge model on a 45-page sample (same pages for both strategies).

Two strategies compared:
- **All-VLM** — every page parsed by the cloud VLM.
- **Local-first** — free local baseline (`pymupdf4llm`), escalate **only** flagged pages (mangled text → cheap cleanup; visual/diagram or low-recall → VLM re-parse).

## Head to head

| Metric | All-VLM | Local-first | Delta |
|---|---|---|---|
| Parse wall time | 366.2 s | **23.4 s** | ~16× faster |
| Parse / remediation cost | $0.347 | **$0.019** | ~18× cheaper |
| Cloud parse calls | 180 VLM | **3 VLM + 13 cleanup** | 16 of 180 pages |
| Mean judge score (sample) | **97.3%** | 88.4% | −8.9 pts |

## Full pipeline cost (incl. remediation + structure prep)

The headline cost above is the **parse stage**. The full pipeline also pays for
**structure prep** — classifying every section with the taxonomy — which both
strategies share. (Baseline local parse in local-first is $0 and ran at ingest.)

Structure prep: **367 sections** tagged with `gemini-2.5-flash` → **$0.033**.

| | Parse / remediation | Structure prep | **Total pipeline** |
|---|---|---|---|
| All-VLM | $0.347 | $0.033 | **$0.380** |
| Local-first | $0.019 | $0.033 | **$0.052** |

Judge evaluation overhead (run on both, 45-page sample): **$0.662** — this is
measurement cost, not production cost.

## Takeaway

Local-first is **~18× cheaper and ~16× faster on parsing** (~7× cheaper end-to-end
including the shared structure-prep step), paying the cloud VLM on only **3 of 180
pages** instead of all of them. The cost is a modest quality drop (judge **88.4% vs
97.3%**) because ~164 pages keep the raw local baseline rather than a clean VLM parse.

**When to pick which:** local-first for large/cost-sensitive corpora where the
harness reliably flags the pages that actually need help; all-VLM when maximum
per-page fidelity matters more than cost/latency. A middle ground — running the
cheap cleanup pass on *all* pages (not just flagged) — would lift local-first
quality toward all-VLM at a fraction of the VLM cost.

## Section types (367 sections)

| type | count |
|---|---|
| patient_management | 104 |
| clinical_protocols | 74 |
| medication_management | 45 |
| surgical_procedures | 32 |
| administrative_policies | 28 |
| staff_roles_and_responsibilities | 26 |
| emergency_procedures | 17 |
| training_and_audits | 17 |
| other | 11 |
| research_and_documentation | 10 |
| equipment_and_facilities | 3 |

## Generated structure (27 wiki pages)

Derived from the section hierarchy; page ranges are PDF pages. Internal page
references are rewritten as wiki links (link count shown).

| Wiki page | PDF pages | links |
|---|---|---|
| CHRISTIAN MEDICAL COLLEGE, VELLORE | 1 | |
| REVISION HISTORY | 1–7 | |
| 1. DEPARTMENTAL PROFILE | 7–12 | |
| ORGANOGRAM | 13–16 | |
| 3. RESPONSIBILITIES AND JOB DESCRIPTION | 16–37 | |
| 4. RECORDS MAINTAINED | 37–39 | |
| 5. PROCEDURE FOLLOWED FOR THE ACCESS OF THE PATIENT | 39–85 | |
| 2. **Maternal mortality meeting | 85 | |
| 3. **Gynaecology audit | 85–87 | |
| 6. CLINICAL PROTOCOLS | 87–110 | |
| MISOPROSTOL-ONLY RECOMMENDED REGIMENS 2017 | 110–134 | 1 |
| 6. 3.1 Eclampsia drill | 125–130 | |
| FIGO recommendations | 130–137 | |
| 5. **Perimenopausal | 137–161 | |
| 7. PROCEDURES IN PLACE FOR COMPLIANCE TO PATIENT RIGHTS AND RESPONSIBITIES | 161–165 | |
| 8. PROCEDURES IN PLACE FOR MANAGING MEDICATION | 165 | |
| 1. OPD Prescription | 165 | |
| 2. Dispensing medications in OPD | 165 | |
| 3. IP Prescription and administration of medications | 165–169 | |
| 9. PROCEDURES IN PLACE FOR MONITORING QUALITY OF SERVICES | 169–170 | |
| 10. PROCEDURES FOLLOWED FOR THE PATIENT/STAFF SAFETY | 170–174 | |
| 11. LEGAL REQUIREMENTS | 174–175 | |
| 12. CONTINUOUS LEARNING /TRAINING INITIATIVES | 175–176 | |
| 13. INFORMATION MANAGEMENT SYSTEM | 176–177 | |
| 14. KEY PERFORMANCE INDICATORS | 177–178 | |
| 15. CLINICAL AUDITS | 178–179 | |
| 16. DOCUMENTATION CONTROL | 179–180 | |

**Structure caveat:** a few entries (`2. **Maternal mortality meeting`,
`6. 3.1 Eclampsia drill`, `5. **Perimenopausal`) are numbered *list items* the
parser mis-read as top-level chapters — the known section-detection limitation.
A heading-validation pass would clean these up.

---
*Generated from `storage/benchmark.json`. View live at `/report` in the app.*
