# 0.2 Implementation Plan — Tracer-Bullet Slices

Continues the v0.1 spine (slices 1a–9, see
[`../product/IMPLEMENTATION-PLAN.md`](../product/IMPLEMENTATION-PLAN.md)). Each 0.2 slice
still cuts through **every layer** (DocType → `engine/`/`agent/` → job → whitelisted API
→ realtime → SPA) and ends in something **demoable on its own**.

Numbering continues at **10** so the delivery sequence stays monotonic across versions.

> Source of truth for behavior is the numbered 0.2 specs
> ([01-project-hierarchy](01-project-hierarchy.md) · [02-ai-agent](02-ai-agent.md) ·
> [03-wiki-preview](03-wiki-preview.md)). This file is the *delivery order*.

## Legend

- **HITL** — needs human interaction (architectural decision, design/UX review, or a
  spine-verification checkpoint).
- **AFK** — well-specified enough to implement and merge without a checkpoint.

## Slice map

| # | Slice | Type | Blocked by | Spec | Status |
|---|---|---|---|---|---|
| 10 | Project hierarchy (DocType + backfill + project/imports UI) | HITL | 9 | 01 | ✅ |
| 11 | Project context → pipeline + project settings | AFK | 10 | 01 | ✅ |
| 12 | Agent walking skeleton (chat + 1 read tool + streaming) | HITL | 10 | 02 | ✅ |
| 13 | Agent context attachment + full read tools | HITL | 12 | 02 | — |
| 14 | Agent write / action tools (tree · retag · re-parse · pipeline) | HITL | 13, 11 | 02 | — |
| 15 | Wiki rendered preview | HITL | 9 | 03 | — |
| 16 | Polish (session history · per-project agent model · settings · empty states) | AFK | 14 | 01, 02 | — |

**Spine:** 10 → 11 → 12 → 13 → 14 → 16 is the main chain. **Parallelism:** 15 (wiki
preview) floats off v0.1 slice 9 and can be built any time after 10; 11 can proceed
alongside 12.

The guiding move (as in v0.1): **Slice 12 is the agent walking skeleton** — the thinnest
end-to-end chat that proves the litellm loop + realtime + one tool. Slices 13–14 *thicken*
it (context, then write power) rather than adding disconnected layers.

---

## Verification

Same protocol as v0.1: verify every slice against **`pdf.localhost`** (login
**Administrator / admin**) before starting the next. Run `bench` from the bench root
(`/Users/mdhussain/Frappe/benches/december-bench`).

### Standing loop (per slice)

```bash
bench --site pdf.localhost migrate            # pick up DocType/schema/patch changes
bench build --app wikify                       # (or vite dev) for frontend slices
bench start                                     # web + socketio + workers — required for jobs + realtime + the agent
```

1. **Headless first** — `bench --site pdf.localhost execute <dotted.path>` or `console`;
   assert the rows/fields/status the slice produces. For the agent, exercise
   `AgentRunner.run()` headlessly with a stub/live model before touching the UI.
2. **Automated** — extend `FrappeTestCase` tests under `wikify/wikify/doctype/**/test_*.py`
   or `wikify/tests/`; run `bench --site pdf.localhost run-tests --app wikify`. Cover the
   slice's job/API logic + the state it introduces. Mock litellm for agent unit tests.
3. **UI walkthrough** — at `/wikify` as Administrator, reproduce the slice's demo; confirm
   realtime where applicable (the `/verify` skill can drive the browser).
4. **Regression** — re-run the prior slice's demo (and a v0.1 end-to-end parse) to confirm
   the spine still works.

Reuse the POC sample PDFs / a small fixture (one text-heavy + one visual page).

---

## 10 — Project hierarchy

**Type:** HITL (first structural change to the data model since 0.1; new landing screen).
**Blocked by:** 9. **Spec:** [01-project-hierarchy](01-project-hierarchy.md).

### What to build
- **DocType** `Wikify Project` (`project_name`, `description`, `context_prompt`, `status`,
  `is_default`, `agent_model`, `import_count`) with the controller guards (no second
  default; block deleting default or non-empty projects).
