<script setup>
import { computed, ref, watch } from "vue";
import { Badge, Button, useList } from "frappe-ui";
import { CodeEditor } from "frappe-ui/code-editor";
import { Splitpanes, Pane } from "splitpanes";
import "splitpanes/dist/splitpanes.css";

const props = defineProps({
	sourceDocument: { type: String, default: null },
	pdfUrl: { type: String, default: null },
});

const pages = useList({
	doctype: "Source Page",
	fields: [
		"name",
		"page_no",
		"kind",
		"image",
		"baseline_markdown",
		"verdict",
		"composite",
		"text_recall",
		"extra_ratio",
		"table_score",
		"judge_score",
		"notes",
		"remediation_method",
		"remediation_adopted",
		"remediation_composite",
		"remediation_notes",
		"remediation_markdown",
		"canonical_source",
		"canonical_composite",
		"canonical_markdown",
	],
	filters: computed(() => ({ source_document: props.sourceDocument || "__none__" })),
	orderBy: "page_no asc",
	limit: 1000,
	auto: true,
});

// Let the parent (ImportDetail) refetch after a remediation run completes.
defineExpose({ reload: () => pages.reload() });

// Default to the Flagged view — the operator's job is triaging non-pass pages.
const filter = ref("flagged");
const filters = [
	{ label: "Flagged", key: "flagged" },
	{ label: "All", key: "all" },
];

const visiblePages = computed(() => {
	const all = pages.data || [];
	if (filter.value === "flagged") return all.filter((p) => p.verdict !== "pass");
	return all;
});

const selectedName = ref(null);
const selected = computed(
	() => (pages.data || []).find((p) => p.name === selectedName.value) || null,
);

// Keep a valid selection as the list / filter changes.
watch(
	visiblePages,
	(list) => {
		if (!list.length) {
			selectedName.value = null;
		} else if (!list.some((p) => p.name === selectedName.value)) {
			selectedName.value = list[0].name;
		}
	},
	{ immediate: true },
);

const flaggedCount = computed(() => (pages.data || []).filter((p) => p.verdict !== "pass").length);

const tabs = [
	{ label: "PDF", key: "pdf" },
	{ label: "Snapshot", key: "snapshot" },
	{ label: "Markdown", key: "markdown" },
];
const activeTab = ref("markdown");

const verdictTheme = { pass: "green", escalate: "orange", review: "red" };

// Markdown sub-view: Baseline vs Remediation vs Canonical. Remediation/Canonical
// options only appear once a remediation pass has produced them for the page.
const mdView = ref("baseline");
const mdViews = computed(() => {
	const p = selected.value;
	const views = [{ label: "Baseline", key: "baseline" }];
	if (p?.remediation_method) views.push({ label: "Remediation", key: "remediation" });
	if (p?.canonical_source) views.push({ label: "Canonical", key: "canonical" });
	return views;
});
// Keep the chosen view valid as the selection changes; prefer canonical when present.
watch(
	selected,
	(p) => {
		const keys = mdViews.value.map((v) => v.key);
		if (!keys.includes(mdView.value)) {
			mdView.value = p?.canonical_source ? "canonical" : "baseline";
		}
	},
	{ immediate: true },
);
const mdContent = computed(() => {
	const p = selected.value;
	if (!p) return "";
	if (mdView.value === "remediation") return p.remediation_markdown || "";
	if (mdView.value === "canonical") return p.canonical_markdown || "";
	return p.baseline_markdown || "";
});

// 0.0 reads as "n/a" for table/judge (no table on the page / not judged). A genuine
// table miss still surfaces via the harness notes, so hiding the bare 0 is honest.
function fmt(v) {
	return v === null || v === undefined ? "—" : Number(v).toFixed(2);
}
function fmtOptional(v) {
	return v ? Number(v).toFixed(2) : "—";
}

const pdfSrc = computed(() =>
	selected.value && props.pdfUrl
		? `${props.pdfUrl}#page=${selected.value.page_no}&view=FitH`
		: null,
);

