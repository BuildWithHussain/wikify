"""Tag each section with a section_type via OpenRouter.

Falls back to 'other' (no error) when no key is configured.
"""

from __future__ import annotations

import json

import config


def classify_section(title: str, content: str) -> str:
    if not config.has_openrouter():
        return "other"
    taxonomy = ", ".join(config.SECTION_TYPES)
    prompt = (
        f"Classify this document section into exactly one of: {taxonomy}.\n"
        f'Respond ONLY as JSON: {{"type":"<one of the labels>"}}.\n\n'
        f"TITLE: {title}\nCONTENT (truncated):\n{content[:1500]}"
    )
    try:
        resp = config.chat_completion(
            config.CLASSIFIER_MODEL,
            [{"role": "user", "content": prompt}],
            label="classify",
            response_format={"type": "json_object"},
        )
        label = json.loads(resp.choices[0].message.content or "{}").get("type", "other")
        return label if label in config.SECTION_TYPES else "other"
    except Exception:
        return "other"
