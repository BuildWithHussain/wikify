<script setup>
import { FrappeUIProvider } from "frappe-ui";
import AppShell from "@/components/AppShell.vue";
import { session } from "@/data/session";
</script>

<template>
	<FrappeUIProvider>
		<AppShell v-if="session.isLoggedIn" />
	</FrappeUIProvider>
</template>
