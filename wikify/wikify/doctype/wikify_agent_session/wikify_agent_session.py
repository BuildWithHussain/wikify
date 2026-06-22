# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document


class WikifyAgentSession(Document):
	def on_trash(self) -> None:
		"""Cascade-delete this session's messages (they aren't a child table)."""
		frappe.db.delete("Wikify Agent Message", {"session": self.name})
