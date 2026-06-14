from __future__ import annotations

from typing import Any


def render_markdown(canonical: dict[str, Any], *, include_source_comments: bool = False) -> str:
    if canonical.get("sections"):
        parts = []
        block_by_id = _block_index(canonical)
        for section in canonical["sections"]:
            blocks = [block_by_id[block_id] for block_id in section.get("block_ids", []) if block_id in block_by_id]
            if include_source_comments:
                parts.append(
                    f"<!-- section:{section['id']} pages:{section.get('page_start')}-{section.get('page_end')} -->"
                )
            parts.append(render_blocks(blocks))
        return "\n\n".join(part for part in parts if part).strip() + "\n"

    blocks = [
        block
        for page in sorted(canonical.get("pages") or [], key=lambda item: item["page_number"])
        for block in sorted(page.get("blocks") or [], key=lambda item: item.get("reading_order") or 0)
    ]
    return render_blocks(blocks).strip() + "\n"


def render_blocks(blocks: list[dict[str, Any]]) -> str:
    rendered = []
    for block in blocks:
        markdown = str(block.get("markdown") or "").strip()
        if not markdown:
            markdown = str(block.get("text") or "").strip()
        if markdown:
            rendered.append(markdown)
    return "\n\n".join(rendered).strip()


def _block_index(canonical: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        block["id"]: block
        for page in canonical.get("pages") or []
        for block in page.get("blocks") or []
    }