// Scores strip: text pages show the full deterministic set; visual pages drop
// recall/extra (meaningless on diagrams) and lean on the judge.
const scoreCells = computed(() => {
	const p = selected.value;
	if (!p) return [];
	if (p.kind === "visual") {
		return [
			{ label: "Judge", value: fmtOptional(p.judge_score) },
			{ label: "Table", value: fmtOptional(p.table_score) },
			{ label: "Composite", value: fmt(p.composite), strong: true },
		];
	}
	return [
		{ label: "Recall", value: fmt(p.text_recall) },
		{ label: "Extra", value: fmt(p.extra_ratio) },
		{ label: "Table", value: fmtOptional(p.table_score) },
		{ label: "Judge", value: fmtOptional(p.judge_score) },
		{ label: "Composite", value: fmt(p.composite), strong: true },
	];
});

// Before↔after summary once a page has been remediated: which method ran, whether
// it was adopted as canonical, and the baseline→remediation composite delta.
const remediation = computed(() => {
	const p = selected.value;
	if (!p?.remediation_method) return null;
	const delta = Number(p.remediation_composite || 0) - Number(p.composite || 0);
	return {
		method: p.remediation_method,
		adopted: !!p.remediation_adopted,
		base: p.composite,
		after: p.remediation_composite,
		delta,
		canonical: p.canonical_composite,
		notes: p.remediation_notes,
	};
});
function fmtDelta(v) {
	const n = Number(v || 0);
	return `${n >= 0 ? "+" : ""}${n.toFixed(3)}`;
}
</script>

