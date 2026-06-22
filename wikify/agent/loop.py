"""The agent round loop — `AgentRunner.run()`.

One streaming, tool-calling completion per round: stream text deltas to the panel,
accumulate any tool calls (Builder's by-index pattern), run server tools, feed results
back, and finish when the model answers with no tool call. Everything is `server` or
`terminal` (no live canvas → no `client` side).
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from wikify.agent import llm, session
from wikify.agent.context import Ctx, resolve_attachments
from wikify.agent.prompts import system_prompt
from wikify.agent.registry import build_default_registry

MAX_ROUNDS = 25


def cancel_key(session_id: str) -> str:
	return f"wikify_agent_cancel:{session_id}"


def request_cancel(session_id: str) -> None:
	frappe.cache().set_value(cancel_key(session_id), "1", expires_in_sec=600)


class AgentRunner:
	"""Runs one user turn end-to-end: stream → tool loop → persist → realtime."""

	def __init__(self, session_id: str, user: str, *, attachments: list | None = None):
		self.session_id = session_id
		self.user = user
		self.doc = frappe.get_doc("Wikify Agent Session", session_id)
		self.attachments = attachments or []
		# Resolve the turn's attachments into scoping defaults + a context block. The most
		# specific attachment wins; fall back to the session's opening scope.
		self.resolved = resolve_attachments(self.attachments)
		project = self.resolved.project or self.doc.project
		source_document = self.resolved.source_document or self.doc.source_document
		self.model = self.doc.model or llm.resolve_model(project=project)
		self.registry = build_default_registry()
		self.ctx = Ctx(
			session=session_id,
			user=user,
			project=project,
			source_document=source_document,
			attachments=self.attachments,
		)

	# --- realtime ---------------------------------------------------------------------

	def _emit(self, event: str, payload: dict) -> None:
		frappe.publish_realtime(f"{event}:{self.session_id}", payload, user=self.user)

	def _cancelled(self) -> bool:
		return bool(frappe.cache().get_value(cancel_key(self.session_id)))

	def _clear_cancel(self) -> None:
		frappe.cache().delete_value(cancel_key(self.session_id))

	# --- entry point ------------------------------------------------------------------

	def run(self) -> None:
		self._clear_cancel()
		try:
			messages = self._build_messages()
			for _round in range(MAX_ROUNDS):
				if self._cancelled():
					self._finish_cancelled()
					return
				done = self._run_round(messages)
				if done:
					return
			# Ran out of rounds without a final answer.
			self._emit_error(_("The assistant took too many steps without finishing."))
		except Exception:
			frappe.log_error(title="Wikify agent run failed")
			self._emit_error(_("The assistant hit an error. Please try again."))
		finally:
			session.set_running(self.session_id, False)

	# --- one round --------------------------------------------------------------------

	def _run_round(self, messages: list[dict]) -> bool:
		"""Stream one completion. Returns True when the turn is finished."""
		tools = list(self.registry.values())
		assistant_msg = session.append_message(self.session_id, "assistant", "", status="streaming")
		message_id = assistant_msg.name

		text_acc = ""
		tool_calls: dict[int, dict] = {}

		response = llm.complete_with_tools(self.model, messages, tools, stream=True)
		for chunk in response:
			if self._cancelled():
				break
			delta = chunk.choices[0].delta if chunk.choices else None
			if not delta:
				continue
			if getattr(delta, "content", None):
				text_acc += delta.content
				self._emit("wikify_agent_stream", {"message_id": message_id, "chunk": delta.content})
			for tcd in getattr(delta, "tool_calls", None) or []:
				self._accumulate_tool_call(tool_calls, tcd)

		if self._cancelled():
			session.update_message(message_id, content=text_acc, status="done")
			self._finish_cancelled()
			return True

		ordered = [tool_calls[i] for i in sorted(tool_calls)]

		if not ordered:
			# Model answered — turn ends.
			session.update_message(message_id, content=text_acc, status="done")
			session.touch(self.session_id)
			self._emit("wikify_agent_complete", {"message_id": message_id})
			return True

		# Persist the assistant turn (text + requested tool calls), then run them.
		persisted_calls = [
			{"id": c["id"], "name": c["name"], "args": _safe_json(c["arguments"])} for c in ordered
		]
		session.update_message(message_id, content=text_acc, tool_calls=persisted_calls, status="done")
		messages.append(
			{
				"role": "assistant",
				"content": text_acc or None,
				"tool_calls": [
					{
						"id": c["id"],
						"type": "function",
						"function": {"name": c["name"], "arguments": c["arguments"]},
					}
					for c in ordered
				],
			}
		)

		for call in ordered:
			result = self._run_tool(call)
			messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
		return False

	def _accumulate_tool_call(self, acc: dict[int, dict], tcd) -> None:
		idx = tcd.index or 0
		entry = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
		if getattr(tcd, "id", None):
			entry["id"] = tcd.id
		fn = getattr(tcd, "function", None)
		if fn:
			if getattr(fn, "name", None):
				entry["name"] = fn.name
			if getattr(fn, "arguments", None):
				entry["arguments"] += fn.arguments

	def _run_tool(self, call: dict) -> str:
		"""Run one tool call and return the result string fed back to the model."""
		name = call["name"]
		args = _safe_json(call["arguments"])
		tool = self.registry.get(name)
		self._emit(
			"wikify_agent_tool",
			{"name": name, "args": args, "status": "running", "call_id": call["id"]},
		)
		if not tool:
			result = _("Unknown tool: {0}").format(name)
		else:
			try:
				result = tool.handler(self.ctx, args)
			except Exception:
				frappe.log_error(title=f"Wikify agent tool failed: {name}")
				result = _("Tool {0} failed: {1}").format(name, frappe.get_traceback(with_context=False))
		summary = result if len(result) <= 200 else result[:200] + "…"
		session.append_message(
			self.session_id,
			"tool",
			result,
			tool_name=name,
			tool_call_id=call["id"],
			metadata={"args": args},
		)
		self._emit(
			"wikify_agent_tool",
			{"name": name, "args": args, "status": "done", "summary": summary, "call_id": call["id"]},
		)
		return result

	# --- message assembly -------------------------------------------------------------

	def _build_messages(self) -> list[dict]:
		# Project context comes from the attached project (or the attached document's
		# project), falling back to the session's project.
		project_context = self.resolved.project_context
		if not project_context and self.doc.project:
			project_context = frappe.db.get_value("Wikify Project", self.doc.project, "context_prompt") or ""
		messages: list[dict] = [{"role": "system", "content": system_prompt(project_context)}]
		if self.resolved.block:
			# A second system message carries the bounded attachment context for this turn.
			messages.append({"role": "system", "content": self.resolved.block})
		messages.extend(session.history_messages(self.session_id))
		return messages

	# --- terminal states --------------------------------------------------------------

	def _finish_cancelled(self) -> None:
		self._clear_cancel()
		session.touch(self.session_id)
		self._emit("wikify_agent_complete", {"message_id": None, "cancelled": True})

	def _emit_error(self, message: str) -> None:
		session.append_message(self.session_id, "assistant", message, status="error")
		self._emit("wikify_agent_error", {"message": message})


def _safe_json(raw: str) -> dict:
	try:
		return json.loads(raw) if raw else {}
	except (ValueError, TypeError):
		return {}
