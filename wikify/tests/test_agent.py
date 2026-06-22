# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

"""Slice 12 — agent walking skeleton: the litellm tool-loop, the `read_tree` tool, message
persistence, the concurrency guard, and cancel. litellm is mocked (no live model).
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from wikify.agent import session
from wikify.agent.context import Ctx, resolve_attachments
from wikify.agent.loop import AgentRunner, cancel_key, request_cancel
from wikify.agent.tools.read import (
	_list_section_types,
	_read_page,
	_read_section,
	_read_tree,
	_search_sections,
)
from wikify.api import agent as agent_api
from wikify.engine import store
from wikify.engine.loader.sectionizer import Section


def _sec(title, level, path, p_start, p_end):
	return Section(
		title=title,
		level=level,
		hierarchy_path=path,
		page_start=p_start,
		page_end=p_end,
		markdown=f"body of {title}",
	)


def _text_chunk(text):
	return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))])


def _tool_chunk(index, call_id, name, arguments):
	tc = SimpleNamespace(
		index=index,
		id=call_id,
		function=SimpleNamespace(name=name, arguments=arguments),
	)
	return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[tc]))])


class FakeLLM:
	"""Replays canned streaming responses for successive `complete_with_tools` calls."""

	def __init__(self, streams):
		self.streams = list(streams)
		self.calls = []

	def __call__(self, model, messages, tools, *, stream=True):
		self.calls.append({"model": model, "messages": list(messages)})
		return iter(self.streams.pop(0))


class TestAgent(FrappeTestCase):
	def setUp(self):
		self.sd = frappe.get_doc({"doctype": "Source Document", "title": "Agent Test"}).insert(
			ignore_permissions=True
		)
		store.replace_sections(
			self.sd.name,
			[
				_sec("1. Alpha", 1, ["1. Alpha"], 1, 2),
				_sec("1.1 Alpha-One", 2, ["1. Alpha", "1.1 Alpha-One"], 1, 1),
				_sec("2. Beta", 1, ["2. Beta"], 3, 3),
			],
		)

	# --- the read_tree tool ----------------------------------------------------------

	def test_read_tree_renders_hierarchy(self):
		ctx = Ctx(session="x", user="Administrator", source_document=self.sd.name)
		out = _read_tree(ctx, {})
		self.assertIn("1. Alpha", out)
		self.assertIn("  1.1 Alpha-One".strip(), out)
		self.assertIn("[p.1-2]", out)

	def test_read_tree_without_document_asks(self):
		ctx = Ctx(session="x", user="Administrator")
		out = _read_tree(ctx, {})
		self.assertIn("No document", out)

	# --- the loop --------------------------------------------------------------------

	def _make_session(self):
		sess = session.get_or_create(
			None, user="Administrator", scope="document", source_document=self.sd.name
		)
		session.append_message(sess.name, "user", "Summarize the tree.", status="done")
		session.set_running(sess.name, True)
		return sess

	def test_loop_calls_tool_then_answers(self):
		"""Round 1 streams a read_tree call; round 2 streams the final answer."""
		sess = self._make_session()
		fake = FakeLLM(
			[
				[_tool_chunk(0, "call_1", "read_tree", "{}")],
				[_text_chunk("The tree has "), _text_chunk("Alpha and Beta.")],
			]
		)
		with patch("wikify.agent.llm.complete_with_tools", fake):
			AgentRunner(sess.name, "Administrator").run()

		msgs = frappe.get_all(
			"Wikify Agent Message",
			filters={"session": sess.name},
			fields=["role", "status", "tool_name", "content", "tool_calls"],
			order_by="creation asc",
		)
		roles = [m.role for m in msgs]
		self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])

		# The assistant's first turn requested the tool; the tool ran read_tree.
		self.assertIn("read_tree", msgs[1].tool_calls)
		self.assertEqual(msgs[2].tool_name, "read_tree")
		self.assertIn("Alpha", msgs[2].content)
		# Final answer is the streamed text, accumulated.
		self.assertEqual(msgs[3].content, "The tree has Alpha and Beta.")
		self.assertEqual(msgs[3].status, "done")

		# is_running cleared; the tool result was fed back to the model on round 2.
		self.assertEqual(frappe.db.get_value("Wikify Agent Session", sess.name, "is_running"), 0)
		self.assertEqual(len(fake.calls), 2)
		self.assertEqual(fake.calls[1]["messages"][-1]["role"], "tool")

	def test_loop_streams_realtime(self):
		sess = self._make_session()
		fake = FakeLLM([[_text_chunk("hi "), _text_chunk("there")]])
		events = []
		with (
			patch("wikify.agent.llm.complete_with_tools", fake),
			patch("frappe.publish_realtime", lambda event, *a, **k: events.append(event)),
		):
			AgentRunner(sess.name, "Administrator").run()
		self.assertTrue(any(e.startswith("wikify_agent_stream") for e in events))
		self.assertTrue(any(e.startswith("wikify_agent_complete") for e in events))

	def test_cancel_stops_mid_stream(self):
		"""A cancel signalled mid-stream stops the loop without persisting an answer.

		`run()` clears stale flags on entry, so cancel must arrive while streaming — here
		the stream requests it as it yields the first chunk; the per-chunk check catches it.
		"""
		sess = self._make_session()

		def cancelling_stream():
			request_cancel(sess.name)
			yield _text_chunk("should not finish")

		fake = FakeLLM([cancelling_stream()])
		with patch("wikify.agent.llm.complete_with_tools", fake):
			AgentRunner(sess.name, "Administrator").run()
		# No assistant answer persisted as done with that text.
		answers = frappe.get_all(
			"Wikify Agent Message",
			filters={"session": sess.name, "role": "assistant"},
			pluck="content",
		)
		self.assertNotIn("should not finish", answers)
		self.assertFalse(frappe.cache().get_value(cancel_key(sess.name)))

	# --- the API guard ---------------------------------------------------------------

	def test_run_rejects_when_already_running(self):
		sess = session.get_or_create(None, user="Administrator", scope="global")
		session.set_running(sess.name, True)
		with patch("frappe.enqueue"):
			with self.assertRaises(frappe.ValidationError):
				agent_api.run(prompt="hello", session_id=sess.name)

	def test_run_enqueues_and_returns_ids(self):
		with patch("frappe.enqueue") as enq:
			result = agent_api.run(prompt="hello", scope="document", source_document=self.sd.name)
		self.assertIn("session_id", result)
		self.assertIn("message_id", result)
		enq.assert_called_once()
		self.assertEqual(frappe.db.get_value("Wikify Agent Session", result["session_id"], "is_running"), 1)

	# --- slice 13: the extra read tools ----------------------------------------------

	def _first_section(self):
		return frappe.get_all(
			"Source Section", filters={"source_document": self.sd.name}, order_by="lft asc", limit=1
		)[0].name

	def test_read_section_returns_body_and_meta(self):
		name = self._first_section()
		out = _read_section(Ctx(session="x", user="Administrator"), {"name": name})
		self.assertIn("1. Alpha", out)
		self.assertIn("body of 1. Alpha", out)

	def test_read_page_uses_attached_document(self):
		frappe.get_doc(
			{
				"doctype": "Source Page",
				"source_document": self.sd.name,
				"page_no": 1,
				"verdict": "pass",
				"canonical_markdown": "Canonical page one body.",
			}
		).insert(ignore_permissions=True)
		ctx = Ctx(session="x", user="Administrator", source_document=self.sd.name)
		out = _read_page(ctx, {"page_no": 1})
		self.assertIn("Canonical page one body.", out)
		self.assertIn("Page 1", out)

	def _make_type(self, **kwargs):
		tname = f"t_{frappe.generate_hash(length=6)}"
		return frappe.get_doc({"doctype": "Section Type", "type_name": tname, **kwargs}).insert(
			ignore_permissions=True
		)

	def test_list_section_types_lists_taxonomy(self):
		st = self._make_type(label="Introduction")
		out = _list_section_types(Ctx(session="x", user="Administrator"), {})
		self.assertIn(st.type_name, out)

	def test_search_sections_by_type_spans_documents(self):
		st = self._make_type()
		name = self._first_section()
		frappe.db.set_value("Source Section", name, "section_type", st.type_name)
		out = _search_sections(Ctx(session="x", user="Administrator"), {"section_type": st.type_name})
		self.assertIn("1. Alpha", out)
		self.assertIn(self.sd.name, out)

	def test_explicit_bad_document_falls_back_to_attached(self):
		"""A model echoing "Title (id)" instead of the bare id falls back to the attachment."""
		ctx = Ctx(session="x", user="Administrator", source_document=self.sd.name)
		out = _read_tree(ctx, {"source_document": f"Agent Test ({self.sd.name})"})
		self.assertIn("1. Alpha", out)

	# --- slice 13: attachment resolution ---------------------------------------------

	def test_resolve_document_attachment_sets_scope_and_block(self):
		resolved = resolve_attachments([{"type": "document", "name": self.sd.name}])
		self.assertEqual(resolved.source_document, self.sd.name)
		self.assertIn("1. Alpha", resolved.block)

	def test_resolve_section_attachment_pins_its_document(self):
		name = self._first_section()
		resolved = resolve_attachments([{"type": "section", "name": name}])
		self.assertEqual(resolved.source_document, self.sd.name)
		self.assertIn("body of 1. Alpha", resolved.block)

	def test_resolve_project_attachment_injects_context_prompt(self):
		proj = frappe.get_doc(
			{
				"doctype": "Wikify Project",
				"project_name": f"Proj {frappe.generate_hash(length=6)}",
				"context_prompt": "Use UK spelling.",
			}
		).insert(ignore_permissions=True)
		resolved = resolve_attachments([{"type": "project", "name": proj.name}])
		self.assertEqual(resolved.project, proj.name)
		self.assertEqual(resolved.project_context, "Use UK spelling.")

	def test_stale_attachment_is_skipped(self):
		resolved = resolve_attachments([{"type": "document", "name": "does-not-exist"}])
		self.assertEqual(resolved.block, "")

	def test_loop_prepends_attachment_block(self):
		"""An attached document's tree outline reaches the model as a system message."""
		sess = session.get_or_create(None, user="Administrator", scope="global")
		session.append_message(sess.name, "user", "What's in this doc?", status="done")
		session.set_running(sess.name, True)
		fake = FakeLLM([[_text_chunk("It has Alpha and Beta.")]])
		with patch("wikify.agent.llm.complete_with_tools", fake):
			AgentRunner(
				sess.name, "Administrator", attachments=[{"type": "document", "name": self.sd.name}]
			).run()
		systems = [m["content"] for m in fake.calls[0]["messages"] if m["role"] == "system"]
		self.assertTrue(any("1. Alpha" in s for s in systems))

	# --- slice 13: session listing ---------------------------------------------------

	def test_list_and_new_session(self):
		created = agent_api.new_session(scope="document", source_document=self.sd.name)
		self.assertIn("session_id", created)
		frappe.db.set_value("Wikify Agent Session", created["session_id"], "title", "My chat")
		listed = agent_api.list_sessions()
		self.assertTrue(any(s["name"] == created["session_id"] for s in listed))
