<script setup>
import { computed, ref, onMounted, onUnmounted } from "vue";
import { Badge, Button, Dropdown, Progress, Tabs, useCall, useDoc, useList } from "frappe-ui";
import { useSocket } from "@/socket";
import { statusTheme, isActive } from "@/utils/status";
import PageReview from "@/components/PageReview.vue";
import SectionTree from "@/components/SectionTree.vue";

const props = defineProps({
	name: { type: String, required: true },
	tab: { type: String, default: "overview" },
});

const imp = useDoc({ doctype: "Wikify Import", name: props.name });

const tabs = [
	{ label: "Overview", key: "overview" },
	{ label: "Pages", key: "pages" },
	{ label: "Tree", key: "tree" },
];
const activeTab = ref({ pages: 1, tree: 2 }[props.tab] ?? 0);

// Streaming log
const logs = useList({
	doctype: "Import Log Entry",
	fields: ["name", "idx_seq", "level", "stage", "message", "creation"],
	filters: { import: props.name },
	orderBy: "idx_seq asc",
	limit: 500,
});

const status = computed(() => imp.doc?.status);
const canRemediate = computed(() => status.value === "Review" && !!imp.doc?.source_document);

const pageReview = ref(null);
const sectionTree = ref(null);

// Remediation — route flagged (or all) pages through cleanup/VLM, adopt the best.
const remediate = useCall({
	url: "/api/v2/method/wikify.api.imports.trigger_remediation",
	method: "POST",
	immediate: false,
});
function runRemediation(scope) {
	remediate.submit({ import_name: props.name, scope });
}

// Realtime
const socket = useSocket();
function onProgress(payload) {
	if (payload.import !== props.name || !imp.doc) return;
	const wasRemediating = imp.doc.status === "Remediating";
	imp.doc.stage_progress = payload.percent;
	if (payload.status) imp.doc.status = payload.status;
	// Terminal transitions carry fields set server-side (source_document, error).
	if (payload.status === "Review" || payload.status === "Failed") {
		imp.reload();
		// A finished remediation rewrote canonical scores + rebuilt the tree — refetch both.
		if (wasRemediating && payload.status === "Review") {
			pageReview.value?.reload();
			sectionTree.value?.reload();
		}
	}
}
function onLog(payload) {
	if (payload.import !== props.name) return;
	if (Array.isArray(logs.data)) {
		logs.data.push({
			name: `live-${payload.idx_seq}`,
			idx_seq: payload.idx_seq,
			level: payload.level,
			stage: payload.stage,
			message: payload.message,
		});
	}
}
onMounted(() => {
	socket?.on("wikify_import_progress", onProgress);
	socket?.on("wikify_import_log", onLog);
});
onUnmounted(() => {
	socket?.off("wikify_import_progress", onProgress);
	socket?.off("wikify_import_log", onLog);
});

const levelColor = { info: "text-ink-gray-7", warn: "text-ink-amber-6", error: "text-ink-red-6" };
</script>

<template>
	<div class="flex h-full flex-col">
		<header
			class="sticky top-0 z-10 flex min-h-12 items-center gap-3 border-b border-outline-gray-1 bg-surface-base px-3 sm:px-5"
		>
			<Button variant="ghost" icon="lucide-arrow-left" :route="{ name: 'Imports' }" />
			<h1 class="truncate text-lg text-ink-gray-9">{{ imp.doc?.import_title || name }}</h1>
			<Badge v-if="status" :label="status" :theme="statusTheme(status)" variant="subtle" />
			<Progress
				v-if="isActive(status)"
				:value="imp.doc?.stage_progress || 0"
				size="sm"
				class="w-40"
			/>
			<span v-if="isActive(status)" class="text-sm text-ink-gray-5">{{
				imp.doc?.stage_label
			}}</span>

			<Dropdown
				v-if="canRemediate"
				class="ml-auto"
				:options="[
					{ label: 'Remediate flagged', onClick: () => runRemediation('flagged') },
					{ label: 'Remediate all pages', onClick: () => runRemediation('all') },
				]"
			>
				<Button
					variant="solid"
					theme="gray"
					label="Remediate"
					icon-right="lucide-chevron-down"
					:loading="remediate.loading"
				/>
			</Dropdown>
		</header>

		<Tabs v-model="activeTab" :tabs="tabs">
			<template #tab-panel="{ tab }">
				<!-- Overview -->
				<div v-if="tab.key === 'overview'" class="body-container pt-5 pb-40">
					<div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
						<div>
							<p class="text-sm text-ink-gray-5">Pages</p>
							<p class="text-base text-ink-gray-8">
								{{ imp.doc?.page_count ?? "—" }}
							</p>
						</div>
						<div>
							<p class="text-sm text-ink-gray-5">Status</p>
							<p class="text-base text-ink-gray-8">{{ status }}</p>
						</div>
						<div>
							<p class="text-sm text-ink-gray-5">Started</p>
							<p class="text-base text-ink-gray-8">
								{{ imp.doc?.started_at || "—" }}
							</p>
						</div>
						<div>
							<p class="text-sm text-ink-gray-5">Completed</p>
							<p class="text-base text-ink-gray-8">
								{{ imp.doc?.completed_at || "—" }}
							</p>
						</div>
					</div>

					<div
						v-if="imp.doc?.error"
						class="mt-5 rounded border border-outline-red-3 bg-surface-red-2 p-3"
					>
						<p class="mb-1 text-sm font-medium text-ink-red-6">Error</p>
						<pre class="overflow-x-auto whitespace-pre-wrap text-xs text-ink-red-6">{{
							imp.doc.error
						}}</pre>
					</div>

					<div class="mt-6">
						<p class="mb-2 text-sm text-ink-gray-5">Log</p>
						<div
							class="rounded-md border border-outline-gray-1 bg-surface-gray-1 p-3 font-mono text-xs"
						>
							<p v-if="!logs.data?.length" class="text-ink-gray-5">
								No log entries yet.
							</p>
							<div
								v-for="entry in logs.data"
								:key="entry.name"
								class="flex gap-2 py-0.5"
								:class="levelColor[entry.level] || 'text-ink-gray-7'"
							>
								<span class="shrink-0 text-ink-gray-4">[{{ entry.stage }}]</span>
								<span>{{ entry.message }}</span>
							</div>
						</div>
					</div>
				</div>

				<!-- Pages -->
				<div v-else-if="tab.key === 'pages'" class="h-[calc(100vh-7rem)]">
					<PageReview
						ref="pageReview"
						:source-document="imp.doc?.source_document"
						:pdf-url="imp.doc?.pdf"
					/>
				</div>

				<!-- Tree -->
				<div v-else-if="tab.key === 'tree'" class="h-[calc(100vh-7rem)]">
					<SectionTree
						ref="sectionTree"
						:source-document="imp.doc?.source_document"
						:doc-title="imp.doc?.import_title || name"
						:import-name="name"
						:status="status"
						@graphed="imp.reload()"
					/>
				</div>
			</template>
		</Tabs>
	</div>
</template>
