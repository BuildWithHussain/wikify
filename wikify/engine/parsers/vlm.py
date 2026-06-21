"""Cloud VLM parser: a rendered page image -> markdown via an OpenRouter model.

Used by remediation to re-parse visual / low-recall pages from their image. The
model is a `Wikify Settings` value (`vlm_model`) so it's switchable without code.

Ported from the POC `parsers/vlm_parser.py`. The page is already rendered upstream
(`pdf_utils.render_png` -> data URL), so this takes the data URL directly — no
on-demand re-render, no `image_to_data_url` disk round-trip.
"""

from __future__ import annotations

from wikify.engine import llm, settings
from wikify.engine.loader.cleanup import strip_outer_markdown_fence

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


def parse_page_image(image_data_url: str, model: str | None = None) -> str:
	"""Markdown for a single page, read from its rendered image (data URL)."""
	resp = llm.chat_completion(
		model or settings.get("vlm_model"),
		[
			{
				"role": "user",
				"content": [
					{"type": "text", "text": _PROMPT},
					{"type": "image_url", "image_url": {"url": image_data_url}},
				],
			}
		],
		label="vlm_parse",
		max_tokens=8192,
	)
	return strip_outer_markdown_fence((resp["choices"][0]["message"]["content"] or "").strip())
