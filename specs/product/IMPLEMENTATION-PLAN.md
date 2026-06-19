# Implementation Plan — Tracer-Bullet Slices

A vertical-slice breakdown of the [product spec](README.md), built for incremental
delivery. Each slice cuts through **every layer** (DocType → `engine/` → background
job → whitelisted API → realtime → SPA) and ends in something **demoable or
verifiable on its own** — not a horizontal layer.

The guiding move: **Slice 1b is a walking skeleton** that proves the whole spine
with the thinnest possible parse. Every later slice *thickens* one capability of
that skeleton rather than adding a new disconnected layer.

> Source of truth for behavior remains the numbered spec docs
> ([01-architecture](01-architecture.md) · [02-data-model](02-data-model.md) ·
> [03-backend-plan](03-backend-plan.md) · [04-frontend-plan](04-frontend-plan.md) ·
> [05-wiki-generation](05-wiki-generation.md)). This file is the *delivery order*.

## Legend

- **HITL** — needs human interaction (architectural decision, design/UX review, or a
  spine-verification checkpoint).
- **AFK** — well-specified enough to implement and merge without a checkpoint.

## Slice map

| # | Slice | Type | Blocked by | Spec phase |
|---|---|---|---|---|
| 1a | Scaffold + empty SPA shell behind auth | HITL | — | 0 |
| 1b | Walking skeleton: upload → parse → see markdown | HITL | 1a | 0 + 1 |
| 2 | Page scoring + review split-pane | HITL | 1b | 2 |
| 3 | Remediation (cleanup / VLM) + canonical | AFK | 2 | 2 |
| 4 | Sectionize → Source Section tree (read-only) | AFK | 1b | 1 + 3 |
| 5 | Tree drag-review + graph approval | HITL | 4 | 3 |
| 6 | Classification + Explore (cross-document) | HITL | 4 | 4 |
| 7 | Wiki generation (tree → Wiki Documents) | AFK | 5, 6 | 5 |
| 8 | Inline editing (later) | AFK | 2 | 6 |

Dependency spine is mostly linear (it is a pipeline). Parallelism: **6** can proceed
off **4** alongside **5**; **8** floats off **2**.

---

## Verification

Every slice is verified against the dev site **`pdf.localhost`** (login
**Administrator / admin**), which has `frappe`, `wiki`, `wikify` installed. Run all
`bench` commands from the bench root
(`/Users/mdhussain/Frappe/benches/december-bench`). See [`../../CLAUDE.md`](../../CLAUDE.md)
for the environment.

A slice is **done** only when both its **Acceptance criteria** check boxes pass *and*
its **Verify** steps below reproduce them.

### Standing loop (per slice)

```bash
bench --site pdf.localhost migrate            # pick up DocType/schema changes
bench build --app wikify                       # (or vite dev) for frontend slices
bench start                                     # web + socketio + workers — required for jobs + realtime
```

1. **Headless first** — exercise the backend without the UI:
   `bench --site pdf.localhost execute <dotted.path>` or `bench --site pdf.localhost
   console`. Assert the rows/fields/status the slice should produce.
2. **Automated** — add/extend `FrappeTestCase` tests under
   `wikify/wikify/doctype/**/test_*.py` (or `wikify/tests/`); run
   `bench --site pdf.localhost run-tests --app wikify`. Cover the slice's job/API logic
   and the state transition it introduces.
3. **UI walkthrough** — at `/wikify` as Administrator, reproduce the slice's demo and
   confirm realtime (progress/log) where applicable. The `/verify` skill can drive the
   browser for this.
4. **Regression** — re-run the prior slice's demo to confirm the spine still works
   (each slice thickens the same skeleton).

Use a small fixture PDF (a few pages, ideally one text-heavy + one visual page) checked
into `scratch/` or uploaded ad hoc; reuse the POC's sample PDFs where possible.

---

## 1a — Scaffold + empty SPA shell behind auth

**Type:** HITL (scaffold-cloning decisions + first look at the app shell).
**Blocked by:** none.

