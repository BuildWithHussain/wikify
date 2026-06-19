# Copyright (c) 2026, BWH and Contributors
# See license.txt

import frappe
from frappe.core.api.file import get_max_file_size
from frappe.utils import get_system_timezone

no_cache = 1


def get_context(context):
	"""Server-side gate + boot payload for the Wikify SPA.

	Guests are bounced to the login screen (with a redirect back to /wikify);
	authenticated users get the boot dict that main.js reads off `window`.
	"""
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/wikify"
		raise frappe.Redirect

	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()

	context.boot = get_boot()
	context.boot.csrf_token = csrf_token
	context.csrf_token = csrf_token
	return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
	"""Dev-only: vite dev server fetches boot values to put on `window`."""
	if not frappe.conf.developer_mode:
		frappe.throw("This method is only meant for developer mode")
	return get_boot()


def get_boot():
	return frappe._dict(
		{
			"frappe_version": frappe.__version__,
			"site_name": frappe.local.site,
			"default_route": "/",
			"read_only_mode": frappe.flags.read_only,
			"max_file_size": get_max_file_size(),
			"system_timezone": get_system_timezone(),
		}
	)
