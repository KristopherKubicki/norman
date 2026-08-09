#!/usr/bin/env python3
"""Compare native Codex and the transparent Norman bridge on safe repo tasks.

This runner is deliberately opt-in for live model work. Raw prompts, event
streams, and final answers stay in a temporary directory; durable reports
contain only case IDs, hashes, aggregate metrics, and gate results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tui_bedrock_shortstop_benchmark import response_has_unfinished_promise
from tui_quality_benchmark import AnswerScore, load_cases, score_answer


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPO_ROOT / "db" / "codex_bridge_parity_cases.json"
DEFAULT_WORKSPACE = Path(
    os.environ.get("NORMAN_CODEX_PARITY_WORKSPACE", "~/code/control_plane")
).expanduser()
DEFAULT_STATE_DIR = Path(
    os.environ.get("NORMAN_CODEX_PARITY_STATE_DIR", "~/.local/state/norman")
).expanduser()
DEFAULT_OUTPUT_JSON = DEFAULT_STATE_DIR / "codex-bridge-parity.json"
DEFAULT_OUTPUT_MD = DEFAULT_STATE_DIR / "codex-bridge-parity.md"
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_MIN_COMPLETED_PAIRS = 5
DEFAULT_MAX_SCORE_REGRESSION = 5.0
SCHEMA = "norman.codex-bridge-parity.v1"
TOOL_ITEM_TYPES = frozenset(
    {
        "command_execution",
        "custom_tool_call",
        "function_call",
        "mcp_tool_call",
        "tool_call",
        "web_search_call",
    }
)
USAGE_KEYS = frozenset(
    {
        "cached_input_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    }
)


@dataclass(frozen=True)
class RouteSpec:
    key: str
    binary: Path
    codex_home: Path | None = None


@dataclass(frozen=True)
class RouteExecution:
    route: str
    status: str
    returncode: int | None
    duration_ms: int
    answer: str
    answer_sha256: str
    answer_chars: int
    tool_events: int
    retry_events: int
    usage: dict[str, int]
    short_stop: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_path(value: Path) -> str:
    """Return a basename-only artifact name for persisted reports."""
    return value.name or "."


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_mapping(value: object) -> bool:
    return isinstance(value, dict)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _event_item(event: dict[str, Any]) -> dict[str, Any]:
    item = event.get("item")
    return item if isinstance(item, dict) else {}


def _item_type(event: dict[str, Any]) -> str:
    item = _event_item(event)
    return str(item.get("type") or event.get("item_type") or "").strip().lower()


def _item_identity(event: dict[str, Any], index: int) -> str:
    item = _event_item(event)
    for source in (item, event):
        for key in ("id", "call_id", "item_id"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return f"event-{index}"


def _usage_from_event(event: dict[str, Any]) -> dict[str, int]:
    candidates = [event.get("usage"), _event_item(event).get("usage")]
    result: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key, value in candidate.items():
            if key in USAGE_KEYS:
                result[key] = max(result.get(key, 0), _int(value))
    return result


def parse_event_metrics(events_path: Path) -> tuple[int, int, dict[str, int]]:
    tool_ids: set[str] = set()
    retry_events = 0
    usage: dict[str, int] = {}
    for index, event in enumerate(_iter_jsonl(events_path)):
        item_type = _item_type(event)
        if item_type in TOOL_ITEM_TYPES:
            tool_ids.add(_item_identity(event, index))
        event_type = str(event.get("type") or "").lower()
        if "retry" in event_type or "retry" in item_type:
            retry_events += 1
        for key, value in _usage_from_event(event).items():
            usage[key] = max(usage.get(key, 0), value)
    return len(tool_ids), retry_events, usage


def resolve_native_codex_bin(value: str | None = None) -> Path:
    if value:
        candidate = Path(value).expanduser().resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        raise ValueError(f"native Codex binary is not executable: {candidate}")

    configured = os.environ.get("CODEX_REAL_BIN", "").strip()
    if configured:
        return resolve_native_codex_bin(configured)

    try:
        from codex_route import resolve_real_codex

        return resolve_real_codex()
    except (ImportError, RuntimeError) as exc:
        raise ValueError(
            "Unable to resolve the native Codex binary. Set CODEX_REAL_BIN or "
            "pass --native-codex-bin."
        ) from exc


def resolve_executable(value: str, *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate.resolve()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry) / value
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise ValueError(f"{label} executable is not available: {value}")


def validate_cases(cases: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    for case in cases:
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            errors.append("case is missing id")
        if not str(case.get("title") or "").strip():
            errors.append(f"{case_id}: title is required")
        if not str(case.get("prompt") or "").strip():
            errors.append(f"{case_id}: prompt is required")
        if not bool(case.get("requires_repository_tools")):
            errors.append(f"{case_id}: requires_repository_tools must be true")
    if errors:
        raise ValueError("invalid bridge parity cases: " + "; ".join(errors))


def read_cases(path: Path) -> list[dict[str, Any]]:
    cases = load_cases(path)
    validate_cases(cases)
    return cases


def _evaluation_prompt(case: dict[str, Any]) -> str:
    return "\n".join(
        (
            "You are participating in a read-only Codex route parity evaluation.",
            "Do not edit files, create artifacts, run tests, call network services,",
            "access credentials, or inspect environment/secret configuration.",
            "Use only local repository files needed to answer the task. Cite",
            "repository-relative paths for your evidence. Complete the task now;",
            "do not promise future work or ask for a follow-up.",
            "",
            str(case["prompt"]).strip(),
        )
    )


def _route_environment(route: RouteSpec) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("CODEX_REAL_BIN", None)
    if route.codex_home is not None:
        environment["CODEX_HOME"] = str(route.codex_home)
    else:
        environment.pop("CODEX_HOME", None)
    # Direct parity runs must remain read-only too, even outside the work wrapper.
    environment["NORMAN_TUI_NO_DIRECT_VAULT"] = "1"
    return environment


def run_route_case(
    *,
    route: RouteSpec,
    case: dict[str, Any],
    workspace: Path,
    temp_dir: Path,
    timeout_seconds: int,
) -> RouteExecution:
    case_id = str(case["id"])
    answer_path = temp_dir / f"{route.key}-{case_id}.final.txt"
    events_path = temp_dir / f"{route.key}-{case_id}.events.jsonl"
    command = [
        str(route.binary),
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--cd",
        str(workspace),
        "--output-last-message",
        str(answer_path),
        _evaluation_prompt(case),
    ]
    started = time.monotonic()
    status = "completed"
    returncode: int | None = None
    try:
        with events_path.open("w", encoding="utf-8") as events_file:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=_route_environment(route),
                stdout=events_file,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        returncode = completed.returncode
        if returncode != 0:
            status = "nonzero"
    except subprocess.TimeoutExpired:
        status = "timeout"
    except OSError:
        status = "execution_error"
    duration_ms = round((time.monotonic() - started) * 1000)
    answer = ""
    try:
        answer = answer_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    if status == "completed" and not answer:
        status = "empty_output"
    tool_events, retry_events, usage = parse_event_metrics(events_path)
    return RouteExecution(
        route=route.key,
        status=status,
        returncode=returncode,
        duration_ms=duration_ms,
        answer=answer,
        answer_sha256=_sha256(answer) if answer else "",
        answer_chars=len(answer),
        tool_events=tool_events,
        retry_events=retry_events,
        usage=usage,
        short_stop=response_has_unfinished_promise(answer),
    )


def _score_payload(score: AnswerScore | None) -> dict[str, Any]:
    if score is None:
        return {}
    return {
        "score": score.score,
        "fact_recall": score.fact_recall,
        "evidence_recall": score.evidence_recall,
        "wisdom": score.wisdom,
        "trap_free": score.trap_free,
        "completeness": score.completeness,
        "reasoning_depth": score.reasoning_depth,
        "contract_score": score.contract_score,
        "claim_precision_proxy": score.claim_precision_proxy,
        "hallucination_trap_hits": score.hallucination_trap_hits,
        "estimated_answer_tokens": score.estimated_answer_tokens,
        "missing_rule_ids": sorted(
            hit.id
            for hits in (
                score.fact_hits,
                score.evidence_hits,
                score.wisdom_hits,
                score.contract_hits,
            )
            for hit in hits
            if not hit.matched
        ),
        "trap_rule_ids": sorted(hit.id for hit in score.trap_hits if hit.matched),
    }


def _execution_payload(
    execution: RouteExecution, case: dict[str, Any]
) -> dict[str, Any]:
    score = (
        score_answer(case, execution.route, execution.answer)
        if execution.status == "completed"
        else None
    )
    return {
        "status": execution.status,
        "returncode": execution.returncode,
        "duration_ms": execution.duration_ms,
        "answer_sha256": execution.answer_sha256,
        "answer_chars": execution.answer_chars,
        "tool_events": execution.tool_events,
        "retry_events": execution.retry_events,
        "usage": execution.usage,
        "short_stop": execution.short_stop,
        "score": _score_payload(score),
    }


def _completed(execution: dict[str, Any]) -> bool:
    return bool(
        execution.get("status") == "completed" and execution.get("answer_chars")
    )


def _score_value(execution: dict[str, Any]) -> float | None:
    score = execution.get("score")
    if not isinstance(score, dict) or not score:
        return None
    value = score.get("score")
    return float(value) if isinstance(value, int | float) else None


def _usage_total(case_rows: list[dict[str, Any]], route: str, key: str) -> int:
    return sum(
        _int(execution.get("usage", {}).get(key))
        for row in case_rows
        if isinstance((execution := row[route]), dict)
    )


def _duration_summary(case_rows: list[dict[str, Any]], route: str) -> dict[str, int]:
    durations = [
        _int(row[route].get("duration_ms"))
        for row in case_rows
        if _completed(row[route])
    ]
    return {
        "total_ms": sum(durations),
        "average_ms": round(sum(durations) / len(durations)) if durations else 0,
    }


def build_summary(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [
        row
        for row in case_rows
        if _completed(row["native"]) and _completed(row["transparent"])
    ]
    native_completed = sum(_completed(row["native"]) for row in case_rows)
    transparent_completed = sum(_completed(row["transparent"]) for row in case_rows)
    score_deltas = [
        transparent - native
        for row in paired
        if (native := _score_value(row["native"])) is not None
        and (transparent := _score_value(row["transparent"])) is not None
    ]
    native_short_stops = sum(
        bool(row["native"].get("short_stop"))
        for row in case_rows
        if _completed(row["native"])
    )
    transparent_short_stops = sum(
        bool(row["transparent"].get("short_stop"))
        for row in case_rows
        if _completed(row["transparent"])
    )
    tool_regression_case_ids = [
        str(row["id"])
        for row in paired
        if row["requires_repository_tools"]
        and _int(row["native"].get("tool_events")) > 0
        and _int(row["transparent"].get("tool_events")) == 0
    ]
    native_tool_events = sum(
        _int(row["native"].get("tool_events")) for row in case_rows
    )
    transparent_tool_events = sum(
        _int(row["transparent"].get("tool_events")) for row in case_rows
    )
    native_duration = _duration_summary(case_rows, "native")
    transparent_duration = _duration_summary(case_rows, "transparent")
    return {
        "case_count": len(case_rows),
        "completed_pairs": len(paired),
        "native_completed_cases": native_completed,
        "transparent_completed_cases": transparent_completed,
        "native_completion_rate": round(native_completed / len(case_rows), 3)
        if case_rows
        else 0.0,
        "transparent_completion_rate": round(transparent_completed / len(case_rows), 3)
        if case_rows
        else 0.0,
        "average_score_delta": round(sum(score_deltas) / len(score_deltas), 2)
        if score_deltas
        else None,
        "native_short_stop_count": native_short_stops,
        "transparent_short_stop_count": transparent_short_stops,
        "short_stop_delta": transparent_short_stops - native_short_stops,
        "native_tool_events": native_tool_events,
        "transparent_tool_events": transparent_tool_events,
        "tool_continuity_regression_case_ids": tool_regression_case_ids,
        "native_retry_events": sum(
            _int(row["native"].get("retry_events")) for row in case_rows
        ),
        "transparent_retry_events": sum(
            _int(row["transparent"].get("retry_events")) for row in case_rows
        ),
        "native_duration_ms": native_duration,
        "transparent_duration_ms": transparent_duration,
        "duration_delta_ms": (
            transparent_duration["average_ms"] - native_duration["average_ms"]
        ),
        "native_usage": {
            key: _usage_total(case_rows, "native", key) for key in sorted(USAGE_KEYS)
        },
        "transparent_usage": {
            key: _usage_total(case_rows, "transparent", key)
            for key in sorted(USAGE_KEYS)
        },
    }


def evaluate_gate(
    *,
    live: bool,
    summary: dict[str, Any],
    min_completed_pairs: int,
    max_score_regression: float,
) -> dict[str, Any]:
    if not live:
        return {
            "state": "hold",
            "reason_codes": ["dry_run"],
            "min_completed_pairs": min_completed_pairs,
            "max_score_regression": max_score_regression,
        }
    reasons: list[str] = []
    if _int(summary.get("completed_pairs")) < min_completed_pairs:
        reasons.append("incomplete_pairs")
    average_score_delta = summary.get("average_score_delta")
    if (
        isinstance(average_score_delta, int | float)
        and average_score_delta < -max_score_regression
    ):
        reasons.append("score_regression")
    if _int(summary.get("short_stop_delta")) > 0:
        reasons.append("short_stop_regression")
    if summary.get("tool_continuity_regression_case_ids"):
        reasons.append("tool_continuity_regression")
    return {
        "state": "fail" if reasons else "pass",
        "reason_codes": reasons,
        "min_completed_pairs": min_completed_pairs,
        "max_score_regression": max_score_regression,
    }


def build_dry_run_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        route_order = (
            ["native", "transparent"] if index % 2 == 0 else ["transparent", "native"]
        )
        empty = {
            "status": "not_run",
            "returncode": None,
            "duration_ms": 0,
            "answer_sha256": "",
            "answer_chars": 0,
            "tool_events": 0,
            "retry_events": 0,
            "usage": {},
            "short_stop": False,
            "score": {},
        }
        rows.append(
            {
                "id": str(case["id"]),
                "title": str(case["title"]),
                "category": str(case.get("category") or ""),
                "requires_repository_tools": True,
                "route_order": route_order,
                "native": dict(empty),
                "transparent": dict(empty),
            }
        )
    return rows


def run_live(
    *,
    cases: list[dict[str, Any]],
    workspace: Path,
    native: RouteSpec,
    transparent: RouteSpec,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="norman-codex-bridge-parity-") as name:
        temp_dir = Path(name)
        for index, case in enumerate(cases):
            routes = [native, transparent] if index % 2 == 0 else [transparent, native]
            executions: dict[str, RouteExecution] = {}
            for route in routes:
                executions[route.key] = run_route_case(
                    route=route,
                    case=case,
                    workspace=workspace,
                    temp_dir=temp_dir,
                    timeout_seconds=timeout_seconds,
                )
            rows.append(
                {
                    "id": str(case["id"]),
                    "title": str(case["title"]),
                    "category": str(case.get("category") or ""),
                    "requires_repository_tools": True,
                    "route_order": [route.key for route in routes],
                    "native": _execution_payload(executions["native"], case),
                    "transparent": _execution_payload(executions["transparent"], case),
                }
            )
    return rows


def build_report(
    *,
    cases: list[dict[str, Any]],
    workspace: Path,
    live: bool,
    rows: list[dict[str, Any]],
    native: RouteSpec | None,
    transparent: RouteSpec | None,
    timeout_seconds: int,
    min_completed_pairs: int,
    max_score_regression: float,
) -> dict[str, Any]:
    summary = build_summary(rows)
    gate = evaluate_gate(
        live=live,
        summary=summary,
        min_completed_pairs=min_completed_pairs,
        max_score_regression=max_score_regression,
    )
    return {
        "schema": SCHEMA,
        "generated_at": _utc_now(),
        "run": {
            "mode": "live" if live else "dry_run",
            "workspace_name": _safe_path(workspace),
            "case_count": len(cases),
            "timeout_seconds": timeout_seconds,
            "native_binary": _safe_path(native.binary) if native else "",
            "transparent_binary": _safe_path(transparent.binary) if transparent else "",
            "raw_artifacts": "temporary_only",
        },
        "gate": gate,
        "summary": summary,
        "cases": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    summary = report["summary"]
    gate = report["gate"]
    lines = [
        "# Codex Bridge Parity Evaluation",
        "",
        f"- Mode: `{run['mode']}`",
        f"- Workspace: `{run['workspace_name']}`",
        f"- Gate: `{gate['state']}`",
        f"- Completed pairs: {summary['completed_pairs']}/{summary['case_count']}",
        f"- Average transparent score delta: {summary['average_score_delta']}",
        f"- Completion: native {summary['native_completion_rate']:.0%}, transparent {summary['transparent_completion_rate']:.0%}",
        f"- Short-stop delta: {summary['short_stop_delta']}",
        f"- Tool events: native {summary['native_tool_events']}, transparent {summary['transparent_tool_events']}",
        f"- Retries: native {summary['native_retry_events']}, transparent {summary['transparent_retry_events']}",
        (
            "- Average duration: native "
            f"{summary['native_duration_ms']['average_ms'] / 1000:.1f}s, "
            f"transparent {summary['transparent_duration_ms']['average_ms'] / 1000:.1f}s "
            f"(delta {summary['duration_delta_ms'] / 1000:+.1f}s)"
        ),
        (
            "- Input tokens: native "
            f"{summary['native_usage']['input_tokens']}, transparent "
            f"{summary['transparent_usage']['input_tokens']}"
        ),
        (
            "- Output tokens: native "
            f"{summary['native_usage']['output_tokens']}, transparent "
            f"{summary['transparent_usage']['output_tokens']}"
        ),
        "",
        "## Cases",
        "",
        "| Case | Order | Native | Transparent | Score delta | Tools N/T |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in report["cases"]:
        native_score = _score_value(row["native"])
        transparent_score = _score_value(row["transparent"])
        delta = (
            f"{transparent_score - native_score:+.0f}"
            if native_score is not None and transparent_score is not None
            else "n/a"
        )
        lines.append(
            "| {id} | {order} | {native} | {transparent} | {delta} | {nt}/{tt} |".format(
                id=row["id"],
                order=" -> ".join(row["route_order"]),
                native=row["native"]["status"],
                transparent=row["transparent"]["status"],
                delta=delta,
                nt=row["native"]["tool_events"],
                tt=row["transparent"]["tool_events"],
            )
        )
    if gate["reason_codes"]:
        lines.extend(("", "## Gate Reasons", ""))
        lines.extend(f"- `{reason}`" for reason in gate["reason_codes"])
    lines.extend(
        (
            "",
            "Raw prompts, event streams, and answers are temporary-only. This report stores no model text.",
            "",
        )
    )
    return "\n".join(lines)


def write_private(path: Path, contents: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(contents, encoding="utf-8")
    try:
        temp_path.chmod(0o600)
    except OSError:
        pass
    temp_path.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare direct native Codex with codex-work's transparent Norman "
            "bridge on safe, read-only repository tasks."
        )
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--native-codex-bin",
        default="",
        help="Real Codex executable. Defaults to CODEX_REAL_BIN or codex_route resolution.",
    )
    parser.add_argument(
        "--direct-codex-home",
        type=Path,
        default=Path(
            os.environ.get("NORMAN_CODEX_PARITY_DIRECT_HOME", "~/.codex")
        ).expanduser(),
    )
    parser.add_argument(
        "--transparent-codex-bin",
        default=os.environ.get("NORMAN_CODEX_PARITY_WORK_BIN", "codex-work"),
    )
    parser.add_argument(
        "--min-completed-pairs", type=int, default=DEFAULT_MIN_COMPLETED_PAIRS
    )
    parser.add_argument(
        "--max-score-regression", type=float, default=DEFAULT_MAX_SCORE_REGRESSION
    )
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    if args.min_completed_pairs <= 0:
        raise ValueError("--min-completed-pairs must be positive")
    if args.max_score_regression < 0:
        raise ValueError("--max-score-regression must be non-negative")
    cases = read_cases(args.cases)
    if args.live and not args.workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {args.workspace}")

    native: RouteSpec | None = None
    transparent: RouteSpec | None = None
    if args.live:
        native = RouteSpec(
            key="native",
            binary=resolve_native_codex_bin(args.native_codex_bin or None),
            codex_home=args.direct_codex_home,
        )
        transparent = RouteSpec(
            key="transparent",
            binary=resolve_executable(
                args.transparent_codex_bin, label="transparent Codex work"
            ),
        )
        rows = run_live(
            cases=cases,
            workspace=args.workspace,
            native=native,
            transparent=transparent,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        rows = build_dry_run_rows(cases)

    report = build_report(
        cases=cases,
        workspace=args.workspace,
        live=args.live,
        rows=rows,
        native=native,
        transparent=transparent,
        timeout_seconds=args.timeout_seconds,
        min_completed_pairs=args.min_completed_pairs,
        max_score_regression=args.max_score_regression,
    )
    write_private(args.output_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    write_private(args.output_md, render_markdown(report))
    print(
        "codex-bridge-parity: state={state} pairs={pairs}/{cases}".format(
            state=report["gate"]["state"],
            pairs=report["summary"]["completed_pairs"],
            cases=report["summary"]["case_count"],
        )
    )
    if report["gate"]["state"] == "fail":
        return 1
    if args.require_complete and report["gate"]["state"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
