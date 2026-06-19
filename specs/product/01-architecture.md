# 01 — Architecture

## System shape

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser — Frappe UI SPA  (Vue 3, vite, mounted at /wikify)          │
│                                                                       │
│  Imports list ─▶ Import detail (Tabs)                                 │
│     │              ├─ Overview + Logs                                 │
│     │              ├─ Pages   (split-pane review)                     │
│     │              ├─ Tree    (drag-rearrange)                        │
│     │              ├─ Explore (typed sections + cross-doc)            │
│     │              └─ Wiki    (generate into a Wiki Space)            │
│     └─ New Import dialog (PDF + name)                                 │
└───────────────┬───────────────────────────────────┬─────────────────┘
        REST (useCall / useList / useDoc)         realtime (socket.io)
                │                                       │
┌───────────────▼───────────────────────────────────────▼─────────────┐
│  Frappe backend  (app: wikify)                                        │
│                                                                       │
│  DocTypes ── Wikify Import · Source Document · Source Page            │
│              Source Section (tree) · Section Type · Import Log Entry  │
│                                                                       │
│  Whitelisted API (wikify/api/*.py)                                    │
│     start_import · trigger_remediation · reorder_section ·           │
│     reclassify · build_graph · generate_wiki · …                     │
│                                                                       │
│  Background jobs (frappe.enqueue, queue="long")                      │
│     parse_import → remediate → sectionize+classify → generate_wiki   │
│     └─ each publishes progress + log lines via frappe.publish_realtime│
│                                                                       │
│  Pipeline package  wikify/engine/  (ported from scratch/pdf_lab/)    │
│     parsers/ · verify/ · loader/ · pdf_utils · llm client            │
│                                                                       │
│  Integration ── creates Wiki Document rows under a Wiki Space tree    │
└───────────────────────────────────────────────────────────────────────┘
```

## The three layers

### 1. The pipeline package — `wikify/engine/`

A near-verbatim port of `scratch/pdf_lab/`, restructured as an importable package
with **no Flask and no SQLite**. The POC's `loader/graph.py` (the SQLite layer) is
the one module we *drop* — its tables become DocTypes (see `02-data-model.md`), and
reads/writes go through `frappe.db` / the ORM instead.

Port as-is (logic unchanged, only I/O boundaries swapped):

| POC module | Ported to | Change |
|---|---|---|
| `parsers/` (pymupdf, vlm, docling, registry) | `engine/parsers/` | none beyond client wiring |
| `verify/` (harness, deterministic, judge) | `engine/verify/` | none |
| `loader/` (sectionizer, cleanup, cleanup_llm, table_stitch, toc, classifier, wiki) | `engine/loader/` | `classifier`/`wiki` read taxonomy + sections from DocTypes |
| `pdf_utils.py` | `engine/pdf_utils.py` | write PNG/markdown as **File** docs, not loose paths |
| `config.py` | `engine/config.py` + **Wikify Settings** (Single) | model ids/thresholds become site-configurable |
| `loader/graph.py` | — (deleted) | replaced by DocTypes + a thin `engine/store.py` adapter |
| `app.py`, `benchmark.py`, `gen_report.py` | — | not ported (replaced by the SPA / optional reporting) |

`engine/store.py` is the seam: a small module exposing the same call-shapes the
pipeline used against `graph.py` (`create_document`, `add_page_score`,
`add_section`, `add_escalation`, `sections_by_type`, …) but backed by Frappe ORM.
This keeps the pipeline logic diff-minimal against the POC.

### 2. Persistence — DocTypes

Full schema in `02-data-model.md`. Mapping summary:

| POC SQLite table | DocType |
|---|---|
| `documents` | `Source Document` (+ `Wikify Import` wraps the run) |
| `page_scores` + `escalations` | `Source Page` (baseline + remediation folded into one row) |
| `nodes` (type=section) + `edges` | `Source Section` (`is_tree`, `parent_source_section`) |
| `wiki_pages` | **not stored** — we generate real `Wiki Document` rows instead |
| (new) | `Section Type`, `Import Log Entry`, `Wikify Settings` |

### 3. The SPA — `wikify/frontend/`

Vue 3 + frappe-ui v1 (`1.0.0-beta.10`), built by Vite 8, served from a www Jinja page,
mounted at `/wikify`. Scaffold adapted from frappe/gameplan's frontend. Details in
`04-frontend-plan.md`.

## Backgrounding & progress

The POC ran the whole pipeline **synchronously inside the upload request**. In the
app, every long stage is a background job:

```
start_import (API)
  └─ enqueue parse_import(import)          queue="long", timeout high
       ├─ render+parse+score each page  ── publish_realtime("wikify_import_progress", {import, percent, stage_label})
       ├─ append Import Log Entry rows  ── publish_realtime("wikify_import_log", {import, line})
       ├─ sectionize → Source Section tree
       ├─ classify (ThreadPool inside the job, as POC)
       └─ set status = "Review", publish final
```

- **Concurrency stays inside the job** (the POC's `ThreadPoolExecutor` for LLM calls
  — remediation/classify workers). DB writes remain sequential after the concurrent
  LLM map, exactly as the POC does, to avoid write contention.
- **Realtime events** drive the `<Progress>` bar and stream the log. Two channels:
  `wikify_import_progress` (coarse percent + stage label) and `wikify_import_log`
  (one Import Log Entry per line). The SPA also `useList`/`useDoc`-subscribes so the
  Import doc's `status`/`stage_progress` fields reflect state on refetch.
- **Remediation**, **reclassify**, and **generate_wiki** are separately enqueueable
  jobs triggered from their respective tabs, each with the same progress/log pattern.

## Stage → status state machine (`Wikify Import.status`)

```
Draft ─▶ Queued ─▶ Parsing ─▶ Review ─▶ (Remediating ⇄ Review) ─▶ Tree Review
       ▲                                                              │
       └────────────────── Failed ◀── (any stage on error)           ▼
                                              Graphed ─▶ Generating Wiki ─▶ Completed
```

`Review`, `Tree Review`, `Graphed`, `Completed` are user-gated checkpoints (the user
approves to advance). `Parsing`, `Remediating`, `Generating Wiki` are job-owned.

## Component reuse map (frontend)

| Need | Use | Source |
|---|---|---|
| App shell | `FrappeUIProvider` + `Sidebar` | frappe-ui v1 |
| Imports list | `ListView` + `ListFilter` (`ItemListRow` for custom rows) | frappe-ui v1 |
| New Import dialog | `Dialog` + `FileUploader` + `FormControl` | frappe-ui v1 |
| Confirms / quick prompts | imperative `dialog.confirm` / `dialog.prompt`, `toast.*` | frappe-ui v1 |
| Progress bar | `Progress` / `Spinner` / `LoadingText` | frappe-ui v1 |
| Tabs / segmented filters | `Tabs` / `TabButtons` | frappe-ui v1 |
| **Markdown source editor** | **`CodeEditor`** (`frappe-ui/code-editor`, `language="markdown"`) + **`CodePreview`** | **frappe-ui v1 (built in)** |
| **Split pane (page review)** | **`splitpanes`** | external |
| **Drag-rearrange tree** | **vuedraggable**, modeled on `NestedDraggable.vue` | copy/adapt from `apps/wiki` |
| Tree display (read-only previews) | `Tree` (display-only) | frappe-ui v1 |
| Section explorer | `ListView` + `Badge` type-filter chips | frappe-ui v1 |
| Status badges | `Badge` (`variant`/`theme`) | frappe-ui v1 |
| PDF page render (tab 1) | PDF.js | external (or `<iframe>` to the File) |
| Data fetching | **`useCall` / `useList` / `useDoc`** (v3; *not* legacy `createResource`) | frappe-ui v1 |
| Live updates | socket / `frappe.realtime` | frappe-ui `initSocket` |

## Why Import and Source Document are separate (1:1)

`Wikify Import` is the **run**: status, progress, logs, the model-config snapshot,
errors, retries. `Source Document` is the **durable artifact**: the parsed,
typed knowledge that the cross-PDF Explore queries and the wiki generation read from.
Keeping them separate means an Import can be re-run or archived without disturbing the
artifact, and the headline query (*"all sections of type X across all PDFs"*) is a
clean scan over `Source Section` rows joined to `Source Document` — independent of any
import-job bookkeeping. They are created together and stay 1:1; collapse them only if
v1 simplicity demands it.
