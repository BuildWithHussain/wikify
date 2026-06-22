"""Whitelisted APIs for the AI agent.

Slice 12 (walking skeleton): `run` (enqueue + 202), `cancel`, `get_session`. Session
listing / new-session / clearing and richer scoping arrive in slices 13 + 16.
"""

from __future__ import annotations

import frappe
from frappe import _

from wikify.agent import llm, session
from wikify.agent.loop import request_cancel


@frappe.whitelist()
def run(
	prompt: str,
	session_id: str | None = None,
	scope: str = "global",
	project: str | None = None,
	source_document: str | None = None,
	attachments: list | str | None = None,
	model: str | None = None,
) -> dict:
	"""Start an agent turn: append the user message, enqueue the loop, return 202.

	The answer arrives over `wikify_agent_*:<session_id>` realtime, not this response.
	"""
	prompt = (prompt or "").strip()
	if not prompt:
		frappe.throw(_("Message can't be empty."))
	if isinstance(attachments, str):
		attachments = frappe.parse_json(attachments) or []
	attachments = attachments or []

	user = frappe.session.user
	resolved_model = llm.resolve_model(model, project)
	sess = session.get_or_create(
		session_id,
		user=user,
		scope=scope,
		project=project,
		source_document=source_document,
		model=resolved_model,
	)

	if sess.is_running:
		frappe.local.response["http_status_code"] = 429
		frappe.throw(_("This session is already running. Wait for it to finish or cancel it."))

	user_msg = session.append_message(sess.name, "user", prompt, status="done", attachments=attachments)
	session.touch(sess.name, first_user_message=prompt)
	session.set_running(sess.name, True)

	frappe.enqueue(
		"wikify.jobs.agent.run_agent_job",
		queue="long",
		timeout=1800,
		session_id=sess.name,
		user=user,
		attachments=attachments,
	)

	frappe.local.response["http_status_code"] = 202
	return {"session_id": sess.name, "message_id": user_msg.name}


@frappe.whitelist()
def cancel(session_id: str) -> dict:
	"""Signal the running loop to stop at its next chunk."""
	request_cancel(session_id)
	return {"ok": True}


@frappe.whitelist()
def get_session(session_id: str) -> dict:
	"""A session + its ordered messages, for hydration when the panel opens/reloads."""
	sess = frappe.get_doc("Wikify Agent Session", session_id)
	messages = frappe.get_all(
		"Wikify Agent Message",
		filters={"session": session_id},
		fields=[
			"name",
			"role",
			"content",
			"status",
			"tool_name",
			"tool_call_id",
			"tool_calls",
			"attachments_json",
			"metadata_json",
			"creation",
		],
		order_by="creation asc",
	)
	return {"session": sess.as_dict(), "messages": messages}
