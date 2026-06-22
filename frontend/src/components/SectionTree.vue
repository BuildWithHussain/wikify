<script setup>
import { computed, ref, watch } from "vue";
import { Badge, Button, Dialog, useCall, useList, toast } from "frappe-ui";
import { Splitpanes, Pane } from "splitpanes";
import "splitpanes/dist/splitpanes.css";
import SectionDraggable from "@/components/SectionDraggable.vue";
import WikiPreview from "@/components/WikiPreview.vue";
import { setSection } from "@/data/agentContext";

const props = defineProps({
	sourceDocument: { type: String, default: null },
	docTitle: { type: String, default: "Document" },
	importName: { type: String, default: null },
	status: { type: String, default: null },
});
const emit = defineEmits(["graphed"]);

// Flat sections ordered by tree position (`lft`); the nesting is rebuilt client-side.
const sections = useList({
	doctype: "Source Section",
	fields: [
		"name",
		"parent_source_section",
		"title",
		"is_group",
		"level",
		"section_type",
		"hierarchy_path",
		"page_start",
		"page_end",
		"sort_order",
		"include_in_wiki",
		"markdown",
	],
	filters: computed(() => ({ source_document: props.sourceDocument || "__none__" })),
	orderBy: "lft asc",
	limit: 1000,
	auto: true,
});
defineExpose({ reload: () => sections.reload() });

const sectionCount = computed(() => (sections.data || []).length);

// Reactive nested tree (vuedraggable mutates these child arrays in place); rebuilt from
// the flat rows whenever the server data changes.
const tree = ref([]);
const byName = computed(() => {
	const out = {};
	for (const r of sections.data || []) out[r.name] = r;
	return out;
});

watch(
	() => sections.data,
	(rows) => {
		const nodes = {};
		for (const r of rows || []) nodes[r.name] = { ...r, children: [] };
		const roots = [];
		for (const r of rows || []) {
			const parent = r.parent_source_section;
			if (parent && nodes[parent]) nodes[parent].children.push(nodes[r.name]);
			else roots.push(nodes[r.name]);
		}
		tree.value = roots;
		if (roots.length && !byName.value[selectedName.value]) selectedName.value = roots[0].name;
	},
	{ immediate: true, deep: false }
);

const selectedName = ref(null);
const selected = computed(() => byName.value[selectedName.value] || null);
function onSelect(name) {
	selectedName.value = name;
}

// Attach the selected section as the agent's default context (swaps out any page chip).
watch(selected, (s) => {
	if (s) setSection({ name: s.name, label: s.title || "Section" });
});

// --- Mutations -----------------------------------------------------------------------
// useCall.submit resolves (doesn't reject) on a server error and sets `.error`, so we
// inspect that. Every mutation re-reads the list from the server to pick up the
// re-derived lft/level/hierarchy_path/is_group (and to revert an optimistic drag on
// failure).
const mutating = ref(false);
async function mutate(call, params) {
	mutating.value = true;
	try {
		await call.submit(params);
		if (call.error) throw call.error;
	} catch (e) {
		toast.error(e?.messages?.[0] || e?.message || "Could not save change");
	} finally {
		await sections.reload();
		mutating.value = false;
	}
}

function sectionCall(method) {
	return useCall({
		url: `/api/v2/method/wikify.api.sections.${method}`,
		method: "POST",
		immediate: false,
	});
}
const reorder = sectionCall("reorder_section");
const rename = sectionCall("rename_section");
const toggle = sectionCall("toggle_include");
const remove = sectionCall("delete_section");
const graph = sectionCall("build_graph");

function onMove({ name, newParent, siblings }) {
	mutate(reorder, { name, new_parent: newParent, new_index: siblings.indexOf(name), siblings });
}
function onRename(name, title) {
	mutate(rename, { name, title });
}
function onToggle(name, include) {
	mutate(toggle, { name, include: include ? 1 : 0 });
}

// Delete with a cascade-aware confirm.
const pendingDelete = ref(null);
const deleteOpen = computed({
	get: () => !!pendingDelete.value,
	set: (v) => {
		if (!v) pendingDelete.value = null;
	},
});
function subtreeSize(node) {
	return 1 + (node.children || []).reduce((n, c) => n + subtreeSize(c), 0);
}
function onRemove(node) {
	pendingDelete.value = node;
}
function confirmDelete() {
	const node = pendingDelete.value;
	pendingDelete.value = null;
	if (selectedName.value === node.name) selectedName.value = null;
	mutate(remove, { name: node.name });
}

// --- Approve & build graph -----------------------------------------------------------
const isGraphed = computed(() => props.status === "Graphed");
async function buildGraph() {
	try {
		await graph.submit({ import_name: props.importName });
		toast.success("Graph built — Explore & Wiki unlocked");
		emit("graphed");
	} catch (e) {
		toast.error(e?.messages?.[0] || e?.message || "Could not build graph");
	}
}

</script>

<template>
	<div class="h-full">
		<p
			v-if="sections.loading && !sections.data"
			class="py-10 text-center text-sm text-ink-gray-5"
		>
			Loading sections…
		</p>
		<p v-else-if="!sectionCount" class="py-10 text-center text-sm text-ink-gray-5">
			No sections yet — parse the document to build its tree.
		</p>

		<Splitpanes v-else class="h-full">
			<!-- Left: the editable section tree -->
			<Pane :size="40" :min-size="25" class="flex flex-col border-r border-outline-gray-1">
				<div
					class="flex items-center gap-2 border-b border-outline-gray-1 px-3 py-2 text-sm text-ink-gray-6"
				>
					<span class="font-medium text-ink-gray-8">Sections</span>
					<Badge :label="String(sectionCount)" theme="gray" variant="subtle" size="sm" />
					<Badge
						v-if="isGraphed"
						label="Graphed"
						theme="green"
						variant="subtle"
						size="sm"
					/>
					<span v-if="mutating" class="text-xs text-ink-gray-4">Saving…</span>
					<Button
						class="ml-auto"
						size="sm"
						variant="solid"
						:label="isGraphed ? 'Rebuild graph' : 'Approve & Build Graph'"
						:loading="graph.loading"
						@click="buildGraph"
					/>
				</div>
				<div class="flex-1 overflow-auto p-2">
					<SectionDraggable
						:list="tree"
						:parent-name="null"
						:selected-name="selectedName"
						:on-select="onSelect"
						:on-move="onMove"
						:on-rename="onRename"
						:on-toggle="onToggle"
						:on-remove="onRemove"
					/>
				</div>
			</Pane>

			<!-- Right: wiki-fidelity preview of the selected section -->
			<Pane :size="60" class="flex flex-col">
				<WikiPreview :section="selectedName" @navigate="onSelect" />
			</Pane>
		</Splitpanes>

		<!-- Cascade-aware delete confirm -->
		<Dialog v-model:open="deleteOpen" title="Delete section">
			<template #default>
				<p class="text-base text-ink-gray-7">
					Delete
					<span class="font-medium text-ink-gray-9">{{ pendingDelete?.title }}</span
					><template v-if="pendingDelete && subtreeSize(pendingDelete) > 1">
						and its {{ subtreeSize(pendingDelete) - 1 }} nested section{{
							subtreeSize(pendingDelete) - 1 === 1 ? "" : "s"
						}}</template
					>? This can't be undone.
				</p>
			</template>
			<template #actions>
				<Button variant="ghost" label="Cancel" @click="pendingDelete = null" />
				<Button variant="solid" theme="red" label="Delete" @click="confirmDelete" />
			</template>
		</Dialog>
	</div>
</template>
