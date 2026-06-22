"""Tool dataclass + registry.

Builder's pattern — plain `Tool` instances collected from module-level `TOOLS` lists,
no decorator. Adding a capability = registering one Tool; the loop never changes.
Handlers call existing `api/` and `jobs/` functions; they don't re-implement pipeline
logic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from wikify.agent.context import Ctx


@dataclass
class Tool:
	name: str
	side: Literal["server", "terminal"]
	description: str
	parameters: dict  # raw JSON-schema for the function args
	handler: Callable[[Ctx, dict], str]  # runs it; returns a result/summary string


def build_default_registry() -> dict[str, Tool]:
	"""All available tools, keyed by name. Slice 12: read tools only."""
	from wikify.agent.tools import read

	registry: dict[str, Tool] = {}
	for module in (read,):
		for tool in module.TOOLS:
			registry[tool.name] = tool
	return registry
