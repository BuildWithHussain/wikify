from __future__ import annotations

from typing import Any

from pdfpoc.parsers.base import ParserAdapter, ParserUnavailable
from pdfpoc.parsers.docling_adapter import DoclingAdapter
from pdfpoc.parsers.openrouter_vlm_adapter import OpenRouterVLMAdapter
from pdfpoc.parsers.pymupdf_adapter import PyMuPDFAdapter

_ADAPTERS: dict[str, ParserAdapter] = {
    PyMuPDFAdapter.provider: PyMuPDFAdapter(),
    "pymupdf": PyMuPDFAdapter(),
    DoclingAdapter.provider: DoclingAdapter(),
    OpenRouterVLMAdapter.provider: OpenRouterVLMAdapter(),
}


def available_adapters(profile: dict[str, Any] | None = None) -> dict[str, str]:
    return {
        provider: adapter.status(profile).reason or "available"
        for provider, adapter in _ADAPTERS.items()
        if adapter.available(profile)
    }


def adapter_for_profile(profile: dict[str, Any]) -> ParserAdapter:
    provider = str(profile.get("provider", ""))
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise ParserUnavailable(f"No adapter registered for provider '{provider}'")
    status = adapter.status(profile)
    if not status.available:
        raise ParserUnavailable(status.reason)
    return adapter

