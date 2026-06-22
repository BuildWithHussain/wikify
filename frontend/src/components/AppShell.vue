<script setup>
import { Button } from "frappe-ui";
import { RouterLink } from "vue-router";
import { onMounted, ref } from "vue";
import { useTheme } from "@/utils/useTheme";
import { session } from "@/data/session";
import AgentChatPanel from "@/components/AgentChatPanel.vue";

const { resolvedTheme, toggleTheme, initializeTheme } = useTheme();

const nav = [
	{ label: "Projects", to: { name: "Projects" }, icon: "lucide-folder" },
	{ label: "Explore", to: { name: "Explore" }, icon: "lucide-shapes" },
];

// The agent panel + its floating button are mounted once here so they're available on
// every screen (slice 12).
const agentOpen = ref(false);

onMounted(initializeTheme);
</script>

<template>
	<div class="flex h-screen bg-surface-base text-ink-gray-9">
		<aside
			class="flex w-56 shrink-0 flex-col border-r border-outline-gray-1 bg-surface-sidebar"
		>
			<div class="flex min-h-12 items-center gap-2 px-3">
				<span class="lucide-book-open size-5 text-ink-gray-7" aria-hidden="true" />
				<span class="text-base font-medium text-ink-gray-9">Wikify</span>
			</div>

			<nav class="flex flex-1 flex-col gap-0.5 px-2 pt-2">
				<RouterLink
					v-for="item in nav"
					:key="item.label"
					:to="item.to"
					class="flex items-center gap-2 rounded px-2 py-1.5 text-base text-ink-gray-7 hover:bg-surface-gray-2"
					active-class="bg-surface-gray-3 text-ink-gray-9"
				>
					<span :class="[item.icon, 'size-4']" aria-hidden="true" />
					{{ item.label }}
				</RouterLink>
			</nav>

			<div
				class="flex items-center justify-between gap-2 border-t border-outline-gray-1 px-2 py-2"
			>
				<span class="truncate px-1 text-sm text-ink-gray-5">{{ session.user }}</span>
				<Button
					variant="ghost"
					:icon="resolvedTheme === 'dark' ? 'lucide-sun' : 'lucide-moon'"
					:tooltip="resolvedTheme === 'dark' ? 'Light mode' : 'Dark mode'"
					@click="toggleTheme"
				/>
			</div>
		</aside>

		<main class="flex flex-1 flex-col overflow-y-auto">
			<router-view />
		</main>

		<!-- Floating assistant button (every screen) + the slide-over panel. -->
		<Button
			v-show="!agentOpen"
			variant="solid"
			icon="lucide-sparkles"
			class="fixed bottom-5 right-5 z-30 !size-11 !rounded-full shadow-lg"
			tooltip="Ask the assistant"
			@click="agentOpen = true"
		/>
		<AgentChatPanel v-model:open="agentOpen" />
	</div>
</template>