- **Links:** add `project` (reqd) to `Wikify Import`; add `project` (ro, denormalized) to
  `Source Document`. Stamp `Source Document.project` from the Import at parse time
  (`jobs/parse.py` / `engine/store.create_document`).
- **Seed + backfill:** `after_install` seeds "Uncategorized"; patch
  `wikify.patches.v0_2.seed_uncategorized_and_backfill` (registered in `patches.txt`)
  ensures it + backfills all existing Imports and Source Documents into it.
- **API:** `api/projects.py` (`create_project`, `list_projects`); `start_import` gains a
  `project` param (defaults to Uncategorized).
- **UI:** `pages/ProjectList.vue` (new home at `/wikify`), `pages/ProjectDetail.vue`
  (project-scoped imports list — reuse `ImportList` with a `project` filter), New Project
  dialog, **Project** picker added to `NewImportDialog.vue`, sidebar nav → Projects +
  Explore, import detail shows a project breadcrumb. Explore gains a project filter.

### Acceptance criteria
- [x] New Project → New Import inside it files the Import + (after parse) its Source
  Document under that project; the project card shows the count.
- [x] After `migrate`, every pre-0.2 Import + Source Document is under "Uncategorized";
  none orphaned.
- [x] Deleting "Uncategorized" or a non-empty project is blocked with a clear message.
- [x] Explore can be scoped to one project and still spans its documents.

**Verify:** migrate on a copy with existing imports → confirm backfill in `console`; create
a project + import via UI; attempt the blocked deletes; run the v0.1 parse end-to-end to
confirm regression-free.

### As built
- **DocType** `Wikify Project` (`PRJ-.YYYY.-.#####` autoname, `project_name` title) with
  the controller guards (`validate` → single `is_default`; `on_trash` → block deleting the
  default or a non-empty project). `import_count` is denormalized via
  `Wikify Import.after_insert/on_trash` hooks.
- **Links:** `project` (reqd, indexed) on `Wikify Import`; `project` (ro, indexed,
  denormalized) on `Source Document`, stamped at parse time through
  `engine.parse_pdf` → `store.create_document`. Added a `project_name` **fetch_from** field
  on the Import (drives the import-detail breadcrumb without an extra fetch); the backfill
  patch stamps it on existing rows since `fetch_from` only fires on save.
- **Seed + backfill:** `seed.seed_uncategorized_project` (get-or-create by `is_default`)
  is called from `after_install` and the `wikify.patches.v0_2.seed_uncategorized_and_backfill`
  patch, which backfills Imports + Source Documents and recomputes every `import_count`.
