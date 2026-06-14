"""Cloud VLM parser: render page -> image -> markdown via an OpenRouter model.

Model is a config string (VLM_MODEL) so you can switch between Gemini/Mistral/etc.
Renders the page on demand to avoid coupling to the upload pipeline.
"""

from __future__ import annotations

import config
from parsers.base import ParserAdapter
from pdf_utils import image_to_data_url

_PROMPT = (
    "Convert this PDF page into clean, faithful GitHub-flavored Markdown. "
    "Preserve headings with correct levels, lists, and tables (use Markdown table "
    "syntax). Transcribe text exactly as it appears — do NOT summarize, add, or "
    "invent content.\n"
    "If the page contains a flowchart, decision tree, or diagram with boxes and "
    "arrows, represent it as a Mermaid diagram inside a ```mermaid fenced block. "
    "Use `flowchart TD`. Give each node a short id (A, B, C...) and ALWAYS wrap the "
    'node text in double quotes so special characters are safe, e.g. A["Vaginal '
    'delivery >500 mL"]. Use <br> for line breaks inside a label (never \\n). Arrows '
    "are -->. Capture every box and connection. You may follow the diagram with the "
    "same content as a nested list. For non-diagram pages do not emit mermaid.\n"
    "Output only the Markdown — no commentary, and no code fences except ```mermaid."
)


class VLMParser(ParserAdapter):
    name = "vlm"
    requires_api_key = True

    def __init__(self, model: str | None = None):
        self.model = model or config.VLM_MODEL

    def available(self) -> bool:
        return config.has_openrouter()

    def parse_page(self, pdf_path: str, page_no: int, image_path: str | None = None) -> str:
        if image_path is None:
            # Fallback: render just this page if no pre-rendered image was supplied.
            import hashlib

            from pdf_utils import render_and_extract

            key = hashlib.sha1(f"{pdf_path}:{page_no}".encode()).hexdigest()[:12]
            assets = render_and_extract(pdf_path, f"_vlm_{key}")
            image_path = str(next(a for a in assets if a.page_no == page_no).image_path)
        data_url = image_to_data_url(image_path)

        resp = config.chat_completion(
            self.model,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            label="vlm_parse",
            max_tokens=8192,
        )
        return (resp.choices[0].message.content or "").strip()