<template>
	<div class="h-full">
		<p v-if="!pages.data?.length" class="py-10 text-center text-sm text-ink-gray-5">
			No pages yet — parse still running or not started.
		</p>

		<Splitpanes v-else class="h-full">
			<!-- Left: thumbnail list -->
			<Pane :size="30" :min-size="20" class="flex flex-col border-r border-outline-gray-1">
				<div class="flex items-center gap-1 border-b border-outline-gray-1 px-3 py-2">
					<Button
						v-for="f in filters"
						:key="f.key"
						:label="f.key === 'flagged' ? `Flagged (${flaggedCount})` : 'All'"
						size="sm"
						:variant="filter === f.key ? 'subtle' : 'ghost'"
						@click="filter = f.key"
					/>
				</div>
				<div class="flex-1 overflow-y-auto p-2">
					<p
						v-if="!visiblePages.length"
						class="px-2 py-6 text-center text-sm text-ink-gray-5"
					>
						No flagged pages — everything passed.
					</p>
					<button
						v-for="page in visiblePages"
						:key="page.name"
						class="mb-1 flex w-full items-center gap-2 rounded-md p-1.5 text-left hover:bg-surface-gray-2"
						:class="selectedName === page.name ? 'bg-surface-gray-3' : ''"
						@click="selectedName = page.name"
					>
						<img
							v-if="page.image"
							:src="page.image"
							:alt="`Page ${page.page_no}`"
							class="h-14 w-11 shrink-0 rounded border border-outline-gray-1 object-cover object-top"
						/>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-1.5">
								<span class="text-sm font-medium text-ink-gray-8"
									>Page {{ page.page_no }}</span
								>
								<Badge
									:label="page.kind"
									:theme="page.kind === 'visual' ? 'orange' : 'gray'"
									variant="subtle"
									size="sm"
								/>
							</div>
							<div class="mt-1 flex items-center gap-1.5">
								<Badge
									:label="page.verdict || '—'"
									:theme="verdictTheme[page.verdict] || 'gray'"
									variant="subtle"
									size="sm"
								/>
								<span class="text-xs text-ink-gray-5">{{
									fmt(page.composite)
								}}</span>
								<Badge
									v-if="page.remediation_adopted"
									label="remediated"
									theme="blue"
									variant="subtle"
									size="sm"
								/>
							</div>
						</div>
					</button>
				</div>
			</Pane>

			<!-- Right: detail -->
			<Pane :size="70" class="flex flex-col">
				<template v-if="selected">
					<!-- Scores strip -->
					<div class="border-b border-outline-gray-1 px-4 py-3">
						<div class="mb-2 flex items-center gap-2">
							<span class="text-base font-medium text-ink-gray-9"
								>Page {{ selected.page_no }}</span
							>
							<Badge
								:label="selected.verdict || '—'"
								:theme="verdictTheme[selected.verdict] || 'gray'"
								variant="subtle"
							/>
							<Badge
								:label="selected.kind"
								:theme="selected.kind === 'visual' ? 'orange' : 'gray'"
								variant="subtle"
							/>
						</div>
						<div class="flex flex-wrap gap-x-6 gap-y-1">
							<div
								v-for="c in scoreCells"
								:key="c.label"
								class="flex items-baseline gap-1.5"
							>
								<span class="text-xs uppercase tracking-wide text-ink-gray-5">{{
									c.label
								}}</span>
								<span
									class="text-sm tabular-nums"
									:class="
										c.strong
											? 'font-semibold text-ink-gray-9'
											: 'text-ink-gray-7'
									"
									>{{ c.value }}</span
								>
							</div>
						</div>
						<p
							v-if="selected.kind === 'visual'"
							class="mt-1.5 text-xs text-ink-gray-5"
						>
							Recall / extra are not meaningful on visual pages — judged on the
							rendered image.
						</p>
						<p v-if="selected.notes" class="mt-1.5 text-xs text-ink-amber-6">
							{{ selected.notes }}
						</p>

						<!-- Remediation before↔after -->
						<div
							v-if="remediation"
							class="mt-2 flex flex-wrap items-center gap-2 border-t border-outline-gray-1 pt-2"
						>
							<Badge
								:label="remediation.method"
								theme="blue"
								variant="subtle"
								size="sm"
							/>
							<Badge
								:label="remediation.adopted ? 'adopted' : 'kept baseline'"
								:theme="remediation.adopted ? 'green' : 'gray'"
								variant="subtle"
								size="sm"
							/>
							<span class="text-xs text-ink-gray-6">
								{{ fmt(remediation.base) }} → {{ fmt(remediation.after) }}
								<span
									class="ml-1 tabular-nums"
									:class="
										remediation.delta >= 0
											? 'text-ink-green-6'
											: 'text-ink-red-6'
									"
									>({{ fmtDelta(remediation.delta) }})</span
								>
							</span>
							<span class="text-xs text-ink-gray-5">
								canonical {{ fmt(remediation.canonical) }}
							</span>
						</div>
						<p v-if="remediation?.notes" class="mt-1 text-xs text-ink-gray-5">
							{{ remediation.notes }}
						</p>
					</div>

					<!-- Tabs (PDF / Snapshot / Markdown) -->
					<div
						class="flex items-center gap-1 border-b border-outline-gray-1 px-3 py-1.5"
					>
						<Button
							v-for="t in tabs"
							:key="t.key"
							:label="t.label"
							size="sm"
							:variant="activeTab === t.key ? 'subtle' : 'ghost'"
							@click="activeTab = t.key"
						/>
					</div>

					<div class="min-h-0 flex-1 overflow-auto">
						<!-- PDF -->
						<template v-if="activeTab === 'pdf'">
							<object
								v-if="pdfSrc"
								:data="pdfSrc"
								type="application/pdf"
								class="h-full w-full"
							>
								<p class="p-4 text-sm text-ink-gray-5">
									Can't embed the PDF here —
									<a :href="pdfUrl" target="_blank" class="underline"
										>open it in a new tab</a
									>.
								</p>
							</object>
							<p v-else class="p-4 text-sm text-ink-gray-5">No PDF attached.</p>
						</template>

						<!-- Snapshot -->
						<div v-else-if="activeTab === 'snapshot'" class="p-4">
							<img
								v-if="selected.image"
								:src="selected.image"
								:alt="`Page ${selected.page_no} snapshot`"
								class="mx-auto max-w-full rounded border border-outline-gray-1"
							/>
							<p v-else class="text-sm text-ink-gray-5">No snapshot rendered.</p>
						</div>

						<!-- Markdown (Baseline / Remediation / Canonical) -->
						<div v-else-if="activeTab === 'markdown'" class="flex h-full flex-col p-3">
							<div v-if="mdViews.length > 1" class="mb-2 flex items-center gap-1">
								<Button
									v-for="v in mdViews"
									:key="v.key"
									:label="v.label"
									size="sm"
									:variant="mdView === v.key ? 'subtle' : 'ghost'"
									@click="mdView = v.key"
								/>
							</div>
							<CodeEditor
								:model-value="mdContent"
								language="markdown"
								variant="outline"
								:disabled="true"
								class="min-h-0 flex-1"
							/>
						</div>
					</div>
				</template>
				<p v-else class="py-10 text-center text-sm text-ink-gray-5">
					Select a page to review.
				</p>
			</Pane>
		</Splitpanes>
	</div>
</template>
