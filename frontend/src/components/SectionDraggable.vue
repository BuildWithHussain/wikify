<script setup>
import { ref } from "vue";
import { Badge, Button, Dropdown } from "frappe-ui";
import draggable from "vuedraggable";

// Recursive draggable row list for the section tree. One instance renders the children
// of a single parent (or the roots when `parentName` is null); groups recurse. Drag is
// handle-only and uses a single shared `group` name so a node can be dropped at any depth.
// Mutations bubble up via the handler props (kept stateful in SectionTree).
const props = defineProps({
	list: { type: Array, required: true },
	parentName: { type: String, default: null },
	selectedName: { type: String, default: null },
	onSelect: { type: Function, required: true },
	onMove: { type: Function, required: true },
	onRename: { type: Function, required: true },
	onToggle: { type: Function, required: true },
	onRemove: { type: Function, required: true },
});

// Collapsed groups (default expanded), and inline-rename state — both scoped to the node
// in *this* list, which is the only place a given node is rendered.
const collapsed = ref(new Set());
const editingKey = ref(null);
const draft = ref("");

// Focus + select the rename input as soon as it mounts.
const vFocus = { mounted: (el) => el.focus() };

function toggleCollapse(name) {
	const next = new Set(collapsed.value);
	next.has(name) ? next.delete(name) : next.add(name);
	collapsed.value = next;
}

function startRename(el) {
	editingKey.value = el.name;
	draft.value = el.title;
}
function commitRename(el) {
	const title = draft.value.trim();
	editingKey.value = null;
	if (title && title !== el.title) props.onRename(el.name, title);
}

// vuedraggable mutates `list` in place; on add/move report the node's new parent + the
// post-drop sibling order so the server can rewrite sort_order and rebuild the tree.
function onChange(evt) {
	const change = evt.added || evt.moved;
	if (!change) return;
	props.onMove({
		name: change.element.name,
		newParent: props.parentName,
		siblings: props.list.map((n) => n.name),
	});
}

function pageRange(node) {
	if (node.page_start == null) return null;
	return node.page_start === node.page_end
		? `p${node.page_start}`
		: `p${node.page_start}–${node.page_end}`;
}

function rowActions(el) {
	return [
		{ label: "Rename", icon: "edit-3", onClick: () => startRename(el) },
		{
			label: el.include_in_wiki ? "Exclude from wiki" : "Include in wiki",
			icon: el.include_in_wiki ? "eye-off" : "eye",
			onClick: () => props.onToggle(el.name, !el.include_in_wiki),
		},
		{ label: "Delete", icon: "trash-2", onClick: () => props.onRemove(el) },
	];
}
</script>

<template>
	<draggable
		:list="list"
		:group="{ name: 'wikify-sections' }"
		item-key="name"
		tag="div"
		handle=".drag-handle"
		ghost-class="opacity-40"
		:animation="150"
		@change="onChange"
	>
		<template #item="{ element }">
			<div>
				<div
					class="group flex items-center gap-1.5 rounded py-0.5 pr-1.5 hover:bg-surface-gray-2"
					:class="selectedName === element.name ? 'bg-surface-gray-3' : ''"
				>
					<button
						class="drag-handle shrink-0 cursor-grab rounded p-0.5 text-ink-gray-4 opacity-0 transition-opacity hover:bg-surface-gray-3 active:cursor-grabbing group-hover:opacity-100"
						title="Drag to move"
						@click.stop
					>
						<span class="lucide-grip-vertical size-4" aria-hidden="true" />
					</button>

					<button
						v-if="element.is_group"
						class="shrink-0 rounded p-0.5 text-ink-gray-5 hover:bg-surface-gray-3"
						@click.stop="toggleCollapse(element.name)"
					>
						<span
							class="lucide-chevron-right size-4 transition-transform"
							:class="collapsed.has(element.name) ? '' : 'rotate-90'"
							aria-hidden="true"
						/>
					</button>
					<span v-else class="w-5 shrink-0" />

					<!-- Inline rename, else the clickable title -->
					<input
						v-if="editingKey === element.name"
						v-model="draft"
						class="min-w-0 flex-1 rounded border border-outline-gray-2 bg-surface-white px-1 py-0.5 text-sm text-ink-gray-9 outline-none focus:border-outline-gray-4"
						@click.stop
						@keydown.enter.prevent="commitRename(element)"
						@keydown.esc.prevent="editingKey = null"
						@blur="commitRename(element)"
						v-focus
					/>
					<button
						v-else
						class="flex min-w-0 flex-1 items-center gap-2 text-left"
						@click.stop="onSelect(element.name)"
					>
						<span
							class="truncate text-sm"
							:class="
								element.include_in_wiki
									? 'text-ink-gray-8'
									: 'text-ink-gray-4 line-through'
							"
							>{{ element.title }}</span
						>
						<Badge
							v-if="element.section_type"
							:label="element.section_type"
							theme="blue"
							variant="subtle"
							size="sm"
						/>
						<span
							v-if="pageRange(element)"
							class="shrink-0 text-xs tabular-nums text-ink-gray-4"
							>{{ pageRange(element) }}</span
						>
					</button>

					<Dropdown :options="rowActions(element)" placement="right">
						<button
							class="shrink-0 rounded p-0.5 text-ink-gray-5 opacity-0 hover:bg-surface-gray-3 group-hover:opacity-100"
						>
							<span class="lucide-more-horizontal size-4" aria-hidden="true" />
						</button>
					</Dropdown>
				</div>

				<!-- Children -->
				<div
					v-if="element.is_group && !collapsed.has(element.name)"
					class="ml-4 border-l border-outline-gray-1 pl-1"
				>
					<SectionDraggable
						:list="element.children"
						:parent-name="element.name"
						:selected-name="selectedName"
						:on-select="onSelect"
						:on-move="onMove"
						:on-rename="onRename"
						:on-toggle="onToggle"
						:on-remove="onRemove"
					/>
				</div>
			</div>
		</template>
	</draggable>
</template>
