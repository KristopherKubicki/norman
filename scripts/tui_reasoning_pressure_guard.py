#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.tui.reasoning-pressure-guard.v1"
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/reasoning_pressure_guard.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/reasoning_pressure_guard.md")
DEFAULT_ROUTE_POLICY_JSON = Path("tmp/local_model_route_policy.json")
DEFAULT_USAGE_DB = Path(
    os.environ.get(
        "NORMAN_CODEX_STATE_DB_PATH",
        str(
            Path(
                os.environ.get(
                    "NORMAN_CODEX_WEB_STATE_DIR",
                    f"{os.environ.get('NORMAN_CODEX_HOME', '/root/.codex-housebot')}/web-bridge",
                )
            )
            / "tui_state.sqlite3"
        ),
    )
)

AUTHORITY_PATTERN = re.compile(
    r"\b(purse|key|seal|sword|deploy|restart|reboot|ack|takeover|blocked|"
    r"approval|credential|secret|delete|production|live routing)\b",
    re.I,
)
LOW_PRESSURE_PATTERN = re.compile(
    r"\b(status|quick|what'?s next|summary|summarize|check|inspect|one check)\b",
    re.I,
)
UNCERTAINTY_PATTERN = re.compile(
    r"\b(maybe|probably|likely|guess|guessing|not sure|uncertain|appears|"
    r"seems|might)\b",
    re.I,
)
EVIDENCE_PATTERN = re.compile(
    r"\b(command|ran|test|passed|failed|file|line|log|artifact|evidence|"
    r"output|http|json|sqlite|jq|pytest|make)\b",
    re.I,
)


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_usage_records(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_iter_jsonl(path))
    return rows


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_usage_db_records(db_path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, thread_id, started_at, finished_at, runtime, model, speed,
                   service_tier, success, input_tokens, cached_input_tokens,
                   output_tokens, reasoning_output_tokens, total_tokens,
                   usage_meter_mode, payload_json
            FROM usage_events
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, int(limit or 1)),),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass
    records: list[dict[str, Any]] = []
    for row in reversed(rows):
        payload = _safe_json(row["payload_json"])
        record = dict(payload)
        for key in row.keys():
            if key == "payload_json":
                continue
            if record.get(key) in (None, ""):
                record[key] = row[key]
        record.setdefault("usage", {})
        if isinstance(record["usage"], dict):
            for key in (
                "runtime",
                "model",
                "speed",
                "service_tier",
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "total_tokens",
                "usage_meter_mode",
            ):
                if record["usage"].get(key) in (None, ""):
                    record["usage"][key] = row[key]
        records.append(record)
    return records


def _usage_block(raw: dict[str, Any]) -> dict[str, Any]:
    usage = raw.get("usage")
    return usage if isinstance(usage, dict) else raw


def normalize_usage_record(raw: dict[str, Any]) -> dict[str, Any]:
    usage = _usage_block(raw)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    prompt = (
        raw.get("prompt")
        or raw.get("prompt_preview")
        or raw.get("input")
        or metadata.get("prompt")
        or ""
    )
    response = raw.get("response") or raw.get("reply") or raw.get("final") or ""
    model = usage.get("model") or raw.get("model") or ""
    speed = (
        usage.get("speed") or usage.get("reasoning_effort") or raw.get("speed") or ""
    )
    reasoning = _coerce_int(
        usage.get("reasoning_output_tokens")
        or usage.get("raw_reasoning_output_tokens")
        or raw.get("reasoning_output_tokens")
    )
    output = _coerce_int(usage.get("output_tokens") or raw.get("output_tokens"))
    input_tokens = _coerce_int(usage.get("input_tokens") or raw.get("input_tokens"))
    total = _coerce_int(usage.get("total_tokens") or raw.get("total_tokens"))
    authority_pressure = bool(raw.get("authority_pressure")) or bool(
        AUTHORITY_PATTERN.search(f"{prompt} {response}")
    )
    low_pressure_prompt = bool(LOW_PRESSURE_PATTERN.search(str(prompt)))
    uncertainty_without_evidence = bool(
        (
            UNCERTAINTY_PATTERN.search(str(response))
            or UNCERTAINTY_PATTERN.search(str(prompt))
        )
        and not EVIDENCE_PATTERN.search(str(response))
    )
    return {
        "id": _clean_str(raw.get("id") or raw.get("turn_id") or raw.get("event_id")),
        "thread_id": _clean_str(raw.get("thread_id") or usage.get("thread_id")),
        "runtime": _clean_str(usage.get("runtime") or raw.get("runtime")),
        "model": _clean_str(model),
        "speed": _clean_str(speed),
        "input_tokens": input_tokens,
        "output_tokens": output,
        "reasoning_output_tokens": reasoning,
        "total_tokens": total or input_tokens + output + reasoning,
        "prompt_preview": _clean_str(prompt)[:240],
        "response_preview": _clean_str(response)[:240],
        "authority_pressure": authority_pressure,
        "low_pressure_prompt": low_pressure_prompt,
        "uncertainty_without_evidence": uncertainty_without_evidence,
    }


