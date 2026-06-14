from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from pdfpoc.models import warning
from pdfpoc.parsers.base import AdapterStatus, ParserAdapter
from pdfpoc.pdf_utils import MissingDependency, filter_page_infos, page_infos, render_page_png


class DoclingAdapter(ParserAdapter):
    provider = "docling"

    def status(self, profile: dict[str, Any] | None = None) -> AdapterStatus:
        if importlib.util.find_spec("docling") is None:
            return AdapterStatus(False, "Docling is not installed. Install docling to use this profile.")
        return AdapterStatus(True, "available")

    def parse_document(
        self,
        pdf_path: str | Path,
        profile: dict[str, Any],
        *,
        run_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        from docling.document_converter import DocumentConverter

        raw_warnings: list[dict[str, Any]] = []
        converter = DocumentConverter()
        try:
            all_infos = page_infos(pdf_path)
            infos = filter_page_infos(all_infos, profile.get("page_range"))
        except MissingDependency:
            all_infos = []
            infos = [{"page_number": 1, "width": None, "height": None, "rotation": 0, "text": ""}]
            raw_warnings.append(
                warning(
                    "pymupdf_missing",
                    "PyMuPDF is not installed; Docling output could not be split by page.",
                    severity="warning",
                )
            )

        assets: list[dict[str, Any]] = []
        asset_dir = Path(run_dir or ".") / "assets"
        render_dpi = int((profile.get("provider_options") or {}).get("render_dpi", 150))
        pages: list[dict[str, Any]] = []

        for info in infos:
            page_number = int(info["page_number"])
            markdown = _convert_page_to_markdown(converter, pdf_path, page_number, raw_warnings)
            page_assets: list[dict[str, Any]] = []
            if profile.get("store_page_images") and info.get("width") is not None:
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
            "metadata": {"parser": "docling", "total_page_count": len(all_infos) or len(infos)},
        }


def _convert_page_to_markdown(
    converter: Any,
    pdf_path: str | Path,
    page_number: int,
    raw_warnings: list[dict[str, Any]],
) -> str:
    try:
        result = converter.convert(str(pdf_path), page_range=(page_number, page_number))
    except TypeError:
        if not raw_warnings or raw_warnings[-1].get("code") != "docling_page_range_unsupported":
            raw_warnings.append(
                warning(
                    "docling_page_range_unsupported",
                    "Docling convert() did not accept page_range; falling back to full-document conversion.",
                    severity="warning",
                )
            )
        result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown().strip()
