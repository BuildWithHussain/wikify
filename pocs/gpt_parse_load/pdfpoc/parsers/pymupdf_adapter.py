from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from pdfpoc.models import warning
from pdfpoc.parsers.base import AdapterStatus, ParserAdapter
from pdfpoc.pdf_utils import MissingDependency, filter_page_infos, page_infos, render_page_png


class PyMuPDFAdapter(ParserAdapter):
    provider = "pymupdf4llm"

    def status(self, profile: dict[str, Any] | None = None) -> AdapterStatus:
        if importlib.util.find_spec("fitz") is None:
            return AdapterStatus(False, "PyMuPDF is not installed. Install pymupdf.")
        if importlib.util.find_spec("pymupdf4llm") is None:
            return AdapterStatus(True, "pymupdf4llm missing; will fall back to PyMuPDF text extraction")
        return AdapterStatus(True, "available")

    def parse_document(
        self,
        pdf_path: str | Path,
        profile: dict[str, Any],
        *,
        run_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        raw_warnings: list[dict[str, Any]] = []
        try:
            all_infos = page_infos(pdf_path)
            infos = filter_page_infos(all_infos, profile.get("page_range"))
        except MissingDependency as exc:
            raise RuntimeError(str(exc))

        pymupdf4llm = None
        try:
            import pymupdf4llm as pymupdf4llm_module

            pymupdf4llm = pymupdf4llm_module
        except Exception:
            raw_warnings.append(
                warning(
                    "pymupdf4llm_missing",
                    "pymupdf4llm is not installed; used PyMuPDF selectable text fallback.",
                    severity="warning",
                )
            )

        assets: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        asset_dir = Path(run_dir or ".") / "assets"
        render_dpi = int((profile.get("provider_options") or {}).get("render_dpi", 150))

        for info in infos:
            page_number = int(info["page_number"])
            markdown = ""
            if pymupdf4llm is not None:
                markdown = pymupdf4llm.to_markdown(
                    str(pdf_path),
                    pages=[page_number - 1],
                    show_progress=False,
                ).strip()
            if not markdown:
                markdown = str(info.get("text") or "").strip()

            page_assets: list[dict[str, Any]] = []
            if profile.get("store_page_images"):
                image_path = asset_dir / f"page_{page_number:03d}.png"
                render_page_png(pdf_path, page_number, image_path, dpi=render_dpi)
                asset = {
                    "id": f"asset_page_{page_number:03d}",
                    "type": "page_image",
                    "page_number": page_number,
                    "path": str(image_path),
                    "mime_type": "image/png",
                    "bbox": None,
                    "metadata": {"dpi": render_dpi},
                }
                assets.append(asset)
                page_assets.append(asset)

            pages.append(
                {
                    "page_number": page_number,
                    "width": info.get("width"),
                    "height": info.get("height"),
                    "rotation": info.get("rotation", 0),
                    "markdown": markdown,
                    "text": info.get("text") or "",
                    "source_text": info.get("text") or "",
                    "blocks": [],
                    "assets": page_assets,
                }
            )

        return {
            "provider": self.provider,
            "profile_name": profile["name"],
            "model": profile.get("model", "default"),
            "pages": pages,
            "assets": assets,
            "warnings": raw_warnings,
            "metadata": {
                "parser": "pymupdf4llm" if pymupdf4llm is not None else "pymupdf_text",
                "total_page_count": len(all_infos),
            },
        }
