import { createRouter, createWebHistory } from "vue-router";
import { session } from "@/data/session";

const routes = [
	{
		path: "/",
		name: "Imports",
		component: () => import("@/pages/ImportList.vue"),
	},
];

// __FRONTEND_ROUTE__ is injected by the frappe-ui vite plugin (= '/wikify').
const router = createRouter({
	history: createWebHistory(__FRONTEND_ROUTE__ + "/"),
	routes,
});

router.beforeEach((to, from, next) => {
	if (!session.isLoggedIn) {
		// Not authenticated — hand off to the Frappe login screen.
		window.location.href = "/login?redirect-to=/wikify";
		return;
	}
	next();
});

export default router;
