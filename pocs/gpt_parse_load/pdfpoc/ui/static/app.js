const state = {
  overview: null,
  documentId: null,
  page: null,
  selectedRuns: new Set(),
  pageData: null,
  review: null,
};

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

function metric(value) {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "number") return fmt.format(value);
  return String(value);
}

function money(value) {
  if (value === null || value === undefined) return "n/a";
  return `$${Number(value).toFixed(6)}`;
}

function shortId(value) {
  return String(value || "").replace(/^run_/, "").slice(0, 34);
}

async function loadOverview() {
  const response = await fetch("/api/overview");
  state.overview = await response.json();
  const docs = state.overview.documents;
  document.getElementById("runSummary").textContent = `${state.overview.run_count} canonical runs indexed`;
  document.getElementById("statusStrip").innerHTML = [
    `<span class="pill">DB ${state.overview.db_path ? "connected" : "not set"}</span>`,
    `<span class="pill">Runs ${state.overview.run_count}</span>`,
    `<span class="pill good">Reviews writable</span>`,
  ].join("");

  const docSelect = document.getElementById("documentSelect");
  docSelect.innerHTML = docs.map((doc) => `<option value="${doc.id}">${doc.filename}</option>`).join("");
  state.documentId = docs[0]?.id || null;
  docSelect.value = state.documentId || "";
  docSelect.addEventListener("change", () => {
    state.documentId = docSelect.value;
    hydrateDocument();
  });
  hydrateDocument();
}

function currentDocument() {
  return state.overview.documents.find((doc) => doc.id === state.documentId);
}

function hydrateDocument() {
  const doc = currentDocument();
  if (!doc) return;

  const pageSelect = document.getElementById("pageSelect");
  pageSelect.innerHTML = doc.pages.map((page) => `<option value="${page}">${page}</option>`).join("");
  const preferred = doc.pages.includes(13) ? 13 : doc.pages[0];
  state.page = state.page && doc.pages.includes(state.page) ? state.page : preferred;
  pageSelect.value = state.page;
  pageSelect.onchange = () => {
    state.page = Number(pageSelect.value);
    refreshPage();
  };

  const preferredRuns = pickDefaultRuns(doc.runs, state.page);
  state.selectedRuns = new Set(preferredRuns.map((run) => run.id));
  renderRunPicker(doc);
  renderScoreTable(doc);
  refreshPage();
}

function pickDefaultRuns(runs, page) {
  const wanted = [
    "pymupdf_fast",
    "openrouter_gemini_flash",
    "openrouter_mistral_medium",
    "hybrid_pymupdf_fast_openrouter_gemini_flash",
    "hybrid_pymupdf_fast_openrouter_mistral_medium",
  ];
  const picked = [];
  for (const profile of wanted) {
    const run = runs.find((item) => item.profile === profile && item.pages.includes(page))
      || runs.find((item) => item.profile === profile);
    if (run) picked.push(run);
  }
  return picked.length ? picked : runs.slice(0, 4);
}

function renderRunPicker(doc) {
  const runList = document.getElementById("runList");
  runList.innerHTML = doc.runs.map((run) => {
    const checked = state.selectedRuns.has(run.id) ? "checked" : "";
    const score = run.scorecard || {};
    return `
      <label class="run-option">
        <input type="checkbox" value="${run.id}" ${checked}>
        <span>
          <span class="run-name">${run.profile}</span>
          <span class="run-meta">${run.model || run.provider} · pages ${run.pages.join(", ")} · recall ${metric(score.text_recall_avg)}</span>
        </span>
      </label>
    `;
  }).join("");
  runList.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selectedRuns.add(input.value);
      else state.selectedRuns.delete(input.value);
      renderScoreTable(doc);
      refreshPage();
    });
  });
}

function renderScoreTable(doc) {
  const tbody = document.querySelector("#scoreTable tbody");
  tbody.innerHTML = doc.runs.map((run) => {
    const score = run.scorecard || {};
    const ingest = run.ingest || {};
    const tagging = run.tagging || {};
    const selected = state.selectedRuns.has(run.id) ? "checked" : "";
    return `
      <tr>
        <td><input class="score-check" type="checkbox" value="${run.id}" ${selected}></td>
        <td><strong>${run.profile}</strong><div class="run-meta">${shortId(run.id)}</div></td>
        <td>${run.model || run.provider || ""}</td>
        <td>${run.pages.join(", ")}</td>
        <td class="number">${metric(score.text_recall_avg)}</td>
        <td class="number">${metric(score.text_recall_min)}</td>
        <td class="number">${metric(score.extra_text_ratio_avg)}</td>
        <td class="number">${metric(score.bbox_coverage)}</td>
        <td class="number">${money(run.cost_usd)}</td>
        <td>${ingest.loaded ? `<span class="pill good">${ingest.node_count} nodes</span>` : `<span class="pill bad">not loaded</span>`}</td>
        <td>${tagging.semantic_observation_count ? `<span class="pill good">${tagging.semantic_observation_count}</span>` : `<span class="pill warn">none</span>`}</td>
      </tr>
    `;
  }).join("");
  tbody.querySelectorAll(".score-check").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selectedRuns.add(input.value);
      else state.selectedRuns.delete(input.value);
      renderRunPicker(doc);
      refreshPage();
    });
  });
}

