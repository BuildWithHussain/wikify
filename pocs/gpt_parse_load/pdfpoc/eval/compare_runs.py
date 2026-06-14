from __future__ import annotations

from typing import Any

from pdfpoc.eval.checks import evaluate_canonical


def compare_canonicals(canonicals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [evaluate_canonical(canonical) for canonical in canonicals]
    return sorted(rows, key=lambda row: (row.get("document") or "", row.get("profile") or ""))

