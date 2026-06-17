#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import sqlite3
import time
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/bedrock_region_smoke.json")
DEFAULT_SINCE_HOURS = 24
DEFAULT_PROFILE_V2 = "traqline-bedrock-us-west-2"
DEFAULT_MODEL = "openai.gpt-5.5"
DEFAULT_AWS_REGION = "us-west-2"
DEFAULT_LIVE_TIMEOUT_SECONDS = 180
WORK_SPECIAL_DB_PATHS = {
    "compere": "/home/kristopher/.codex-compere/web-bridge/tui_state.sqlite3",
    "control-plane": "/home/kristopher/.codex-control-plane/web-bridge/tui_state.sqlite3",
    "earlybird": "/home/kristopher/.codex-earlybird/web-bridge/tui_state.sqlite3",
    "gold-book": "/home/kristopher/.codex-gold-book/web-bridge/tui_state.sqlite3",
    "infra": "/home/kristopher/.codex-infra/web-bridge/tui_state.sqlite3",
    "leadership-kpis": "/home/kristopher/.codex-leadership-kpis/web-bridge/tui_state.sqlite3",
    "market-sizing": "/home/kristopher/.codex-market-sizing/web-bridge/tui_state.sqlite3",
    "mls": "/home/kristopher/.codex-mls/web-bridge/tui_state.sqlite3",
    "panelbot": "/home/kristopher/.codex-panelbot/web-bridge/tui_state.sqlite3",
    "platinum-standard": "/home/kristopher/.codex-platinum-standard/web-bridge/tui_state.sqlite3",
    "scout": "/home/kristopher/.codex-scout/web-bridge/tui_state.sqlite3",
    "tmi-dashboards": "/home/kristopher/.codex-tmi-dashboards/web-bridge/tui_state.sqlite3",
}


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


