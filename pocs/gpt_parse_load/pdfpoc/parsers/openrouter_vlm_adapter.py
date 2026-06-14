from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from typing import Any

import requests

from pdfpoc.config import openrouter_api_key
from pdfpoc.models import warning
from pdfpoc.parsers.base import AdapterStatus, ParserAdapter
from pdfpoc.pdf_utils import MissingDependency, filter_page_infos, image_to_data_url, page_infos, render_page_png

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PROMPTS = {
    "pdf_page_to_markdown_v1": (
        "Convert this PDF page into faithful Markdown and JSON metadata. "
        "Preserve headings with correct levels, lists, tables, reading order, and visible text. "
        "Do not summarize or invent content. Use HTML tables when Markdown would lose merged cells. "
        "Respond with JSON containing: markdown, warnings, and optional blocks. "
        "Each block may include type, text, markdown, level, bbox, confidence, and reading_order."
    ),
    "pdf_page_to_markdown_plain_v1": (
        "Convert this PDF page into faithful Markdown. Preserve all visible text, reading order, "
        "headings, lists, and tables. Do not summarize or invent content. Use a Markdown table for "
        "simple tabular content. Output only Markdown, with no commentary and no code fences."
    ),
}


class OpenRouterVLMAdapter(ParserAdapter):
    provider = "openrouter"

    def status(self, profile: dict[str, Any] | None = None) -> AdapterStatus:
        if not openrouter_api_key(profile):
            return AdapterStatus(False, "OpenRouter key not found in env, OPENROUTER_API_KEY, or OPENROUTER_KEY.")
        try:
            from pdfpoc.pdf_utils import import_fitz

            import_fitz()
        except MissingDependency as exc:
            return AdapterStatus(False, str(exc))
        return AdapterStatus(True, "available")

    def parse_document(
        self,
        pdf_path: str | Path,
        profile: dict[str, Any],
        *,
        run_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        api_key = openrouter_api_key(profile)
        if not api_key:
            raise RuntimeError("OpenRouter API key not found.")

        provider_options = profile.get("provider_options") or {}
        render_dpi = int(provider_options.get("render_dpi", 200))
        prompt_name = str(provider_options.get("prompt_name", "pdf_page_to_markdown_v1"))
        require_json = bool(provider_options.get("require_json_response", True))
        fallback_on_error = bool(provider_options.get("fallback_on_error", True))
        asset_dir = Path(run_dir or ".") / "assets"

        all_infos = page_infos(pdf_path)
        infos = filter_page_infos(all_infos, profile.get("page_range"))
        pages: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        raw_warnings: list[dict[str, Any]] = []
        total_cost = 0.0

        for info in infos:
            page_number = int(info["page_number"])
            image_path = asset_dir / f"page_{page_number:03d}.png"
            render_page_png(pdf_path, page_number, image_path, dpi=render_dpi)
            asset = {
                "id": f"asset_page_{page_number:03d}",
                "type": "page_image",
                "page_number": page_number,
                "path": str(image_path),
                "mime_type": "image/png",
                "bbox": None,
                "metadata": {"dpi": render_dpi, "prompt_name": prompt_name, "fallback": False},
            }

            try:
                data, parsed, cost = _request_openrouter_page(
                    api_key,
                    profile,
                    provider_options,
                    image_path,
                    prompt_name,
                    require_json,
                    page_number,
                    len(all_infos),
                )
                active_asset = asset
            except Exception as exc:
                if not fallback_on_error:
                    raise
                raw_warnings.append(
                    warning(
                        "openrouter_primary_failed",
                        f"Primary OpenRouter parse failed; retried with fallback settings. Error: {exc}",
                        severity="warning",
                        page_number=page_number,
                    )
                )
                fallback_render_dpi = int(provider_options.get("fallback_render_dpi", 120))
                fallback_prompt_name = str(provider_options.get("fallback_prompt_name", "pdf_page_to_markdown_plain_v1"))
                fallback_require_json = bool(provider_options.get("fallback_require_json_response", False))
                fallback_image_path = asset_dir / f"page_{page_number:03d}_fallback_{fallback_render_dpi}.png"
                render_page_png(pdf_path, page_number, fallback_image_path, dpi=fallback_render_dpi)
                active_asset = {
                    "id": f"asset_page_{page_number:03d}_fallback",
                    "type": "page_image",
                    "page_number": page_number,
                    "path": str(fallback_image_path),
                    "mime_type": "image/png",
                    "bbox": None,
                    "metadata": {
                        "dpi": fallback_render_dpi,
                        "prompt_name": fallback_prompt_name,
                        "fallback": True,
                        "fallback_reason": str(exc),
                    },
                }
                data, parsed, cost = _request_openrouter_page(
                    api_key,
                    profile,
                    provider_options,
                    fallback_image_path,
                    fallback_prompt_name,
                    fallback_require_json,
                    page_number,
                    len(all_infos),
                )

            assets.append(active_asset)
            total_cost += cost
            for item in parsed.get("warnings", []) or []:
                raw_warnings.append(
                    warning(
                        str(item.get("code") or "model_warning"),
                        str(item.get("message") or item),
                        severity=str(item.get("severity") or "warning"),
                        page_number=page_number,
                    )
                )

            pages.append(
                {
                    "page_number": page_number,
                    "width": info.get("width"),
                    "height": info.get("height"),
                    "rotation": info.get("rotation", 0),
                    "markdown": parsed.get("markdown", ""),
                    "text": parsed.get("text", ""),
                    "source_text": info.get("text") or "",
                    "blocks": parsed.get("blocks") or [],
                    "assets": [active_asset],
                    "raw_response": data if profile.get("store_raw_output") else None,
                }
            )

        return {
            "provider": self.provider,
            "profile_name": profile["name"],
            "model": profile.get("model"),
            "pages": pages,
            "assets": assets,
            "warnings": raw_warnings,
            "metadata": {
                "parser": "openrouter_vlm",
                "cost_usd": total_cost or None,
                "total_page_count": len(all_infos),
            },
        }


def _request_openrouter_page(
    api_key: str,
    profile: dict[str, Any],
    provider_options: dict[str, Any],
    image_path: Path,
    prompt_name: str,
    require_json: bool,
    page_number: int,
    total_pages: int,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    prompt = PROMPTS.get(prompt_name, PROMPTS["pdf_page_to_markdown_v1"])
    payload: dict[str, Any] = {
        "model": profile["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                ],
            }
        ],
        "temperature": float(provider_options.get("temperature", 0)),
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    print(
        f"OpenRouter parse page {page_number}/{total_pages} with {profile['model']} ({prompt_name})",
        file=sys.stderr,
        flush=True,
    )
    timeout_seconds = int(profile.get("timeout_seconds", 1200))
    with _wall_clock_timeout(timeout_seconds, f"OpenRouter page {page_number} timed out after {timeout_seconds}s"):
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local.wikify.poc",
                "X-Title": "Wikify GPT Parse Load PoC",
            },
            json=payload,
            timeout=(15, timeout_seconds),
        )
    response.raise_for_status()
    data = response.json()
    print(f"OpenRouter completed page {page_number}", file=sys.stderr, flush=True)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return data, _parse_model_content(content), _extract_cost(data)


def _parse_model_content(content: str) -> dict[str, Any]:
    if not content:
        return {"markdown": "", "warnings": [{"message": "Model returned empty content."}]}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {"markdown": content.strip(), "warnings": []}
    if not isinstance(data, dict):
        return {"markdown": str(data), "warnings": []}
    if "markdown" not in data:
        for key in ("md", "text", "content"):
            if key in data:
                data["markdown"] = data[key]
                break
    data.setdefault("markdown", "")
    data.setdefault("warnings", [])
    return data


def _extract_cost(response_json: dict[str, Any]) -> float:
    usage = response_json.get("usage") or {}
    for key in ("cost", "total_cost", "cost_usd"):
        value = usage.get(key) or response_json.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


class _wall_clock_timeout:
    def __init__(self, seconds: int, message: str):
        self.seconds = seconds
        self.message = message
        self.previous_handler = None

    def __enter__(self):
        if self.seconds <= 0 or not hasattr(signal, "SIGALRM"):
            return self
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self.seconds)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.seconds > 0 and hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, self.previous_handler)
        return False

    def _handle_timeout(self, signum, frame):
        raise TimeoutError(self.message)
