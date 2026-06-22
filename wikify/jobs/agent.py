"""Background job that runs one agent turn off the web worker.

`api.agent.run` enqueues this on the `long` queue and returns 202; the answer streams
back to the user over the `wikify_agent_*` realtime channels.
"""

from __future__ import annotations

import frappe

from wikify.agent.loop import AgentRunner


def run_agent_job(session_id: str, user: str, attachments: list | None = None) -> None:
	frappe.set_user(user)
	AgentRunner(session_id, user, attachments=attachments).run()
