import { createApp } from "vue";
import { FrappeUI, frappeRequest, useCall } from "frappe-ui";
import router from "./router";
import App from "./App.vue";
import { initSocket } from "./socket";
import "./index.css";

const app = createApp(App);
app.use(router); // required — frappe-ui's <Button> injects Symbol(router)

// In dev the vite server proxies to the site but the Jinja boot isn't injected,
// so pull the boot values from the whitelisted dev endpoint and stash them on
// `window` (prod gets them inline from www/wikify.py). Then boot the app.
if (import.meta.env.DEV) {
	useCall({
		url: "/api/v2/method/wikify.www.wikify.get_context_for_dev",
		method: "POST",
		onSuccess(values) {
			for (const key in values) {
				window[key] = values[key];
			}
			setupApp();
		},
	});
} else {
	setupApp();
}

function setupApp() {
	app.use(FrappeUI, {
		config: {
			resourceFetcher: frappeRequest,
			systemTimezone: window.system_timezone || null,
			maxFileSize: window.max_file_size ? Number(window.max_file_size) : null,
		},
	});
	const socket = initSocket();
	app.config.globalProperties.$socket = socket;
	app.mount("#app");
}
