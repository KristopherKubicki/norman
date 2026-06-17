#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_bedrock_shortstop_benchmark.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_bedrock_shortstop_benchmark.md")
DEFAULT_SINCE_HOURS = 24
DEFAULT_MIN_LOW_YIELD_TOKENS = 20_000
DEFAULT_LOW_YIELD_OUTPUT_TOKENS = 1_000
DEFAULT_LOW_YIELD_SECONDS = 90

WORK_SPECIAL_DB_PATHS = {
    "leadership-kpis": "/home/kristopher/.codex-leadership-kpis/web-bridge/tui_state.sqlite3",
    "panelbot": "/home/kristopher/.codex-panelbot/web-bridge/tui_state.sqlite3",
    "tmi-dashboards": "/home/kristopher/.codex-tmi-dashboards/web-bridge/tui_state.sqlite3",
}

PROMISE_RE = re.compile(
    r"(?is)"
    r"(?:^|\b)"
    r"("
    r"i(?:'|’)ll\s+"
    r"|i\s+will\s+"
    r"|i(?:'|’)m\s+(?:going|checking|running|switching|continuing|starting|"
    r"inspecting|reviewing|looking|digging)\b"
    r"|i\s+am\s+(?:going|checking|running|switching|continuing|starting|"
    r"inspecting|reviewing|looking|digging)\b"
    r"|will\s+now\s+"
    r"|next\s+i(?:'|’)?ll\s+"
    r"|then\s+i(?:'|’)?ll\s+"
    r")"
)

DONE_RE = re.compile(
    r"(?is)\b(done|completed|fixed|deployed|verified|implemented|ran|created|"
    r"updated|confirmed|filed)\b"
)


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _one_line(value: Any, limit: int = 220) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def _json_list(value: Any) -> list[str]:
    data = _safe_json(value)
    if isinstance(data, list):
        return [str(item) for item in data if str(item or "").strip()]
    if str(value or "").strip():
        return [str(value)]
    return []


def response_has_unfinished_promise(response: str) -> bool:
    clean = str(response or "").strip()
    if not clean:
        return False
    for match in PROMISE_RE.finditer(clean[:500]):
        prefix = clean[max(0, match.start() - 50) : match.start()].lower()
        if re.search(
            r"(?:like|example|final text|response|progress text|quoted).{0,25}$",
            prefix,
        ):
            continue
        return True
    return False


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _select_existing(
    conn: sqlite3.Connection, table: str, desired: list[str]
) -> list[sqlite3.Row]:
    columns = _table_columns(conn, table)
    if not columns:
        return []
    selected = [column for column in desired if column in columns]
    if not selected:
        return []
    quoted = ", ".join(selected)
    return list(conn.execute(f"SELECT {quoted} FROM {table} ORDER BY started_at"))


def _row_get(
    row: sqlite3.Row | dict[str, Any] | None, key: str, default: Any = ""
) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _usage_key(row: sqlite3.Row | dict[str, Any]) -> tuple[str, int]:
    return (
        str(_row_get(row, "thread_id") or ""),
        _coerce_int(_row_get(row, "started_at")),
    )


