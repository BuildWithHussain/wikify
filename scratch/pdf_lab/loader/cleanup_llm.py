"""Cheap text-only markdown cleanup.

When the baseline extractor produced all the text but mangled the structure
(picture-omitted wrappers, broken tables, <br> blobs), a cheap text model can
restructure it WITHOUT the page image. It must not change the actual content —
the caller re-scores recall as a guard.
"""

from __future__ import annotations

import config

_PROMPT = (
    "You are cleaning Markdown that a PDF-extraction tool produced. The tool sometimes "
    "mangles layout. Fix the FORMATTING without changing the actual content:\n"
    "- Remove extraction artifacts: 'picture intentionally omitted', 'Start/End of picture "
    "text' markers, stray <br>, and empty table rows like ||||.\n"
    "- Remove running page furniture (headers/footers): the repeated document-title banner, "
    "the document-code / version / issue / date line, 'Page X of Y', and the "
    "prepared-by / issued-by / approved-by footer block. Keep only the page's substantive content.\n"
    "- Restore real Markdown structure: headings (#/##/###), numbered and bulleted lists, "
    "and proper Markdown tables (only when the content is genuinely tabular).\n"
    "- Keep ALL substantive text. Do NOT summarize, add, translate, or drop real content.\n"
    "- Output ONLY the cleaned Markdown — no commentary, no code fences.\n\nMARKDOWN:\n"
)


def clean_markdown(raw_markdown: str, model: str | None = None) -> str:
    if not raw_markdown.strip():
        return raw_markdown
    resp = config.chat_completion(
        model or config.CLEANUP_MODEL,
        [{"role": "user", "content": _PROMPT + raw_markdown}],
        label="cleanup",
        max_tokens=4096,
    )
    return (resp.choices[0].message.content or "").strip()
