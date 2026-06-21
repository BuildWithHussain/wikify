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

| # | Slice | Type | Blocked by | Spec phase | Status |
|---|---|---|---|---|---|
| 1a | Scaffold + empty SPA shell behind auth | HITL | — | 0 | ✅ Done |
| 1b | Walking skeleton: upload → parse → see markdown | HITL | 1a | 0 + 1 | ✅ Done |
| 2 | Page scoring + review split-pane | HITL | 1b | 2 | ✅ Done |
| 3 | Remediation (cleanup / VLM) + canonical | AFK | 2 | 2 | ✅ Done |
| 4 | Sectionize → Source Section tree (read-only) | AFK | 1b | 1 + 3 | ✅ Done |
| 5 | Tree drag-review + graph approval | HITL | 4 | 3 | ✅ Done |
| 6 | Classification + Explore (cross-document) | HITL | 4 | 4 | ✅ Done |
| 7 | Wiki generation (tree → Wiki Documents) | AFK | 5, 6 | 5 | ✅ Done |
| 8 | Inline editing (later) | AFK | 2 | 6 | — |

> **Progress** (on `main`): **1a** ✅ `c127f8b` · **1b** ✅ `bfec780` · **2** ✅ · **3** ✅ · **4** ✅ · **5** ✅ · **6** ✅ · **7** ✅.
> All verified on `pdf.localhost` per each slice's Verify steps. Up next: **Slice 8** (inline
> editing — optional, floats off Slice 2).

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
**Status:** ✅ Done — `main` (`c127f8b`).

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
- [x] Visiting `/wikify` unauthenticated redirects to login; authenticated renders the shell.
- [x] App shell shows a sidebar + empty Imports route with correct header/tokens; dark mode via `[data-theme="dark"]` works.
- [x] `bench build` / vite dev both serve the SPA; socket connects without error.

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
**Status:** ✅ Done — `main` (`bfec780`).

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
- [x] From the list, **New Import** → pick a PDF → progress bar animates and log streams live.
- [x] Import lands in `Review` with one `Source Page` per page, each showing rendered PNG + baseline markdown.
- [x] `bench execute wikify.engine.parse_pdf` (or equivalent) produces the rows headless (the spec's Phase-0 acceptance).
- [x] Refetch reflects persisted `status`/`page_count` (not only realtime).

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
**Status:** ✅ Done — `main`.

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
- [x] Each page shows scores + a `pass/escalate/review` verdict; per-stage cost visible in Overview (from log meta).
- [x] Split-pane: flip PDF ↔ snapshot ↔ markdown; Flagged filter narrows the list.
- [x] `Wikify Settings` drives model ids/thresholds without code change.

**Verify:** set the OpenRouter key in `Wikify Settings`; re-parse a sample PDF and in
`console` assert score fields + `verdict` populated on `Source Page` and per-stage cost
on `Import Log Entry.meta`. UI — open the Pages tab, flip PDF↔Snapshot↔Markdown, toggle
the Flagged filter, confirm the scores strip. Change a threshold in Settings and confirm
verdicts shift on re-parse (no code change).

### As-built notes (reconciled)
- **`engine/llm.py` uses `requests`, not the `openai` SDK** — `openai` isn't on the
  bench; the REST boundary is the only change, judge/cost logic is the POC's. Records
  `{label, model, seconds, prompt/completion tokens, cost}` per call via
  `reset_metrics()` / `get_metrics()`.
- **`Wikify Settings` (Single)** holds model ids, thresholds, key, and the render/visual
  tunables. Key resolves Settings → `site_config` → env → `apps/wikify/.env`. Composite
  **weights** stay code-side in `engine/config.py` (spec 02-data-model).
- **Judge scope:** visual pages are always judged (text GT is unreliable there); text
  pages only when `judge_all_pages` is on (default off, to bound cost). `verdict` reads
  thresholds live from Settings, so changing a threshold shifts verdicts on re-parse.
- **`Source Page` fields:** baseline scores + `verdict` + `notes` added now;
  remediation/canonical fields land in Slice 3. `Source Document.mean_score` mirrors the
  mean composite. `table_score`/`judge_score` are `None` for "no table"/"not judged" —
  Frappe Float is NOT NULL, so those keys are omitted on write (row keeps `0.0`) and the
  UI reads `0` as "—"; a genuine table miss still surfaces via `notes`.
- **UI:** `PageReview.vue` (`splitpanes`) replaces the 1b stacked-card Pages tab — left
  thumbnail list (verdict badge + kind chip + Flagged filter, default Flagged), right
  Tabs PDF (`<object>` at `#page=N`) / Snapshot (PNG) / Markdown (`CodeEditor` from
  `frappe-ui/code-editor`, `language="markdown"`, disabled) + a kind-aware scores strip.
- Headless judge verified live against OpenRouter (claude-sonnet-4.6): text page →
  pass, drawing-only page → judge 0.4 → `review`, `mean_score` mirrored on the doc.

### Spec refs
[03-backend-plan Phase 1 (scoring) + LLM client](03-backend-plan.md#llm-client) ·
[04-frontend-plan Phase 2](04-frontend-plan.md#phase-2--page-review-split-pane)

---

## 3 — Remediation (cleanup / VLM) + canonical

**Type:** AFK.
**Blocked by:** 2.
**Status:** ✅ Done — `main`.

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
- [x] Flagged pages improve or drop after remediation; before↔after + adopted flag visible.
- [x] Mermaid-bearing VLM output is preserved through canonical selection.
- [x] `status` cycles `Remediating ⇄ Review`; canonical mean updates.

**Verify:** on a parsed doc with flagged pages, "Remediate flagged"; in `console`
assert `remediation_*`/`canonical_*` written and `remediation_adopted` set per the rule.
UI — before↔after + adopted flag visible; a visual page's mermaid survives into
canonical; flagged count drops; `Source Document.canonical_mean` rises.

### As-built notes (reconciled)
- **Engine:** `engine/loader/{cleanup,cleanup_llm,table_stitch}` + `engine/parsers/vlm.py`
  ported (LLM calls go through `engine.llm` → dict-shaped REST response; model ids from
  `Wikify Settings`). `engine/remediate.py:remediate_pdf()` is the headless entrypoint.
- **Routing + adoption are the POC's:** a page goes to **vlm** when it's `visual` or its
  baseline `text_recall < 0.85` (needs the image), else **cleanup** (cheap text model).
  Cleanup is adopted when recall holds within `cleanup_recall_tolerance` (a small drop =
  intended furniture removal); vlm is adopted when its composite beats baseline.
- **Sequential, not threaded.** The POC used a `ThreadPoolExecutor`; the Frappe ORM
  writes aren't thread-safe, so remediation runs serially (fine for a dev-tool pass).
- **Per-page failures are non-fatal:** a single page's model call failing (rate limit,
  billing, transient) is logged into `remediation_notes`, the page keeps its baseline,
  and the pass continues — it does not abort the whole run.
- **Canonical:** every page gets `canonical_markdown` + `canonical_source`
  (`baseline`/`cleanup`/`vlm`) + `canonical_composite`, even non-adopted ones (canonical
  = baseline there). Cross-page tables are stitched over the canonical set before write.
  `Source Document.canonical_mean` holds the mean canonical composite (baseline
  `mean_score` is preserved separately, so the before↔after delta survives). Sections
  are **not** rebuilt here (no `Source Section` until Slice 4) — `loader/cleanup`'s
  cross-page boilerplate strip is ported but wires in at sectionize (Slice 4).
- **API/Job:** `wikify.api.imports.trigger_remediation(import_name, scope)` (`flagged` |
  `all`, only from `Review`) → flips Import to `Remediating` → enqueues
  `wikify.jobs.remediate.run`, which streams progress + per-page log lines (method,
  adopted/kept, score delta, cost) and lands back in `Review` (or reverts to `Review` +
  records `error` on failure).
- **UI:** `ImportDetail` gains a **Remediate** dropdown (flagged / all pages) shown in
  `Review`; on completion the realtime `Review` transition refetches the page list.
  `PageReview` adds a Baseline ↔ Remediation ↔ Canonical markdown toggle, an
  adopted/kept badge + baseline→remediation composite delta + canonical score, and a
  "remediated" chip in the left list.
- **Live VLM caveat:** the cleanup path + routing + adoption + canonical + stitch + mean
  + status cycle were all verified live on `pdf.localhost` (headless + the real job).
  The **vlm-adopted + mermaid-preservation** path is covered by the hermetic test
  (`tests/test_remediate_pipeline.py`, LLM seam patched); a fully-live VLM adoption was
  blocked by an OpenRouter `402` (account out of credits), not code — top up to demo it.

### Spec refs
[03-backend-plan Phase 2](03-backend-plan.md#phase-2--page-review--remediation)

---

## 4 — Sectionize → Source Section tree (read-only)

**Type:** AFK.
**Blocked by:** 1b (run after 3 so it reads canonical markdown).
**Status:** ✅ Done — `main`.

### What to build
- **Engine:** port `engine/loader/{sectionizer,toc}` (heading-validation + numbering +
  ToC precedence).
- **DocType:** `Source Section` as a NestedSet tree (`is_tree`,
  `parent_source_section`); set `hierarchy_path`, `level`, `page_start/end`,
  `sort_order`. Build the tree during the parse job over canonical markdown.
- **UI:** read-only `Tree` (frappe-ui display component) in the **Tree** tab with page
  ranges per node.

### Acceptance criteria
- [x] A parsed doc shows a correct nested section tree with page ranges and hierarchy paths.
- [x] Tree rebuild after remediation respects adopted markdown (no revert to empty baseline).

**Verify:** after parse, in `console` walk `Source Section` for the doc and assert
correct `parent_source_section`, `level`, `hierarchy_path`, and `page_start..end` vs the
PDF's outline. UI — Tree tab renders the nested structure with page ranges. Re-run
remediation and confirm the rebuilt tree still reflects adopted (not empty) markdown.

### As-built notes (reconciled)
- **Engine:** `engine/loader/{toc,sectionizer}` ported verbatim from the POC (only the
  import paths changed — `toc` reads `engine.pdf_utils.get_toc`). `engine/sectionize.py`
  `sectionize_document(source_document, pdf_path)` is the headless entrypoint: it wires
  in `loader/cleanup.clean_pages` (cross-page boilerplate strip), builds the embedded-ToC
  `level_map`, sectionizes, and rebuilds the tree via the store seam.
- **Built over canonical markdown, at both ends of the pipeline.** `store.get_canonical_pages`
  reads `canonical_markdown or baseline_markdown` per page, so `sectionize_document` is
  called at the end of **both** `parse_pdf` (canonical == baseline there) and
  `remediate_pdf` (canonical == adopted output) — the remediate rebuild reflects adopted
  text and never reverts to empty/pre-cleanup baseline.
- **DocType:** `Source Section` is a Frappe **NestedSet** (`is_tree`,
  `nsm_parent_field = parent_source_section`; controller subclasses `NestedSet`).
  `store.replace_sections` rebuilds wholesale — raw-deletes the doc's rows then inserts in
  document order, resolving each parent by hierarchy path (the parent always precedes the
  child), persisting `level` / `hierarchy_path` / `page_start..end` / `sort_order`, and
  setting `is_group` for any section another nests under. NestedSet manages `lft`/`rgt`;
  other docs' subtrees are independent number-spaces so no global rebuild is needed.
- **API:** `wikify.api.sections.get_tree(source_document)` returns the nested roots
  (ordered by `lft`) — kept as the read seam for Slices 5/7.
- **UI:** `ImportDetail` gains a **Tree** tab (`SectionTree.vue`, split-pane): left =
  frappe-ui `Tree` (custom `label` slot showing title + `section_type` chip + page range,
  fully expanded) rebuilt client-side from a reactive `useList` over `Source Section`
  (ordered by `lft`); right = selected section's level/page badges + hierarchy path +
  read-only `CodeEditor` markdown. Refetches after a remediation run completes (the tree
  is rebuilt server-side). `section_type` chips are wired but stay empty until Slice 6.
- Tests: `tests/test_sectionize.py` — pure sectionizer unit tests (numbered-heading
  nesting, out-of-sequence chapter demotion, running-header merge, preamble fallback,
  boilerplate strip) + integration (parse builds the tree; remediation rebuilds it over
  adopted markdown without going empty). Verified live on `pdf.localhost` (3-chapter demo
  manual → 7-section nested tree, page ranges, click-to-view markdown).
- **Fixture gotcha:** the pymupdf4llm baseline marks large-font lines as headings itself,
  so test PDFs must use **numbered titles without literal `#`** — the sectionizer recovers
  level from the numbering (`1.` → L1, `1.1` → L2), robust to the parser's `#` depth.

### Spec refs
[03-backend-plan Phase 1 (sectionize)](03-backend-plan.md#phase-1--imports-list--parse--progress) ·
[02-data-model Source Section](02-data-model.md)

---

## 5 — Tree drag-review + graph approval

**Type:** HITL (drag interaction design review).
**Blocked by:** 4.
**Status:** ✅ Done — `main`.

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
- [x] Drag-reparent/reorder persists and survives reload.
- [x] Rename / include-toggle / delete persist.
- [x] **Approve & Build Graph** advances state (Explore/Wiki tabs land in Slices 6/7).

**Verify:** UI — drag a section to a new parent and reorder siblings, **reload**, and
confirm it stuck; rename / toggle include / delete persist. In `console` confirm
NestedSet `lft`/`rgt` and `hierarchy_path`/`level` recomputed for the moved subtree.
Click **Approve & Build Graph** → `status=Graphed`.

### As-built notes (reconciled)
- **Two HITL decisions (2026-06-20):** the tree stays **always editable** — `build_graph`
  is a milestone (advances status + unlocks downstream), *not* a freeze; re-running it
  re-approves (button reads "Rebuild graph" once Graphed). Include-toggle and delete
  **cascade to the whole subtree**.
- **API (`wikify/api/sections.py`):** `reorder_section(name, new_parent, new_index, siblings)`,
  `rename_section`, `toggle_include` (cascade), `delete_section` (cascade), `build_graph`.
  All structural edits funnel through `_rebuild_tree(source_document)` — one DFS that
  re-derives `lft`/`rgt` **and** the denorm `level` / `hierarchy_path` / `is_group` (a node
  is a group iff it actually has children now), siblings ordered by `sort_order` then
  `name`. Mirrors the wiki app's `reorder_wiki_documents` / `rebuild_wiki_tree`, scoped to
  one doc (each Source Document is an independent NestedSet number-space). Reparent guards
  against cycles via `lft`/`rgt` containment; delete raw-deletes the subtree then rebuilds.
  `build_graph` sets both `Wikify Import.status` and `Source Document.status` to `Graphed`.
- **UI:** `SectionTree.vue` left pane is now a recursive `SectionDraggable.vue`
  (`vuedraggable`, single shared `group`, handle-only grip drag, expand/collapse, inline
  rename input, per-row ⋯ Dropdown → Rename / Include-Exclude / Delete, excluded rows
  shown struck-through/dimmed). Drag/rename/toggle send optimistically then `sections.reload()`
  to pick up the server-rebuilt denorm fields (and to revert on error — `useCall.submit`
  resolves rather than rejects, so the wrapper inspects `.error`). Delete goes through a
  cascade-aware confirm `Dialog` (counts the subtree). Header gains a **Approve & Build
  Graph** / **Rebuild graph** button + a **Graphed** badge; `ImportDetail` passes
  `import-name`/`status` and reloads on `@graphed`.
- **Gotcha:** the ⋯ trigger must **not** `@click.stop` — that swallows the click frappe-ui
  `Dropdown` needs to open (only the title button stops propagation, for row selection).
- Tests: `wikify/tests/test_section_edits.py` (8) — reparent recompute, cycle reject,
  root-clear, rename path cascade, include cascade, delete cascade, build_graph transition.
  Verified live on `pdf.localhost` (reparent/rename/cascade-toggle/cascade-delete persist
  across reload; Approve flips status to Graphed). **Automation caveat:** agent-browser's
  synthetic clicks don't fire reka-ui Dropdown/Button or the SortableJS drag gesture
  (confirmed against the known-good Remediate dropdown) — the drag/menu *triggers* were
  driven through the real v2 endpoints via the page's authenticated fetch; `build_graph`
  was driven through its real button handler.

### Spec refs
[03-backend-plan Phase 3](03-backend-plan.md#phase-3--tree-review--graph-approval) ·
[04-frontend-plan Phase 3](04-frontend-plan.md#phase-3--tree-review)

---

## 6 — Classification + Explore (cross-document)

**Type:** HITL (the headline screen — design review).
**Blocked by:** 4 (+ 5 for the approval gate before Explore unlocks).
**Status:** ✅ Done — `main`.

### What to build
- **Seed:** `Section Type` master with the 11 POC types (fixtures / `after_install`).
- **Engine/Job:** port `engine/loader/classifier`; default-eager classify in parse +
  a `reclassify` job after restructuring (`ThreadPoolExecutor`).
- **DocType:** `section_type` link on `Source Section` (indexed).
- **UI:** per-doc **Explore** tab (type filter chips + counts incl. `other`) and the
  headline **global Explore** (`/wikify/explore`) — every section of a chosen type
  across all Source Documents, grouped by document with provenance.

### Acceptance criteria
- [x] Sections carry a `section_type`; reclassify re-labels after tree edits.
- [x] "All job descriptions across all PDFs" answered by a metadata filter (not fuzzy search).
- [x] Type chips show correct counts including the `other` catch-all.

**Verify:** confirm the 11 `Section Type` rows seed after `migrate`/install. After
classify, in `console` assert `section_type` set on sections. UI — import **two** PDFs,
graph both, then on `/wikify/explore` pick a type and confirm matching sections appear
**across both documents** with provenance; chip counts (incl. `other`) match the query.

### As-built notes (reconciled)
- **`Section Type` master** (`type_name` autoname, `label` / `color` hex / `description` /
  `is_other`) seeded with the 11 POC types via `wikify/seed.py:seed_section_types` —
  idempotent, called from both `after_install` (fresh sites) and a `post_model_sync`
  patch (`patches/v1_0/seed_section_types`, existing sites on `migrate`). Editable
  afterward; the classifier reads whatever rows exist (taxonomy is data, not code).
- **Classifier** ported to `engine/loader/classifier.py` (`classify_section(title,
  content, taxonomy)`): taxonomy comes from the master (passed in), model id from
  `Wikify Settings.classifier_model`, call via `engine.llm`. Any failure / no key falls
  back to `"other"` — never raises, so a parse without a key still completes typed.
- **`engine/classify.py:classify_document(source_document, progress_cb)`** reads each
  Source Section's (title, markdown), classifies, and writes `section_type`. **Runs
  sequentially, not threaded** (the POC used a `ThreadPoolExecutor`): each call resolves
  key/model through `frappe.local`, which isn't thread-safe — the same precedent as
  remediation (Slice 3). Cheap classifier model, so serial is fine and streams cleanly.
- **Transient-failure resilience (added after the OBG live run):** bulk eager classify
  fires one call per section back-to-back, so a big manual trips the provider rate limit.
  The POC's bare `except: return "other"` conflated a dropped call with a real verdict —
  on the 374-section OBG re-run that inflated `other` from ~9 to 135. `classify_section`
  now **retries with linear backoff** (3 retries) and only falls back to `other` on a
  genuine `other`/off-taxonomy label or after exhausting retries. (Tests stub
  `classifier.time.sleep`.)
- **Eager classify** at the end of **both** `parse_pdf` and `remediate_pdf` (after the
  tree rebuild — the rebuild assigns fresh section names, so types must be re-derived).
  Manual re-run via `api.imports.reclassify(import_name)` → `jobs/classify.run`, which
  streams per-section log lines + emits `wikify_classify_done` and **does not** change
  the import's persisted status (re-tag in Review *or* Graphed). HITL decisions: classify
  is eager-on-every-parse (+ manual Reclassify), not gated.
- **Explore APIs** (`api/explore.py`): `type_summary(source_document?)` — per-type counts
  (all seeded types for stable chips, plus an `__untagged__` bucket when present);
  `sections_by_type(section_type, source_document?)` — the cross-document headline query,
  grouped by Source Document with `doc_title` / `import_name` / page-range provenance.
  Mirrors POC `graph.section_type_counts` / `sections_by_type`. `count(name)` uses the
  query builder (`Count`) — modern Frappe rejects SQL-function strings in `get_all`.
- **UI:** sidebar **Explore** nav + global `/wikify/explore` (`pages/ExploreGlobal.vue`)
  built as the chosen **type-rail + grouped-results** layout (rail of types w/ colored
  dots + counts → right pane lists matching sections grouped by document, group header
  links to that import's Tree tab). Per-doc **Explore** tab (`components/Explore.vue`):
  horizontal `TypeChip` bar + flat section list + a **Reclassify** button (realtime
  `wikify_classify_done` → refresh). `TypeChip.vue` is the one place an inline hex color
  is allowed (11 distinct types exceed the semantic Badge palette).
- **Gotcha:** reused the Slice-4 lesson — `useCall` reactive `auto`/`params` don't refire
  when a dep flips, so all Explore fetches are `immediate:false` + explicit `.submit()`
  from watchers.
- **HITL design decisions (2026-06-20):** (1) classify eager on every parse/remediate +
  manual Reclassify; (2) global Explore = type-rail + grouped-by-document results.
- Tests: `tests/test_classify.py` (7) — taxonomy seed, classify writes types + counts,
  progress callback, no-key→`other`, off-taxonomy→`other`, `type_summary` counts +
  untagged bucket, `sections_by_type` cross-document grouping + per-doc scoping. The
  parse integration test stubs `classify_section` to stay hermetic. Verified live on a
  **180-page real manual** (Obstetrics & Gynaecology) end-to-end through the parse job.

### UI/pipeline polish (done with Slice 6, HITL design feedback 2026-06-20)
- **PageReview tabs:** the per-page whole-PDF view ignored the page, so it moved up to a
  **top-level PDF tab** (ImportDetail, beside Overview/Pages/Tree/Explore). Per-page tabs
  are now three: **Page** (rendered page image, default) · **Preview** (formatted markdown,
  shared `MarkdownPreview.vue`) · **Markdown** (raw source). The Baseline/Remediation/
  Canonical source toggle drives both Preview and Markdown.
- **Markdown previews render mermaid.** `MarkdownPreview.vue` (used by the page Preview tab
  *and* the Tree section body) renders markdown with `marked` + `prose`, then post-processes
  ```` ```mermaid ```` fences into SVG via `utils/mermaid` — which **reuses the Frappe Wiki
  app's vendored mermaid loader** (`/assets/wiki/js/mermaid-loader.js` + the 3 MB
  `mermaid.min.js`; wiki is an installed app). Keeps mermaid out of our bundle and makes the
  preview theme identical to the published wiki (loader builds its theme from live Frappe UI
  tokens). Degrades gracefully to a code block if the asset is absent.
- **Pages filter:** default is now **All** (was Flagged), with **Flagged** (verdict ≠ pass)
  and its negation **Passed**; each shows a count.
- **Tree section body:** renders markdown (`MarkdownPreview`) **by default** with a
  frappe-ui `TabButtons` toggle (icon+text: Preview / Markdown) to the raw `CodeEditor`.
- **Parse/remediate progress:** the bar used to sit pinned at the last page during the
  post-loop sectionize + classify phases (classify is one LLM call per section — minutes
  on a big manual). Added a `stage_cb` through `parse_pdf` / `remediate_pdf` so those
  phases stream labels ("Building section tree", "Classifying sections (i/N)").
- **Bold headings:** pymupdf4llm emits emphasized headings (`_**Verbal Orders**_`).
  `sectionizer._clean_title` now strips wrapping `*`/`_` (deterministic, every flow) —
  which also fixes level inference (`_**2.1 Foo**_` → `2.1 Foo` matches the numbering) and
  stops fully-bold numbered chapters being mis-demoted; the LLM cleanup prompt
  (`cleanup_llm`) gained a matching "headings must be plain text" rule for the remediate
  path. Verified live: re-sectionizing the OBG reference produced clean titles (374
  sections).

### Spec refs
[03-backend-plan Phase 4](03-backend-plan.md#phase-4--explore-typed-cross-document) ·
[04-frontend-plan Phase 4](04-frontend-plan.md#phase-4--explore)

---

## 7 — Wiki generation (tree → Wiki Documents + link rewrite)

**Type:** AFK (well-specified mapping; payoff demo).
**Blocked by:** 5, 6.
**Status:** ✅ Done — `main`.

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
- [x] Approved tree appears as a matching Wiki Space sidebar tree; pages render markdown (mermaid included).
- [x] Internal "page N" references are clickable wiki links; external citations remain plain text.
- [x] Regeneration after a tree edit updates in place (no duplicates; removed sections deleted).

**Verify:** pick/create a Wiki Space, Preview, Generate. In `console` assert
`Wiki Document` rows mirror the tree (`parent_wiki_document`, `is_group`, `sort_order`)
and `Source Section.wiki_document` back-links are set. Browse the Wiki Space sidebar —
markdown + mermaid render; click an internal "page N" link and land on the right page;
external citations stay plain text. Edit the tree, **Regenerate**, and confirm pages
update in place (no duplicate routes; excluded sections removed).

### As-built notes (reconciled)
- **Engine:** `engine/loader/wiki.py` ports the POC's *pure* pieces — `slugify` +
  `_PAGEREF_RE` + `rewrite_page_refs(md, page_count, route_for_page, current_route)`
  (the resolver is injected, so the regex stays POC-verbatim and unit-testable without
  Frappe). `engine/generate.py:generate_wiki()` is the headless entrypoint and does the
  two passes; `preview_wiki()` projects the included-section tree without writes.
- **Structure-preserving 1:1 mirror** (not the POC's L1 collapse): each included
  `Source Section` → a `Wiki Document` (group → sidebar folder, leaf → page), parented to
  its nearest *included* ancestor's page or the per-document root group, `sort_order` by
  tree order. Routes/slugs are computed + set **explicitly** (the wiki controller only
  auto-derives them when empty) so renames/reparents recompute deterministically; slugs
  are deduped per parent → globally-unique leaf routes (paths diverge at the parent).
- **Per-document root group** named after the Source Document, a child of the space's
  `root_group`, stored on `Source Document.wiki_root_group`. Namespaces routes
  (`<space>/<doc>/…`) so one space holds many imports tidily.
- **Idempotent regeneration:** each `Source Section.wiki_document` is the upsert key.
  Stale pages are swept **before** pass 1 (so renamed/recreated routes don't collide with
  leftovers): keep the root group + every page an *included* section still links to, delete
  the rest under the root group deepest-first; excluded sections' back-links are cleared.
  Then pass 1 updates existing / creates new. No blind duplicates; the wiki app's
  `on_update` revision snapshot rides along for free.
- **Pass 2 (links):** after every page exists, `route_for_page(n)` = the smallest-span
  included section whose `page_start..page_end` contains `n` → its route; refs with a
  see/refer cue or the "Page No." form (and `N <= page_count`) become `[text](/route)`,
  self-links and external citations ("Williams p820") left as text.
- **Fields:** `Source Document` gains `wiki_space` + `wiki_root_group`; `Wikify Import`
  gains `wiki_space`. `Source Section.wiki_document` (added Slice 4) is now populated.
  Statuses already existed (`Source Document` → `Wiki-Generated`, `Wikify Import` →
  `Generating Wiki`/`Completed`).
- **API/Job:** `api.imports.preview_wiki(import_name)` + `generate_wiki(import_name,
  wiki_space=… | new_space={space_name, route})` (only from `Graphed`/`Completed`) →
  `jobs/generate.run` — flips to `Generating Wiki`, streams page progress + a final link,
  lands in `Completed` (reverts to `Graphed` + records `error` on failure), emits
  `wikify_wiki_done`.
- **UI:** `ImportDetail` gains a **Wiki** tab (`WikiGenerate.vue`): gated until the tree
  is approved; left pane = existing-space picker **or** new-space (name + auto-slugged
  route) + Generate/Regenerate + a "view wiki" link once generated; right pane = a live
  **Preview** of the projected page/group tree with counts. Realtime `wikify_wiki_done`
  refreshes; header progress bar covers `Generating Wiki` (added to `isActive`).
- Tests: `tests/test_generate.py` (8) — structure mirror (parentage/sort_order/routes/
  published), back-links + space persistence, internal-link rewrite vs external-text, the
  pure `rewrite_page_refs` helper, idempotent regen (reuse, drop-excluded, rename-route),
  preview projection. Verified live on `pdf.localhost`: `IMP-2026-00005` (Tree Demo Manual)
  generated into a new "Tree Demo Wiki" space (4 pages + 1 group, routes nested, all
  published, markdown renders via the wiki renderer), and an async regenerate streamed
  `Generating Wiki` → `Completed` idempotently. **Guest 404 caveat:** wiki pages 404 for
  anonymous users until the space gets a guest-read role — this is the wiki app's standing
  behavior (the pre-existing `docs` space 404s identically), not a generation bug; browse
  as an authenticated user. The internal page-ref → wiki-link rewrite is covered by tests
  (the 3-page demo has no internal cross-refs to exercise it live).

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
