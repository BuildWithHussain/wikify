<script setup>
import { Button } from "frappe-ui";
</script>

<template>
	<div class="flex h-full flex-col">
		<header
			class="sticky top-0 z-10 flex min-h-12 items-center justify-between border-b border-outline-gray-1 bg-surface-base px-3 sm:px-5"
		>
			<h1 class="text-lg text-ink-gray-9">Imports</h1>
			<Button
				variant="solid"
				theme="gray"
				icon-left="lucide-plus"
				label="New Import"
				disabled
			/>
		</header>

		<div class="body-container pt-5 pb-40">
			<div class="flex flex-col items-center justify-center gap-3 py-16 text-center">
				<div class="rounded-full bg-surface-gray-2 p-3 text-ink-gray-5">
					<span class="lucide-inbox size-6" aria-hidden="true" />
				</div>
				<p class="text-base text-ink-gray-7">No imports yet</p>
				<p class="text-sm text-ink-gray-5">
					Upload a PDF to start an import. (Coming in the next slice.)
				</p>
			</div>
		</div>
	</div>
</template>
