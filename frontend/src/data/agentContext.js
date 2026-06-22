// Reactive store for the agent's "what you're looking at" context (slice 13). Pages write
// to it on mount / selection; the AgentChatPanel reads `defaultAttachments` for its default
// context chips (the removable ✕ chips, like Claude's file mentions).
//
// Slots are cumulative but mutually consistent: setting a broader scope clears the narrower
// ones (a new project drops the old document/page/section), and page ⇄ section are
// exclusive (you're on either the Pages or the Tree tab). `defaultAttachments` projects the
// set slots into the `[{type, name, label}]` shape `api.agent.run` expects.
import { computed, reactive } from "vue";

const state = reactive({
	project: null, // { name, label }
	document: null, // { name, label }
	page: null, // { name, label }
	section: null, // { name, label }
});

export const agentContext = state;

export function setProject(project) {
	state.project = project || null;
	state.document = null;
	state.page = null;
	state.section = null;
}

export function setDocument(document, project = null) {
	state.document = document || null;
	state.project = project || null;
	state.page = null;
	state.section = null;
}

export function setPage(page) {
	state.page = page || null;
	state.section = null;
}

export function setSection(section) {
	state.section = section || null;
	state.page = null;
}

export function clear() {
	state.project = null;
	state.document = null;
	state.page = null;
	state.section = null;
}

// The default context chips, broadest → narrowest. The panel seeds its editable chip row
// from this and re-seeds when it changes (navigation / selection).
export const defaultAttachments = computed(() => {
	const out = [];
	if (state.project)
		out.push({ type: "project", name: state.project.name, label: state.project.label });
	if (state.document)
		out.push({ type: "document", name: state.document.name, label: state.document.label });
	if (state.page) out.push({ type: "page", name: state.page.name, label: state.page.label });
	if (state.section)
		out.push({ type: "section", name: state.section.name, label: state.section.label });
	return out;
});

// The session scope implied by the most specific attached thing.
export const defaultScope = computed(() => {
	if (state.section) return "section";
	if (state.page) return "page";
	if (state.document) return "document";
	if (state.project) return "project";
	return "global";
});
