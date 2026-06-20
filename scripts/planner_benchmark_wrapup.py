#!/usr/bin/env python3
"""Summarize planner, optimizer, and offline-readiness benchmark state."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.planner-benchmark-wrapup.v1"
DEFAULT_SCORECARD_JSON = Path(
    "/tmp/norman_tui_benchmarks/planner_excellence_scorecard.json"
)
DEFAULT_PREROUTE_JSON = Path("/tmp/norman_tui_benchmarks/planner_preroute_policy.json")
DEFAULT_ROUTE_POLICY_JSON = Path(
    "/tmp/norman_tui_benchmarks/local_model_route_policy.json"
)
DEFAULT_RUNTIME_HEALTH_JSON = Path(
    "/tmp/norman_tui_benchmarks/local_runtime_health.json"
)
DEFAULT_SKILL_MATRIX_JSON = Path(
    "/tmp/norman_tui_benchmarks/work_domain_skill_matrix.json"
)
DEFAULT_LLM_SCORE_JSON = Path(
    "/tmp/norman_tui_benchmarks/planner_llm_benchmark_score.json"
)
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/planner_benchmark_wrapup.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/planner_benchmark_wrapup.md")


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report, dict) else {}
    return summary if isinstance(summary, dict) else {}


def _int(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _float(summary: dict[str, Any], key: str) -> float:
    try:
        return float(summary.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: float) -> float:
    return round(max(0.0, value), 6)


def _readiness_status(*, ready: bool, blockers: list[str]) -> str:
    if ready:
        return "ready"
    if blockers:
        return "blocked"
    return "watch"


def build_report(
    *,
    scorecard: dict[str, Any],
    preroute: dict[str, Any] | None = None,
    route_policy: dict[str, Any],
    runtime_health: dict[str, Any],
    skill_matrix: dict[str, Any],
    llm_score: dict[str, Any],
) -> dict[str, Any]:
    scorecard_summary = _summary(scorecard)
    preroute_summary = _summary(preroute or {})
    route_summary = _summary(route_policy)
    runtime_summary = _summary(runtime_health)
    skill_summary = _summary(skill_matrix)
    llm_summary = _summary(llm_score)

    planner_gate = str(scorecard_summary.get("gate") or "unknown")
    planner_score = _int(scorecard_summary, "overall_score")
    planner_watch_count = _int(scorecard_summary, "watch_dimension_count")
    planner_ready = planner_gate == "pass" and planner_watch_count == 0
    planner_state = (
        "strong"
        if planner_ready
        else str(scorecard_summary.get("maturity") or "unknown")
    )

    healthy_runtime_count = _int(runtime_summary, "healthy_runtime_count")
    spark_route_count = _int(route_summary, "spark_vllm_route_count")
    ollama_route_count = _int(route_summary, "ollama_fallback_route_count")
    deterministic_count = _int(route_summary, "offline_first_route_count")
    local_promoted_role_count = _int(llm_summary, "local_promoted_role_count")
    llm_score_gate = str(llm_summary.get("gate") or "unknown")

    offline_blockers = []
    if healthy_runtime_count <= 0:
        offline_blockers.append("no_healthy_local_runtime")
    if spark_route_count <= 0 and ollama_route_count <= 0:
        offline_blockers.append("no_routeable_local_llm")
    if llm_score_gate != "pass" or local_promoted_role_count <= 0:
        offline_blockers.append("no_passing_local_promotion_record")

    more_live_offline_ready = not offline_blockers
    personal_offline_ready = more_live_offline_ready
    work_offline_ready = more_live_offline_ready and planner_ready

    recommended_pipeline = _float(
        skill_summary, "recommended_bedrock_pipeline_total_usd"
    )
    openai_frontier = _float(skill_summary, "openai_frontier_fast_xhigh_total_usd")
    spark_guarded = _float(skill_summary, "spark_guarded_pipeline_total_usd")
    current_policy_savings = _float(route_summary, "estimated_cloud_savings_usd")
    spark_modeled_savings = _float(
        skill_summary, "spark_savings_vs_current_recommended_usd"
    )
    bedrock_vs_openai_savings = _money(openai_frontier - recommended_pipeline)

    route_counts = route_summary.get("route_counts") or {}
    cloud_policy_count = max(
        _int(preroute_summary, "cloud_candidate_requires_policy_check_count"),
        _int(route_summary, "cloud_candidate_requires_policy_check_count"),
        _int(route_counts, "cloud_only"),
    )
    routed_skill_count = max(
        _int(preroute_summary, "skill_count"), _int(route_summary, "skill_count")
    )
    optimizer_ready = planner_gate == "pass" and (
        cloud_policy_count > 0 or routed_skill_count > 0
    )
    optimizer_state = "guarded_cloud_policy_ready" if optimizer_ready else "not_ready"

    next_actions = []
    if "no_healthy_local_runtime" in offline_blockers:
        next_actions.append(
            "Bring one Ollama or Spark/vLLM runtime to healthy status and regenerate local_runtime_health."
        )
    if "no_passing_local_promotion_record" in offline_blockers:
        next_actions.append(
            "Have Uplink fill planner_llm_benchmark_answers.json, then run planner_llm_benchmark_score."
        )
    if planner_watch_count:
        next_actions.append(
            "Burn down planner watch dimensions before raising local authority."
        )

    summary = {
        "planner_state": planner_state,
        "planner_gate": planner_gate,
        "planner_score": planner_score,
        "planner_watch_dimension_count": planner_watch_count,
        "optimizer_state": optimizer_state,
        "more_live_offline_ready": more_live_offline_ready,
        "personal_offline_ready": personal_offline_ready,
        "work_offline_ready": work_offline_ready,
        "offline_readiness_status": _readiness_status(
            ready=more_live_offline_ready, blockers=offline_blockers
        ),
        "offline_blockers": offline_blockers,
        "deterministic_offline_route_count": deterministic_count,
        "spark_vllm_route_count": spark_route_count,
        "ollama_route_count": ollama_route_count,
        "healthy_runtime_count": healthy_runtime_count,
        "local_promoted_role_count": local_promoted_role_count,
        "current_policy_savings_usd": _money(current_policy_savings),
        "modeled_spark_savings_vs_recommended_usd": _money(spark_modeled_savings),
        "modeled_bedrock_vs_openai_frontier_savings_usd": bedrock_vs_openai_savings,
        "recommended_pipeline_cost_usd": _money(recommended_pipeline),
        "openai_frontier_baseline_cost_usd": _money(openai_frontier),
        "spark_guarded_pipeline_cost_usd": _money(spark_guarded),
        "next_action_count": len(next_actions),
    }

    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "source_schemas": {
            "scorecard": scorecard.get("schema"),
            "preroute": (preroute or {}).get("schema"),
            "route_policy": route_policy.get("schema"),
            "runtime_health": runtime_health.get("schema"),
            "skill_matrix": skill_matrix.get("schema"),
            "llm_score": llm_score.get("schema"),
        },
        "summary": summary,
        "next_actions": next_actions,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Planner Benchmark Wrap-Up",
        "",
        f"- Planner: `{summary['planner_state']}` "
        f"score `{summary['planner_score']}` gate `{summary['planner_gate']}`",
        f"- Optimizer: `{summary['optimizer_state']}`",
        f"- More live offline ready: `{str(summary['more_live_offline_ready']).lower()}`",
        f"- Personal offline ready: `{str(summary['personal_offline_ready']).lower()}`",
        f"- Work offline ready: `{str(summary['work_offline_ready']).lower()}`",
        f"- Offline blockers: `{', '.join(summary['offline_blockers']) or 'none'}`",
        f"- Healthy local runtimes: `{summary['healthy_runtime_count']}`",
        f"- Spark/vLLM routes: `{summary['spark_vllm_route_count']}`",
        f"- Ollama routes: `{summary['ollama_route_count']}`",
        f"- Local promoted roles: `{summary['local_promoted_role_count']}`",
        "",
        "## Savings Evidence",
        "",
        f"- Current policy savings: `${summary['current_policy_savings_usd']:.6f}`",
        f"- Modeled Spark savings vs recommended pipeline: `${summary['modeled_spark_savings_vs_recommended_usd']:.6f}`",
        f"- Modeled Bedrock-vs-OpenAI frontier savings: `${summary['modeled_bedrock_vs_openai_frontier_savings_usd']:.6f}`",
        "",
        "## Next Actions",
        "",
    ]
    for action in report.get("next_actions") or []:
        lines.append(f"- {action}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorecard-json", type=Path, default=DEFAULT_SCORECARD_JSON)
    parser.add_argument(
        "--route-policy-json", type=Path, default=DEFAULT_ROUTE_POLICY_JSON
    )
    parser.add_argument("--preroute-json", type=Path, default=DEFAULT_PREROUTE_JSON)
    parser.add_argument(
        "--runtime-health-json", type=Path, default=DEFAULT_RUNTIME_HEALTH_JSON
    )
    parser.add_argument(
        "--skill-matrix-json", type=Path, default=DEFAULT_SKILL_MATRIX_JSON
    )
    parser.add_argument("--llm-score-json", type=Path, default=DEFAULT_LLM_SCORE_JSON)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        scorecard=load_optional_json(args.scorecard_json),
        preroute=load_optional_json(args.preroute_json),
        route_policy=load_optional_json(args.route_policy_json),
        runtime_health=load_optional_json(args.runtime_health_json),
        skill_matrix=load_optional_json(args.skill_matrix_json),
        llm_score=load_optional_json(args.llm_score_json),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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
