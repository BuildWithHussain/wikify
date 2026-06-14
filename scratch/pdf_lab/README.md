# PDF Lab

Throwaway Flask app to validate wikify's **parse + load** pipeline interactively.
Upload a PDF → see markdown beside the original → per-page fidelity score → typed
sections loaded into a SQLite graph you can browse, including the cross-document
"all sections of type X" query. **Vectors / chat are out of scope** (chatbot phase).

## Setup

Docling pulls in torch, which may lag the latest Python — use **Python 3.12**.

```bash
cd scratch/pdf_lab
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set OPENROUTER_API_KEY
flask --app app run --debug
```

Open http://127.0.0.1:5000.

- Works with **no key** on the `pymupdf4llm` baseline (no judge, no section tags).
- With an `OPENROUTER_API_KEY`: the `vlm` parser, the LLM judge, and section
  classification turn on. Switch models via `VLM_MODEL` / `JUDGE_MODEL` /
  `CLASSIFIER_MODEL` in `.env`.
- Docling is optional; if it isn't installed the `docling` parser is hidden.

## What maps to what

| Spec | Code |
|---|---|
| POC-0 verification harness | `verify/` (`deterministic.py`, `judge.py`, `harness.py`) |
| POC-1 parser bake-off | `parsers/` adapters + per-page scores in the document view |
| Load (graph) | `loader/` (`cleanup.py`, `toc.py`, `sectionizer.py`, `classifier.py`, `graph.py`) |
| Escalation (router) | `pipeline.escalate_document` + `escalations` table |
| Classification | `pipeline.classify_document` (parallel) + `config.SECTION_TYPES` |
| Pipeline | `pipeline.py` |
| UI | `app.py` + `templates/` |

The SQLite graph (`storage/lab.db`) is beagle-style: typed `nodes` + `edges`,
every section node carrying its page range as citation. The headline query is
`SELECT * FROM nodes WHERE section_type=?` (e.g. `staff_roles_and_responsibilities`).

## Escalation (the router)

Pages the harness flags (`verdict != pass`) can be re-parsed with a stronger parser
(`vlm`). The document view defaults to a **Flagged** tab (toggle to **All**) and an
**Escalate** button. Each re-parse is **re-scored** and, with keep-best, the higher-
scoring parser becomes the page's canonical markdown (sections rebuilt from it). The
before/after columns make this visible. Lesson from real data: the VLM is **not**
always better — re-scoring, not blind trust, is what makes escalation safe.

## Taxonomy

`config.SECTION_TYPES` drives section tagging. Derive it bottom-up from your corpus:
sample real headings → have a model propose 8–12 types → curate around how users will
ask. The current list was derived from the two medical manuals.