def _is_5_5(model: str) -> bool:
    return "5.5" in model or "gpt-5-5" in model


def _is_high_effort(speed: str) -> bool:
    clean = speed.lower()
    return clean in {"high", "xhigh", "deep", "careful"} or "xhigh" in clean


def classify_record(
    record: dict[str, Any],
    *,
    high_reasoning_tokens: int,
    high_reasoning_ratio: float,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    reasoning = _coerce_int(record.get("reasoning_output_tokens"))
    output = _coerce_int(record.get("output_tokens"))
    ratio = reasoning / max(1, output)
    model = _clean_str(record.get("model"))
    speed = _clean_str(record.get("speed"))
    authority_pressure = bool(record.get("authority_pressure"))
    high_reasoning = reasoning >= high_reasoning_tokens or (
        reasoning >= 1000 and ratio >= high_reasoning_ratio
    )
    if high_reasoning:
        alerts.append(
            {
                "kind": "reasoning_pressure_detected",
                "severity": "info" if authority_pressure else "warning",
                "reason": (
                    f"reasoning_output_tokens={reasoning}; "
                    f"reasoning_to_output_ratio={ratio:.2f}"
                ),
                "suggested_action": (
                    "allow_extra_reasoning_with_checkpoint"
                    if authority_pressure
                    else "checkpoint_or_gather_evidence_before_more_reasoning"
                ),
            }
        )
    if _is_5_5(model) and not authority_pressure:
        alerts.append(
            {
                "kind": "frontier_without_authority_pressure",
                "severity": "approval_recommended",
                "reason": f"model={model}; no authority-pressure marker detected",
                "suggested_action": "ask_operator_before_5_5_or_downshift_to_5_4_local",
            }
        )
    if (
        _is_high_effort(speed)
        and record.get("low_pressure_prompt")
        and not high_reasoning
    ):
        alerts.append(
            {
                "kind": "high_effort_low_pressure_prompt",
                "severity": "warning",
                "reason": f"speed={speed}; prompt looks status/simple",
                "suggested_action": "downshift_next_turn_to_standard_or_local_first",
            }
        )
    if record.get("uncertainty_without_evidence"):
        alerts.append(
            {
                "kind": "guessing_pressure",
                "severity": "warning",
                "reason": "uncertainty language without evidence marker",
                "suggested_action": "stop_guessing_and_collect_local_evidence",
            }
        )
    return alerts


def _status_from_alerts(alerts: list[dict[str, Any]]) -> str:
    if any(alert.get("severity") == "approval_recommended" for alert in alerts):
        return "approval_recommended"
    if any(alert.get("severity") == "warning" for alert in alerts):
        return "warn"
    if alerts:
        return "pressure_confirmed"
    return "ok"


def _admission_from_status(status: str, alerts: list[dict[str, Any]]) -> dict[str, str]:
    if status == "approval_recommended":
        return {
            "action": "ask_operator_before_5_5",
            "reason": "frontier/high-cost route lacks enough pressure evidence",
        }
    if any(alert.get("kind") == "guessing_pressure" for alert in alerts):
        return {
            "action": "gather_evidence_before_spending_more",
            "reason": "uncertainty detected without evidence marker",
        }
    if status == "warn":
        return {
            "action": "downshift_or_checkpoint",
            "reason": "reasoning/cost pressure should be justified before continuing",
        }
    if status == "pressure_confirmed":
        return {
            "action": "allow_extra_reasoning_with_checkpoint",
            "reason": "reasoning pressure exists and no approval gap was detected",
        }
    return {
        "action": "prefer_local_or_5_4",
        "reason": "no extra reasoning pressure detected",
    }


def _operator_prompt(status: str, admission: dict[str, str]) -> str:
    action = admission.get("action")
    if action == "ask_operator_before_5_5":
        return (
            "This looks like a high-cost/frontier route without clear pressure. "
            "Approve 5.5/high reasoning, or downshift to local/5.4?"
        )
    if action == "gather_evidence_before_spending_more":
        return (
            "Uncertainty is showing without enough evidence. Gather proof/check local "
            "state before spending more reasoning."
        )
    if action == "downshift_or_checkpoint":
        return (
            "Reasoning pressure is elevated. Checkpoint, gather evidence, or justify "
            "continuing high reasoning."
        )
    if status == "pressure_confirmed":
        return (
            "Reasoning pressure is justified. Continue with extra reasoning, but leave "
            "a checkpoint and evidence."
        )
    return "No extra reasoning pressure detected; prefer local/5.4 routes."


def build_report(
    usage_records: list[dict[str, Any]],
    *,
    route_policy: dict[str, Any] | None = None,
    source: str = "unknown",
    high_reasoning_tokens: int = 6000,
    high_reasoning_ratio: float = 1.5,
    window_records: int = 20,
    generated_at: int | None = None,
) -> dict[str, Any]:
    normalized = [normalize_usage_record(row) for row in usage_records]
    window = normalized[-max(1, window_records) :]
    row_alerts = [
        {
            "record": row,
            "alerts": classify_record(
                row,
                high_reasoning_tokens=high_reasoning_tokens,
                high_reasoning_ratio=high_reasoning_ratio,
            ),
        }
        for row in window
    ]
    alerts = [
        {**alert, "record_id": item["record"].get("id", "")}
        for item in row_alerts
        for alert in item["alerts"]
    ]
    status = _status_from_alerts(alerts)
    admission = _admission_from_status(status, alerts)
    route_summary = (route_policy or {}).get("summary")
    if not isinstance(route_summary, dict):
        route_summary = {}
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()) if generated_at is None else int(generated_at),
        "dry_run_only": True,
        "status": status,
        "admission": admission,
        "operator_prompt": _operator_prompt(status, admission),
        "thresholds": {
            "high_reasoning_tokens": high_reasoning_tokens,
            "high_reasoning_ratio": high_reasoning_ratio,
            "window_records": window_records,
        },
        "summary": {
            "source": source,
            "records_seen": len(normalized),
            "records_evaluated": len(window),
            "alert_count": len(alerts),
            "approval_recommended_count": sum(
                1 for alert in alerts if alert.get("severity") == "approval_recommended"
            ),
            "warning_count": sum(
                1 for alert in alerts if alert.get("severity") == "warning"
            ),
            "local_preferred_routes": (
                route_summary.get("network_priority_counts", {}).get(
                    "local_preferred", 0
                )
                if isinstance(route_summary.get("network_priority_counts"), dict)
                else 0
            ),
            "estimated_savings_vs_5_4_usd": route_summary.get(
                "estimated_cloud_savings_vs_bedrock_5_4_usd", 0.0
            ),
            "estimated_5_5_authority_premium_vs_5_4_usd": route_summary.get(
                "estimated_5_5_authority_premium_vs_bedrock_5_4_usd", 0.0
            ),
        },
        "alerts": alerts,
        "evaluated_records": row_alerts,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    admission = report.get("admission") or {}
    lines = [
        "# TUI Reasoning Pressure Guard",
        "",
        f"- Dry run only: `{str(report.get('dry_run_only')).lower()}`",
        f"- Status: `{report.get('status')}`",
        f"- Admission: `{admission.get('action')}`",
        f"- Reason: {admission.get('reason')}",
        f"- Operator prompt: {report.get('operator_prompt')}",
        f"- Source: `{summary.get('source')}`",
        f"- Records evaluated: {summary.get('records_evaluated')}",
        f"- Alerts: {summary.get('alert_count')}",
        f"- Local-preferred routes available: {summary.get('local_preferred_routes')}",
        f"- Estimated savings vs 5.4: `${float(summary.get('estimated_savings_vs_5_4_usd') or 0):.6f}`",
        f"- 5.5 authority premium vs 5.4: `${float(summary.get('estimated_5_5_authority_premium_vs_5_4_usd') or 0):.6f}`",
        "",
        "## Alerts",
        "",
    ]
    alerts = report.get("alerts") or []
    if not alerts:
        lines.append("No alerts.")
        return "\n".join(lines).rstrip() + "\n"
    lines.extend(["| Severity | Kind | Action | Reason |", "| --- | --- | --- | --- |"])
    for alert in alerts:
        lines.append(
            "| {severity} | {kind} | {action} | {reason} |".format(
                severity=alert.get("severity") or "",
                kind=alert.get("kind") or "",
                action=alert.get("suggested_action") or "",
                reason=str(alert.get("reason") or "").replace("|", "\\|"),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run alerting for excess reasoning, guessing, and 5.5 use."
    )
    parser.add_argument(
        "--usage-db",
        type=Path,
        default=DEFAULT_USAGE_DB,
        help="SQLite TUI state DB containing usage_events.",
    )
    parser.add_argument("--db-limit", type=int, default=200)
    parser.add_argument("--usage-jsonl", type=Path, action="append", default=[])
    parser.add_argument(
        "--route-policy-json", type=Path, default=DEFAULT_ROUTE_POLICY_JSON
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--high-reasoning-tokens", type=int, default=6000)
    parser.add_argument("--high-reasoning-ratio", type=float, default=1.5)
    parser.add_argument("--window-records", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_records = load_usage_db_records(args.usage_db, limit=args.db_limit)
    jsonl_records = [] if db_records else load_usage_records(args.usage_jsonl)
    usage_records = db_records or jsonl_records
    source = "state_db" if db_records else "jsonl" if jsonl_records else "none"
    report = build_report(
        usage_records,
        route_policy=_load_json(args.route_policy_json, {}),
        source=source,
        high_reasoning_tokens=max(1, int(args.high_reasoning_tokens or 1)),
        high_reasoning_ratio=max(0.1, float(args.high_reasoning_ratio or 0.1)),
        window_records=max(1, int(args.window_records or 1)),
    )
    _write_json(args.output_json, report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "status": report["status"],
                "admission": report["admission"],
                "summary": report["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
