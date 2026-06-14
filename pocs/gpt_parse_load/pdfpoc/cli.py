from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # pragma: no cover - supports direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdfpoc.config import PROFILES_DIR, RUNS_DIR, load_profile, load_root_dotenv, resolve_profile_path
from pdfpoc.eval.checks import evaluate_canonical
from pdfpoc.eval.compare_runs import compare_canonicals
from pdfpoc.load.loader import load_canonical
from pdfpoc.load.sqlite_graph import inspect_database
from pdfpoc.models import new_run_id, read_json, slugify, utc_now, write_json
from pdfpoc.normalize.canonical import canonicalize_raw
from pdfpoc.normalize.markdown_renderer import render_markdown
from pdfpoc.normalize.section_builder import build_sections
from pdfpoc.parsers.base import ParserUnavailable
from pdfpoc.parsers.registry import adapter_for_profile


def main(argv: list[str] | None = None) -> int:
    load_root_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdfpoc", description="Standalone GPT PDF parse/load PoC")
    sub = parser.add_subparsers(required=True)

    parse_cmd = sub.add_parser("parse", help="Parse a PDF into raw, canonical, and markdown artifacts")
    parse_cmd.add_argument("pdf")
    parse_cmd.add_argument("--profile", required=True, help="Profile path or profile name from profiles/")
    parse_cmd.add_argument("--runs-dir", default=str(RUNS_DIR))
    parse_cmd.add_argument("--out-dir", default=None)
    parse_cmd.add_argument("--pages", default=None, help="Override profile page_range, e.g. 1-3 or 1,5,8")
    parse_cmd.add_argument("--timeout-seconds", type=int, default=None, help="Override profile timeout_seconds")
    parse_cmd.add_argument(
        "--provider-option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override profile.provider_options, e.g. render_dpi=120",
    )
    parse_cmd.set_defaults(func=cmd_parse)

    render_cmd = sub.add_parser("render", help="Render canonical JSON to markdown")
    render_cmd.add_argument("canonical_json")
    render_cmd.add_argument("--out", required=True)
    render_cmd.add_argument("--source-comments", action="store_true")
    render_cmd.set_defaults(func=cmd_render)

    load_cmd = sub.add_parser("load", help="Load canonical JSON into SQLite graph tables")
    load_cmd.add_argument("canonical_json")
    load_cmd.add_argument("--db", required=True)
    load_cmd.set_defaults(func=cmd_load)

    inspect_cmd = sub.add_parser("inspect", help="Inspect SQLite graph contents")
    inspect_cmd.add_argument("--db", required=True)
    inspect_cmd.add_argument("--document", default=None, help="Document id or filename")
    inspect_cmd.set_defaults(func=cmd_inspect)

    eval_cmd = sub.add_parser("eval", help="Evaluate canonical JSON invariants and basic quality metrics")
    eval_cmd.add_argument("canonical_json")
    eval_cmd.set_defaults(func=cmd_eval)

    compare_cmd = sub.add_parser("compare", help="Run one PDF through multiple profiles")
    compare_cmd.add_argument("pdf")
    compare_cmd.add_argument("--profiles", required=True, help="Comma-separated profile names or paths")
    compare_cmd.add_argument("--runs-dir", default=str(RUNS_DIR))
    compare_cmd.add_argument("--db", default=None, help="Optional SQLite DB to load successful runs")
    compare_cmd.add_argument("--pages", default=None, help="Override each profile page_range, e.g. 1-3")
    compare_cmd.add_argument("--timeout-seconds", type=int, default=None, help="Override each profile timeout_seconds")
    compare_cmd.add_argument(
        "--provider-option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override provider_options for each profile, e.g. prompt_name=pdf_page_to_markdown_plain_v1",
    )
    compare_cmd.add_argument("--fail-fast", action="store_true")
    compare_cmd.set_defaults(func=cmd_compare)

    hybrid_cmd = sub.add_parser("hybrid", help="Run local first, then cloud only for low-scoring pages")
    hybrid_cmd.add_argument("pdf")
    hybrid_cmd.add_argument("--local-profile", default="pymupdf_fast")
    hybrid_cmd.add_argument("--cloud-profile", required=True)
    hybrid_cmd.add_argument("--runs-dir", default=str(RUNS_DIR))
    hybrid_cmd.add_argument("--db", default=None, help="Optional SQLite DB to load the hybrid run")
    hybrid_cmd.add_argument("--pages", default=None, help="Override local profile page_range, e.g. 1-3")
    hybrid_cmd.add_argument("--timeout-seconds", type=int, default=None, help="Override cloud profile timeout_seconds")
    hybrid_cmd.add_argument("--recall-threshold", type=float, default=0.95)
    hybrid_cmd.add_argument("--extra-threshold", type=float, default=0.15)
    hybrid_cmd.add_argument("--escalate-table-miss", action=argparse.BooleanOptionalAction, default=True)
    hybrid_cmd.add_argument(
        "--accept-worse-cloud",
        action="store_true",
        help="Replace escalated local pages even when the cloud score is not better.",
    )
    hybrid_cmd.set_defaults(func=cmd_hybrid)

    ui_cmd = sub.add_parser("ui", help="Serve a local browser UI for reviewing parser runs")
    ui_cmd.add_argument("--host", default="127.0.0.1")
    ui_cmd.add_argument("--port", type=int, default=8765)
    ui_cmd.add_argument("--runs-dir", default=str(RUNS_DIR))
    ui_cmd.add_argument("--db", default=str(RUNS_DIR / "index.sqlite"))
    ui_cmd.set_defaults(func=cmd_ui)

    return parser


