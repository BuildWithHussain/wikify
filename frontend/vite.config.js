import path from "path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";

// The frappeui plugin wires the dev proxy to the Frappe site, injects boot data
// into the built index.html, and emits it to ../wikify/www/wikify.html — the
// page served at /wikify (see hooks.website_route_rules + www/wikify.py).
export default defineConfig({
	plugins: [
		frappeui({
			frontendRoute: "/wikify",
		}),
		vue(),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
	optimizeDeps: {
		include: ["feather-icons", "showdown", "engine.io-client", "socket.io-client"],
	},
});
