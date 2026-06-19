import frappeUIPreset from "frappe-ui/tailwind";

/** @type {import('tailwindcss').Config} */
export default {
	presets: [frappeUIPreset],
	content: [
		"./index.html",
		"./src/**/*.{vue,js,ts,jsx,tsx}",
		// Tailwind v3 ignores `content` declared in presets, so frappe-ui's source
		// must be scanned here for its components' utilities (string-based lucide-*
		// icon classes, etc.).
		"./node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}",
		"./node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}",
	],
};