def cmd_parse(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    if args.pages:
        profile["page_range"] = args.pages
    if args.timeout_seconds:
        profile["timeout_seconds"] = args.timeout_seconds
    _apply_provider_options(profile, args.provider_option)
    result = run_parse(Path(args.pdf), profile, Path(args.runs_dir), args.out_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_parse(
    pdf_path: Path,
    profile: dict[str, Any],
    runs_dir: Path,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    run_id = new_run_id(profile["name"])
    run_dir = Path(out_dir) if out_dir else runs_dir / slugify(pdf_path.stem) / slugify(profile["name"]) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    adapter = adapter_for_profile(profile)
    started_at = utc_now()
    start = time.monotonic()
    raw = adapter.parse_document(pdf_path, profile, run_dir=run_dir)
    duration_ms = int((time.monotonic() - start) * 1000)
    canonical = canonicalize_raw(
        raw,
        pdf_path,
        profile,
        run_id=run_id,
        started_at=started_at,
        duration_ms=duration_ms,
    )
    markdown = render_markdown(canonical)

    raw_path = run_dir / "raw.json"
    canonical_path = run_dir / "canonical.json"
    markdown_path = run_dir / "output.md"
    if profile.get("store_raw_output", True):
        write_json(raw_path, raw)
    write_json(canonical_path, canonical)
    markdown_path.write_text(markdown, encoding="utf-8")
    return {
        "run_dir": str(run_dir),
        "raw": str(raw_path) if profile.get("store_raw_output", True) else None,
        "canonical": str(canonical_path),
        "markdown": str(markdown_path),
        "scorecard": evaluate_canonical(canonical),
    }


def cmd_render(args: argparse.Namespace) -> int:
    canonical = read_json(args.canonical_json)
    markdown = render_markdown(canonical, include_source_comments=args.source_comments)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    print(str(out))
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    result = load_canonical(read_json(args.canonical_json), args.db)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    print(json.dumps(inspect_database(args.db, args.document), indent=2, sort_keys=True))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    print(json.dumps(evaluate_canonical(read_json(args.canonical_json)), indent=2, sort_keys=True))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    profiles = [item.strip() for item in args.profiles.split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    canonicals: list[dict[str, Any]] = []
    for profile_ref in profiles:
        profile = load_profile(profile_ref)
        if args.pages:
            profile["page_range"] = args.pages
        if args.timeout_seconds:
            profile["timeout_seconds"] = args.timeout_seconds
        _apply_provider_options(profile, args.provider_option)
        try:
            result = run_parse(Path(args.pdf), profile, Path(args.runs_dir))
            canonical = read_json(result["canonical"])
            canonicals.append(canonical)
            if args.db:
                result["load"] = load_canonical(canonical, args.db)
            results.append({"profile": profile["name"], "status": "ok", **result})
        except ParserUnavailable as exc:
            entry = {"profile": profile.get("name", profile_ref), "status": "skipped", "reason": str(exc)}
            results.append(entry)
            if args.fail_fast:
                raise
        except Exception as exc:
            entry = {"profile": profile.get("name", profile_ref), "status": "error", "reason": str(exc)}
            results.append(entry)
            if args.fail_fast:
                raise
    summary = {"runs": results, "scorecards": compare_canonicals(canonicals)}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if any(row["status"] == "error" for row in results) else 0


def cmd_hybrid(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf)
    runs_dir = Path(args.runs_dir)
    local_profile = load_profile(args.local_profile)
    if args.pages:
        local_profile["page_range"] = args.pages

    local_result = run_parse(pdf_path, local_profile, runs_dir)
    local_canonical = read_json(local_result["canonical"])
    escalation_reasons = _escalation_reasons(
        local_result["scorecard"],
        recall_threshold=args.recall_threshold,
        extra_threshold=args.extra_threshold,
        escalate_table_miss=args.escalate_table_miss,
    )

    cloud_result = None
    cloud_canonical = None
    if escalation_reasons:
        cloud_profile = load_profile(args.cloud_profile)
        cloud_profile["page_range"] = ",".join(str(page) for page in sorted(escalation_reasons))
        if args.timeout_seconds:
            cloud_profile["timeout_seconds"] = args.timeout_seconds
        cloud_result = run_parse(pdf_path, cloud_profile, runs_dir)
        cloud_canonical = read_json(cloud_result["canonical"])
    else:
        cloud_profile = load_profile(args.cloud_profile)

    hybrid_result = _write_hybrid_run(
        pdf_path,
        local_profile,
        cloud_profile,
        local_result,
        local_canonical,
        cloud_result,
        cloud_canonical,
        escalation_reasons,
        runs_dir,
        recall_threshold=args.recall_threshold,
        extra_threshold=args.extra_threshold,
        accept_only_if_better=not args.accept_worse_cloud,
    )
    if args.db:
        hybrid_result["load"] = load_canonical(read_json(hybrid_result["canonical"]), args.db)

    print(
        json.dumps(
            {
                "local_run": local_result,
                "cloud_run": cloud_result,
                "hybrid_run": hybrid_result,
                "escalated_pages": [
                    {"page_number": page, "reasons": reasons}
                    for page, reasons in sorted(escalation_reasons.items())
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from pdfpoc.ui.server import serve_ui

    serve_ui(host=args.host, port=args.port, runs_dir=args.runs_dir, db_path=args.db)
    return 0


def _apply_provider_options(profile: dict[str, Any], overrides: list[str]) -> None:
    if not overrides:
        return
    provider_options = dict(profile.get("provider_options") or {})
    for override in overrides:
        if "=" not in override:
            raise ValueError(f"Provider option must be KEY=VALUE: {override}")
        key, value = override.split("=", 1)
        provider_options[key.strip()] = _parse_option_value(value.strip())
    profile["provider_options"] = provider_options


def _parse_option_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _escalation_reasons(
    scorecard: dict[str, Any],
    *,
    recall_threshold: float,
    extra_threshold: float,
    escalate_table_miss: bool,
) -> dict[int, list[str]]:
    reasons: dict[int, list[str]] = {}
    for page in scorecard.get("page_scores") or []:
        page_number = int(page["page_number"])
        page_reasons: list[str] = []
        text_recall = page.get("text_recall")
        if text_recall is not None and float(text_recall) < recall_threshold:
            page_reasons.append(f"text_recall {text_recall} < {recall_threshold}")
        extra_text_ratio = page.get("extra_text_ratio")
        if extra_text_ratio is not None and float(extra_text_ratio) > extra_threshold:
            page_reasons.append(f"extra_text_ratio {extra_text_ratio} > {extra_threshold}")
        table_score = page.get("table_score")
        if escalate_table_miss and table_score is not None and float(table_score) < 1.0:
            page_reasons.append(f"table_score {table_score} < 1.0")
        if page_reasons:
            reasons[page_number] = page_reasons
    return reasons


def _write_hybrid_run(
    pdf_path: Path,
    local_profile: dict[str, Any],
    cloud_profile: dict[str, Any],
    local_result: dict[str, Any],
    local_canonical: dict[str, Any],
    cloud_result: dict[str, Any] | None,
    cloud_canonical: dict[str, Any] | None,
    escalation_reasons: dict[int, list[str]],
    runs_dir: Path,
    *,
    recall_threshold: float,
    extra_threshold: float,
    accept_only_if_better: bool,
) -> dict[str, Any]:
    started_at = utc_now()
    profile_name = f"hybrid_{local_profile['name']}_{cloud_profile['name']}"
    run_id = new_run_id(profile_name)
    run_dir = runs_dir / slugify(pdf_path.stem) / slugify(profile_name) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    hybrid = copy.deepcopy(local_canonical)
    cloud_pages = {
        int(page["page_number"]): copy.deepcopy(page)
        for page in (cloud_canonical or {}).get("pages", [])
    }
    local_scores = _scores_by_page(local_result.get("scorecard") or {})
    cloud_scores = _scores_by_page((cloud_result or {}).get("scorecard") or {})
    accepted_pages: set[int] = set()
    rejected_pages: set[int] = set()
    pages = []
    for page in sorted(hybrid.get("pages") or [], key=lambda item: int(item["page_number"])):
        page_number = int(page["page_number"])
        selected = page
        if page_number in cloud_pages:
            should_accept = (
                not accept_only_if_better
                or _cloud_improves_page(
                    local_scores.get(page_number) or {},
                    cloud_scores.get(page_number) or {},
                    recall_threshold=recall_threshold,
                    extra_threshold=extra_threshold,
                )
            )
            if should_accept:
                selected = cloud_pages[page_number]
                accepted_pages.add(page_number)
            else:
                rejected_pages.add(page_number)
        selected = copy.deepcopy(selected)
        selected.setdefault("metadata", {})
        selected["metadata"]["hybrid_source_profile"] = (
            cloud_profile["name"] if page_number in accepted_pages else local_profile["name"]
        )
        selected["metadata"]["hybrid_escalated"] = page_number in cloud_pages
        selected["metadata"]["hybrid_cloud_accepted"] = page_number in accepted_pages
        if page_number in escalation_reasons:
            selected["metadata"]["hybrid_escalation_reasons"] = escalation_reasons[page_number]
        pages.append(selected)

    _renumber_pages_and_blocks(pages)
    hybrid["pages"] = pages
    hybrid["sections"] = build_sections(pages) if local_profile.get("build_sections", True) else []
    escalated_pages = set(escalation_reasons)
    hybrid["assets"] = [
        asset
        for asset in local_canonical.get("assets") or []
        if int(asset.get("page_number") or 0) not in accepted_pages
    ] + list((cloud_canonical or {}).get("assets") or [])
    hybrid["warnings"] = [
        item
        for item in local_canonical.get("warnings") or []
        if int(item.get("page_number") or 0) not in accepted_pages
    ] + list((cloud_canonical or {}).get("warnings") or [])
    for page_number, reasons in sorted(escalation_reasons.items()):
        hybrid["warnings"].append(
            {
                "code": "hybrid_page_escalated",
                "severity": "info",
                "message": f"Page sent to {cloud_profile['name']}: " + "; ".join(reasons),
                "page_number": page_number,
                "block_id": None,
            }
        )
    for page_number in sorted(rejected_pages):
        hybrid["warnings"].append(
            {
                "code": "hybrid_cloud_rejected",
                "severity": "info",
                "message": f"Cloud result from {cloud_profile['name']} did not improve the local page score.",
                "page_number": page_number,
                "block_id": None,
            }
        )

    local_run = local_canonical.get("parse_run") or {}
    cloud_run = (cloud_canonical or {}).get("parse_run") or {}
    duration_ms = (local_run.get("duration_ms") or 0) + (cloud_run.get("duration_ms") or 0)
    hybrid["parse_run"] = {
        "id": run_id,
        "profile_name": profile_name,
        "provider": "hybrid",
        "model": f"{local_run.get('model') or local_profile.get('model')} + {cloud_run.get('model') or cloud_profile.get('model')}",
        "started_at": started_at,
        "duration_ms": duration_ms,
        "cost_usd": cloud_run.get("cost_usd"),
        "config": {
            "local_profile": local_profile,
            "cloud_profile": cloud_profile,
            "escalation_reasons": escalation_reasons,
            "accepted_pages": sorted(accepted_pages),
            "rejected_pages": sorted(rejected_pages),
        },
    }

    canonical_path = run_dir / "canonical.json"
    markdown_path = run_dir / "output.md"
    write_json(canonical_path, hybrid)
    markdown_path.write_text(render_markdown(hybrid), encoding="utf-8")
    return {
        "run_dir": str(run_dir),
        "raw": None,
        "canonical": str(canonical_path),
        "markdown": str(markdown_path),
        "scorecard": evaluate_canonical(hybrid),
    }


def _renumber_pages_and_blocks(pages: list[dict[str, Any]]) -> None:
    block_counter = 0
    for page in sorted(pages, key=lambda item: int(item["page_number"])):
        page_id = f"page_{int(page['page_number']):03d}"
        page["id"] = page_id
        for order, block in enumerate(
            sorted(page.get("blocks") or [], key=lambda item: item.get("reading_order") or 0),
            start=1,
        ):
            block_counter += 1
            block["id"] = f"block_{block_counter:06d}"
            block["page_id"] = page_id
            block["reading_order"] = order


def _scores_by_page(scorecard: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(page["page_number"]): page for page in scorecard.get("page_scores") or []}


def _cloud_improves_page(
    local_score: dict[str, Any],
    cloud_score: dict[str, Any],
    *,
    recall_threshold: float,
    extra_threshold: float,
) -> bool:
    local_recall = _score_float(local_score.get("text_recall"), 1.0)
    cloud_recall = _score_float(cloud_score.get("text_recall"), 0.0)
    local_extra = _score_float(local_score.get("extra_text_ratio"), 0.0)
    cloud_extra = _score_float(cloud_score.get("extra_text_ratio"), 1.0)
    local_table = _score_float(local_score.get("table_score"), 1.0)
    cloud_table = _score_float(cloud_score.get("table_score"), 1.0)

    if cloud_recall < min(recall_threshold, local_recall):
        return False
    if cloud_table < local_table:
        return False
    if cloud_recall > local_recall and cloud_extra <= max(local_extra, extra_threshold):
        return True
    return cloud_extra < local_extra and cloud_recall >= recall_threshold


def _score_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
