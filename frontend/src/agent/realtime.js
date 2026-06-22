// Subscribe the five `wikify_agent_*:<sid>` realtime events for one session and route
// them to controller handlers. Returns an unsubscribe function. Socket events, not polling
// — mirrors the import progress/log streaming in ImportDetail.
import { useSocket } from "@/socket";

const CHANNELS = {
	stream: "onStream",
	tool: "onTool",
	clarify: "onClarify",
	complete: "onComplete",
	error: "onError",
};

export function bindAgentRealtime(sessionId, handlers) {
	const socket = useSocket();
	if (!socket || !sessionId) return () => {};

	const bound = [];
	for (const [suffix, handlerName] of Object.entries(CHANNELS)) {
		const event = `wikify_agent_${suffix}:${sessionId}`;
		const fn = (payload) => handlers[handlerName]?.(payload);
		socket.on(event, fn);
		bound.push([event, fn]);
	}

	return () => bound.forEach(([event, fn]) => socket.off(event, fn));
}
