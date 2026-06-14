"""Parser registry. Cloud/optional parsers auto-hide when unavailable."""

from __future__ import annotations

from parsers.base import ParserAdapter
from parsers.docling_parser import DoclingParser
from parsers.pymupdf_parser import PyMuPDFParser
from parsers.vlm_parser import VLMParser

_ALL: list[ParserAdapter] = [PyMuPDFParser(), DoclingParser(), VLMParser()]


def available_parsers() -> list[ParserAdapter]:
    return [p for p in _ALL if p.available()]


def get_parser(name: str) -> ParserAdapter:
    for p in _ALL:
        if p.name == name:
            return p
    raise KeyError(f"Unknown parser: {name}")
