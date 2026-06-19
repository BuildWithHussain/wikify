# Wikify — Product Spec (Frappe app + Frappe UI frontend)

This directory specs the **actual product**: a Frappe app with a Frappe UI (v1 beta)
SPA that takes a user from *"here is a PDF"* to *"here is a reviewed, typed,
navigable wiki"* — porting the validated POC pipeline (`scratch/pdf_lab/`, see
[`../README.md`](../README.md) and the POC specs) into first-class DocTypes and a
guided review UI.

> The POC proved the *pipeline* (parse → verify → remediate → sectionize → classify
> → graph → wiki). This spec is about the *experience and the persistence model*
> around it.

## The experience in one paragraph

You log in to the Wikify portal and see a **list of Imports**. You start a **New
Import**, pick a PDF, and confirm a name (defaulted from the filename, editable).
A **progress bar** streams the background parse. You land in a **page-by-page
review**: a split pane with page thumbnails on the left and, on the right, tabs to
flip between the original PDF page, the snapshot the models actually saw, and the
parsed **markdown** (syntax-highlighted). You then review and **drag-rearrange the
section tree**, approve it, and get an **Explore** view to filter sections by type
across this and every other document (*"all job descriptions across all PDFs"*).
Finally you **generate a wiki** into a Wiki Space.

## Naming (locked 2026-06-19)

| Concept | Name | DocType | Notes |
|---|---|---|---|
| The job you list & start (one per PDF) | **Import** | `Wikify Import` | Lifecycle + logs + progress. Doctype prefixed to avoid colliding with Frappe Data Import; UI label is "Import". |
| The durable parsed artifact (1:1 with an Import) | **Source Document** | `Source Document` | What cross-PDF queries span. Owns pages + sections. |
| One PDF page's parse + scores + artifacts | **Source Page** | `Source Page` | Image, baseline/remediated markdown, scores, verdict. |
| A node in the section hierarchy | **Source Section** | `Source Section` (tree) | The rearrangeable tree; becomes a wiki page/group. |
| The taxonomy label | **Section Type** | `Section Type` (master) | Seeded with the 11 POC types; editable/extensible. |
| An append-only log line | — | `Import Log Entry` | Streamed to the UI during processing. |

Decisions: **one PDF per Import**; **Wiki Space is chosen at the wiki-generation
step**, not in the create dialog (so the dialog is just *PDF + name*).

## Phase roadmap

Each phase is a vertical slice that ends in something usable.

| Phase | Title | Outcome |
|---|---|---|
| **0** | Foundations | App scaffolding (SPA cloned from CRM pattern), DocType schema, pipeline package ported from `scratch/pdf_lab/`, background-job + realtime plumbing, model config. |
| **1** | Imports list + New Import + Parse | List view, create dialog, enqueue parse, live progress bar + streaming logs, Import detail Overview. |
| **2** | Page Review (split-pane) | Per-page review: thumbnails + verdict, split pane, PDF / Snapshot / Markdown tabs, scores, before↔after for remediated pages, trigger remediation. |
| **3** | Tree Review + approval | Drag-rearrange the Source Section tree (reparent/reorder), (re)classify, approve → lock the graph. |
| **4** | Explore | Filter typed sections per-doc and **across all Source Documents** — the headline completeness query. |
| **5** | Wiki generation | Pick/create a Wiki Space, map the approved tree → Wiki Document tree, rewrite page-number refs into wiki links, generate. |
| **6** (later) | Inline editing | Editable markdown with edit history + diffs; re-derive sections from edits. |
| Future | Semantic chat / vectors | Out of scope here; schema leaves room. |

## Spec index

| Doc | Covers |
|---|---|
| [`01-architecture.md`](01-architecture.md) | System shape: SPA ↔ Frappe backend ↔ pipeline package ↔ Wiki app; component reuse; the two frontend gaps; jobs + realtime. |
| [`02-data-model.md`](02-data-model.md) | Every DocType, fields, states, and the mapping from the POC SQLite tables. |
| [`03-backend-plan.md`](03-backend-plan.md) | Pipeline port, background jobs, whitelisted APIs, realtime events, model config — phase by phase. |
| [`04-frontend-plan.md`](04-frontend-plan.md) | SPA scaffold, routes, screens & components — phase by phase. |
| [`05-wiki-generation.md`](05-wiki-generation.md) | Source Section tree → Wiki Document tree, page-ref link rewriting, regeneration. |

## Key reuse decisions (grounded in the bench)

- **Frontend scaffold:** clone `apps/crm/frontend/` (main.js + vite.config.js + www
  html/py + router guard + socket.js + `website_route_rules`).
- **Wiki target:** the live model is **Wiki Document** (nested-set tree under a Wiki
  Space's `root_group`); legacy `Wiki Page` is hard-deprecated. Create pages with
  `frappe.new_doc("Wiki Document").insert()`; content is raw **Markdown**.
- **Drag tree:** model after `apps/wiki/frontend/src/components/NestedDraggable.vue`
  (vuedraggable, arbitrary-depth reparent + reorder).
- **Markdown editor is now built in (frappe-ui v1):** `CodeEditor`
  (`frappe-ui/code-editor`, `language="markdown"`, CodeMirror 6, lazy-loaded) for the
  source pane + `CodePreview` (marked + DOMPurify) for the rendered view. **The earlier
  "add vue-codemirror / copy LMS" plan is dropped** — v1 ships it. (`TextEditor` /
  the `frappe-ui/editor` molecule are TipTap rich-text — not used here.)
- **Two things still not in frappe-ui** — add them:
  - **Resizable split pane** → `splitpanes` (or a small custom drag handle).
  - **Drag-rearrange tree** → `vuedraggable`, modeled on wiki's `NestedDraggable.vue`
    (frappe-ui `Tree` is display-only — fine for the read-only wiki-projection preview).
- **Everything else from frappe-ui v1:** `ListView`, `ItemListRow`, `Dialog` +
  imperative `dialog.confirm/prompt` + `toast.*`, `Tabs`/`TabButtons`, `Sidebar`,
  `Progress`/`Spinner`, `Badge`, `FileUploader`, and **`useCall`/`useList`/`useDoc`**
  for data (the v3 path — *not* the legacy `createResource` family), realtime socket.
- **Follow the frappe-ui skill** (`skills/frappe-ui/` in the upstream repo:
  SKILL/COMPONENTS/PATTERNS/TOKENS/SETUP) for layout + tokens: app shell =
  `FrappeUIProvider` + `Sidebar`; 48px sticky page header with `Breadcrumbs`;
  `body-container` (`max-w-[940px]`, `px-3 sm:px-5`); semantic tokens only
  (`bg-surface-*`, `text-ink-*`, `border-outline-*`); color = `variant` + `theme`;
  one solid primary action per page. Authoritative index: `ui.frappe.io/llms.txt`.
