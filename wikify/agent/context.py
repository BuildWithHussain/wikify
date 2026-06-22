"""Per-turn context for tool handlers + (later) attachment resolution.

Slice 12 is global-scope only: `Ctx` carries the session/user and an optional default
`source_document`/`project`, and `attachment_messages()` is a no-op. Slice 13 grows
`Ctx` to resolve `attachments[]` into a bounded context block and to scope tool
defaults from the attached document/project.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ctx:
	"""What a tool handler needs: the session it runs in + scoping defaults."""

	session: str
	user: str
	project: str | None = None
	source_document: str | None = None
	attachments: list[dict] = field(default_factory=list)

	def default_document(self, explicit: str | None = None) -> str | None:
		"""A tool's `source_document` arg, falling back to the attached document."""
		return explicit or self.source_document


def attachment_messages(ctx: Ctx) -> list[dict]:
	"""Resolve attachments into a context block prepended to the turn (slice 13).

	Walking skeleton: no attachments yet, so no context block.
	"""
	return []
