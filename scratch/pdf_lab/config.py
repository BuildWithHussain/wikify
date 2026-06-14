"""Central config: env, model names, paths, scoring thresholds.

One OpenRouter client is shared by the VLM parser, the LLM-as-judge, and the
section classifier. Models are config strings so you can swap them without
touching code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# Search upward from cwd so a repo-root .env is found too (not just pdf_lab/.env).
load_dotenv(find_dotenv(usecwd=True))

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
PAGES_DIR = STORAGE_DIR / "pages"  # rendered page PNGs, served for preview
DB_PATH = STORAGE_DIR / "lab.db"

for _d in (STORAGE_DIR, UPLOADS_DIR, PAGES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Accept either OPENROUTER_API_KEY or OPENROUTER_KEY.
OPENROUTER_API_KEY = (
    os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY") or ""
).strip()
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Mistral-medium-3.1 won the flagged-page bake-off (most robust; Gemini failed on
# dense pages). See bakeoff.py.
VLM_MODEL = os.environ.get("VLM_MODEL", "mistralai/mistral-medium-3.1")
# Cheap text model for the markdown cleanup pass (restructures mangled baseline
# text — no image needed when the text is present but badly formatted).
CLEANUP_MODEL = os.environ.get("CLEANUP_MODEL", "google/gemini-2.5-flash")
# Cleanup runs on every page; adopt it unless recall drops more than this below the
# baseline (a small drop = intended header/footer removal; a big drop = content loss).
CLEANUP_RECALL_TOLERANCE = 0.12
# Judge is intentionally a DIFFERENT model from the parser — an independent grader
# shouldn't be the same model that produced the output (avoids self-confirmation).
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "anthropic/claude-sonnet-4.6")
CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", "google/gemini-2.5-flash")

# Section taxonomy used by the classifier. Derived bottom-up from the real
# manuals' headings (see README); edit to fit your corpus.
SECTION_TYPES = [
    "staff_roles_and_responsibilities",
    "clinical_protocols",
    "surgical_procedures",
    "patient_management",
    "medication_management",
    "administrative_policies",
    "equipment_and_facilities",
    "training_and_audits",
    "research_and_documentation",
    "emergency_procedures",
    "other",
]

# Verdict thresholds on the composite score (tune during calibration).
PASS_THRESHOLD = 0.90
ESCALATE_THRESHOLD = 0.70

# Composite weights for TEXT pages (table term dropped + renormalized when no table).
WEIGHTS = {
    "text_recall": 0.40,
    "not_hallucinated": 0.15,  # applied to (1 - extra_ratio)
    "table_score": 0.15,
    "judge_score": 0.30,
}

# VISUAL pages (diagrams/flowcharts/images): PyMuPDF text is near-empty there, so
# recall/extra are meaningless and even inverted (they reward an empty parse). The
# judge looking at the page image is the only valid arbiter.
VISUAL_WEIGHTS = {
    "judge_score": 0.85,
    "table_score": 0.15,
}

# A page is "visual" when it has little extractable text but does have images or
# substantial vector drawings (a flowchart is vector lines + a few labels).
VISUAL_MIN_CHARS = 250
VISUAL_MIN_DRAWINGS = 40

# DPI for rendering pages to PNG (preview + VLM/judge input).
RENDER_DPI = 150


def has_openrouter() -> bool:
    return bool(OPENROUTER_API_KEY)


@lru_cache(maxsize=1)
def openrouter_client():
    """Lazy singleton OpenAI-compatible client pointed at OpenRouter."""
    if not has_openrouter():
        raise RuntimeError("OPENROUTER_API_KEY not set; cloud features unavailable.")
    from openai import OpenAI

    return OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)


# --- lightweight per-call metrics (cost + latency), used by the benchmark ---
import threading  # noqa: E402
import time as _time  # noqa: E402

_metrics_lock = threading.Lock()
_metrics: list[dict] = []


def reset_metrics() -> None:
    with _metrics_lock:
        _metrics.clear()


def get_metrics() -> list[dict]:
    with _metrics_lock:
        return list(_metrics)


def chat_completion(model: str, messages: list, label: str = "", **kw):
    """Wrapper around OpenRouter chat that records latency + token cost per call."""
    client = openrouter_client()
    kw.setdefault("temperature", 0)
    body = kw.pop("extra_body", {}) or {}
    body.setdefault("usage", {"include": True})  # ask OpenRouter to return cost
    t0 = _time.time()
    resp = client.chat.completions.create(model=model, messages=messages, extra_body=body, **kw)
    dt = _time.time() - t0
    usage = {}
    try:
        usage = (resp.model_dump().get("usage") or {})
    except Exception:
        pass
    with _metrics_lock:
        _metrics.append({
            "label": label, "model": model, "seconds": dt,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cost": usage.get("cost"),
        })
    return resp
