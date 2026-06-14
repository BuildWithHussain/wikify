"""Baseline: pymupdf4llm. Fast, local, no key. The floor every parser must beat."""

from __future__ import annotations

import pymupdf4llm

from parsers.base import ParserAdapter


class PyMuPDFParser(ParserAdapter):
    name = "pymupdf4llm"
    requires_api_key = False

    def parse_page(self, pdf_path: str, page_no: int, image_path: str | None = None) -> str:
        # pymupdf4llm uses 0-based page indices; image_path unused (text-based).
        return pymupdf4llm.to_markdown(pdf_path, pages=[page_no - 1], show_progress=False)
