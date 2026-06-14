"""Docling adapter (local ML). Optional/lazy: heavy (torch) deps.

If docling isn't installed, `available()` returns False and the registry hides it.
Per-page conversion uses docling's page_range so per-page scoring stays uniform.
"""

from __future__ import annotations

from functools import lru_cache

from parsers.base import ParserAdapter


@lru_cache(maxsize=1)
def _converter():
    from docling.document_converter import DocumentConverter

    return DocumentConverter()


class DoclingParser(ParserAdapter):
    name = "docling"
    requires_api_key = False

    def available(self) -> bool:
        try:
            import docling  # noqa: F401

            return True
        except Exception:
            return False

    def parse_page(self, pdf_path: str, page_no: int, image_path: str | None = None) -> str:
        # docling page_range is 1-based inclusive; image_path unused.
        result = _converter().convert(pdf_path, page_range=(page_no, page_no))
        return result.document.export_to_markdown()
