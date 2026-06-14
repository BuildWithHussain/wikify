from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - handled at runtime with a clear error
    yaml = None

POC_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = POC_ROOT.parents[1]
PROFILES_DIR = POC_ROOT / "profiles"
RUNS_DIR = POC_ROOT / "runs"
ROOT_DOTENV = APP_ROOT / ".env"

COMMON_PROFILE_DEFAULTS: dict[str, Any] = {
    "model": "default",
    "mode": "local",
    "page_range": "all",
    "ocr": "auto",
    "extract_images": False,
    "extract_tables": True,
    "table_format": "markdown",
    "include_bboxes": True,
    "include_confidence": False,
    "remove_headers_footers": False,
    "build_sections": True,
    "markdown_style": "commonmark",
    "store_raw_output": True,
    "store_page_images": False,
    "timeout_seconds": 600,
    "provider_options": {},
}


def load_root_dotenv(path: str | Path = ROOT_DOTENV) -> dict[str, str]:
    """Load simple KEY=VALUE pairs without adding a python-dotenv dependency."""

    env_path = Path(path)
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        value = value.strip()
        if value:
            try:
                parsed = shlex.split(value, comments=False, posix=True)
            except ValueError:
                parsed = [value]
            value = parsed[0] if len(parsed) == 1 else value
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


def openrouter_api_key(profile: dict[str, Any] | None = None) -> str | None:
    load_root_dotenv()
    candidates: list[str] = []
    if profile and profile.get("api_key_env"):
        candidates.append(str(profile["api_key_env"]))
    candidates.extend(["OPENROUTER_API_KEY", "OPENROUTER_KEY"])
    for key in candidates:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def read_yaml(path: str | Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to read profile files. Install requirements.txt.")
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Profile must be a mapping: {path}")
    return data


def resolve_profile_path(profile: str | Path) -> Path:
    candidate = Path(profile)
    if candidate.exists():
        return candidate
    if candidate.suffix not in {".yaml", ".yml"}:
        for suffix in (".yaml", ".yml"):
            named = PROFILES_DIR / f"{profile}{suffix}"
            if named.exists():
                return named
    named = PROFILES_DIR / str(profile)
    if named.exists():
        return named
    raise FileNotFoundError(f"Profile not found: {profile}")


def load_profile(profile: str | Path) -> dict[str, Any]:
    path = resolve_profile_path(profile)
    loaded = read_yaml(path)
    effective = {**COMMON_PROFILE_DEFAULTS, **loaded}
    effective["provider_options"] = {
        **COMMON_PROFILE_DEFAULTS["provider_options"],
        **(loaded.get("provider_options") or {}),
    }
    effective["_profile_path"] = str(path)
    if not effective.get("name"):
        effective["name"] = path.stem
    if not effective.get("provider"):
        raise ValueError(f"Profile missing provider: {path}")
    return effective

