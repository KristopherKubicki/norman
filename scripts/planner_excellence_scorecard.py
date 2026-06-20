#!/usr/bin/env python3
"""Score planner quality across safety, timing, spend, and local routing."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.planner-excellence-scorecard.v1"
DEFAULT_GUARDRAIL_JSON = Path("tmp/planner_guardrail_dashboard.json")
DEFAULT_PREROUTE_JSON = Path("tmp/planner_preroute_policy.json")
DEFAULT_TIME_CONTRACT_JSON = Path("tmp/planner_time_contract_benchmark.json")
DEFAULT_ROUTE_POLICY_JSON = Path("tmp/local_model_route_policy.json")
DEFAULT_OUTPUT_JSON = Path("tmp/planner_excellence_scorecard.json")
DEFAULT_OUTPUT_MD = Path("tmp/planner_excellence_scorecard.md")


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


def _signal_count(report: dict[str, Any], code: str) -> int:
    total = 0
    for signal in report.get("signals") or []:
        if isinstance(signal, dict) and signal.get("code") == code:
            total += _count(signal, "count")
    return total


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _status(score: int, *, fail: bool = False, warn: bool = False) -> str:
    if fail:
        return "fail"
    if warn or score < 85:
        return "watch"
    return "strong"


def _dimension(
    name: str,
    *,
    score: int,
    status: str,
    evidence: dict[str, Any],
    next_action: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "score": score,
        "status": status,
        "evidence": evidence,
        "next_action": next_action,
    }


def build_report(
    *,
    guardrail: dict[str, Any],
    preroute: dict[str, Any],
    time_contract: dict[str, Any],
    route_policy: dict[str, Any],
) -> dict[str, Any]:
    guardrail_summary = _summary(guardrail)
    preroute_summary = _summary(preroute)
    time_summary = _summary(time_contract)
    route_summary = _summary(route_policy)

    block_count = _count(guardrail_summary, "block_count")
    warn_count = _count(guardrail_summary, "warn_count")
    safety_score = _clamp_score(100 - block_count * 35 - warn_count * 6)

    policy_fail_count = _count(time_summary, "policy_case_fail_count")
    history_violations = sum(
        _count(time_summary.get("history_violation_counts") or {}, key)
        for key in (time_summary.get("history_violation_counts") or {})
    )
    time_gate_failed = str(time_summary.get("gate") or "") == "fail"
    timing_score = _clamp_score(100 - policy_fail_count * 35 - history_violations * 20)

    skill_count = _count(preroute_summary, "skill_count")
    deterministic_count = _count(preroute_summary, "deterministic_bypass_count")
    local_planner_count = _count(preroute_summary, "local_planner_candidate_count")
    spark_count = _count(preroute_summary, "spark_vllm_planner_candidate_count")
    ollama_count = _count(preroute_summary, "ollama_planner_candidate_count")
    local_or_deterministic = deterministic_count + local_planner_count
    local_share = _ratio(local_or_deterministic, skill_count)
    spark_share = _ratio(spark_count, max(1, spark_count + ollama_count))
    offline_score = _clamp_score(local_share * 75 + spark_share * 25)

    cloud_policy_count = _count(
        preroute_summary, "cloud_candidate_requires_policy_check_count"
    )
    covered_routes = local_or_deterministic + cloud_policy_count
    policy_coverage = _ratio(covered_routes, skill_count)
    spend_score = _clamp_score(policy_coverage * 100)

    route_drift_count = max(
        _count(route_summary, "route_drift_count"),
        _signal_count(guardrail, "route_drift"),
    )
    spark_route_count = _count(route_summary, "spark_vllm_route_count")
    ollama_fallback_count = _count(route_summary, "ollama_fallback_route_count")
    route_score = _clamp_score(
        100
        - route_drift_count * 15
        - (20 if spark_route_count == 0 and ollama_fallback_count else 0)
    )

    dimensions = [
        _dimension(
            "safety",
            score=safety_score,
            status=_status(safety_score, fail=block_count > 0, warn=warn_count > 0),
            evidence={"block_count": block_count, "warn_count": warn_count},
            next_action="Clear block signals before promotion; burn down warning queues next.",
        ),
        _dimension(
            "timing_contract",
            score=timing_score,
            status=_status(
                timing_score,
                fail=time_gate_failed or policy_fail_count > 0,
                warn=history_violations > 0,
            ),
            evidence={
                "time_gate": time_summary.get("gate"),
                "policy_case_fail_count": policy_fail_count,
                "history_violation_count": history_violations,
            },
            next_action="Convert timing misses into policy cases and require checkpoint use on overruns.",
        ),
        _dimension(
            "offline_first",
            score=offline_score,
            status=_status(offline_score, warn=spark_count == 0 and ollama_count > 0),
            evidence={
                "skill_count": skill_count,
                "deterministic_bypass_count": deterministic_count,
                "local_planner_candidate_count": local_planner_count,
                "spark_vllm_planner_candidate_count": spark_count,
                "ollama_planner_candidate_count": ollama_count,
            },
            next_action="Push eligible planner work to Spark/vLLM first, with Ollama as fallback.",
        ),
        _dimension(
            "spend_control",
            score=spend_score,
            status=_status(
                spend_score, warn=cloud_policy_count > local_or_deterministic
            ),
            evidence={
                "skill_count": skill_count,
                "covered_route_count": covered_routes,
                "cloud_candidate_requires_policy_check_count": cloud_policy_count,
            },
            next_action="Keep every cloud candidate behind deterministic policy and explicit spend bounds.",
        ),
        _dimension(
            "route_stability",
            score=route_score,
            status=_status(
                route_score, warn=route_drift_count > 0 or spark_route_count == 0
            ),
            evidence={
                "route_drift_count": route_drift_count,
                "spark_vllm_route_count": spark_route_count,
                "ollama_fallback_route_count": ollama_fallback_count,
            },
            next_action="Use route receipts to close drift and restore Spark/vLLM as the preferred local lane.",
        ),
    ]

    overall_score = _clamp_score(
        sum(dimension["score"] for dimension in dimensions) / len(dimensions)
    )
    failed_dimensions = [
        dimension["name"] for dimension in dimensions if dimension["status"] == "fail"
    ]
    watch_dimensions = [
        dimension["name"] for dimension in dimensions if dimension["status"] == "watch"
    ]
    gate = "fail" if failed_dimensions else "pass"
    if gate == "pass" and watch_dimensions:
        maturity = "improving"
    elif overall_score >= 95:
        maturity = "spectacular_candidate"
    elif overall_score >= 85:
        maturity = "strong"
    else:
        maturity = "developing"

    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "source_schemas": {
            "guardrail": guardrail.get("schema"),
            "preroute": preroute.get("schema"),
            "time_contract": time_contract.get("schema"),
            "route_policy": route_policy.get("schema"),
        },
        "summary": {
            "overall_score": overall_score,
            "gate": gate,
            "maturity": maturity,
            "dimension_count": len(dimensions),
            "failed_dimension_count": len(failed_dimensions),
            "watch_dimension_count": len(watch_dimensions),
            "failed_dimensions": failed_dimensions,
            "watch_dimensions": watch_dimensions,
        },
        "dimensions": dimensions,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Planner Excellence Scorecard",
        "",
        f"- Dry run only: `{str(report.get('dry_run_only')).lower()}`",
        f"- Model calls executed: `{report.get('model_calls_executed')}`",
        f"- Overall score: `{summary['overall_score']}`",
        f"- Gate: `{summary['gate']}`",
        f"- Maturity: `{summary['maturity']}`",
        f"- Watch dimensions: `{summary['watch_dimension_count']}`",
        f"- Failed dimensions: `{summary['failed_dimension_count']}`",
        "",
        "| Dimension | Status | Score | Next action |",
        "| --- | --- | ---: | --- |",
    ]
    for dimension in report.get("dimensions") or []:
        lines.append(
            "| {name} | `{status}` | {score} | {next_action} |".format(
                name=dimension.get("name") or "",
                status=dimension.get("status") or "",
                score=dimension.get("score") or 0,
                next_action=dimension.get("next_action") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guardrail-json", type=Path, default=DEFAULT_GUARDRAIL_JSON)
    parser.add_argument("--preroute-json", type=Path, default=DEFAULT_PREROUTE_JSON)
    parser.add_argument(
        "--time-contract-json", type=Path, default=DEFAULT_TIME_CONTRACT_JSON
    )
    parser.add_argument(
        "--route-policy-json", type=Path, default=DEFAULT_ROUTE_POLICY_JSON
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        guardrail=load_optional_json(args.guardrail_json),
        preroute=load_optional_json(args.preroute_json),
        time_contract=load_optional_json(args.time_contract_json),
        route_policy=load_optional_json(args.route_policy_json),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
