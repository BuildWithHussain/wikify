# Wikify — POC Specs

High-accuracy PDF → markdown ingestion, stored as structured documents, with a
semantic chat layer that answers cross-document questions (e.g. *"give me all the
job descriptions across all PDFs"*) completely.

Status: **exploration / POC stage**. Nothing is built into the Frappe app yet.
These POCs are standalone Python; the winning approach gets ported into `wikify`
DocTypes later.

## Decisions (2026-06-14)

| Topic | Decision |
|---|---|
| Hosting | **Both** cloud (Gemini, Mistral) and self-hosted (Docling, Marker). Run a bake-off; maximize accuracy. |
| Doc profile | Digital-native (selectable text), with **tables** and **ToC**. No heavy OCR need. Samples provided by user. |
| Build target | **Standalone Python POCs first**, port winner into Frappe later. |

## Guiding architecture

Per-page pipeline, not "pick one tool":

```
triage → primary parse → verify → escalate hard pages → stitch → fix headings
```

Core principles:
- **No universal winner** (2026 benchmarks agree) → router + verify + fallback.
- **Digital-native = trustworthy ground truth.** `PyMuPDF` selectable text lets the
  harness mechanically catch dropped/hallucinated content with no LLM.
- **Exploit the embedded outline** (`doc.get_toc()`) for authoritative heading
  hierarchy instead of inferring it — the weakness all parsers share.
- **Parser disagreement = free "hard page" signal** → tie-break with a VLM.
- **Completeness queries are structured, not fuzzy.** Store sections as typed
  first-class rows; "all X" = metadata filter, not vector similarity (recall-limited).

## POCs

| # | Spec | Purpose |
|---|---|---|
| 0 | [poc-0-verification-harness.md](poc-0-verification-harness.md) | The ruler: score parse fidelity per page. Build first. |
| 1 | [poc-1-parser-bakeoff.md](poc-1-parser-bakeoff.md) | Rank parsers on real samples using POC-0. Pick default + fallback. |
| 2 | [poc-2-sectioning-retrieval.md](poc-2-sectioning-retrieval.md) | Section chunking + type tagging + the "all job descriptions" query. |

## Repo layout (proposed)

```
specs/                 # these docs
samples/               # user-provided sample PDFs (gitignored if sensitive)
pocs/
  common/              # shared: pdf io, ground-truth, models, config
  poc0_verify/
  poc1_bakeoff/
  poc2_retrieval/
results/               # scorecards, judged outputs (gitignored)
```
