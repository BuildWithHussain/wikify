<script setup>
// Slide-over chat panel for the Wikify AI agent. Slice 12 shipped the message list +
// tool-call cards + streaming bubble + input. Slice 13 adds the context chips row (the
// removable attachments the agent knows about) and a session-history dropdown.
import { computed, nextTick, ref, watch } from "vue";
import { Button, Dropdown, Spinner } from "frappe-ui";
import MarkdownPreview from "@/components/MarkdownPreview.vue";
import { useAgentChat } from "@/composables/useAgentChat";

const props = defineProps({ open: { type: Boolean, default: false } });
const emit = defineEmits(["update:open"]);

const chat = useAgentChat();
const { messages, prompt, isRunning, errorText, attachments } = chat;

const CHIP_ICON = {
	project: "lucide-folder",
	document: "lucide-file-text",
	page: "lucide-file",
	section: "lucide-list-tree",
};

// Session-history dropdown — fetched lazily when opened.
const sessionOptions = computed(() =>
	(chat.sessions.value || []).map((s) => ({
		label: s.title || "Untitled chat",
		onClick: () => chat.loadSession(s.name),
	}))
);
async function refreshSessions() {
	await chat.listSessions();
}

const listEl = ref(null);
async function scrollToBottom() {
	await nextTick();
	if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
}
watch(() => messages.value.length, scrollToBottom);
watch(() => messages.value.map((m) => m.content).join("").length, scrollToBottom);

function onSubmit() {
	chat.submitPrompt();
}

function onKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		onSubmit();
	}
}
</script>

<template>
	<Transition
		enter-active-class="transition-transform duration-200 ease-out"
		leave-active-class="transition-transform duration-150 ease-in"
		enter-from-class="translate-x-full"
		leave-to-class="translate-x-full"
	>
		<aside
			v-if="props.open"
			class="fixed inset-y-0 right-0 z-40 flex w-[26rem] max-w-[90vw] flex-col border-l border-outline-gray-1 bg-surface-base shadow-2xl"
		>
			<header
				class="flex min-h-12 items-center justify-between gap-2 border-b border-outline-gray-1 px-3"
			>
				<div class="flex items-center gap-2">
					<span class="lucide-sparkles size-4 text-ink-gray-7" aria-hidden="true" />
					<span class="text-base font-medium text-ink-gray-9">Assistant</span>
				</div>
				<div class="flex items-center gap-1">
					<Dropdown :options="sessionOptions" placement="right">
						<Button
							variant="ghost"
							icon="lucide-history"
							tooltip="Chat history"
							@click="refreshSessions"
						/>
					</Dropdown>
					<Button
						variant="ghost"
						icon="lucide-plus"
						tooltip="New chat"
						@click="chat.newSession()"
					/>
					<Button
						variant="ghost"
						icon="lucide-x"
						tooltip="Close"
						@click="emit('update:open', false)"
					/>
				</div>
			</header>

			<div ref="listEl" class="flex-1 space-y-3 overflow-y-auto px-3 py-4">
				<div
					v-if="!messages.length"
					class="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-ink-gray-5"
				>
					<span class="lucide-sparkles size-7" aria-hidden="true" />
					<p class="text-base text-ink-gray-7">Ask about a document's tree</p>
					<p class="text-sm">
						Try: "Summarize the section tree of document &lt;name&gt;".
					</p>
				</div>

				<template v-for="m in messages" :key="m.id">
					<!-- User bubble -->
					<div v-if="m.role === 'user'" class="flex justify-end">
						<div
							class="max-w-[85%] whitespace-pre-wrap rounded-lg bg-surface-gray-3 px-3 py-2 text-base text-ink-gray-9"
						>
							{{ m.content }}
						</div>
					</div>

					<!-- Tool-call card -->
					<div
						v-else-if="m.role === 'tool'"
						class="rounded-lg border border-outline-gray-1 bg-surface-gray-1 px-3 py-2"
					>
						<div class="flex items-center gap-2 text-sm text-ink-gray-7">
							<Spinner v-if="m.status === 'running'" class="size-3.5" />
							<span
								v-else
								class="lucide-check size-3.5 text-ink-green-6"
								aria-hidden="true"
							/>
							<span class="font-medium text-ink-gray-8">{{ m.toolName }}</span>
							<span class="text-ink-gray-5">{{
								m.status === "running" ? "running…" : "done"
							}}</span>
						</div>
					</div>

					<!-- Assistant bubble -->
					<div v-else class="flex justify-start">
						<div
							class="max-w-[90%] rounded-lg px-3 py-2 text-base"
							:class="
								m.status === 'error'
									? 'bg-surface-red-1 text-ink-red-6'
									: 'bg-surface-gray-2 text-ink-gray-9'
							"
						>
							<MarkdownPreview v-if="m.content" :content="m.content" />
							<span v-else class="flex items-center gap-2 text-ink-gray-5">
								<Spinner class="size-3.5" /> Thinking…
							</span>
						</div>
					</div>
				</template>
			</div>

			<div class="border-t border-outline-gray-1 p-3">
				<!-- Context chips (the removable attachments the agent knows about). -->
				<div v-if="attachments.length" class="mb-2 flex flex-wrap gap-1.5">
					<span
						v-for="att in attachments"
						:key="`${att.type}-${att.name}`"
						class="flex max-w-[14rem] items-center gap-1 rounded-md border border-outline-gray-2 bg-surface-gray-2 py-0.5 pl-1.5 pr-1 text-xs text-ink-gray-7"
					>
						<span
							:class="[CHIP_ICON[att.type], 'size-3 shrink-0']"
							aria-hidden="true"
						/>
						<span class="truncate">{{ att.label || att.name }}</span>
						<button
							class="flex shrink-0 rounded p-0.5 hover:bg-surface-gray-3"
							:aria-label="`Remove ${att.label || att.name}`"
							@click="chat.removeAttachment(att)"
						>
							<span class="lucide-x size-3" aria-hidden="true" />
						</button>
					</span>
				</div>
				<p v-if="errorText" class="mb-2 text-sm text-ink-red-6">{{ errorText }}</p>
				<div
					class="flex items-end gap-2 rounded-lg border border-outline-gray-2 bg-surface-base px-2 py-1.5 focus-within:border-outline-gray-3"
				>
					<textarea
						v-model="prompt"
						rows="1"
						placeholder="Ask the assistant…"
						class="max-h-32 flex-1 resize-none bg-transparent py-1 text-base text-ink-gray-9 outline-none placeholder:text-ink-gray-4"
						@keydown="onKeydown"
					/>
					<Button
						v-if="isRunning"
						variant="ghost"
						icon="lucide-square"
						tooltip="Stop"
						@click="chat.cancel()"
					/>
					<Button
						v-else
						variant="solid"
						icon="lucide-arrow-up"
						:disabled="!prompt.trim()"
						@click="onSubmit"
					/>
				</div>
			</div>
		</aside>
	</Transition>
</template>
