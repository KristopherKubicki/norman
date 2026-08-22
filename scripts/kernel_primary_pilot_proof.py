#!/usr/bin/env python3
"""Evaluate exported Console Runtime events for a five-case kernel-primary pilot.

This tool is intentionally offline: it reads a JSON or JSONL event export, produces
JSON/Markdown evidence, and never calls a TUI, starts work, or changes rollout
settings. An operator runs the safe pilot separately, then exports its events from
``/console-runtime/events`` for evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "norman.kernel-primary-pilot-proof.v1"
CASES = (
    {
        "id": "planner",
        "title": "Planner",
        "prompt": "Create a bounded plan for this read-only repository task. Do not change files.",
        "required_events": (
            "model.completed",
            "route.receipt_audited",
            "route.completion_gate",
        ),
        "requires_tool": False,
        "requires_verification": False,
        "requires_workstream": False,
        "requires_local": True,
    },
    {
        "id": "tool_loop",
        "title": "Tool Loop",
        "prompt": "Inspect the requested files with read-only tools, then summarize the evidence.",
        "required_events": ("model.completed", "tool.completed", "reasoning.tool_gate"),
        "requires_tool": True,
        "requires_verification": False,
        "requires_workstream": False,
        "requires_local": True,
    },
    {
        "id": "parallel",
        "title": "Parallel Workstream",
        "prompt": "Delegate two independent read-only inspections and merge their findings.",
        "required_events": ("workstream.created", "workstream.subtasks_delegated"),
        "requires_tool": False,
        "requires_verification": False,
        "requires_workstream": True,
        "requires_local": True,
    },
    {
        "id": "verifier",
        "title": "Verifier",
        "prompt": "Draft a read-only answer, verify it against the available evidence, and return a final answer.",
        "required_events": (
            "model.completed",
            "verification.completed",
            "route.receipt_audited",
            "route.completion_gate",
        ),
        "requires_tool": False,
        "requires_verification": True,
        "requires_workstream": False,
        "requires_local": True,
    },
    {
        "id": "degraded",
        "title": "Degraded Route",
        "prompt": "With one preferred local lane unavailable, complete a safe read-only summary and make the fallback visible.",
        "required_events": ("model.completed", "route.receipt_audited"),
        "requires_tool": False,
        "requires_verification": False,
        "requires_workstream": False,
        "requires_local": True,
    },
)
CASE_IDS = {case["id"] for case in CASES}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {"1", "true", "yes", "on"}


def _event_case(event: dict[str, Any]) -> str:
    payload = _as_dict(event.get("payload"))
    metadata = _as_dict(payload.get("metadata"))
    for candidate in (
        event.get("pilot_case"),
        payload.get("pilot_case"),
        metadata.get("pilot_case"),
        payload.get("scenario"),
    ):
        value = _clean(candidate).lower().replace("-", "_")
        if value in CASE_IDS:
            return value
    return ""


def load_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load either an API JSON event object/list or newline-delimited event export."""

    errors: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"cannot read {path}: {exc}"]
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        if "events" in decoded or "items" in decoded:
            candidates = decoded.get("events", decoded.get("items", []))
            if not isinstance(candidates, list):
                return [], ["JSON object must contain an events or items list"]
            return [item for item in candidates if isinstance(item, dict)], errors
        # A one-line JSONL export is valid JSON too; treat an event-shaped object
        # as a single JSONL record rather than silently discarding it.
        if "event_type" in decoded:
            return [decoded], errors
        return [], ["JSON object must contain an events or items list"]
    if isinstance(decoded, list):
        return [item for item in decoded if isinstance(item, dict)], errors
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_no}: malformed JSON: {exc.msg}")
            continue
        if not isinstance(item, dict):
            errors.append(f"{path}:{line_no}: event is not a JSON object")
            continue
        events.append(item)
    return events, errors


def _route_receipt(event: dict[str, Any]) -> dict[str, Any]:
    payload = _as_dict(event.get("payload"))
    return _as_dict(payload.get("route_receipt"))


def _has_local_proof(receipts: list[dict[str, Any]]) -> bool:
    for receipt in receipts:
        bucket = _clean(receipt.get("usage_bucket")).lower()
        worker = _clean(receipt.get("observed_worker"))
        source = _clean(receipt.get("observed_worker_source")).lower()
        if (
            bucket in {"offline_local", "local", "norllama"}
            and worker
            and source == "gateway_response"
        ):
            return True
    return False


