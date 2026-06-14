from __future__ import annotations

from typing import Any

from pdfpoc.normalize.markdown_renderer import render_blocks


def build_sections(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered_blocks = [
        (page["page_number"], block)
        for page in sorted(pages, key=lambda item: item["page_number"])
        for block in sorted(page.get("blocks") or [], key=lambda item: item.get("reading_order") or 0)
    ]
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is None or not current["block_ids"]:
            return
        section_blocks = [
            block
            for _page_number, block in ordered_blocks
            if block["id"] in set(current["block_ids"])
        ]
        current["page_start"] = min(_page_for_block(pages, block["id"]) for block in section_blocks)
        current["page_end"] = max(_page_for_block(pages, block["id"]) for block in section_blocks)
        current["markdown"] = render_blocks(section_blocks)
        sections.append(current.copy())

    for page_number, block in ordered_blocks:
        if block.get("type") == "heading":
            flush()
            level = int(block.get("level") or 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            title = str(block.get("text") or "").strip() or "Untitled"
            stack.append((level, title))
            current = {
                "id": f"section_{len(sections) + 1:03d}",
                "title": title,
                "heading_path": [item[1] for item in stack],
                "level": level,
                "page_start": page_number,
                "page_end": page_number,
                "block_ids": [block["id"]],
                "markdown": "",
                "confidence": block.get("confidence"),
                "metadata": {},
            }
            continue

        if current is None:
            current = {
                "id": f"section_{len(sections) + 1:03d}",
                "title": "Preamble",
                "heading_path": ["Preamble"],
                "level": 1,
                "page_start": page_number,
                "page_end": page_number,
                "block_ids": [],
                "markdown": "",
                "confidence": None,
                "metadata": {"synthetic": True},
            }
        current["block_ids"].append(block["id"])
        current["page_end"] = page_number

    flush()
    return sections


def _page_for_block(pages: list[dict[str, Any]], block_id: str) -> int:
    for page in pages:
        for block in page.get("blocks") or []:
            if block["id"] == block_id:
                return int(page["page_number"])
    raise KeyError(block_id)

