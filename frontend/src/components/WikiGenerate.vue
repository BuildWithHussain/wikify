<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from "vue";
import { Badge, Button, Dialog, FormControl, TabButtons, useCall, useList, toast } from "frappe-ui";
import WikiPreview from "@/components/WikiPreview.vue";
import { useSocket } from "@/socket";

const props = defineProps({
	sourceDocument: { type: String, default: null },
	importName: { type: String, default: null },
	status: { type: String, default: null },
	wikiSpace: { type: String, default: null },
});
const emit = defineEmits(["generated"]);

// Generation is gated on an approved tree (Graphed) — or a prior run (Completed → it
// regenerates in place). Once generated, the space link + Regenerate stay available.
const graphed = computed(() => ["Graphed", "Completed", "Generating Wiki"].includes(props.status));
const generating = computed(() => props.status === "Generating Wiki");
const alreadyGenerated = computed(() => props.status === "Completed" || !!props.wikiSpace);

// Existing spaces (also resolves the current space's route for the "View wiki" link).
const spaces = useList({
	doctype: "Wiki Space",
	fields: ["name", "space_name", "route"],
	orderBy: "modified desc",
	limit: 100,
	auto: true,
});
const currentSpace = computed(() => (spaces.data || []).find((s) => s.name === props.wikiSpace));

// Target choice: reuse an existing space, or create a new one.
const mode = ref("existing");
const targetSpace = ref(null);
const newName = ref("");
const newRoute = ref("");
watch(
	() => spaces.data,
	(list) => {
		if (!list?.length) mode.value = "new";
		else if (!targetSpace.value) targetSpace.value = props.wikiSpace || list[0]?.name;
	},
	{ immediate: true },
);
// Suggest a slug-y route from the typed name.
watch(newName, (n) => {
	newRoute.value = (n || "")
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "");
});

const spaceOptions = computed(() =>
	(spaces.data || []).map((s) => ({ label: `${s.space_name} (/${s.route})`, value: s.name })),
);

// Preview — projected structure, no writes. Flattened to indented rows for display.
const preview = useCall({
	url: "/api/v2/method/wikify.api.imports.preview_wiki",
	method: "GET",
	immediate: false,
});
function loadPreview() {
	if (props.importName) preview.submit({ import_name: props.importName });
}
const previewRows = computed(() => {
	const out = [];
	const walk = (nodes, depth) => {
		for (const n of nodes || []) {
			out.push({
				name: n.name,
				title: n.title,
				is_group: n.is_group,
				depth,
				page_start: n.page_start,
				page_end: n.page_end,
			});
			walk(n.children, depth + 1);
		}
	};
	walk(preview.data?.tree, 0);
	return out;
});
watch(graphed, (ok) => ok && loadPreview(), { immediate: true });

// Generate / regenerate.
const generate = useCall({
	url: "/api/v2/method/wikify.api.imports.generate_wiki",
	method: "POST",
	immediate: false,
});
const canGenerate = computed(() =>
	mode.value === "existing" ? !!targetSpace.value : !!(newName.value && newRoute.value),
);
async function runGenerate() {
	const params = { import_name: props.importName };
	if (mode.value === "existing") params.wiki_space = targetSpace.value;
	else params.new_space = { space_name: newName.value, route: newRoute.value };
	await generate.submit(params);
	if (generate.error) {
		toast.error(generate.error?.messages?.[0] || "Could not start wiki generation");
		return;
	}
	emit("generated");
}

// Realtime — the job emits wikify_wiki_done on completion.
const lastRoute = ref(null);
const socket = useSocket();
function onWikiDone(payload) {
	if (payload.import !== props.importName) return;
	lastRoute.value = payload.space_route;
	spaces.reload();
	emit("generated");
	toast.success("Wiki generated");
}
onMounted(() => socket?.on("wikify_wiki_done", onWikiDone));
onUnmounted(() => socket?.off("wikify_wiki_done", onWikiDone));

const wikiUrl = computed(() => {
	const route = lastRoute.value || currentSpace.value?.route;
	return route ? `/${route}` : null;
});

function pageRange(n) {
	if (n.page_start == null) return "";
	return n.page_start === n.page_end ? `p${n.page_start}` : `p${n.page_start}–${n.page_end}`;
}

// Clicking a projected node opens the same wiki preview as the Tree tab.
const previewSection = ref(null);
const previewOpen = computed({
	get: () => !!previewSection.value,
	set: (v) => {
		if (!v) previewSection.value = null;
	},
});
</script>

