"""Uniform parser interface so engines are pluggable and skippable.

Every adapter exposes per-page markdown; `parse_document` defaults to looping
pages so per-page verification scoring works identically across engines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pdf_utils import page_count


class ParserAdapter(ABC):
    name: str = "base"
    requires_api_key: bool = False

    def available(self) -> bool:
        """Whether this parser can run right now (deps installed, key present)."""
        return True

    @abstractmethod
    def parse_page(self, pdf_path: str, page_no: int, image_path: str | None = None) -> str:
        """Return markdown for a single 1-based page.

        image_path is an optional pre-rendered PNG of the page (lets image-based
        parsers skip re-rendering). Text-based parsers ignore it.
        """

    def parse_document(self, pdf_path: str) -> list[str]:
        return [self.parse_page(pdf_path, p) for p in range(1, page_count(pdf_path) + 1)]
