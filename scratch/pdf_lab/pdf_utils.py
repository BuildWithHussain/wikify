"""PDF rendering and ground-truth text extraction via PyMuPDF.

Because the target docs are digital-native (selectable text), PyMuPDF's text is a
reliable ground truth for the verification harness.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

import config
from config import PAGES_DIR, RENDER_DPI


@dataclass
class PageAssets:
    page_no: int  # 1-based
    image_path: Path  # rendered PNG
    ground_truth_text: str
    kind: str = "text"  # "text" | "visual"


def classify_page(page) -> str:
    """Heuristic page type. Visual = diagram/flowchart/image-dominant, where the
    extractable text is too sparse to use as ground truth."""
    nchars = len(page.get_text("text").strip())
    n_images = len(page.get_images())
    try:
        n_drawings = len(page.get_drawings())
    except Exception:
        n_drawings = 0
    if nchars < config.VISUAL_MIN_CHARS and (n_images > 0 or n_drawings >= config.VISUAL_MIN_DRAWINGS):
        return "visual"
    return "text"


def page_count(pdf_path: str | Path) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_and_extract(pdf_path: str | Path, doc_id: str) -> list[PageAssets]:
    """Render every page to a PNG and pull its selectable text (ground truth)."""
    out_dir = PAGES_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    zoom = RENDER_DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    assets: list[PageAssets] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            png_path = out_dir / f"page-{i + 1:04d}.png"
            page.get_pixmap(matrix=matrix).save(png_path)
            assets.append(
                PageAssets(
                    page_no=i + 1,
                    image_path=png_path,
                    ground_truth_text=page.get_text("text"),
                    kind=classify_page(page),
                )
            )
    return assets


def page_kind(pdf_path: str | Path, page_no: int) -> str:
    with fitz.open(pdf_path) as doc:
        return classify_page(doc[page_no - 1])


def get_toc(pdf_path: str | Path) -> list[tuple[int, str, int]]:
    """Embedded outline: list of (level, title, page_no). Empty if none."""
    with fitz.open(pdf_path) as doc:
        return [(lvl, title, page) for lvl, title, page in doc.get_toc()]


def image_to_data_url(image_path: str | Path) -> str:
    data = Path(image_path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"