### What to build
Adapt the gameplan frontend skeleton and stand up an empty, authenticated SPA at
`/wikify`. No DocTypes, no pipeline — just the shell everything mounts into.

- `wikify/frontend/` adapted from `apps/gameplan/frontend/` (frappe-ui
  `1.0.0-beta.10`): `main.js` (createApp + router + FrappeUI + initSocket),
  `router.js` (`createWebHistory(__FRONTEND_ROUTE__)` + `beforeEach` auth guard),
  `socket.js` (`initSocket`), `vite.config.js` (`frappeui({ frontendRoute: '/wikify' })`),
  a cookie-based reactive `session` store in `src/data/`.
- `wikify/www/wikify.html` (Jinja host + `<div id="app">` + boot injection) and
  `wikify/www/wikify.py` (`get_context()` auth gate + boot).
- `hooks.py`: `website_route_rules` → SPA, `app_icon_route = "/wikify"`.
- App shell: `FrappeUIProvider` + `Sidebar` + `<router-view>`, one empty
  **Imports** route. Follow the frappe-ui skill for layout/tokens (48px sticky
  header, `body-container`, semantic tokens only).
- Extra deps wired: `splitpanes`, `vuedraggable@^4`, `pdfjs-dist` (no CodeMirror —
  `CodeEditor` self-loads). Tailwind v3 + Vite 8; the `frappeui({ frontendRoute })`
  plugin handles proxy/boot/build (no manual `optimizeDeps.exclude`).

### Acceptance criteria
- [ ] Visiting `/wikify` unauthenticated redirects to login; authenticated renders the shell.
- [ ] App shell shows `Sidebar` + empty Imports route with correct header/tokens; dark mode via `[data-theme="dark"]` works.
- [ ] `bench build` / vite dev both serve the SPA; socket connects without error.

**Verify:** `bench build --app wikify` then `bench start`; open `/wikify` in a fresh/
incognito session (expect login redirect), log in as Administrator (expect the shell),
toggle dark mode, and confirm no socket errors in the console.

