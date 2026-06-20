"""Whitelisted APIs for the Imports flow."""

from __future__ import annotations

import frappe


@frappe.whitelist()
def start_import(pdf_file_url: str, title: str) -> str:
	"""Create a Wikify Import for an uploaded PDF and enqueue the parse job.

	Returns the new Import's name so the SPA can route to its detail page.
	"""
	imp = frappe.new_doc("Wikify Import")
	imp.import_title = title
	imp.pdf = pdf_file_url
	imp.status = "Queued"
	imp.insert()

	frappe.enqueue(
		"wikify.jobs.parse.run",
		queue="long",
		timeout=3600,
		import_name=imp.name,
	)
	return imp.name


@frappe.whitelist()
def trigger_remediation(import_name: str, scope: str = "flagged") -> str:
	"""Enqueue the remediation pass over an imported doc's pages.

	`scope` is `flagged` (non-pass pages only) or `all` (every page). Only runs from
	`Review`; flips the Import to `Remediating` and returns its name.
	"""
	if scope not in ("flagged", "all"):
		frappe.throw(f"Invalid scope: {scope!r} (expected 'flagged' or 'all').")

	imp = frappe.get_doc("Wikify Import", import_name)
	if not imp.source_document:
		frappe.throw("Nothing to remediate — parse hasn't produced a document yet.")
	if imp.status != "Review":
		frappe.throw(f"Can only remediate from Review (current status: {imp.status}).")

	imp.db_set("status", "Remediating")
	frappe.enqueue(
		"wikify.jobs.remediate.run",
		queue="long",
		timeout=3600,
		import_name=import_name,
		scope=scope,
	)
	return import_name
