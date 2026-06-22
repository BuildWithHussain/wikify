"""litellm adapter for the agent — the only LLM client on the agent side.

The pipeline keeps its own requests-based `engine/llm.py` (scoring/cleanup); the agent
streams tool-calling completions through litellm against OpenRouter, reusing the same
key resolver (`engine.settings.openrouter_key`). Models are `openrouter/`-prefixed.
"""

from __future__ import annotations

import litellm

from wikify.engine import settings

# Send only params the target model supports (drop the rest) instead of erroring.
litellm.drop_params = True

# Default when neither the session, its project, nor Settings names a model. A capable
# tool-caller; per-project / Settings overrides land in slice 16.
DEFAULT_AGENT_MODEL = "anthropic/claude-sonnet-4.6"


def resolve_model(explicit: str | None = None, project: str | None = None) -> str:
	"""Resolve the agent model: explicit → project override → default.

	(Wikify Settings + the populated picker arrive in slice 16; this already honours the
	per-project `agent_model` set in slice 11.)
	"""
	if explicit:
		return explicit
	if project:
		import frappe

		model = frappe.db.get_value("Wikify Project", project, "agent_model")
		if model:
			return model
	return DEFAULT_AGENT_MODEL


def _openrouter_model(model: str) -> str:
	return model if model.startswith("openrouter/") else f"openrouter/{model}"


def complete_with_tools(model: str, messages: list, tools: list, *, stream: bool = True):
	"""Stream a tool-calling completion. `tools` is a list of `registry.Tool`.

	Returns the litellm streaming response (iterate chunks) when `stream`, else the
	full response object.
	"""
	key = settings.openrouter_key()
	if not key:
		raise RuntimeError("OPENROUTER key not set; the agent is unavailable.")

	tool_schemas = [
		{
			"type": "function",
			"function": {
				"name": t.name,
				"description": t.description,
				"parameters": t.parameters,
			},
		}
		for t in tools
	] or None

	return litellm.completion(
		model=_openrouter_model(model),
		messages=messages,
		tools=tool_schemas,
		stream=stream,
		api_key=key,
		num_retries=2,
	)