<template>
	<div class="flex h-full flex-col">
		<!-- Not yet approved -->
		<div v-if="!graphed" class="flex flex-1 items-center justify-center p-8">
			<div class="max-w-md text-center">
				<p class="text-base text-ink-gray-7">Approve the section tree first</p>
				<p class="mt-1 text-sm text-ink-gray-5">
					Review and arrange the tree, then
					<span class="font-medium">Approve &amp; Build Graph</span> on the Tree tab to
					unlock wiki generation.
				</p>
			</div>
		</div>

		<div v-else class="flex min-h-0 flex-1">
			<!-- Left: target + actions -->
			<div class="flex w-80 shrink-0 flex-col gap-4 border-r border-outline-gray-1 p-4">
				<div>
					<p class="text-sm font-medium text-ink-gray-8">Generate wiki</p>
					<p class="mt-0.5 text-xs text-ink-gray-5">
						Mirror the approved tree into a Wiki Space as linked pages.
					</p>
				</div>

				<!-- Already generated → link to it -->
				<div
					v-if="alreadyGenerated && wikiUrl"
					class="rounded-md border border-outline-gray-2 bg-surface-gray-1 p-3"
				>
					<p class="text-xs text-ink-gray-5">Generated wiki</p>
					<a
						:href="wikiUrl"
						target="_blank"
						class="mt-1 inline-flex items-center gap-1 text-sm font-medium text-ink-blue-6 hover:underline"
					>
						{{ currentSpace?.space_name || "Open wiki" }}
						<span aria-hidden>↗</span>
					</a>
				</div>

				<!-- Target chooser -->
				<TabButtons
					v-model="mode"
					:options="[
						{ label: 'Existing space', value: 'existing' },
						{ label: 'New space', value: 'new' },
					]"
				/>

				<template v-if="mode === 'existing'">
					<FormControl
						v-if="spaceOptions.length"
						type="select"
						label="Wiki Space"
						:options="spaceOptions"
						v-model="targetSpace"
					/>
					<p v-else class="text-sm text-ink-gray-5">No spaces yet — create one.</p>
				</template>
				<template v-else>
					<FormControl
						type="text"
						label="Space name"
						placeholder="My Manual"
						v-model="newName"
					/>
					<FormControl
						type="text"
						label="Route"
						placeholder="my-manual"
						v-model="newRoute"
					/>
				</template>

				<Button
					variant="solid"
					:label="alreadyGenerated ? 'Regenerate wiki' : 'Generate wiki'"
					:loading="generate.loading || generating"
					:disabled="!canGenerate || generating"
					@click="runGenerate"
				/>
				<p v-if="generating" class="text-xs text-ink-gray-5">
					Generating… watch progress in the header.
				</p>
			</div>

			<!-- Right: preview of what will be generated -->
			<div class="flex min-h-0 flex-1 flex-col">
				<div
					class="flex items-center gap-2 border-b border-outline-gray-1 px-4 py-2 text-sm text-ink-gray-6"
				>
					<span class="font-medium text-ink-gray-8">Preview</span>
					<Badge
						v-if="preview.data"
						:label="`${preview.data.pages} pages · ${preview.data.groups} groups`"
						theme="gray"
						variant="subtle"
						size="sm"
					/>
					<Badge
						v-if="preview.data?.excluded"
						:label="`${preview.data.excluded} excluded`"
						theme="orange"
						variant="subtle"
						size="sm"
					/>
					<Button
						class="ml-auto"
						size="sm"
						variant="subtle"
						icon-left="lucide-refresh-cw"
						label="Refresh"
						:loading="preview.loading"
						@click="loadPreview"
					/>
				</div>
				<div class="min-h-0 flex-1 overflow-auto p-2">
					<p
						v-if="!previewRows.length && !preview.loading"
						class="py-10 text-center text-sm text-ink-gray-5"
					>
						No sections to generate — include sections in the tree first.
					</p>
					<button
						v-for="row in previewRows"
						:key="row.name"
						type="button"
						class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-surface-gray-2"
						:style="{ paddingLeft: `${row.depth * 1.25 + 0.5}rem` }"
						@click="previewSection = row.name"
					>
						<span
							class="size-4 shrink-0 text-ink-gray-4"
							:class="row.is_group ? 'lucide-folder' : 'lucide-file-text'"
							aria-hidden="true"
						/>
						<span class="truncate text-sm text-ink-gray-8">{{ row.title }}</span>
						<Badge
							v-if="pageRange(row)"
							:label="pageRange(row)"
							theme="gray"
							variant="subtle"
							size="sm"
							class="ml-auto shrink-0"
						/>
					</button>
				</div>
			</div>
		</div>

		<!-- Wiki preview of a projected node (same component as the Tree tab) -->
		<Dialog v-model:open="previewOpen" :options="{ size: '4xl' }">
			<template #body>
				<div class="h-[75vh]">
					<WikiPreview :section="previewSection" @navigate="(n) => (previewSection = n)" />
				</div>
			</template>
		</Dialog>
	</div>
</template>
