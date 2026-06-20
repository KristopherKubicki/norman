#!/usr/bin/env python3
"""Combine planner guardrail artifacts into one attention queue."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.planner-guardrail-dashboard.v1"
DEFAULT_CUTOVER_JSON = Path("tmp/tui_cutover_readiness.json")
DEFAULT_PREROUTE_JSON = Path("tmp/planner_preroute_policy.json")
DEFAULT_ROUTE_POLICY_JSON = Path("tmp/local_model_route_policy.json")
DEFAULT_LOCAL_FLOORS_JSON = Path("tmp/local_model_skill_floors.json")
DEFAULT_OUTPUT_JSON = Path("tmp/planner_guardrail_dashboard.json")
DEFAULT_OUTPUT_MD = Path("tmp/planner_guardrail_dashboard.md")


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report, dict) else {}
    return summary if isinstance(summary, dict) else {}


def _count(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _signal(
    signals: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    source: str,
    count: int,
    message: str,
    next_action: str,
) -> None:
    if count <= 0:
        return
    signals.append(
        {
            "severity": severity,
            "code": code,
            "source": source,
            "count": count,
            "message": message,
            "next_action": next_action,
        }
    )


def build_report(
    *,
    cutover: dict[str, Any],
    preroute: dict[str, Any],
    route_policy: dict[str, Any],
    local_floors: dict[str, Any],
) -> dict[str, Any]:
    cutover_summary = _summary(cutover)
    preroute_summary = _summary(preroute)
    route_summary = _summary(route_policy)
    floor_summary = _summary(local_floors)
    signals: list[dict[str, Any]] = []

    _signal(
        signals,
        severity="block",
        code="boundary_violation",
        source="tui_cutover_readiness",
        count=_count(cutover_summary, "boundary_violation_count"),
        message="Route receipts include boundary violations.",
        next_action="Hold promotion and inspect offending receipts before any cutover.",
    )
    _signal(
        signals,
        severity="block",
        code="live_write_attempt",
        source="tui_cutover_readiness",
        count=_count(cutover_summary, "live_write_attempt_count"),
        message="Shadow route receipts attempted live writes.",
        next_action="Hold cutover and review the action path that attempted mutation.",
    )
    _signal(
        signals,
        severity="block",
        code="receipt_chain_issue",
        source="tui_cutover_readiness",
        count=_count(cutover_summary, "route_receipt_chain_issue_count"),
        message="Route receipt hash chains are broken.",
        next_action="Repair or discard invalid receipt chains before scoring readiness.",
    )
    _signal(
        signals,
        severity="warn",
        code="route_drift",
        source="tui_cutover_readiness",
        count=_count(cutover_summary, "route_drift_count"),
        message="Actual receipts drifted from intended planner route.",
        next_action="Compare planned route against selected model tier and executor.",
    )
    _signal(
        signals,
        severity="warn",
        code="blocked_cutover_targets",
        source="tui_cutover_readiness",
        count=_count(cutover_summary, "blocked_target_count"),
        message="Planner targets are blocked from cutover.",
        next_action="Resolve target blockers or continue collecting clean shadow receipts.",
    )
    _signal(
        signals,
        severity="warn",
        code="cloud_policy_check_queue",
        source="planner_preroute_policy",
        count=_count(preroute_summary, "cloud_candidate_requires_policy_check_count"),
        message="Pre-route found cloud candidates requiring deterministic policy checks.",
        next_action="Require policy acceptance before cloud spend or final authority.",
    )
    _signal(
        signals,
        severity="warn",
        code="spark_vllm_unavailable",
        source="local_model_skill_floors",
        count=1 if _count(floor_summary, "online_spark_vllm_model_count") == 0 else 0,
        message="No usable Spark/vLLM model is available in the local floor report.",
        next_action="Fix vLLM health before expecting Spark pre-route/offload wins.",
    )
    _signal(
        signals,
        severity="warn",
        code="ollama_fallback_without_spark",
        source="local_model_route_policy",
        count=_count(route_summary, "ollama_fallback_route_count")
        if _count(route_summary, "spark_vllm_route_count") == 0
        else 0,
        message="Offline routes are falling back to Ollama instead of Spark/vLLM.",
        next_action="Keep Ollama fallback, but prioritize Spark/vLLM service recovery.",
    )
    _signal(
        signals,
        severity="observe",
        code="local_planner_contracts_required",
        source="planner_preroute_policy",
        count=_count(preroute_summary, "local_planner_contract_required_count"),
        message="Local planner proposal contracts are required before route execution.",
        next_action="Validate local planner JSON before accepting route proposals.",
    )

    severity_counts: dict[str, int] = {}
    for signal in signals:
        severity = str(signal["severity"])
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "source_schemas": {
            "cutover": cutover.get("schema"),
            "preroute": preroute.get("schema"),
            "route_policy": route_policy.get("schema"),
            "local_floors": local_floors.get("schema"),
        },
        "summary": {
            "signal_count": len(signals),
            "block_count": severity_counts.get("block", 0),
            "warn_count": severity_counts.get("warn", 0),
            "observe_count": severity_counts.get("observe", 0),
            "needs_attention": bool(
                severity_counts.get("block", 0) or severity_counts.get("warn", 0)
            ),
        },
        "signals": signals,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Planner Guardrail Dashboard",
        "",
        f"- Dry run only: `{str(report.get('dry_run_only')).lower()}`",
        f"- Model calls executed: `{report.get('model_calls_executed')}`",
        f"- Signals: `{summary['signal_count']}`",
        f"- Blocks: `{summary['block_count']}`",
        f"- Warnings: `{summary['warn_count']}`",
        f"- Observations: `{summary['observe_count']}`",
        f"- Needs attention: `{str(summary['needs_attention']).lower()}`",
        "",
        "| Severity | Code | Count | Source | Next action |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for signal in report.get("signals") or []:
        lines.append(
            "| {severity} | `{code}` | {count} | `{source}` | {next_action} |".format(
                severity=signal.get("severity") or "",
                code=signal.get("code") or "",
                count=signal.get("count") or 0,
                source=signal.get("source") or "",
                next_action=signal.get("next_action") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutover-json", type=Path, default=DEFAULT_CUTOVER_JSON)
    parser.add_argument("--preroute-json", type=Path, default=DEFAULT_PREROUTE_JSON)
    parser.add_argument(
        "--route-policy-json", type=Path, default=DEFAULT_ROUTE_POLICY_JSON
    )
    parser.add_argument(
        "--local-floors-json", type=Path, default=DEFAULT_LOCAL_FLOORS_JSON
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        cutover=load_optional_json(args.cutover_json),
        preroute=load_optional_json(args.preroute_json),
        route_policy=load_optional_json(args.route_policy_json),
        local_floors=load_optional_json(args.local_floors_json),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "summary": report["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