async function refreshPage() {
  const doc = currentDocument();
  if (!doc || !state.page) return;
  const runIds = [...state.selectedRuns];
  if (!runIds.length) {
    document.getElementById("compareColumns").innerHTML = "";
    return;
  }
  const params = new URLSearchParams({
    document_id: state.documentId,
    page: String(state.page),
    runs: runIds.join(","),
  });
  const response = await fetch(`/api/page?${params.toString()}`);
  const data = await response.json();
  document.getElementById("pageLabel").textContent = `${doc.filename} · page ${state.page}`;
  document.getElementById("compareLabel").textContent = `${data.runs.length} selected runs`;
  document.getElementById("sourceText").textContent = data.source_text || "";
  state.pageData = data;
  state.review = data.review || defaultReview();
  renderImage(data.image_asset);
  renderReviewForm(data);
  renderColumns(data.runs);
}

function renderImage(asset) {
  const wrap = document.getElementById("pageImageWrap");
  if (!asset || !asset.path) {
    wrap.innerHTML = `<span class="pill warn">no page image</span>`;
    return;
  }
  const url = `/asset?path=${encodeURIComponent(asset.path)}`;
  wrap.innerHTML = `<img src="${url}" alt="Page image">`;
}

function renderColumns(rows) {
  const columns = document.getElementById("compareColumns");
  columns.innerHTML = rows.map((row) => runPanel(row.run, row.page)).join("");
}

function renderReviewForm(data) {
  const wrap = document.getElementById("reviewForm");
  const review = state.review || defaultReview();
  const selectedRows = data.runs || [];
  const winnerOptions = [
    `<option value="">No winner</option>`,
    ...selectedRows.map((row) => {
      const selected = review.winning_parse_run_id === row.run.id ? "selected" : "";
      return `<option value="${escapeAttr(row.run.id)}" ${selected}>${escapeHtml(row.run.profile)} · ${shortId(row.run.id)}</option>`;
    }),
  ].join("");
  const rejected = new Set(review.rejected_run_ids || []);
  wrap.innerHTML = `
    <div class="review-head">
      <div>
        <div class="subhead">Review</div>
        <div class="run-meta">${review.updated_at ? `Saved ${escapeHtml(review.updated_at)}` : "Not saved"}</div>
      </div>
      <button id="saveReview" type="button">Save Review</button>
    </div>
    <div class="review-fields">
      <label class="field compact">
        <span>Status</span>
        <select id="reviewStatus">
          ${option("unreviewed", "Unreviewed", review.status)}
          ${option("needs_review", "Needs review", review.status)}
          ${option("reviewed", "Reviewed", review.status)}
        </select>
      </label>
      <label class="field compact">
        <span>Page Type</span>
        <select id="pageType">
          ${option("", "Unset", review.page_type)}
          ${option("text", "Text", review.page_type)}
          ${option("table", "Table", review.page_type)}
          ${option("diagram", "Diagram", review.page_type)}
          ${option("organogram", "Organogram", review.page_type)}
          ${option("mixed", "Mixed", review.page_type)}
          ${option("blank", "Blank", review.page_type)}
        </select>
      </label>
      <label class="field compact wide">
        <span>Winning Run</span>
        <select id="winningRun">${winnerOptions}</select>
      </label>
      <label class="field compact wide">
        <span>Rejection Reason</span>
        <select id="rejectionReason">
          ${option("", "None", review.rejection_reason)}
          ${option("missing_text", "Missing text", review.rejection_reason)}
          ${option("extra_text", "Extra text", review.rejection_reason)}
          ${option("bad_reading_order", "Bad reading order", review.rejection_reason)}
          ${option("table_error", "Table error", review.rejection_reason)}
          ${option("diagram_error", "Diagram error", review.rejection_reason)}
          ${option("bad_bbox", "Bad bbox", review.rejection_reason)}
          ${option("formatting_error", "Formatting error", review.rejection_reason)}
        </select>
      </label>
    </div>
    <div class="subhead">Rejected Runs</div>
    <div class="reject-list">
      ${selectedRows.map((row) => `
        <label class="reject-option">
          <input type="checkbox" value="${escapeAttr(row.run.id)}" ${rejected.has(row.run.id) ? "checked" : ""}>
          <span>${escapeHtml(row.run.profile)}</span>
        </label>
      `).join("") || `<span class="pill warn">select runs to reject</span>`}
    </div>
    <label class="field compact">
      <span>Notes</span>
      <textarea id="reviewNotes" rows="3">${escapeHtml(review.notes || "")}</textarea>
    </label>
    <div id="reviewSaveState" class="save-state"></div>
  `;
  document.getElementById("saveReview").addEventListener("click", saveReview);
}