- **API:** `api/projects.py` (`create_project`, `list_projects` default-pinned,
  `default_project`); `start_import` gained an optional `project` param (defaults to
  Uncategorized); `explore.type_summary` / `sections_by_type` gained an optional `project`
  filter (resolved to the project's Source Documents, empty project → empty result).
- **UI:** `pages/ProjectList.vue` (new `/wikify` home — cards via `useList`, New Project
  dialog, Uncategorized pinned + Default badge); `pages/ProjectDetail.vue` (breadcrumb +
  New Import, embeds the now project-scoped `ImportList`); `NewImportDialog` gained a
  Project picker (preset to the current project, else Uncategorized); `ImportDetail` shows a
  project breadcrumb + back-to-project; Explore gained a project filter dropdown; sidebar
  nav is now **Projects + Explore**.
- **Deviation:** project **settings** (the `context_prompt` editor at
  `/project/:name/settings`) is intentionally deferred to Slice 11 per the plan; Slice 10
  ships the hierarchy + scoping only. Permissions use the existing **System Manager** role
  (matching the 0.1 DocTypes), not a separate "Wikify User" role.
- **Tests:** `wikify/tests/test_projects.py` (8 tests — seed idempotency, single-default +
  delete guards, `import_count`/`project_name` denorm, project-scoped Explore);
  `test_section_edits` updated to set the now-reqd `project`. Full suite 55 green.

### Spec refs
[01-project-hierarchy](01-project-hierarchy.md) (data model, seed/backfill, UI).

---

## 11 — Project context → pipeline + project settings

**Type:** AFK. **Blocked by:** 10. **Spec:** [01-project-hierarchy](01-project-hierarchy.md) → *Where the context prompt threads*.

### What to build
- **Project settings UI** (`components/ProjectSettings.vue` at
  `/wikify/project/:name/settings`): edit `project_name`, `description`,
  **`context_prompt`** (textarea), `agent_model`, archive.
- **Thread `project_context`** from the jobs into the engine prompts as an optional
  string argument (blank = current behavior): `engine/loader/cleanup_llm.py`,
  `engine/parsers/vlm.py`, `engine/loader/classifier.py`, `engine/loader/wiki.py`. Jobs
  (`parse`, `remediate`, `classify`, `generate`) read `import.project.context_prompt` and
  pass it down. Keep `engine/` functions pure (no DocType reads for context).

### Acceptance criteria
- [x] Saving a context prompt persists it; it appears in the model_config/log provenance.
- [x] Re-running cleanup / a VLM re-parse with a distinctive context (e.g. a terminology
  rule) visibly changes output vs. blank context.
- [x] Blank context reproduces v0.1 output byte-for-byte (no regression).

**Verify:** headless — call the cleanup/VLM engine fn with and without `project_context`
and diff; set a context in the UI and re-run remediation on a flagged page.

### As built
- **Engine seam:** `engine/loader/context.py:context_block(project_context)` builds the
  one shared, clearly-delimited `"Project context:\n{…}\n\n"` preamble — and returns
  `""` for blank/whitespace-only input, so a project with no context yields prompts
  **byte-identical** to v0.1 (the "no regression" criterion is structural, not just
  tested). Threaded as an optional `project_context: str = ""` argument (default = current
  behavior) through every LLM step: `clean_markdown` (prepend), `vlm.parse_page_image`
  (prepend to the vision text part), `classify_section` (inserted after the taxonomy/format
  lines, before the section body, per the spec's "append after the taxonomy"). The string
  flows down the call chains `classify_document → classify_section` and
  `parse_pdf`/`remediate_pdf → rebuild_and_classify → classify_document`. **Engine stays
  pure** — no DocType reads for context.
- **Jobs resolve once:** `jobs/_util.py:project_context(import_doc)` reads
  `import.project.context_prompt` (blank when unset); `parse`, `remediate`, and `classify`
  jobs resolve it and pass it into the engine. Each also emits a `Using project context
  (N chars)` Import Log line when non-blank — the **log provenance** for the criterion.
- **Settings UI:** `components/ProjectSettings.vue` at `/wikify/project/:name/settings`
  (route ordered before `/project/:name`) — a `useDoc`-seeded form editing `project_name`,
  `description`, the **`context_prompt`** textarea (8 rows + helper copy), `agent_model`
  (free-text Data, "leave blank to use the site default"), and an **Archive** checkbox
  (maps to `status` Active/Archived). One solid "Save" → `api.projects.update_project`
  (new whitelisted endpoint, only-passed-fields update; controller guards still enforce
  unique name + single default), then `project.reload()` + a success toast. A ghost
  settings icon was added to the `ProjectDetail` header.
- **Deviation:** the spec's threading table lists `engine/loader/wiki.py`, but wiki
  generation is purely structural (slugify + page-ref rewrite — **no LLM call**), so there
  is nothing to steer there; context threading is correctly a no-op for generation and was
  skipped. `agent_model` is a plain text field here (the populated model picker is Slice 16).
- **Tests:** `wikify/tests/test_project_context.py` (7 — `context_block` blank/filled, and
  that cleanup/VLM/classify embed the block in the right place + blank leaves the prompt
  verbatim). Updated the `clean_markdown`/`classify_section` mocks in
  `test_remediate_pipeline` / `test_classify` for the new kwarg. Full suite 62 green.

### Spec refs
[01-project-hierarchy](01-project-hierarchy.md) → *Where the context prompt threads*.

---

## 12 — Agent walking skeleton

**Type:** HITL (the agent spine-verification checkpoint — first litellm tool-loop streaming
end-to-end). **Blocked by:** 10. **Spec:** [02-ai-agent](02-ai-agent.md).

### What to build
The tracer bullet for the agent. Thinnest chat that proves the whole loop. **Global scope
only, one tool, no attachments, no write tools.**
- **Dep:** add `litellm` to `pyproject.toml`; install in the bench env.
- **DocTypes:** `Wikify Agent Session` + `Wikify Agent Message` (per spec).
- **`wikify/agent/`:** `llm.py` (litellm + OpenRouter via `engine.settings.openrouter_key`),
  `registry.py` (Tool dataclass + registry), `loop.py` (`AgentRunner.run` round loop:
  stream text → `wikify_agent_stream`, accumulate tool calls, run `server` tool, feed
  back, finish on no-tool-call), `session.py` (facade), `prompts.py`. One tool only:
  **`read_tree`** (reuse `api.sections.get_tree`).
- **Job + API:** `jobs/agent.py` (`run_agent_job`); `api/agent.py` (`run` → enqueue +
  202, `cancel`, `get_session`).
- **Realtime:** `wikify_agent_stream/tool/complete/error` channels.
- **UI:** minimal `AgentChatPanel.vue` + a floating button in `AppShell.vue`; message
  list + input + streaming; `useAgentChat` controller; `agent/realtime.js` listeners.

### Acceptance criteria
- [x] Floating button opens the panel on any screen.
- [x] "Summarize the tree of document <X>" streams an answer **after** the agent calls
  `read_tree` (visible as a tool-call card / log).
- [x] Tokens stream live over realtime; the final message persists as a
  `Wikify Agent Message` and survives a panel reload (`get_session`).
- [x] `cancel` stops a running stream; a second concurrent `run` on the session is
  rejected (`is_running`).

**Verify:** headless `AgentRunner.run()` with a live model + a stubbed model; then UI —
ask a tree question, watch the stream, reload the panel, cancel mid-stream.

### As built
- **Dep:** `litellm` added to `pyproject.toml` and installed in the bench env (1.83.7).
  litellm pins `click==8.1.8` but frappe/bench need `click~=8.3`; litellm imports fine
  against the newer click, so click was restored to 8.3.3 (litellm's pin is over-strict).
- **DocTypes:** `Wikify Agent Session` (`AGT-.YYYY.-.#####`, `title` from the first user
  message, `scope`/`project`/`source_document`/`model`/`status`/`is_running`/
  `last_interaction_on`; `on_trash` cascades its messages) + `Wikify Agent Message`
  (`hash` autoname, sorted `creation asc`; `role`/`content`/`tool_calls`/`tool_name`/
  `tool_call_id`/`attachments_json`/`status`/`metadata_json`). No patch (new doctypes).
- **`wikify/agent/`:** `llm.py` (litellm adapter — `litellm.drop_params=True`,
  `openrouter/`-prefix, `resolve_model` = explicit → project `agent_model` → default
  `anthropic/claude-sonnet-4.6`), `registry.py` (`Tool` dataclass + `build_default_registry`
  collecting module `TOOLS` lists), `context.py` (`Ctx` + `default_document`;
  attachment resolution is a no-op until slice 13), `prompts.py` (system prompt, already
  accepts a project-context arg for 13), `session.py` (facade: get_or_create /
  append_message / update_message / `history_messages` replay in OpenAI format /
  set_running / touch), `loop.py` (`AgentRunner.run` — per-round streaming completion;
  text deltas → `wikify_agent_stream`, tool-call deltas accumulated by index, server
  tools run + fed back as `tool` messages, finishes on no-tool-call; `MAX_ROUNDS=25`;
  per-chunk cancel via Redis `wikify_agent_cancel:<sid>`), `tools/read.py` (the one tool,
  `read_tree`, rendering `api.sections.get_tree` as indented text, defaulting
  `source_document` to the session's).
- **Job + API:** `jobs/agent.py:run_agent_job` (sets the user, runs `AgentRunner`);
  `api/agent.py` — `run` (validates, get-or-creates the session, **429 + throw** if
  `is_running`, appends the user message, enqueues on `long`, returns **202**
  `{session_id, message_id}`), `cancel` (sets the Redis flag), `get_session` (session +
  ordered messages for hydration).
- **Realtime:** `wikify_agent_stream|tool|clarify|complete|error:<sid>`, published to the
  requesting `user` (mirrors the import progress/log streaming).
- **UI:** `composables/useAgentChat.js` (controller — reactive messages + streaming
  accumulators, optimistic user + "Thinking…" bubbles, `submitPrompt`/`cancel`/
  `loadSession`/`newSession`, calls `wikify.api.agent.*` via frappe-ui `call`),
  `agent/realtime.js` (binds the five `wikify_agent_*:<sid>` socket events → controller
  handlers, returns an unsubscribe), `components/AgentChatPanel.vue` (right slide-over:
  message bubbles, tool-call cards running→done, streamed assistant bubble rendered via
  `MarkdownPreview`, textarea + send/stop), floating button + the panel mounted once in
  `AppShell.vue` so it's on every screen.
- **Scope held to the skeleton:** global scope only, no attachment chips and no session
  history yet (slices 13/16) — the controller already passes `scope`/`source_document`
  through `run`, and `context.py`/`prompts.py` already take the project-context hook, so
  13 thickens without reshaping. The conversation persists in the (always-mounted)
  controller across panel close/open; full reload-rehydration via the history dropdown is
  slice 13/16, but `get_session` + `loadSession` are already wired.
- **Verified:** headless `AgentRunner.run()` live (read_tree → 3-bullet summary persisted
  as 4 messages) and stubbed (7 mocked-litellm tests — tool loop, realtime emit, cancel
  mid-stream, 429 concurrency reject, enqueue). UI walkthrough on `pdf.localhost`: floating
  button opens the panel, a tree question streamed an answer after a `read_tree` tool card,
  message persisted + session titled, close/reopen kept the thread. Full suite 69 green;
  pre-commit clean.

### Spec refs
[02-ai-agent](02-ai-agent.md) (stack, DocTypes, loop, API, realtime).

---

## 13 — Agent context attachment + full read tools

**Type:** HITL (the context-attachment UX is the heart of "knows what you're looking at").
**Blocked by:** 12. **Spec:** [02-ai-agent](02-ai-agent.md) → *Context attachment*.

### What to build
- **`data/agentContext.js`** store + wiring: `ProjectDetail`/`ImportDetail`/`PageReview`/
  `SectionTree` set the current project/document/page/section; the panel reads it for
  **default attachment chips** (removable ✕).
- **`agent/context.py`:** resolve `attachments[]` → a bounded context block (tree outline
  + focused item body) prepended to messages; inject the attached **project's
  `context_prompt`** into the system prompt; default tool args (e.g. `source_document`)
  from attachments.
- **Read tools:** add `read_section`, `read_page`, `list_section_types`,
  `search_sections` (`tools/read.py`, reusing existing `api.sections`/`api.explore`).
- **API:** `run` accepts `scope`/`project`/`source_document`/`attachments`;
  `list_sessions`/`new_session`.
- **UI:** attachment chips row with ✕; session-history dropdown.

### Acceptance criteria
- [ ] Opening the panel on a project / document / page / section attaches that thing by
  default; removing a chip drops it from context.
- [ ] With a document attached, "what types are my sections?" answers without the user
  naming an id (default scoping works).
- [ ] The attached project's context prompt measurably steers answers.
- [ ] Sessions are scoped/listed; switching sessions hydrates history.

**Verify:** open the panel from each surface and confirm the right default chip; ask a
context-dependent question with and without the chip; confirm project context injection.

### Spec refs
[02-ai-agent](02-ai-agent.md) → *Context attachment*, *Read tools*.

---

## 14 — Agent write / action tools

**Type:** HITL (the agent now mutates real data — needs a confirmation-UX review).
**Blocked by:** 13, 11. **Spec:** [02-ai-agent](02-ai-agent.md) → *Tool catalogue*.

### What to build
- **Tree/taxonomy tools:** `move_section`, `rename_section`, `set_section_type`,
  `toggle_include_in_wiki`, `create_section_type` (reuse `api.sections` mutations).
- **Re-parse tools:** `use_page_image` (deterministic image-embed), `reparse_page`
  (instruction-steered single-page re-parse — extend the remediate path to take a custom
  instruction + page scope), `reparse_document` (doc-wide, confirm-gated).
- **Pipeline tools:** `reclassify`, `regenerate_wiki` (reuse `jobs/classify`/`generate`,
  confirm-gated).
- **Confirmation UX:** expensive/destructive tools (`reparse_document`, `regenerate_wiki`,
  full `reclassify`) render a confirm card before executing; cheap edits apply directly.
  Tools mutate DocTypes; the panel re-fetches affected resources on `complete`
  (`useDoc`/`useList` auto-refetch → Tree/Pages reflect changes).
- **UI:** tool-call cards show running → done with a short summary; affected-item links.

### Acceptance criteria
- [ ] "Move 'Anaesthesia' under 'Clinical Protocols'" reorders the tree; Tree tab updates
  on refetch.
- [ ] "Tag pages 40–45 as surgical_procedures" retags those sections.
- [ ] "Don't make page 7 a mermaid diagram — just embed the page image" runs
  `use_page_image`; the page's canonical markdown becomes the image embed.
- [ ] "Re-parse page 12 keeping the table as real markdown" enqueues an instruction-steered
  `reparse_page`; canonical updates and the page review shows it.
- [ ] Reparse-whole-document / regenerate-wiki ask for confirmation before running.

**Verify:** drive each tool from the panel; confirm DB mutations in `console`; confirm the
review/tree UI reflects them; confirm the confirm-gate on expensive ops.

### Spec refs
[02-ai-agent](02-ai-agent.md) → *Write / tree tools*, *Re-parse tools*, *Pipeline tools*.

---

## 15 — Wiki rendered preview

**Type:** HITL (renderer-fidelity decision against `apps/wiki`; design review of the frame).
**Blocked by:** 9 (floats — buildable any time after 10). **Spec:** [03-wiki-preview](03-wiki-preview.md).

### What to build
- **Decide the renderer:** read `apps/wiki` to see how `Wiki Document.content` is rendered;
  match it. Either `api/wiki.render_section_preview` (backend HTML, true fidelity) or a
  client render with identical config — document the choice.
- **`components/WikiPreview.vue`:** wiki-framed read-only view (breadcrumb from
  `hierarchy_path` + title + rendered HTML + mermaid via the existing util); Rendered ⇄
  Source toggle; muted banner for excluded sections.
- **Page-ref resolution (preview):** dry-run the pass-2 resolver to show "Page No. N" refs
  as preview links + a "N refs will resolve" hint.
- **Wire in:** Tree tab node click → preview in the right pane; Wiki tab projected tree →
  clickable → same preview.

### Acceptance criteria
- [ ] Clicking a tree node renders it (headings/tables/mermaid-as-SVG) in a wiki-style
  frame with the correct breadcrumb.
- [ ] A "refer Page No. 130" ref shows as a preview link to the resolved section; the count
  hint is correct.
- [ ] Wiki tab projected tree is clickable → same preview; Rendered ⇄ Source toggles.
- [ ] A generated Wiki Document page matches its preview (spot-check).

**Verify:** open previews for a text page, a table page, and a mermaid-bearing visual page;
generate the wiki and compare one page to its preview.

### Spec refs
[03-wiki-preview](03-wiki-preview.md).

---

## 16 — Polish

**Type:** AFK. **Blocked by:** 14. **Spec:** [01](01-project-hierarchy.md) · [02](02-ai-agent.md).

### What to build
- Agent **session history** list + switch/rename/archive in the panel.
- **`agent_model`** in `Wikify Settings` + per-project override resolution; model picker
  populated from `get_agent_models`.
- Empty/error states (no projects, no sessions, agent error + retry), the no-op guard
  (port Builder's `claims_unbacked_action` if the model narrates edits without tool calls),
  and prompt-caching markers for the (large) tree/context blocks.
- Project list polish (pinned "Uncategorized", archived filter), breadcrumbs.

### Acceptance criteria
- [ ] Sessions can be listed, reopened, renamed, archived.
- [ ] Agent model resolves project-override → settings → default; the picker works.
- [ ] Empty/error states render cleanly; cancel/retry behave.

**Verify:** exercise session history + model resolution; force an agent error and confirm
the retry path.

### Spec refs
[02-ai-agent](02-ai-agent.md) (API, loop guards) · [01-project-hierarchy](01-project-hierarchy.md) (settings).
