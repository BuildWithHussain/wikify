// Chat controller for the AI agent panel (à la Builder's AIChatController, simplified):
// reactive messages + streaming accumulators; submitPrompt/cancel/loadSession. Calls the
// whitelisted `wikify.api.agent.*` methods, optimistically pushes the user bubble + a
// "Thinking…" assistant bubble, then lets realtime drive.
import { ref } from "vue";
import { call } from "frappe-ui";
import { bindAgentRealtime } from "@/agent/realtime";

const THINKING_ID = "__thinking__";

export function useAgentChat() {
	const messages = ref([]);
	const prompt = ref("");
	const sessionId = ref(null);
	const isRunning = ref(false);
	const errorText = ref("");
	let unbind = null;

	function rebind() {
		unbind?.();
		unbind = bindAgentRealtime(sessionId.value, {
			onStream: ({ message_id, chunk }) => {
				const m = adoptStreaming(message_id);
				m.content += chunk;
			},
			onTool: ({ name, args, status, summary, call_id }) => {
				let card = messages.value.find((x) => x.role === "tool" && x.callId === call_id);
				if (!card) {
					card = {
						id: `tool-${call_id}`,
						role: "tool",
						toolName: name,
						args,
						status,
						content: summary || "",
						callId: call_id,
					};
					// Insert the tool card before any trailing "Thinking…" bubble.
					const at = messages.value.findIndex((x) => x.id === THINKING_ID);
					if (at >= 0) messages.value.splice(at, 0, card);
					else messages.value.push(card);
				} else {
					card.status = status;
					if (summary) card.content = summary;
				}
			},
			onComplete: ({ message_id }) => {
				isRunning.value = false;
				dropThinking();
				const m = messages.value.find((x) => x.id === message_id);
				if (m) m.status = "done";
			},
			onError: ({ message }) => {
				isRunning.value = false;
				dropThinking();
				errorText.value = message;
				messages.value.push({
					id: `err-${Date.now()}`,
					role: "assistant",
					status: "error",
					content: message,
				});
			},
		});
	}

	// Turn the optimistic "Thinking…" bubble into the real streaming bubble on first chunk.
	function adoptStreaming(messageId) {
		let m = messages.value.find((x) => x.id === messageId);
		if (m) return m;
		const placeholder = messages.value.find((x) => x.id === THINKING_ID);
		if (placeholder) {
			placeholder.id = messageId;
			placeholder.status = "streaming";
			placeholder.content = "";
			return placeholder;
		}
		m = { id: messageId, role: "assistant", status: "streaming", content: "" };
		messages.value.push(m);
		return m;
	}

	function dropThinking() {
		const i = messages.value.findIndex((x) => x.id === THINKING_ID);
		if (i >= 0) messages.value.splice(i, 1);
	}

	async function submitPrompt(extra = {}) {
		const text = prompt.value.trim();
		if (!text || isRunning.value) return;
		messages.value.push({ id: `u-${Date.now()}`, role: "user", content: text });
		messages.value.push({
			id: THINKING_ID,
			role: "assistant",
			status: "streaming",
			content: "",
		});
		prompt.value = "";
		isRunning.value = true;
		errorText.value = "";
		try {
			const res = await call("wikify.api.agent.run", {
				prompt: text,
				session_id: sessionId.value,
				scope: "global",
				...extra,
			});
			sessionId.value = res.session_id;
			rebind();
		} catch (e) {
			isRunning.value = false;
			dropThinking();
			errorText.value = e?.messages?.[0] || e?.message || "Failed to start the assistant.";
		}
	}

	async function cancel() {
		if (!sessionId.value) return;
		await call("wikify.api.agent.cancel", { session_id: sessionId.value });
		isRunning.value = false;
		dropThinking();
	}

	async function loadSession(id) {
		const res = await call("wikify.api.agent.get_session", { session_id: id });
		sessionId.value = id;
		messages.value = hydrate(res.messages || []);
		rebind();
	}

	function newSession() {
		unbind?.();
		unbind = null;
		sessionId.value = null;
		messages.value = [];
		errorText.value = "";
		isRunning.value = false;
	}

	return {
		messages,
		prompt,
		sessionId,
		isRunning,
		errorText,
		submitPrompt,
		cancel,
		loadSession,
		newSession,
	};
}

function hydrate(rows) {
	const out = [];
	for (const r of rows) {
		if (r.role === "tool") {
			out.push({
				id: r.name,
				role: "tool",
				toolName: r.tool_name,
				status: "done",
				content: r.content,
			});
		} else if (r.role === "assistant") {
			// Assistant rows that only carried tool calls (no text) are represented by their
			// tool cards; skip the empty bubble.
			if ((r.content || "").trim()) {
				out.push({
					id: r.name,
					role: "assistant",
					status: r.status || "done",
					content: r.content,
				});
			}
		} else if (r.role === "user") {
			out.push({ id: r.name, role: "user", content: r.content });
		}
	}
	return out;
}