def _receipt_issues(receipts: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if not receipts:
        return ["missing route receipt audit"]
    if not any(
        _as_dict(receipt.get("receipt_audit")).get("pass") is True
        for receipt in receipts
    ):
        issues.append("no route receipt audit passed")
    if not any(
        _as_dict(receipt.get("completion_gate")).get("gate_passed") is True
        for receipt in receipts
    ):
        issues.append("no route completion gate passed")
    if any(_truthy(receipt.get("cloud_proxy")) for receipt in receipts):
        issues.append("cloud proxy was used")
    return issues


def evaluate_case(case: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate a single case's tagged events without interpreting prompt contents."""

    # The API export is already cursor-ordered. Retain that order so missing or
    # repeated sequence values cannot fabricate a tool/model ordering result.
    ordered = list(events)
    event_types = [str(item.get("event_type") or "").lower() for item in ordered]
    counts = Counter(event_types)
    receipts = [_route_receipt(item) for item in ordered if _route_receipt(item)]
    failures: list[str] = []
    for required in case["required_events"]:
        if not counts[required]:
            failures.append(f"missing required event: {required}")
    if case["requires_tool"]:
        actual_tools = [
            item
            for item in ordered
            if str(item.get("event_type") or "").lower() == "tool.completed"
            and _clean(_as_dict(item.get("payload")).get("tool_name"))
            != "model_adapter.invoke"
        ]
        if not actual_tools:
            failures.append("no non-model tool completion was observed")
        model_positions = [
            i for i, kind in enumerate(event_types) if kind == "model.completed"
        ]
        actual_tool_positions = [
            index
            for index, item in enumerate(ordered)
            if str(item.get("event_type") or "").lower() == "tool.completed"
            and _clean(_as_dict(item.get("payload")).get("tool_name"))
            != "model_adapter.invoke"
        ]
        if (
            model_positions
            and actual_tool_positions
            and max(actual_tool_positions) >= max(model_positions)
        ):
            failures.append("no model completion followed the tool activity")
    if case["requires_workstream"]:
        delegated = [
            _as_dict(item.get("payload"))
            for item in ordered
            if str(item.get("event_type") or "").lower()
            == "workstream.subtasks_delegated"
        ]
        if not any(int(payload.get("count") or 0) >= 2 for payload in delegated):
            failures.append("fewer than two delegated subtasks were recorded")
    if case["requires_verification"] and not counts["verification.completed"]:
        failures.append("verification completion was not observed")
    if case["requires_local"] and not _has_local_proof(receipts):
        failures.append("missing local observed-worker proof from gateway_response")
    failures.extend(_receipt_issues(receipts))
    if case["id"] == "degraded":
        fallback_visible = any(
            _clean(_as_dict(item.get("payload")).get("fallback_reason"))
            or _clean(_as_dict(item.get("payload")).get("fallback_used"))
            or _clean(_route_receipt(item).get("fallback_reason"))
            or _clean(_route_receipt(item).get("fallback_used"))
            or "fallback" in _clean(item.get("event_type")).lower()
            or "degraded" in _clean(item.get("event_type")).lower()
            for item in ordered
        )
        if not fallback_visible:
            failures.append(
                "degraded/fallback state was not visible in exported events"
            )
    return {
        "case_id": case["id"],
        "title": case["title"],
        "prompt": case["prompt"],
        "event_count": len(ordered),
        "event_counts": dict(sorted(counts.items())),
        "job_ids": sorted(
            {
                _clean(item.get("job_id"))
                for item in ordered
                if _clean(item.get("job_id"))
            }
        ),
        "observed_workers": sorted(
            {
                _clean(receipt.get("observed_worker"))
                for receipt in receipts
                if _clean(receipt.get("observed_worker"))
            }
        ),
        "passed": not failures,
        "failures": failures,
    }


def build_report(events: list[dict[str, Any]], *, source: str = "") -> dict[str, Any]:
    """Group tagged events and return a deterministic pilot-proof report."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    untagged = 0
    for event in events:
        case_id = _event_case(event)
        if case_id:
            grouped[case_id].append(event)
        else:
            untagged += 1
    rows = [evaluate_case(case, grouped[case["id"]]) for case in CASES]
    return {
        "schema": SCHEMA,
        "source": source,
        "offline_only": True,
        "rollout_settings_changed": False,
        "event_count": len(events),
        "untagged_event_count": untagged,
        "passed": all(row["passed"] for row in rows),
        "summary": {
            "required_cases": len(CASES),
            "passed_cases": sum(1 for row in rows if row["passed"]),
            "failed_cases": sum(1 for row in rows if not row["passed"]),
        },
        "cases": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    verdict = "PASS" if report.get("passed") else "NOT YET PROVEN"
    lines = [
        "# Kernel-Primary Pilot Proof",
        "",
        f"**Verdict:** {verdict}",
        "",
        "This is an offline evaluation of exported Console Runtime events. It did not invoke a TUI,",
        "change rollout settings, or execute a workload.",
        "",
        "| Case | Result | Events | Observed Workers |",
        "| --- | --- | ---: | --- |",
    ]
    for row in report.get("cases", []):
        result = "PASS" if row.get("passed") else "FAIL"
        workers = ", ".join(row.get("observed_workers") or []) or "—"
        lines.append(
            f"| {row['title']} | {result} | {row['event_count']} | {workers} |"
        )
    for row in report.get("cases", []):
        if row.get("passed"):
            continue
        lines.extend(["", f"## {row['title']} Gaps", ""])
        lines.extend(f"- {failure}" for failure in row.get("failures", []))
    lines.extend(
        [
            "",
            "## Evidence Requirements",
            "",
            "Every case needs a completed local route with an observed worker reported by the gateway,",
            "a passing receipt audit, and a passing route completion gate. The tool-loop case additionally",
            "requires a real non-model tool completion followed by model completion. The parallel case",
            "requires at least two delegated subtasks. The degraded case requires visible fallback evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events", type=Path, help="JSON/JSONL export from /console-runtime/events"
    )
    parser.add_argument(
        "--output-json", type=Path, help="write the machine-readable report here"
    )
    parser.add_argument("--output-md", type=Path, help="write the operator report here")
    args = parser.parse_args(argv)
    events, errors = load_events(args.events)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    report = build_report(events, source=str(args.events))
    rendered_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    rendered_md = render_markdown(report)
    if args.output_json:
        args.output_json.write_text(rendered_json, encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(rendered_md, encoding="utf-8")
    if not args.output_json:
        print(rendered_json, end="")
    if not args.output_md:
        print(rendered_md)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