async function saveReview() {
  const saveState = document.getElementById("reviewSaveState");
  saveState.textContent = "Saving...";
  const rejectedRunIds = [...document.querySelectorAll(".reject-option input:checked")].map((input) => input.value);
  const payload = {
    document_id: state.documentId,
    page_number: state.page,
    status: document.getElementById("reviewStatus").value,
    page_type: document.getElementById("pageType").value,
    winning_parse_run_id: document.getElementById("winningRun").value,
    rejected_run_ids: rejectedRunIds,
    rejection_reason: document.getElementById("rejectionReason").value,
    notes: document.getElementById("reviewNotes").value,
  };
  const response = await fetch("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    saveState.textContent = data.error || "Save failed";
    saveState.className = "save-state bad";
    return;
  }
  state.review = data.review || defaultReview();
  saveState.textContent = "Saved";
  saveState.className = "save-state good";
  renderReviewForm({ ...state.pageData, review: state.review });
}

function runPanel(run, page) {
  const metrics = page.metrics || {};
  const ingest = page.ingested || {};
  const warnings = page.warnings || [];
  return `
    <article class="run-panel">
      <header>
        <h3>${run.profile}</h3>
        <div class="run-meta">${run.model || run.provider || ""}</div>
      </header>
      <div class="metrics">
        <span class="pill ${metrics.text_recall !== undefined && metrics.text_recall < 0.95 ? "bad" : "good"}">Recall ${metric(metrics.text_recall)}</span>
        <span class="pill ${metrics.extra_text_ratio !== undefined && metrics.extra_text_ratio > 0.15 ? "warn" : "good"}">Extra ${metric(metrics.extra_text_ratio)}</span>
        <span class="pill">Head ${metric(metrics.heading_score)}</span>
        <span class="pill">Tables ${metric(metrics.parsed_table_count)}</span>
        <span class="pill ${run.ingest?.loaded ? "good" : "bad"}">Ingest ${run.ingest?.loaded ? "loaded" : "missing"}</span>
        <span class="pill ${run.tagging?.semantic_observation_count ? "good" : "warn"}">Tags ${run.tagging?.semantic_observation_count || 0}</span>
      </div>
      <section class="panel-section">
        <div class="subhead">Generated Markdown</div>
        <pre class="markdown-box">${escapeHtml(page.generated_markdown || "")}</pre>
      </section>
      <section class="panel-section">
        <div class="subhead">Ingested Nodes</div>
        ${ingest.loaded ? `<pre class="markdown-box">${escapeHtml(ingest.markdown || "")}</pre>${nodeList(ingest.nodes || [])}` : `<span class="pill bad">not loaded into SQLite</span>`}
      </section>
      <section class="panel-section">
        <div class="subhead">Warnings</div>
        ${warningList(warnings)}
      </section>
    </article>
  `;
}

function nodeList(nodes) {
  if (!nodes.length) return `<div class="node-list"><div class="node-row">No page nodes</div></div>`;
  return `
    <div class="node-list">
      ${nodes.slice(0, 80).map((node) => `
        <div class="node-row">
          <strong>${node.type} · ${node.metadata?.block_type || node.label || ""}</strong>
          <span>${escapeHtml((node.text || node.markdown || "").slice(0, 220))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function warningList(warnings) {
  if (!warnings.length) return `<div class="warning-list"><div class="warning-row">No warnings on this page</div></div>`;
  return `
    <div class="warning-list">
      ${warnings.slice(0, 80).map((warning) => `
        <div class="warning-row">
          <strong>${escapeHtml(warning.code || "warning")}</strong>
          <span>${escapeHtml(warning.message || JSON.stringify(warning))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function option(value, label, current) {
  const selected = String(current || "") === value ? "selected" : "";
  return `<option value="${escapeAttr(value)}" ${selected}>${escapeHtml(label)}</option>`;
}

function defaultReview() {
  return {
    status: "unreviewed",
    page_type: "",
    winning_parse_run_id: "",
    rejected_run_ids: [],
    rejection_reason: "",
    notes: "",
    updated_at: null,
  };
}

loadOverview().catch((error) => {
  document.body.innerHTML = `<pre class="text-box">${escapeHtml(error.stack || error)}</pre>`;
});
