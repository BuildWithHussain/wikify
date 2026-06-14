from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ParserUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterStatus:
    available: bool
    reason: str = ""


class ParserAdapter(ABC):
    provider = "base"

    def status(self, profile: dict[str, Any] | None = None) -> AdapterStatus:
        return AdapterStatus(True, "")

    def available(self, profile: dict[str, Any] | None = None) -> bool:
        return self.status(profile).available

    @abstractmethod
    def parse_document(
        self,
        pdf_path: str | Path,
        profile: dict[str, Any],
        *,
        run_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Return raw provider output plus basic metadata."""

