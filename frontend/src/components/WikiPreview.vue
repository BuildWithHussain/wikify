<script setup>
// Wiki-fidelity preview of one Source Section — the wiki-framed sibling of
// MarkdownPreview. The HTML comes from the backend (`api.wiki.render_section_preview`),
// which renders with the *same* renderer the wiki uses (markdown-it-py), so this preview
// matches the eventual generated Wiki Document page. We only post-process ```mermaid
// fences into SVG client-side via the shared wiki mermaid loader (same as today).
import { computed, ref, watch, nextTick } from "vue";
import { Badge, TabButtons, useCall } from "frappe-ui";
import { CodeEditor } from "frappe-ui/code-editor";
import { renderMermaidIn } from "@/utils/mermaid";

const props = defineProps({
	section: { type: String, default: null },
});
const emit = defineEmits(["navigate"]);

const preview = useCall({
	url: "/api/v2/method/wikify.api.wiki.render_section_preview",
	method: "GET",
	immediate: false,
});
function load() {
	if (props.section) preview.submit({ section: props.section });
}
watch(() => props.section, load, { immediate: true });

const data = computed(() => preview.data || null);
const mode = ref("rendered");

const container = ref(null);
async function renderDiagrams() {
	await nextTick();
	renderMermaidIn(container.value);
}
watch([() => data.value?.html, mode], renderDiagrams);

// Internal "page N" refs render as links to a preview sentinel route
// (/section-preview/<name>). Intercept clicks and drive tree navigation instead of
// hitting a non-existent wiki route.
function onBodyClick(e) {
	const a = e.target.closest("a");
	if (!a) return;
	const href = a.getAttribute("href") || "";
	const m = href.match(/section-preview\/([^/?#]+)/);
	if (m) {
		e.preventDefault();
		emit("navigate", decodeURIComponent(m[1]));
	}
}
</script>

<template>
	<div class="flex h-full flex-col">
		<p
			v-if="preview.loading && !data"
			class="py-10 text-center text-sm text-ink-gray-5"
		>
			Loading preview…
		</p>
		<template v-else-if="data">
			<!-- Breadcrumb + Rendered/Source toggle -->
			<div class="flex items-center gap-2 border-b border-outline-gray-1 px-4 py-2">
				<nav class="flex min-w-0 flex-1 items-center gap-1 text-xs text-ink-gray-5">
					<template v-for="(crumb, i) in data.breadcrumb" :key="i">
						<span v-if="i" class="text-ink-gray-3" aria-hidden="true">›</span>
						<span
							class="truncate"
							:class="
								i === data.breadcrumb.length - 1
									? 'font-medium text-ink-gray-7'
									: ''
							"
							>{{ crumb }}</span
						>
					</template>
				</nav>
				<Badge
					v-if="data.page_refs_resolved"
					:label="`${data.page_refs_resolved} ref${
						data.page_refs_resolved === 1 ? '' : 's'
					} → links`"
					theme="blue"
					variant="subtle"
					size="sm"
				/>
				<TabButtons
					v-model="mode"
					:options="[
						{ label: 'Rendered', value: 'rendered', iconLeft: 'lucide-eye' },
						{ label: 'Source', value: 'source', iconLeft: 'lucide-code' },
					]"
				/>
			</div>

			<!-- Excluded banner -->
			<div
				v-if="!data.include_in_wiki"
				class="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-400"
			>
				This section is excluded from the wiki — it won't be generated.
			</div>

			<div class="min-h-0 flex-1 overflow-auto">
				<!-- Rendered wiki page frame -->
				<article
					v-if="mode === 'rendered'"
					class="mx-auto max-w-3xl px-6 py-6"
				>
					<h1 class="mb-4 text-2xl font-semibold text-ink-gray-9">
						{{ data.title }}
					</h1>
					<div
						ref="container"
						class="wiki-preview-body prose prose-sm dark:prose-invert max-w-none"
						v-html="data.html"
						@click="onBodyClick"
					/>
				</article>
				<!-- Raw markdown source -->
				<CodeEditor
					v-else
					:model-value="data.markdown || ''"
					language="markdown"
					variant="outline"
					:disabled="true"
					class="h-full"
				/>
			</div>
		</template>
		<p v-else class="py-10 text-center text-sm text-ink-gray-5">
			Select a section to preview it.
		</p>
	</div>
</template>

<style>
.wiki-preview-body .mermaid-figure {
	display: flex;
	justify-content: center;
	overflow-x: auto;
	margin: 1rem 0;
}
.wiki-preview-body .mermaid-figure svg {
	max-width: 100%;
	height: auto;
}
/* Approximate the wiki's table chrome so preview ≈ published page. */
.wiki-preview-body table {
	width: 100%;
	border-collapse: collapse;
}
.wiki-preview-body th,
.wiki-preview-body td {
	border: 1px solid var(--outline-gray-2, #e5e7eb);
	padding: 0.375rem 0.625rem;
}
</style>