def _json_list(value: Any) -> list[str]:
    data = _safe_json(value)
    if isinstance(data, list):
        return [str(item) for item in data if str(item or "").strip()]
    raw = str(value or "").strip()
    return [raw] if raw else []


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _row_get(row: sqlite3.Row | dict[str, Any], key: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _select_usage_rows(db_path: Path, since_ts: int) -> list[sqlite3.Row]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        columns = _table_columns(conn, "usage_events")
        desired = [
            "thread_id",
            "started_at",
            "finished_at",
            "runtime",
            "model",
            "service_tier",
            "success",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
            "provider_error_kind",
            "provider_request_ids",
            "provider_trace_ids",
            "zero_token_provider_failure",
            "payload_json",
        ]
        selected = [column for column in desired if column in columns]
        if not selected or "started_at" not in selected:
            return []
        quoted = ", ".join(selected)
        return list(
            conn.execute(
                f"SELECT {quoted} FROM usage_events WHERE started_at >= ? ORDER BY started_at",
                (since_ts,),
            )
        )
    finally:
        conn.close()


def _normalize_usage_row(row: sqlite3.Row, label: str) -> dict[str, Any]:
    payload = _safe_json(_row_get(row, "payload_json"))
    usage_payload = payload.get("usage") if isinstance(payload, dict) else {}
    record: dict[str, Any] = {}
    if isinstance(usage_payload, dict):
        record.update(usage_payload)
    if isinstance(payload, dict):
        record.update(payload)
    for key in (
        "thread_id",
        "started_at",
        "finished_at",
        "runtime",
        "model",
        "service_tier",
        "provider_error_kind",
    ):
        if not str(record.get(key) or "").strip():
            record[key] = _row_get(row, key)
    for key in (
        "success",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "zero_token_provider_failure",
    ):
        if key not in record:
            record[key] = _row_get(row, key)
    if not record.get("provider_request_ids"):
        record["provider_request_ids"] = _json_list(
            _row_get(row, "provider_request_ids")
        )
    if not record.get("provider_trace_ids"):
        record["provider_trace_ids"] = _json_list(_row_get(row, "provider_trace_ids"))
    record["tui"] = label
    return record


def load_usage_records(
    db_specs: list[tuple[str, Path]], *, since_ts: int
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for label, db_path in db_specs:
        for row in _select_usage_rows(db_path, since_ts):
            records.append(_normalize_usage_row(row, label))
    return records


def _record_matches_target(
    record: dict[str, Any], *, profile_v2: str, model: str, aws_region: str
) -> bool:
    surface = str(record.get("provider_surface") or "").strip().lower()
    if surface and surface != "aws-bedrock":
        return False
    if profile_v2 and str(record.get("profile_v2") or "").strip() != profile_v2:
        return False
    if model and str(record.get("model") or "").strip() != model:
        return False
    if aws_region and str(record.get("aws_region") or "").strip() != aws_region:
        return False
    return True


def build_smoke_report(
    records: list[dict[str, Any]],
    *,
    profile_v2: str,
    model: str,
    aws_region: str,
    since_ts: int,
    checked_at: int | None = None,
) -> dict[str, Any]:
    checked_at = checked_at or int(time.time())
    matched = [
        record
        for record in records
        if _record_matches_target(
            record, profile_v2=profile_v2, model=model, aws_region=aws_region
        )
    ]
    successes = [
        record
        for record in matched
        if _coerce_int(record.get("success")) > 0
        and _coerce_int(record.get("total_tokens")) > 0
    ]
    failures = [record for record in matched if _coerce_int(record.get("success")) <= 0]
    failure_kinds: dict[str, int] = {}
    request_ids: list[str] = []
    trace_ids: list[str] = []
    sample_errors: list[dict[str, Any]] = []
    for record in failures:
        kind = str(record.get("provider_error_kind") or "provider_error").strip()
        failure_kinds[kind] = failure_kinds.get(kind, 0) + 1
        request_ids.extend(str(item) for item in record.get("provider_request_ids", []))
        trace_ids.extend(str(item) for item in record.get("provider_trace_ids", []))
        if len(sample_errors) < 5:
            sample_errors.append(
                {
                    "tui": str(record.get("tui") or ""),
                    "thread_id": str(record.get("thread_id") or ""),
                    "started_at": _coerce_int(record.get("started_at")),
                    "provider_error_kind": kind,
                    "provider_request_ids": record.get("provider_request_ids", []),
                }
            )
    last_success_at = max(
        (_coerce_int(item.get("finished_at")) for item in successes), default=0
    )
    last_failure_at = max(
        (_coerce_int(item.get("finished_at")) for item in failures), default=0
    )
    status = "ok" if successes else "failing" if failures else "unknown"
    profile_record = {
        "ok": bool(successes),
        "status": status,
        "profile_v2": profile_v2,
        "model": model,
        "aws_region": aws_region,
        "checked_at": checked_at,
        "since_ts": since_ts,
        "successes": len(successes),
        "failures": len(failures),
        "zero_token_failures": sum(
            1 for item in failures if bool(item.get("zero_token_provider_failure"))
        ),
        "failure_kinds": failure_kinds,
        "provider_request_ids": sorted(set(request_ids)),
        "provider_trace_ids": sorted(set(trace_ids)),
        "last_success_at": last_success_at,
        "last_failure_at": last_failure_at,
        "sample_errors": sample_errors,
    }
    summary = (
        f"{profile_v2} {model} in {aws_region}: "
        f"{len(successes)} success, {len(failures)} failure"
        f"{'' if len(failures) == 1 else 's'} since {since_ts}."
    )
    return {
        "schema": "norman.tui.bedrock-region-smoke.v1",
        "source": "usage-ledger",
        "status": status,
        "checked_at": checked_at,
        "since_ts": since_ts,
        "summary": summary,
        "profiles": {profile_v2: profile_record},
        "models": {
            model: {
                "ok": bool(successes),
                "status": status,
                "profile_v2": profile_v2,
                "aws_region": aws_region,
                "checked_at": checked_at,
            }
        },
    }


def provider_error_kind(text: str) -> str:
    clean = str(text or "").lower()
    if "engine not found" in clean or "model" in clean and "not found" in clean:
        return "bedrock_engine_not_found"
    if "stream disconnected before completion" in clean:
        return "bedrock_stream_disconnected"
    if "capacity" in clean and ("exceeded" in clean or "unavailable" in clean):
        return "bedrock_on_demand_capacity_exceeded"
    if "usage limit" in clean:
        return "codex_provider_usage_limit"
    if clean.strip():
        return "codex_provider_error"
    return ""


def parse_candidate(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(
            "candidate must be PROFILE_V2=AWS_REGION, e.g. traqline-bedrock-us-east-1=us-east-1"
        )
    profile_v2, aws_region = raw.split("=", 1)
    profile_v2 = profile_v2.strip()
    aws_region = aws_region.strip()
    if not profile_v2 or not aws_region:
        raise argparse.ArgumentTypeError("candidate profile and region are required")
    return profile_v2, aws_region


def _event_types(stdout_text: str) -> list[str]:
    event_types: list[str] = []
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        event_type = str(event.get("type") or "").strip()
        if event_type:
            event_types.append(event_type)
    return event_types


def run_live_candidate(
    *,
    codex_bin: str,
    codex_home: str,
    workdir: str,
    profile_v2: str,
    model: str,
    aws_region: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    started_at = int(time.time())
    sentinel = "BEDROCK_SMOKE_OK_" + "".join(
        ch if ch.isalnum() else "_" for ch in f"{profile_v2}_{aws_region}"
    )
    with tempfile.TemporaryDirectory(prefix="bedrock-region-smoke-") as tmpdir:
        output_path = Path(tmpdir) / "last_message.txt"
        cmd = [
            codex_bin,
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "-C",
            workdir,
            "--profile-v2",
            profile_v2,
            "-m",
            model,
            "-c",
            'service_tier="default"',
            "-c",
            'model_reasoning_effort="minimal"',
            "-o",
            str(output_path),
            f"Reply exactly: {sentinel}",
        ]
        env = dict(os.environ)
        if codex_home:
            env["CODEX_HOME"] = codex_home
        env["AWS_REGION"] = aws_region
        env["AWS_DEFAULT_REGION"] = aws_region
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=max(1, timeout_seconds),
                check=False,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(
                cmd,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
            )
            timed_out = True
        finished_at = int(time.time())
        last_message = ""
        try:
            last_message = output_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    stdout_text = str(proc.stdout or "")
    stderr_text = str(proc.stderr or "")
    combined_error = "\n".join(
        part for part in [stderr_text.strip(), stdout_text.strip()] if part
    )
    event_types = _event_types(stdout_text)
    ok = proc.returncode == 0 and bool(last_message)
    kind = "" if ok else provider_error_kind(combined_error)
    return {
        "ok": ok,
        "status": "ok" if ok else "failing",
        "source": "live-codex",
        "profile_v2": profile_v2,
        "model": model,
        "aws_region": aws_region,
        "checked_at": finished_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "event_types": event_types,
        "provider_error_kind": kind,
        "provider_error_text": "" if ok else combined_error[-1200:],
        "last_message_preview": last_message[:240],
        "sentinel": sentinel,
    }


def build_live_smoke_report(
    *,
    candidates: list[tuple[str, str]],
    model: str,
    codex_bin: str,
    codex_home: str,
    workdir: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    checked_at = int(time.time())
    profiles: dict[str, Any] = {}
    for profile_v2, aws_region in candidates:
        profiles[profile_v2] = run_live_candidate(
            codex_bin=codex_bin,
            codex_home=codex_home,
            workdir=workdir,
            profile_v2=profile_v2,
            model=model,
            aws_region=aws_region,
            timeout_seconds=timeout_seconds,
        )
    ok_count = sum(1 for item in profiles.values() if item.get("ok"))
    status = "ok" if ok_count else "failing" if profiles else "unknown"
    return {
        "schema": "norman.tui.bedrock-region-smoke.v2",
        "source": "live-codex",
        "status": status,
        "checked_at": checked_at,
        "summary": (
            f"{ok_count}/{len(profiles)} live Bedrock profile candidates passed for {model}."
        ),
        "profiles": profiles,
        "models": {
            model: {
                "ok": ok_count > 0,
                "status": status,
                "checked_at": checked_at,
            }
        },
    }


def parse_db_spec(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        path = Path(raw)
        return path.stem, path
    label, path = raw.split("=", 1)
    return label.strip() or Path(path).stem, Path(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Bedrock cross-region smoke evidence from TUI usage ledgers."
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--since-hours", type=float, default=DEFAULT_SINCE_HOURS)
    parser.add_argument("--profile-v2", default=DEFAULT_PROFILE_V2)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--aws-region", default=DEFAULT_AWS_REGION)
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        type=parse_candidate,
        metavar="PROFILE_V2=AWS_REGION",
        help="Live smoke candidate. Repeat to test multiple regions.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run bounded Codex live smokes instead of scanning prior ledger rows.",
    )
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", ""))
    parser.add_argument("--workdir", default="/tmp")
    parser.add_argument(
        "--timeout-seconds", type=int, default=DEFAULT_LIVE_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--work-special-defaults",
        action="store_true",
        help="Read the standard work-special TUI SQLite ledgers.",
    )
    parser.add_argument(
        "--db",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Additional TUI SQLite usage ledger to scan.",
    )
    parser.add_argument(
        "--fail-on-not-ok",
        action="store_true",
        help="Exit nonzero when the target profile is not smoke-proven OK.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.live:
        candidates = args.candidate or [
            (str(args.profile_v2).strip(), str(args.aws_region).strip())
        ]
        report = build_live_smoke_report(
            candidates=candidates,
            model=str(args.model).strip(),
            codex_bin=str(args.codex_bin).strip() or "codex",
            codex_home=str(args.codex_home).strip(),
            workdir=str(args.workdir).strip() or "/tmp",
            timeout_seconds=max(1, int(args.timeout_seconds or 0)),
        )
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(report, sort_keys=True))
        if args.fail_on_not_ok and not any(
            item.get("ok") for item in report["profiles"].values()
        ):
            return 1
        return 0

    db_specs: list[tuple[str, Path]] = []
    if args.work_special_defaults:
        db_specs.extend(
            (label, Path(path)) for label, path in WORK_SPECIAL_DB_PATHS.items()
        )
    db_specs.extend(parse_db_spec(raw) for raw in args.db)
    since_ts = int(time.time() - max(0.0, float(args.since_hours)) * 3600)
    report = build_smoke_report(
        load_usage_records(db_specs, since_ts=since_ts),
        profile_v2=str(args.profile_v2).strip(),
        model=str(args.model).strip(),
        aws_region=str(args.aws_region).strip(),
        since_ts=since_ts,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    if (
        args.fail_on_not_ok
        and not report["profiles"][str(args.profile_v2).strip()]["ok"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
