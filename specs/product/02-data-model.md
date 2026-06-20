# 02 — Data Model (DocTypes)

Maps the POC SQLite schema (`scratch/pdf_lab/loader/graph.py`) onto Frappe DocTypes.
Field types are Frappe fieldtypes. `reqd` = required; `ro` = read-only (system-set).

> **As built (through Slice 3):** `Wikify Import`, `Source Document`, `Source Page`,
> `Import Log Entry`, and `Wikify Settings` (Single) exist with only the fields their
> slice exercises. Slice 2 added baseline score fields + `verdict` + `notes` on
> `Source Page` and `mean_score` on `Source Document`. Slice 3 added `remediation_*`
> (incl. `remediation_notes`) + `canonical_*` (incl. `canonical_source`) on `Source
> Page` and a distinct `canonical_mean` on `Source Document` (the baseline `mean_score`
> is kept separately, so the before↔after delta survives). `Source Section` /
> `Section Type` are not created yet (Slices 4 / 6). `Source Page` is `hash`-named (the
> spec's `{source_document}::p{page_no}` is noted as optional); `import` / `pdf` are
> present per the tables below.

## Entity-relationship overview

```
Wikify Import ─1:1─▶ Source Document ─1:N─▶ Source Page
      │                     │
      │                     └─1:N─▶ Source Section (tree, parent_source_section)
      │                                   │
      └─1:N─▶ Import Log Entry             └─0:1─▶ Wiki Document  (after generation)

Source Section.section_type ──▶ Section Type (master, seeded)
Wikify Settings (Single) ── model ids, thresholds, taxonomy defaults
```

---

## `Wikify Import`  (label: "Import")

The run/lifecycle record. One per PDF. This is the list-view subject.

| Field | Type | Notes |
|---|---|---|
| `naming_series` | autoname | `IMP-.YYYY.-.#####` |
| `import_title` | Data, reqd | Defaults to PDF filename without extension; user-editable in the create dialog. |
| `pdf` | Attach, reqd | The uploaded File URL. |
| `source_document` | Link → Source Document, ro | Set when parse completes (1:1). |
| `status` | Select, ro | `Draft / Queued / Parsing / Review / Remediating / Tree Review / Graphed / Generating Wiki / Completed / Failed`. |
| `stage_progress` | Percent, ro | 0–100 for the active job; drives `<Progress>`. |
| `stage_label` | Data, ro | e.g. "Parsing page 42/180". |
| `page_count` | Int, ro | Filled after render. |
| `mean_score` | Float, ro | Canonical mean composite. |
| `model_config` | Small Text (JSON), ro | Snapshot of model ids + thresholds used (provenance). |
| `error` | Long Text, ro | Stack/summary on `Failed`. |
| `wiki_space` | Link → Wiki Space, ro | Set at the generation step. |
| `started_at` / `completed_at` | Datetime, ro | |

Permissions: a "Wikify User" role; rows are owner-scoped by default (configurable).

---

## `Source Document`

The durable parsed artifact. Cross-PDF Explore and wiki generation read from here.
≈ POC `documents` table.

| Field | Type | Notes |
|---|---|---|
| `title` | Data, reqd | From `import_title`. |
| `import` | Link → Wikify Import, ro | Back-reference (1:1). |
| `pdf` | Attach / Link → File, ro | Same PDF; needed for re-parse + the PDF.js tab. |
| `page_count` | Int, ro | |
| `parser_used` | Data, ro | Baseline parser name (`pymupdf4llm`, …). |
| `mean_score` | Float, ro | Mean composite over the **baseline** parse of each page (set at parse). |
| `canonical_mean` | Float, ro | Mean **canonical** (best-per-page) composite; set by the remediate job. Rises as flagged pages are improved. |
| `status` | Select, ro | `Parsed / Graphed / Wiki-Generated`. |
| `wiki_space` | Link → Wiki Space, ro | Set on generation. |
| `wiki_root_group` | Link → Wiki Document, ro | The group under which this doc's pages were generated. |

> The POC's `documents.source_path` (absolute PDF path, needed for re-parse) is
> replaced by the `pdf` File reference.

---

## `Source Page`

One row per PDF page. **Folds POC `page_scores` (baseline) + `escalations`
(remediation candidate) into a single row** — the UI diffs baseline vs remediation
fields directly.

| Field | Type | Notes |
|---|---|---|
| `source_document` | Link → Source Document, reqd | Parent. Indexed. |
| `page_no` | Int, reqd | 1-based. |
| `kind` | Select, ro | `text / visual` (POC `pdf_utils.classify_page`). |
| `image` | Attach Image / Link → File, ro | Rendered PNG (150 DPI) — the snapshot the models saw. |
| **Baseline** | | (POC `page_scores`) |
| `baseline_markdown` | Code (Markdown) | |
| `text_recall` `extra_ratio` `table_score` `judge_score` `composite` | Float, ro | Baseline scores. |
| `verdict` | Select, ro | `pass / escalate / review`. |
| `notes` | Small Text, ro | `"; "`-joined harness notes. |
| **Remediation** | | (POC `escalations`) |
| `remediation_method` | Select, ro | `'' / cleanup / vlm` (blank until a pass runs; the route taken). |
| `remediation_markdown` | Code (Markdown), ro | Candidate output (cleanup or vlm); `""` if the page's model call failed. |
| `remediation_composite` | Float, ro | Re-scored candidate composite. |
| `remediation_adopted` | Check, ro | Whether the candidate became canonical. |
| `remediation_notes` | Small Text, ro | Candidate harness notes, or a `"<method> failed: …"` line on a per-page model error (the page keeps its baseline). |
| **Canonical / edits** | | |
| `canonical_markdown` | Code (Markdown), ro | Adopted of {baseline, remediation}, then cross-page-table-stitched — what sectionizing reads. Set for **every** page (baseline where nothing was adopted). |
| `canonical_source` | Select, ro | `'' / baseline / cleanup / vlm` — provenance of the canonical markdown. |
| `canonical_composite` | Float, ro | Best-of score (POC `canonical_mean` logic, mirrored). |
| `edited_markdown` | Code (Markdown) | Phase 6: user inline edit; when set, overrides canonical. |
| `is_edited` | Check | Phase 6. |

Naming: `{source_document}::p{page_no}` (hash autoname acceptable too).
Index on `(source_document, page_no)`.

> The image + markdown variants were loose files on disk in the POC
> (`page-XXXX[.method].md`, `page-XXXX.png`). Here the PNG becomes a File doc
> (`image`); the markdown variants become the Code fields above. The implicit
> `page-XXXX` join key is replaced by the row identity.

---

## `Source Section`  (tree: `is_tree = 1`, `nsm_parent_field = "parent_source_section"`)

The rearrangeable hierarchy. ≈ POC `nodes` (type=section) + `edges`. Modeled as a
Frappe **NestedSet tree** so drag-reparent/reorder maps cleanly (mirrors how
`Wiki Document` works) and so the headline cross-doc scan is a flat indexed query.

| Field | Type | Notes |
|---|---|---|
| `source_document` | Link → Source Document, reqd | Indexed. |
| `parent_source_section` | Link → Source Section | Tree parent (NestedSet). |
| `is_group` | Check | Group (has children) vs leaf content section. |
| `title` | Data, reqd | Heading text. |
| `section_type` | Link → Section Type | Taxonomy label. Indexed (drives Explore). |
| `hierarchy_path` | Small Text, ro | `" > "`-joined ancestor titles (kept for display + page-ref resolution). |
| `level` | Int, ro | Depth; **persisted** (POC derived it — we store it). |
| `sort_order` | Int | Sibling ordering; updated by drag-reorder. |
| `page_start` / `page_end` | Int, ro | PDF page range (citation + page-ref resolution). |
| `markdown` | Code (Markdown) | Section body. |
| `include_in_wiki` | Check, default 1 | Lets the user drop a section from generation. |
| `wiki_document` | Link → Wiki Document, ro | The generated page (set on generation). |
| `lft` / `rgt` / `old_parent` | Int / Link, ro | NestedSet bookkeeping. |

Naming: `{source_document}::s{idx}`.
Index on `(source_document, lft)` for ordered traversal and on `section_type` for
the cross-document Explore query.

> POC kept an explicit `edges` table (`HAS_SECTION`, `PART_OF`). With a real tree
> + `parent_source_section`, edges are redundant and dropped. The document→section
> link is just `source_document`.

---

## `Section Type`  (master, seeded)

Makes the taxonomy first-class and **extensible** — honoring the POC insight that
types were derived bottom-up from real headings and may be re-derived per corpus.

| Field | Type | Notes |
|---|---|---|
| `type_name` | Data, reqd, unique | e.g. `staff_roles_and_responsibilities`. |
| `label` | Data | Display label, e.g. "Staff Roles & Responsibilities". |
| `description` | Small Text | Used in the classifier prompt. |
| `color` | Data | Chip color in Explore. |
| `is_other` | Check | Marks the catch-all `other`. |

Seed via `after_install` / fixtures with the 11 POC types:
`staff_roles_and_responsibilities, clinical_protocols, surgical_procedures,
patient_management, medication_management, administrative_policies,
equipment_and_facilities, training_and_audits, research_and_documentation,
emergency_procedures, other`.

---

## `Import Log Entry`

Append-only log lines for the live log stream. Separate doctype (not a child table)
so the job can append cheaply and stream each row via realtime without rewriting the
parent.

| Field | Type | Notes |
|---|---|---|
| `import` | Link → Wikify Import, reqd | Indexed. |
| `idx_seq` | Int | Monotonic order within an import. |
| `level` | Select | `info / warn / error`. |
| `stage` | Data | `parse / remediate / classify / wiki`. |
| `message` | Small Text | The line. |
| `meta` | Small Text (JSON) | Optional: cost, latency, model, page_no. |

Retention: prune on Import delete (cascade); optionally cap to last N.

---

## `Wikify Settings`  (Single)

Lifts POC `config.py` model ids + tunables into site config so they're switchable
without code (the POC already made them env-overridable).

| Field | Type | Default (POC) |
|---|---|---|
| `vlm_model` | Data | `mistralai/mistral-medium-3.1` |
| `cleanup_model` | Data | `google/gemini-2.5-flash` |
| `judge_model` | Data | `anthropic/claude-sonnet-4.6` |
| `classifier_model` | Data | `google/gemini-2.5-flash` |
| `openrouter_api_key` | Password | from site config / `.env` |
| `pass_threshold` | Float | 0.90 |
| `escalate_threshold` | Float | 0.70 |
| `cleanup_recall_tolerance` | Float | 0.12 |
| `judge_all_pages` | Check | 0 (visual pages always judged; this also judges text pages) |
| `render_dpi` | Int | 150 |
| `visual_min_chars` | Int | 250 |
| `visual_min_drawings` | Int | 40 |
| `remediation_workers` / `classify_workers` | Int | 6 / 8 |

Weights (`WEIGHTS`, `VISUAL_WEIGHTS`) can stay code-side constants in
`engine/config.py` unless we want them tunable too.

## Computed-at-read-time, not stored

The POC computes the **canonical per-page score** at read time
(`graph.canonical_mean`, best of adopted-escalation vs baseline) rather than
persisting a third number. We mirror that: `canonical_markdown` /
`canonical_composite` on `Source Page` are written once at adoption time by the job,
and `Source Document.mean_score` is the mean over them — but the *selection rule*
lives in `engine/store.py`, not duplicated in the UI.
