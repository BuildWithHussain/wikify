from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


class MissingDependency(RuntimeError):
    pass


def import_fitz():
    try:
        import fitz
    except Exception:
        raise MissingDependency("PyMuPDF is required for PDF page inspection/rendering. Install pymupdf.")
    return fitz


def page_infos(pdf_path: str | Path) -> list[dict[str, Any]]:
    fitz = import_fitz()
    infos: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc):
            rect = page.rect
            infos.append(
                {
                    "page_number": index + 1,
                    "width": float(rect.width),
                    "height": float(rect.height),
                    "rotation": int(page.rotation or 0),
                    "text": page.get_text("text"),
                }
            )
    return infos


def page_count(pdf_path: str | Path) -> int:
    return len(page_infos(pdf_path))


def selected_page_numbers(page_count: int, page_range: Any = "all") -> list[int]:
    if page_range in (None, "", "all"):
        return list(range(1, page_count + 1))
    if isinstance(page_range, int):
        page_range = str(page_range)
    if isinstance(page_range, (list, tuple)):
        values = [int(item) for item in page_range]
        return _valid_pages(values, page_count)
    pages: list[int] = []
    for part in str(page_range).split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            step = 1 if end >= start else -1
            pages.extend(range(start, end + step, step))
        else:
            pages.append(int(token))
    return _valid_pages(pages, page_count)


def filter_page_infos(infos: list[dict[str, Any]], page_range: Any = "all") -> list[dict[str, Any]]:
    selected = set(selected_page_numbers(len(infos), page_range))
    return [info for info in infos if int(info["page_number"]) in selected]


def render_page_png(pdf_path: str | Path, page_number: int, out_path: str | Path, dpi: int = 200) -> Path:
    fitz = import_fitz()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        page = doc[page_number - 1]
        page.get_pixmap(matrix=matrix, alpha=False).save(out)
    return out


def image_to_data_url(path: str | Path) -> str:
    data = Path(path).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _valid_pages(pages: list[int], page_count: int) -> list[int]:
    seen: set[int] = set()
    valid: list[int] = []
    for page in pages:
        if page < 1 or page > page_count or page in seen:
            continue
        seen.add(page)
        valid.append(page)
    return valid