### Spec refs
[01-architecture](01-architecture.md#3-the-spa--wikifyfrontend) ·
[04-frontend-plan](04-frontend-plan.md#scaffold-phase-0)

---

## 1b — Walking skeleton: upload → parse → see markdown

**Type:** HITL (the spine-verification checkpoint — first time real data flows end-to-end).
**Blocked by:** 1a.

### What to build
The tracer bullet. Thinnest possible end-to-end path: upload a PDF and watch it
parse to plain markdown per page, with live progress. **No scoring, no remediation,
no sections, no LLM** — those are later slices.

- **DocTypes (minimal fields):** `Wikify Import`, `Source Document`, `Source Page`,
  `Import Log Entry` — only the fields this slice exercises (`status`,
  `stage_progress`, `stage_label`, `page_count`, `pdf`, `baseline_markdown`,
  `image`, log fields). `Source Section` / `Section Type` / `Wikify Settings` come later.
- **`engine/` seed:** port `pdf_utils.py` (render PNG → **File** doc) + a minimal
  pymupdf baseline parse; thin `engine/store.py` seam (`create_document`,
  `add_page`); `jobs/_util.py` (`publish_progress`, `log`).
- **API:** `wikify.api.imports.start_import(pdf_file_url, title)` → create Import
  (`Draft`→`Queued`) → `frappe.enqueue` parse job → return name.
- **Job:** `wikify.jobs.parse.run` — render+extract each page (PNG + baseline
  markdown), `publish_progress` per page, create `Source Document` + `Source Page`
  rows, `status=Review`, final progress.
- **Realtime:** `wikify_import_progress` + `wikify_import_log` channels.
- **UI:** Imports `ListView` (`useList`), **New Import** `Dialog` + `FileUploader`
  (default name from filename, editable), Import detail with Overview (streaming
  log) + raw per-page markdown.

### Acceptance criteria
- [ ] From the list, **New Import** → pick a PDF → progress bar animates and log streams live.
- [ ] Import lands in `Review` with one `Source Page` per page, each showing rendered PNG + baseline markdown.
- [ ] `bench execute wikify.engine.parse_pdf` (or equivalent) produces the rows headless (the spec's Phase-0 acceptance).
- [ ] Refetch reflects persisted `status`/`page_count` (not only realtime).

**Verify:** headless — `bench --site pdf.localhost execute wikify.engine.parse_pdf`
on a sample PDF, then in `console` assert one `Source Document` + N `Source Page` rows
with `image` File + `baseline_markdown`. UI — `bench start`, New Import → watch the
progress bar + streaming log, land in `Review`, eyeball per-page markdown. Reload to
confirm `status`/`page_count` persist.

### Spec refs
[03-backend-plan Phase 0–1](03-backend-plan.md#phase-0--foundations) ·
[04-frontend-plan Phase 1](04-frontend-plan.md#phase-1--imports-list--new-import--progress) ·
[02-data-model](02-data-model.md)

---

## 2 — Page scoring + review split-pane

**Type:** HITL (the product's signature review screen — design/UX review).
**Blocked by:** 1b.

### What to build
Add the scoring pipeline and the page-review experience.

- **Engine:** port `engine/verify/` (harness, deterministic, judge) + `engine/llm.py`
  (OpenRouter client with per-call cost/latency/token metrics) + **`Wikify Settings`**
  (Single — model ids, thresholds, key).
- **DocType:** add baseline score fields (`text_recall`, `extra_ratio`,
  `table_score`, `judge_score`, `composite`) + `verdict` + `notes` to `Source Page`;
  parse job now scores each page and logs cost.
- **UI** (`PageReview.vue`, `splitpanes`): left = thumbnail list with verdict badges +
  text/visual chip + **Flagged** filter (default Flagged); right = `Tabs` PDF /
  Snapshot / **Markdown** (`CodeEditor`, `language="markdown"`, read-only) + a scores
  strip (recall/extra/table/judge/composite + verdict, honest line for visual pages).

### Acceptance criteria
- [ ] Each page shows scores + a `pass/escalate/review` verdict; per-stage cost visible in Overview (from log meta).
- [ ] Split-pane: flip PDF ↔ snapshot ↔ markdown; Flagged filter narrows the list.
- [ ] `Wikify Settings` drives model ids/thresholds without code change.

**Verify:** set the OpenRouter key in `Wikify Settings`; re-parse a sample PDF and in
`console` assert score fields + `verdict` populated on `Source Page` and per-stage cost
on `Import Log Entry.meta`. UI — open the Pages tab, flip PDF↔Snapshot↔Markdown, toggle
the Flagged filter, confirm the scores strip. Change a threshold in Settings and confirm
verdicts shift on re-parse (no code change).

### Spec refs
[03-backend-plan Phase 1 (scoring) + LLM client](03-backend-plan.md#llm-client) ·
[04-frontend-plan Phase 2](04-frontend-plan.md#phase-2--page-review-split-pane)

---

## 3 — Remediation (cleanup / VLM) + canonical

**Type:** AFK.
**Blocked by:** 2.

### What to build
- **Engine:** port `engine/loader/{cleanup,cleanup_llm,table_stitch}` + the VLM path.
- **DocType:** `remediation_*` + `canonical_*` fields on `Source Page`.
- **API/Job:** `trigger_remediation(import_name, scope)` → `wikify.jobs.remediate.run`
  — per-page router (vlm for visual / low recall, else cleanup), re-score, adopt by
  the POC rule, recompute canonical, stitch cross-page tables. Respect the `adopted`
  flag when rebuilding (POC gotcha).
- **UI:** before↔after view in the review pane (baseline vs remediation + score delta
  + adopted flag); "Remediate flagged" / "Remediate all" actions with progress.

### Acceptance criteria
- [ ] Flagged pages improve or drop after remediation; before↔after + adopted flag visible.
- [ ] Mermaid-bearing VLM output is preserved through canonical selection.
- [ ] `status` cycles `Remediating ⇄ Review`; canonical mean updates.

**Verify:** on a parsed doc with flagged pages, "Remediate flagged"; in `console`
assert `remediation_*`/`canonical_*` written and `remediation_adopted` set per the rule.
UI — before↔after + adopted flag visible; a visual page's mermaid survives into
canonical; flagged count drops; `Source Document.mean_score` rises.

### Spec refs
[03-backend-plan Phase 2](03-backend-plan.md#phase-2--page-review--remediation)

---

## 4 — Sectionize → Source Section tree (read-only)

**Type:** AFK.
**Blocked by:** 1b (run after 3 so it reads canonical markdown).

### What to build
- **Engine:** port `engine/loader/{sectionizer,toc}` (heading-validation + numbering +
  ToC precedence).
- **DocType:** `Source Section` as a NestedSet tree (`is_tree`,
  `parent_source_section`); set `hierarchy_path`, `level`, `page_start/end`,
  `sort_order`. Build the tree during the parse job over canonical markdown.
- **UI:** read-only `Tree` (frappe-ui display component) in the **Tree** tab with page
  ranges per node.

### Acceptance criteria
- [ ] A parsed doc shows a correct nested section tree with page ranges and hierarchy paths.
- [ ] Tree rebuild after remediation respects adopted markdown (no revert to empty baseline).

**Verify:** after parse, in `console` walk `Source Section` for the doc and assert
correct `parent_source_section`, `level`, `hierarchy_path`, and `page_start..end` vs the
PDF's outline. UI — Tree tab renders the nested structure with page ranges. Re-run
remediation and confirm the rebuilt tree still reflects adopted (not empty) markdown.

### Spec refs
[03-backend-plan Phase 1 (sectionize)](03-backend-plan.md#phase-1--imports-list--parse--progress) ·
[02-data-model Source Section](02-data-model.md)

---

## 5 — Tree drag-review + graph approval

**Type:** HITL (drag interaction design review).
**Blocked by:** 4.

### What to build
- **UI:** `SectionTree.vue` via `vuedraggable`, adapted from wiki's
  `NestedDraggable.vue` — arbitrary-depth reparent + reorder, drag handle, debounced
  saves; inline rename, include-in-wiki toggle, delete.
- **API:** `reorder_section(name, new_parent, new_index, siblings)` (NestedSet rebuild
  only on parent change; recompute `level`/`hierarchy_path` for moved subtree),
  `rename_section`, `toggle_include`, `delete_section` (with children).
- **Approval gate:** `build_graph(import_name)` → `Source Document.status=Graphed`,
  `Wikify Import.status=Graphed`; unlocks Explore + Wiki tabs.

### Acceptance criteria
- [ ] Drag-reparent/reorder persists and survives reload.
- [ ] Rename / include-toggle / delete persist.
- [ ] **Approve & Build Graph** advances state and enables Explore + Wiki.

**Verify:** UI — drag a section to a new parent and reorder siblings, **reload**, and
confirm it stuck; rename / toggle include / delete persist. In `console` confirm
NestedSet `lft`/`rgt` and `hierarchy_path`/`level` recomputed for the moved subtree.
Click **Approve & Build Graph** → `status=Graphed` and Explore/Wiki tabs enable.

### Spec refs
[03-backend-plan Phase 3](03-backend-plan.md#phase-3--tree-review--graph-approval) ·
[04-frontend-plan Phase 3](04-frontend-plan.md#phase-3--tree-review)

---

## 6 — Classification + Explore (cross-document)

**Type:** HITL (the headline screen — design review).
**Blocked by:** 4 (+ 5 for the approval gate before Explore unlocks).

### What to build
- **Seed:** `Section Type` master with the 11 POC types (fixtures / `after_install`).
- **Engine/Job:** port `engine/loader/classifier`; default-eager classify in parse +
  a `reclassify` job after restructuring (`ThreadPoolExecutor`).
- **DocType:** `section_type` link on `Source Section` (indexed).
- **UI:** per-doc **Explore** tab (type filter chips + counts incl. `other`) and the
  headline **global Explore** (`/wikify/explore`) — every section of a chosen type
  across all Source Documents, grouped by document with provenance.

### Acceptance criteria
- [ ] Sections carry a `section_type`; reclassify re-labels after tree edits.
- [ ] "All job descriptions across all PDFs" answered by a metadata filter (not fuzzy search).
- [ ] Type chips show correct counts including the `other` catch-all.

**Verify:** confirm the 11 `Section Type` rows seed after `migrate`/install. After
classify, in `console` assert `section_type` set on sections. UI — import **two** PDFs,
graph both, then on `/wikify/explore` pick a type and confirm matching sections appear
**across both documents** with provenance; chip counts (incl. `other`) match the query.

### Spec refs
[03-backend-plan Phase 4](03-backend-plan.md#phase-4--explore-typed-cross-document) ·
[04-frontend-plan Phase 4](04-frontend-plan.md#phase-4--explore)

---

## 7 — Wiki generation (tree → Wiki Documents + link rewrite)

**Type:** AFK (well-specified mapping; payoff demo).
**Blocked by:** 5, 6.

### What to build
- **Engine:** port `engine/loader/wiki` (`_PAGEREF_RE` + `slug_for_page`).
- **API/Job:** `preview_wiki(import_name)` (projected tree, no writes) +
  `generate_wiki(import_name, wiki_space|new_space)` → `wikify.jobs.generate.run`:
  - Pass 1 — structure: resolve/create Wiki Space, per-document root group, walk the
    approved tree depth-first → upsert `Wiki Document` rows
    (`frappe.new_doc("Wiki Document").insert(ignore_permissions=True)`,
    `is_group`/content/parent/sort_order); store `Source Section.wiki_document`.
    *Structure-preserving 1:1 mirror — not the POC's L1 collapse.*
  - Pass 2 — links: rewrite internal "page N" refs → wiki routes; leave external
    citations as text.
- **UI:** space selector (existing or new), `Tree` preview, Generate with progress,
  per-section "view page" links; idempotent **Regenerate**.

### Acceptance criteria
- [ ] Approved tree appears as a matching Wiki Space sidebar tree; pages render markdown (mermaid included).
- [ ] Internal "page N" references are clickable wiki links; external citations remain plain text.
- [ ] Regeneration after a tree edit updates in place (no duplicates; removed sections deleted).

**Verify:** pick/create a Wiki Space, Preview, Generate. In `console` assert
`Wiki Document` rows mirror the tree (`parent_wiki_document`, `is_group`, `sort_order`)
and `Source Section.wiki_document` back-links are set. Browse the Wiki Space sidebar —
markdown + mermaid render; click an internal "page N" link and land on the right page;
external citations stay plain text. Edit the tree, **Regenerate**, and confirm pages
update in place (no duplicate routes; excluded sections removed).

### Spec refs
[05-wiki-generation](05-wiki-generation.md) ·
[03-backend-plan Phase 5](03-backend-plan.md#phase-5--wiki-generation)

---

## 8 — Inline editing (later)

**Type:** AFK.
**Blocked by:** 2.

### What to build
- `save_page_edit(source_page, markdown)` → `edited_markdown` / `is_edited` (overrides
  canonical); editable `CodeEditor` + diff vs canonical; re-derive sections from edits.

### Acceptance criteria
- [ ] Editing a page's markdown persists and overrides canonical downstream.
- [ ] Diff against canonical + edit indicator shown.

**Verify:** edit a page's markdown in the UI; in `console` confirm `edited_markdown` +
`is_edited` set and that downstream reads (sectionize/wiki) prefer it over canonical.
Confirm the diff vs canonical + edit indicator render.

### Spec refs
[02-data-model Source Page (Phase 6 fields)](02-data-model.md) ·
[04-frontend-plan Phase 2 (Edits tab)](04-frontend-plan.md#phase-2--page-review-split-pane)
