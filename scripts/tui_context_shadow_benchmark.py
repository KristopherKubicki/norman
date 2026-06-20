#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


WORK_SPECIAL_ENDPOINTS = {
    "compere": "https://keystone.kris.openbrand.com/api/status",
    "control-plane": "https://cp.kris.openbrand.com/api/status",
    "earlybird": "https://earlybird.kris.openbrand.com/api/status",
    "gold-book": "https://goldbook.kris.openbrand.com/api/status",
    "infra": "https://infra.kris.openbrand.com/api/status",
    "leadership-kpis": "https://kpis.kris.openbrand.com/api/status",
    "market-sizing": "https://market.kris.openbrand.com/api/status",
    "mls": "https://mls.kris.openbrand.com/api/status",
    "panelbot": "https://panelbot.kris.openbrand.com/api/status",
    "platinum-standard": "https://platinum.kris.openbrand.com/api/status",
    "scout": "https://ranger.kris.openbrand.com/api/status",
    "tmi-dashboards": "https://dashboards.kris.openbrand.com/api/status",
}

DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_context_shadow_benchmark.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_context_shadow_benchmark.md")
DEFAULT_ANSWER_TEMPLATE = Path("/tmp/norman_tui_quality_shadow_answers.template.json")


@dataclass
class ShadowRow:
    slug: str
    url: str = ""
    reachable: bool = True
    state: str = ""
    pending: bool = False
    queue_depth: int = 0
    current_tokens: int = 0
    packed_tokens: int = 0
    saved_tokens: int = 0
    saved_pct: float = 0.0
    saved_cost_label: str = ""
    preview_state: str = ""
    state_db_enabled: bool = False
    history_format: str = ""
    needs_retrieval_for_older_details: bool = False
    requires_shadow_run_before_activation: bool = True
    live_prompt_behavior_changed: bool = False
    top_current_sources: list[dict[str, Any]] | None = None
    packed_sources: list[dict[str, Any]] | None = None
    excluded_sources: list[dict[str, Any]] | None = None
    error: str = ""


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "norman-context-shadow-benchmark/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def fetch_work_special_statuses(timeout: float = 8.0) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for slug, url in WORK_SPECIAL_ENDPOINTS.items():
        try:
            status = _fetch_json(url, timeout)
            status["_shadow_slug"] = slug
            status["_shadow_url"] = url
            statuses.append(status)
        except (
            OSError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            statuses.append(
                {
                    "_shadow_slug": slug,
                    "_shadow_url": url,
                    "_shadow_error": f"{type(exc).__name__}: {exc}",
                }
            )
    return statuses


def load_status_source(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return [row for row in data["rows"] if isinstance(row, dict)]
    if isinstance(data, dict) and isinstance(data.get("statuses"), list):
        return [row for row in data["statuses"] if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    raise ValueError(f"{path} does not contain rows/statuses")


def _cost_label(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("label") or "")
    return ""


def _sources(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _row_from_status(item: dict[str, Any]) -> ShadowRow:
    slug = str(item.get("_shadow_slug") or item.get("slug") or item.get("name") or "")
    url = str(item.get("_shadow_url") or item.get("url") or "")
    error = str(item.get("_shadow_error") or item.get("error") or "")
    if error:
        return ShadowRow(slug=slug, url=url, reachable=False, error=error)

    preview = item.get("context_pack_preview")
    if not isinstance(preview, dict):
        preview = {}
    current = preview.get("current") if isinstance(preview.get("current"), dict) else {}
    packed = preview.get("packed") if isinstance(preview.get("packed"), dict) else {}
    savings = preview.get("savings") if isinstance(preview.get("savings"), dict) else {}
    storage = preview.get("storage") if isinstance(preview.get("storage"), dict) else {}
    quality_gate = (
        preview.get("quality_gate")
        if isinstance(preview.get("quality_gate"), dict)
        else item.get("quality_gate")
        if isinstance(item.get("quality_gate"), dict)
        else {}
    )

    current_tokens = _coerce_int(
        item.get("current_tokens")
        or current.get("tokens")
        or preview.get("current_tokens")
    )
    packed_tokens = _coerce_int(
        item.get("packed_tokens")
        or packed.get("tokens")
        or preview.get("packed_tokens")
    )
    saved_tokens = _coerce_int(
        item.get("saved_tokens")
        or savings.get("tokens")
        or max(0, current_tokens - packed_tokens)
    )
    saved_pct = _coerce_float(
        item.get("saved_pct")
        if item.get("saved_pct") is not None
        else savings.get("pct")
        if savings.get("pct") is not None
        else round(saved_tokens / current_tokens * 100, 1)
        if current_tokens
        else 0.0
    )
    return ShadowRow(
        slug=slug,
        url=url,
        reachable=True,
        state=str(item.get("state") or item.get("status") or ""),
        pending=bool(item.get("pending")),
        queue_depth=_coerce_int(item.get("queue_depth")),
        current_tokens=current_tokens,
        packed_tokens=packed_tokens,
        saved_tokens=saved_tokens,
        saved_pct=round(saved_pct, 1),
        saved_cost_label=str(
            item.get("saved_cost")
            or _cost_label(savings.get("cost_range"))
            or _cost_label(item.get("saved_cost_range"))
        ),
        preview_state=str(item.get("preview_state") or preview.get("state") or ""),
        state_db_enabled=bool(
            item.get("state_db_enabled")
            if item.get("state_db_enabled") is not None
            else storage.get("state_db_enabled")
        ),
        history_format=str(
            item.get("history_format") or storage.get("history_format") or ""
        ),
        needs_retrieval_for_older_details=bool(
            item.get("needs_retrieval_for_older_details")
            if item.get("needs_retrieval_for_older_details") is not None
            else quality_gate.get("needs_retrieval_for_older_details")
        ),
        requires_shadow_run_before_activation=bool(
            item.get("requires_shadow_run_before_activation")
            if item.get("requires_shadow_run_before_activation") is not None
            else quality_gate.get("requires_shadow_run_before_activation", True)
        ),
        live_prompt_behavior_changed=bool(
            item.get("live_prompt_behavior_changed")
            if item.get("live_prompt_behavior_changed") is not None
            else quality_gate.get("live_prompt_behavior_changed")
        ),
        top_current_sources=_sources(
            item.get("top_current_sources") or current.get("sources")
        ),
        packed_sources=_sources(item.get("packed_sources") or packed.get("sources")),
        excluded_sources=_sources(
            item.get("excluded_sources") or preview.get("excluded_sources")
        ),
    )


def build_report(statuses: list[dict[str, Any]], *, source: str = "") -> dict[str, Any]:
    rows = [_row_from_status(item) for item in statuses]
    reachable = [row for row in rows if row.reachable]
    total_current = sum(row.current_tokens for row in reachable)
    total_packed = sum(row.packed_tokens for row in reachable)
    total_saved = sum(row.saved_tokens for row in reachable)
    summary = {
        "sampled": len(rows),
        "reachable": len(reachable),
        "total_current_tokens": total_current,
        "total_packed_tokens": total_packed,
        "total_saved_tokens": total_saved,
        "saved_pct": round(total_saved / total_current * 100, 1)
        if total_current
        else 0.0,
        "strong_rows": sum(1 for row in reachable if row.preview_state == "strong"),
        "db_enabled_rows": sum(1 for row in reachable if row.state_db_enabled),
        "needs_retrieval_rows": sum(
            1 for row in reachable if row.needs_retrieval_for_older_details
        ),
        "shadow_required_rows": sum(
            1 for row in reachable if row.requires_shadow_run_before_activation
        ),
        "live_prompt_changed_rows": sum(
            1 for row in reachable if row.live_prompt_behavior_changed
        ),
        "pass_bar_rows": sum(
            1
            for row in reachable
            if row.saved_pct >= 50.0
            and row.saved_tokens >= 4000
            and not row.live_prompt_behavior_changed
        ),
    }
    return {
        "schema": "norman.tui.context-shadow-benchmark.v1",
        "generated_at": int(time.time()),
        "source": source,
        "summary": summary,
        "rows": [asdict(row) for row in rows],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# TUI Context Shadow Benchmark",
        "",
        "Read-only context benchmark. This compares the current full-ish context estimate against the compact state-card/reference packet estimate. It does not call a model or change live prompt behavior.",
        "",
        "## Summary",
        "",
        f"- Sampled: {summary.get('sampled')}",
        f"- Reachable: {summary.get('reachable')}",
        f"- Current tokens: {summary.get('total_current_tokens'):,}",
        f"- Packed tokens: {summary.get('total_packed_tokens'):,}",
        f"- Saved tokens: {summary.get('total_saved_tokens'):,}",
        f"- Saved pct: {summary.get('saved_pct')}%",
        f"- DB-enabled rows: {summary.get('db_enabled_rows')}",
        f"- Rows needing old-detail retrieval: {summary.get('needs_retrieval_rows')}",
        f"- Rows still requiring shadow before activation: {summary.get('shadow_required_rows')}",
        f"- Rows with live prompt behavior already changed: {summary.get('live_prompt_changed_rows')}",
        "",
        "## Rows",
        "",
        "| TUI | Reach | State | Current | Packed | Saved | Saved % | Preview | DB | Quality gate |",
        "|---|---:|---|---:|---:|---:|---:|---|---:|---|",
    ]
    for row in report.get("rows", []):
        if not row.get("reachable"):
            lines.append(
                f"| {row.get('slug')} | no | {row.get('error', '')} |  |  |  |  |  |  |  |"
            )
            continue
        quality = []
        if row.get("needs_retrieval_for_older_details"):
            quality.append("needs retrieval")
        if row.get("requires_shadow_run_before_activation"):
            quality.append("shadow required")
        if row.get("live_prompt_behavior_changed"):
            quality.append("live changed")
        lines.append(
            "| {slug} | yes | {state} | {current:,} | {packed:,} | {saved:,} | {pct} | {preview} | {db} | {quality} |".format(
                slug=row.get("slug", ""),
                state=row.get("state", ""),
                current=_coerce_int(row.get("current_tokens")),
                packed=_coerce_int(row.get("packed_tokens")),
                saved=_coerce_int(row.get("saved_tokens")),
                pct=row.get("saved_pct", 0),
                preview=row.get("preview_state", ""),
                db="yes" if row.get("state_db_enabled") else "no",
                quality=", ".join(quality) or "ok",
            )
        )
    return "\n".join(lines) + "\n"


def build_answer_template(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return {
        "schema": "norman.tui.quality-shadow-answers.v1",
        "run_id": f"context-shadow-{int(time.time())}",
        "notes": (
            "Fill in the baseline and candidate answers from a real shadow A/B run. "
            "Context token counts came from the context shadow benchmark."
        ),
        "answers": [
            {
                "case_id": "context-pack-proof-status",
                "label": "baseline",
                "context_tokens": _coerce_int(summary.get("total_current_tokens")),
                "answer": "",
            },
            {
                "case_id": "context-pack-proof-status",
                "label": "candidate",
                "context_tokens": _coerce_int(summary.get("total_packed_tokens")),
                "answer": "",
            },
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only context shadow benchmark for TUI context packing."
    )
    parser.add_argument(
        "--source-json",
        type=Path,
        help="Use a saved status/context-pack JSON sample instead of fetching live TUIs.",
    )
    parser.add_argument(
        "--fetch-work-special",
        action="store_true",
        help="Fetch live work-special /api/status endpoints.",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument(
        "--output-answer-template",
        type=Path,
        help="Write a starter answer overlay for tui_quality_benchmark.py.",
    )
    parser.add_argument("--print-md", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = ""
    if args.source_json:
        statuses = load_status_source(args.source_json)
        source = str(args.source_json)
    else:
        statuses = fetch_work_special_statuses(timeout=args.timeout)
        source = "live:work-special"
    report = build_report(statuses, source=source)
    markdown = render_markdown(report)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.output_answer_template:
        args.output_answer_template.write_text(
            json.dumps(build_answer_template(report), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if args.print_md:
        print(markdown)
    else:
        print(f"wrote {args.output_json}")
        print(f"wrote {args.output_md}")
        if args.output_answer_template:
            print(f"wrote {args.output_answer_template}")
        print(json.dumps(report.get("summary", {}), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
