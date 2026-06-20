#!/usr/bin/env python3
"""Build a deterministic pre-route policy before local/cloud planner calls."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.planner-preroute-policy.v1"
LOCAL_PLANNER_PROPOSAL_SCHEMA = "norman.local-planner-proposal.v1"
LOCAL_PLANNER_ROUTE_CLASSES = {
    "deterministic_only",
    "local_execute",
    "local_draft_cloud_verify",
    "cloud_required",
    "blocked_missing_context",
    "handoff_required",
}
LOCAL_PLANNER_REQUIRED_FIELDS = (
    "schema",
    "route_class",
    "confidence",
    "required_evidence",
    "proposed_executor",
    "cloud_required",
    "max_cloud_spend_usd",
    "stop_before_actions",
)
DEFAULT_ROUTE_POLICY_JSON = Path("tmp/local_model_route_policy.json")
DEFAULT_OUTPUT_JSON = Path("tmp/planner_preroute_policy.json")
DEFAULT_OUTPUT_MD = Path("tmp/planner_preroute_policy.md")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pre_llm_decision(row: dict[str, Any]) -> tuple[str, str, bool]:
    route_kind = str(row.get("route_kind") or "")
    runtime = str(row.get("selected_local_runtime_class") or "")
    final_authority = bool(row.get("final_authority_required"))
    local_runtime_routeable = bool(row.get("local_runtime_routeable", True))
    if route_kind == "deterministic_only":
        return "bypass_llm_deterministic", "exact deterministic contract", False
    if final_authority:
        return (
            "local_draft_cloud_final_policy_check",
            "final authority remains cloud/operator gated",
            True,
        )
    if runtime == "spark_vllm" and local_runtime_routeable:
        return "ask_spark_vllm_planner", "Spark/vLLM is adequate and preferred", False
    if runtime == "ollama" and local_runtime_routeable:
        return "ask_ollama_planner", "Ollama is the available offline fallback", False
    if runtime and not local_runtime_routeable:
        return (
            "cloud_candidate_after_policy_check",
            "local runtime is unavailable",
            True,
        )
    return "cloud_candidate_after_policy_check", "no adequate local runtime", True


def _local_planner_contract(decision: str) -> dict[str, Any]:
    if decision not in {"ask_spark_vllm_planner", "ask_ollama_planner"}:
        return {}
    return {
        "schema": LOCAL_PLANNER_PROPOSAL_SCHEMA,
        "required_fields": list(LOCAL_PLANNER_REQUIRED_FIELDS),
        "route_class_enum": sorted(LOCAL_PLANNER_ROUTE_CLASSES),
        "hard_rules": [
            "Local planner output is advisory until deterministic policy accepts it.",
            "Cloud or live-action requests must set cloud_required=true and stop_before_actions.",
            "Final authority cannot be granted by the local planner.",
            "required_evidence must name concrete files, commands, receipts, or missing context.",
        ],
        "max_prompt_tokens": 1200,
        "model_calls_executed_by_contract": 0,
    }


def validate_local_planner_proposal(proposal: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(proposal, dict):
        return ["proposal must be a JSON object"]
    for field in LOCAL_PLANNER_REQUIRED_FIELDS:
        if field not in proposal:
            errors.append(f"missing required field: {field}")
    if proposal.get("schema") != LOCAL_PLANNER_PROPOSAL_SCHEMA:
        errors.append("schema mismatch")
    if proposal.get("route_class") not in LOCAL_PLANNER_ROUTE_CLASSES:
        errors.append("route_class is not allowed")
    confidence = proposal.get("confidence")
    if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
        errors.append("confidence must be a number between 0 and 1")
    if not isinstance(proposal.get("required_evidence"), list):
        errors.append("required_evidence must be a list")
    if not isinstance(proposal.get("stop_before_actions"), list):
        errors.append("stop_before_actions must be a list")
    if not isinstance(proposal.get("cloud_required"), bool):
        errors.append("cloud_required must be boolean")
    max_spend = proposal.get("max_cloud_spend_usd")
    if not isinstance(max_spend, int | float) or float(max_spend) < 0:
        errors.append("max_cloud_spend_usd must be a non-negative number")
    if proposal.get("cloud_required") and not proposal.get("stop_before_actions"):
        errors.append("cloud_required proposals must stop before cloud/live action")
    return errors


def build_row(row: dict[str, Any]) -> dict[str, Any]:
    decision, reason, cloud_candidate = _pre_llm_decision(row)
    local_planner_contract = _local_planner_contract(decision)
    return {
        "skill_id": row.get("skill_id"),
        "domain": row.get("domain"),
        "family": row.get("family"),
        "route_kind": row.get("route_kind"),
        "network_priority": row.get("network_priority"),
        "pre_llm_decision": decision,
        "decision_reason": reason,
        "local_planner_contract": local_planner_contract,
        "local_planner_contract_required": bool(local_planner_contract),
        "deterministic_bypass": decision == "bypass_llm_deterministic",
        "local_planner_candidate": decision
        in {"ask_spark_vllm_planner", "ask_ollama_planner"},
        "cloud_candidate_requires_policy_check": cloud_candidate,
        "selected_local_runtime_class": row.get("selected_local_runtime_class") or "",
        "selected_local_provider": row.get("selected_local_provider") or "",
        "selected_local_model": row.get("selected_local_model") or "",
        "local_runtime_routeable": bool(row.get("local_runtime_routeable", True)),
        "local_runtime_health_status": row.get("local_runtime_health_status") or "",
        "local_runtime_health_reason": row.get("local_runtime_health_reason") or "",
        "spark_vllm_candidate_count": _safe_int(row.get("spark_vllm_candidate_count")),
        "ollama_candidate_count": _safe_int(row.get("ollama_candidate_count")),
        "offline_optimizer_state": row.get("offline_optimizer_state") or "",
        "final_authority_required": bool(row.get("final_authority_required")),
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def build_report(route_policy: dict[str, Any]) -> dict[str, Any]:
    rows = [
        build_row(row)
        for row in route_policy.get("rows") or []
        if isinstance(row, dict)
    ]
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "source_route_policy_schema": route_policy.get("schema"),
        "summary": {
            "skill_count": len(rows),
            "deterministic_bypass_count": sum(
                1 for row in rows if row["deterministic_bypass"]
            ),
            "local_planner_candidate_count": sum(
                1 for row in rows if row["local_planner_candidate"]
            ),
            "local_planner_contract_required_count": sum(
                1 for row in rows if row["local_planner_contract_required"]
            ),
            "spark_vllm_planner_candidate_count": sum(
                1 for row in rows if row["pre_llm_decision"] == "ask_spark_vllm_planner"
            ),
            "ollama_planner_candidate_count": sum(
                1 for row in rows if row["pre_llm_decision"] == "ask_ollama_planner"
            ),
            "cloud_candidate_requires_policy_check_count": sum(
                1 for row in rows if row["cloud_candidate_requires_policy_check"]
            ),
            "pre_llm_decision_counts": _count_by(rows, "pre_llm_decision"),
            "runtime_counts": _count_by(rows, "selected_local_runtime_class"),
        },
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Planner Pre-Route Policy",
        "",
        f"- Dry run only: `{str(report.get('dry_run_only')).lower()}`",
        f"- Model calls executed: `{report.get('model_calls_executed')}`",
        f"- Skills covered: `{summary['skill_count']}`",
        f"- Deterministic bypasses: `{summary['deterministic_bypass_count']}`",
        f"- Local planner candidates: `{summary['local_planner_candidate_count']}`",
        f"- Local planner contracts required: `{summary['local_planner_contract_required_count']}`",
        f"- Spark/vLLM planner candidates: `{summary['spark_vllm_planner_candidate_count']}`",
        f"- Ollama planner candidates: `{summary['ollama_planner_candidate_count']}`",
        f"- Cloud candidates requiring policy check: `{summary['cloud_candidate_requires_policy_check_count']}`",
        "",
        "## Decision Counts",
        "",
    ]
    for decision, count in summary["pre_llm_decision_counts"].items():
        lines.append(f"- `{decision}`: {count}")
    lines.extend(
        [
            "",
            "## Sample Rows",
            "",
            "| Skill | Route | Pre-LLM Decision | Runtime | Reason |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["rows"][:40]:
        lines.append(
            "| {skill} | {route} | {decision} | {runtime} | {reason} |".format(
                skill=row.get("skill_id") or "",
                route=row.get("route_kind") or "",
                decision=row.get("pre_llm_decision") or "",
                runtime=row.get("selected_local_runtime_class") or "-",
                reason=row.get("decision_reason") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-policy-json", type=Path, default=DEFAULT_ROUTE_POLICY_JSON
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(load_json(args.route_policy_json))
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