def load_tui_records(
    db_path: Path, *, label: str, since_ts: int
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        usage_rows = _select_existing(
            conn,
            "usage_events",
            [
                "id",
                "thread_id",
                "started_at",
                "finished_at",
                "runtime",
                "model",
                "speed",
                "service_tier",
                "success",
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "total_tokens",
                "usage_meter_mode",
                "provider_yield_kind",
                "provider_yield_reasons",
                "provider_error_kind",
                "provider_request_ids",
                "provider_trace_ids",
                "codex_returncode",
                "zero_token_provider_failure",
                "payload_json",
            ],
        )
        usage_by_key = {_usage_key(row): row for row in usage_rows}
        turn_rows = _select_existing(
            conn,
            "turns",
            [
                "id",
                "thread_id",
                "started_at",
                "finished_at",
                "runtime",
                "model",
                "speed",
                "service_tier",
                "success",
                "usage_total_tokens",
                "prompt_preview",
                "response_preview",
                "error_preview",
                "payload_json",
            ],
        )
    finally:
        conn.close()

    records: list[dict[str, Any]] = []
    for turn in turn_rows:
        started_at = _coerce_int(turn["started_at"])
        if started_at < since_ts:
            continue
        usage = usage_by_key.get(_usage_key(turn))
        turn_payload = _safe_json(_row_get(turn, "payload_json"))
        usage_payload = _safe_json(_row_get(usage, "payload_json"))
        turn_usage = (
            turn_payload.get("usage")
            if isinstance(turn_payload.get("usage"), dict)
            else {}
        )
        response = _clean_str(
            turn_payload.get("response") or _row_get(turn, "response_preview")
        )
        error = _clean_str(turn_payload.get("error") or _row_get(turn, "error_preview"))
        prompt = _clean_str(
            turn_payload.get("prompt") or _row_get(turn, "prompt_preview")
        )
        total_tokens = _coerce_int(
            _row_get(usage, "total_tokens")
            or turn_usage.get("total_tokens")
            or _row_get(turn, "usage_total_tokens")
        )
        output_tokens = _coerce_int(
            _row_get(usage, "output_tokens") or turn_usage.get("output_tokens")
        )
        reasoning_tokens = _coerce_int(
            _row_get(usage, "reasoning_output_tokens")
            or turn_usage.get("reasoning_output_tokens")
        )
        input_tokens = _coerce_int(
            _row_get(usage, "input_tokens") or turn_usage.get("input_tokens")
        )
        records.append(
            {
                "tui": label,
                "turn_id": _clean_str(_row_get(turn, "id")),
                "thread_id": _clean_str(_row_get(turn, "thread_id")),
                "started_at": started_at,
                "finished_at": _coerce_int(_row_get(turn, "finished_at")),
                "runtime": _clean_str(
                    _row_get(turn, "runtime") or _row_get(usage, "runtime")
                ),
                "model": _clean_str(
                    _row_get(turn, "model") or _row_get(usage, "model")
                ),
                "speed": _clean_str(
                    _row_get(turn, "speed") or _row_get(usage, "speed")
                ),
                "service_tier": _clean_str(
                    _row_get(turn, "service_tier") or _row_get(usage, "service_tier")
                ),
                "success": bool(_coerce_int(_row_get(turn, "success", 1))),
                "usage_success": bool(_coerce_int(_row_get(usage, "success", 0))),
                "input_tokens": input_tokens,
                "cached_input_tokens": _coerce_int(
                    _row_get(usage, "cached_input_tokens")
                ),
                "output_tokens": output_tokens,
                "reasoning_output_tokens": reasoning_tokens,
                "total_tokens": total_tokens,
                "usage_meter_mode": _clean_str(_row_get(usage, "usage_meter_mode")),
                "provider_yield_kind": _clean_str(
                    _row_get(usage, "provider_yield_kind")
                ),
                "provider_yield_reasons": _json_list(
                    _row_get(usage, "provider_yield_reasons")
                ),
                "provider_error_kind": _clean_str(
                    _row_get(usage, "provider_error_kind")
                ),
                "provider_request_ids": _json_list(
                    _row_get(usage, "provider_request_ids")
                ),
                "provider_trace_ids": _json_list(_row_get(usage, "provider_trace_ids")),
                "codex_returncode": _coerce_int(_row_get(usage, "codex_returncode")),
                "zero_token_provider_failure": bool(
                    _coerce_int(_row_get(usage, "zero_token_provider_failure"))
                ),
                "prompt_preview": _one_line(prompt),
                "response_preview": _one_line(response),
                "error_preview": _one_line(error),
                "raw_turn_payload_keys": sorted(turn_payload.keys())
                if isinstance(turn_payload, dict)
                else [],
                "raw_usage_payload_keys": sorted(usage_payload.keys())
                if isinstance(usage_payload, dict)
                else [],
            }
        )
    return records


def classify_record(
    record: dict[str, Any],
    *,
    min_low_yield_tokens: int = DEFAULT_MIN_LOW_YIELD_TOKENS,
    low_yield_output_tokens: int = DEFAULT_LOW_YIELD_OUTPUT_TOKENS,
    low_yield_seconds: int = DEFAULT_LOW_YIELD_SECONDS,
) -> tuple[str, list[str]]:
    response = str(record.get("response_preview") or "")
    error = str(record.get("error_preview") or "")
    total = _coerce_int(record.get("total_tokens"))
    output = _coerce_int(record.get("output_tokens"))
    reasoning = _coerce_int(record.get("reasoning_output_tokens"))
    duration = max(
        0,
        _coerce_int(record.get("finished_at")) - _coerce_int(record.get("started_at")),
    )
    success = bool(record.get("success")) and not error
    reasons: list[str] = []
    durable_yield_kind = str(record.get("provider_yield_kind") or "").strip()
    if durable_yield_kind:
        durable_reasons = [
            str(reason).strip()
            for reason in record.get("provider_yield_reasons", [])
            if str(reason).strip()
        ]
        return durable_yield_kind, durable_reasons

    provider_error = str(record.get("provider_error_kind") or "")
    if (
        record.get("zero_token_provider_failure")
        or (provider_error and total == 0)
        or ("stream disconnected before completion" in error.lower() and total == 0)
    ):
        return "zero_transport", [provider_error or "zero-token provider failure"]

    promised = response_has_unfinished_promise(response)
    has_done_signal = bool(DONE_RE.search(response))
    if success and promised and not response.strip().upper().startswith("DONE"):
        reasons.append("final response promises future work")
        if not has_done_signal:
            reasons.append("no completion verb in preview")
        if duration <= low_yield_seconds:
            reasons.append(f"fast return: {duration}s")
        if reasoning == 0:
            reasons.append("zero reasoning tokens")
        return "short_stop", reasons

    low_yield = (
        success
        and total >= min_low_yield_tokens
        and output <= low_yield_output_tokens
        and duration <= low_yield_seconds
    )
    if low_yield:
        if output <= low_yield_output_tokens:
            reasons.append(f"low output tokens: {output}")
        if duration <= low_yield_seconds:
            reasons.append(f"fast return: {duration}s")
        if reasoning == 0:
            reasons.append("zero reasoning tokens")
        return "low_yield", reasons

    if success:
        return "useful_or_unclassified", []
    return "failed_nonzero", [provider_error or "nonzero failure"]


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    categorized: list[dict[str, Any]] = []
    for record in records:
        category, reasons = classify_record(record)
        enriched = dict(record)
        enriched["category"] = category
        enriched["reasons"] = reasons
        enriched["duration_seconds"] = max(
            0,
            _coerce_int(record.get("finished_at"))
            - _coerce_int(record.get("started_at")),
        )
        categorized.append(enriched)

    by_tui: dict[str, dict[str, Any]] = {}
    for record in categorized:
        tui = str(record.get("tui") or "unknown")
        row = by_tui.setdefault(
            tui,
            {
                "turns": 0,
                "categories": {},
                "total_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "durations": [],
                "short_stop_reasoning_zero": 0,
                "short_stop_with_request_ids": 0,
            },
        )
        row["turns"] += 1
        category = str(record.get("category") or "")
        row["categories"][category] = row["categories"].get(category, 0) + 1
        row["total_tokens"] += _coerce_int(record.get("total_tokens"))
        row["output_tokens"] += _coerce_int(record.get("output_tokens"))
        row["reasoning_output_tokens"] += _coerce_int(
            record.get("reasoning_output_tokens")
        )
        row["durations"].append(_coerce_int(record.get("duration_seconds")))
        if category == "short_stop":
            if _coerce_int(record.get("reasoning_output_tokens")) == 0:
                row["short_stop_reasoning_zero"] += 1
            if record.get("provider_request_ids") or record.get("provider_trace_ids"):
                row["short_stop_with_request_ids"] += 1

    summaries: list[dict[str, Any]] = []
    for tui, row in sorted(by_tui.items()):
        durations = [int(value) for value in row.pop("durations")]
        output_pct = (
            round(row["output_tokens"] / row["total_tokens"] * 100, 3)
            if row["total_tokens"]
            else 0
        )
        summaries.append(
            {
                "tui": tui,
                **row,
                "median_duration_seconds": statistics.median(durations)
                if durations
                else 0,
                "output_token_pct": output_pct,
            }
        )

    examples = [
        record
        for record in categorized
        if record.get("category") in {"short_stop", "low_yield", "zero_transport"}
    ]
    examples.sort(
        key=lambda item: (
            {"short_stop": 0, "low_yield": 1, "zero_transport": 2}.get(
                str(item.get("category")), 9
            ),
            -_coerce_int(item.get("total_tokens")),
        )
    )
    return {
        "schema": "norman.tui.bedrock-shortstop-benchmark.v1",
        "generated_at": int(time.time()),
        "summary": {
            "turns": len(categorized),
            "tuis": summaries,
            "categories": {
                category: sum(
                    1 for record in categorized if record.get("category") == category
                )
                for category in sorted(
                    {str(record.get("category") or "") for record in categorized}
                )
            },
        },
        "examples": examples[:25],
        "rows": categorized,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TUI Bedrock Short-Stop Benchmark",
        "",
        "Read-only SQLite diagnostic for successful-looking Codex turns that ended with a future-work/status response instead of completed work.",
        "",
        "## Summary",
        "",
        "| TUI | Turns | Categories | Tokens | Output % | Median seconds | Short-stops with zero reasoning |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in report.get("summary", {}).get("tuis", []):
        categories = ", ".join(
            f"{key}={value}" for key, value in sorted(row.get("categories", {}).items())
        )
        lines.append(
            "| {tui} | {turns} | {categories} | {tokens:,} | {output_pct:.3f} | {duration} | {reasoning_zero} |".format(
                tui=row.get("tui", ""),
                turns=_coerce_int(row.get("turns")),
                categories=categories,
                tokens=_coerce_int(row.get("total_tokens")),
                output_pct=float(row.get("output_token_pct") or 0),
                duration=row.get("median_duration_seconds", 0),
                reasoning_zero=_coerce_int(row.get("short_stop_reasoning_zero")),
            )
        )
    lines.extend(
        [
            "",
            "## Examples",
            "",
            "| TUI | Time UTC | Category | Tokens | Output | Reasoning | Seconds | Response preview | Reasons |",
            "|---|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for record in report.get("examples", []):
        started = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.gmtime(_coerce_int(record.get("started_at")))
        )
        lines.append(
            "| {tui} | {started} | {category} | {tokens:,} | {output:,} | {reasoning:,} | {duration} | {response} | {reasons} |".format(
                tui=record.get("tui", ""),
                started=started,
                category=record.get("category", ""),
                tokens=_coerce_int(record.get("total_tokens")),
                output=_coerce_int(record.get("output_tokens")),
                reasoning=_coerce_int(record.get("reasoning_output_tokens")),
                duration=_coerce_int(record.get("duration_seconds")),
                response=str(record.get("response_preview") or "").replace("|", "/"),
                reasons=", ".join(record.get("reasons") or []).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `short_stop`: process-level success, but final response promises future work.",
            "- `low_yield`: process-level success with high input, tiny output, and fast return.",
            "- `zero_transport`: provider/stream failure with zero token usage.",
            "- This report does not call a model or mutate any TUI state.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_db_arg(value: str) -> tuple[str, Path]:
    if "=" in value:
        label, path = value.split("=", 1)
        return label.strip() or Path(path).stem, Path(path).expanduser()
    path = Path(value).expanduser()
    return path.stem, path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only benchmark report for Bedrock Codex short-stops."
    )
    parser.add_argument(
        "--db",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="SQLite state DB to inspect. Can be passed multiple times.",
    )
    parser.add_argument(
        "--work-special-defaults",
        action="store_true",
        help="Use the standard KPI/Panelbot/TMI Work-special DB paths.",
    )
    parser.add_argument("--since-hours", type=int, default=DEFAULT_SINCE_HOURS)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--print-md", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dbs: list[tuple[str, Path]] = []
    if args.work_special_defaults:
        dbs.extend((label, Path(path)) for label, path in WORK_SPECIAL_DB_PATHS.items())
    dbs.extend(parse_db_arg(value) for value in args.db)
    if not dbs:
        raise SystemExit("provide --db LABEL=PATH or --work-special-defaults")

    since_ts = int(time.time()) - max(0, int(args.since_hours or 0)) * 3600
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for label, path in dbs:
        if not path.exists():
            missing.append(f"{label}={path}")
            continue
        records.extend(load_tui_records(path, label=label, since_ts=since_ts))

    report = summarize_records(records)
    report["run"] = {
        "since_hours": args.since_hours,
        "databases": [{"label": label, "path": str(path)} for label, path in dbs],
        "missing_databases": missing,
    }
    markdown = render_markdown(report)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.print_md:
        print(markdown)
    else:
        print(f"wrote {args.output_json}")
        print(f"wrote {args.output_md}")
        print(json.dumps(report.get("summary", {}), indent=2, sort_keys=True))
        if missing:
            print("missing DBs: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
