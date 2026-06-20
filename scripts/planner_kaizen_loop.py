#!/usr/bin/env python3
"""Convert planner scorecard gaps into a measured kaizen improvement loop."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.planner-kaizen-loop.v1"
DEFAULT_SCORECARD_JSON = Path("tmp/planner_excellence_scorecard.json")
DEFAULT_OUTPUT_JSON = Path("tmp/planner_kaizen_loop.json")
DEFAULT_OUTPUT_MD = Path("tmp/planner_kaizen_loop.md")


DIMENSION_EXPERIMENTS: dict[str, dict[str, str]] = {
    "safety": {
        "title": "Burn down planner warning signals without hiding risk.",
        "hypothesis": "If warnings are converted into finite owner/action pairs, safety score improves without weakening block gates.",
        "success_metric": "block_count remains 0 and warn_count falls to 1 or less.",
        "next_action": "Classify each guardrail warning as fix, observe, or accepted-risk with evidence.",
    },
    "timing_contract": {
        "title": "Turn timing misses into permanent regression cases.",
        "hypothesis": "If every timing surprise becomes a policy case, the planner will stop returning too early or running too long.",
        "success_metric": "time gate stays pass and history_violation_count stays 0 across the latest 50 turns.",
        "next_action": "Promote any history timing violation into a synthetic policy case.",
    },
    "offline_first": {
        "title": "Restore Spark/vLLM as the preferred local planner lane.",
        "hypothesis": "If Spark/vLLM health is restored and selected before Ollama fallback, local quality rises without cloud spend.",
        "success_metric": "Spark/vLLM planner candidate count is greater than 0 and offline_first score reaches 50+.",
        "next_action": "Fix vLLM availability, then rerun local model floor and route policy benchmarks.",
    },
    "spend_control": {
        "title": "Reduce cloud policy queue by adding deterministic and local routes.",
        "hypothesis": "If repeated cloud candidates are mined into deterministic or local-safe patterns, spend falls without reducing final quality.",
        "success_metric": "cloud_candidate_requires_policy_check_count decreases while scorecard gate remains pass.",
        "next_action": "Cluster cloud candidates by domain and convert safe repeats into deterministic/local route rows.",
    },
    "route_stability": {
        "title": "Close route drift using route receipts.",
        "hypothesis": "If actual receipts are compared against intended lanes each run, drift can be fixed before promotion.",
        "success_metric": "route_drift_count reaches 0 and Spark/vLLM route count is non-zero when local service is healthy.",
        "next_action": "Inspect route drift receipts, then update route policy or receipt capture rules.",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _score(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _priority(status: str, score: int) -> str:
    if status == "fail":
        return "blocker"
    if score < 50:
        return "high"
    if score < 85:
        return "medium"
    return "low"


def _dimension_map(scorecard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dimensions = scorecard.get("dimensions") if isinstance(scorecard, dict) else []
    return {
        str(dimension.get("name")): dimension
        for dimension in dimensions or []
        if isinstance(dimension, dict) and dimension.get("name")
    }


def build_report(scorecard: dict[str, Any]) -> dict[str, Any]:
    scorecard_summary = scorecard.get("summary") or {}
    dimensions = _dimension_map(scorecard)
    experiments: list[dict[str, Any]] = []

    for name, dimension in dimensions.items():
        status = str(dimension.get("status") or "")
        score = _score(dimension.get("score"))
        if status not in {"watch", "fail"}:
            continue
        template = DIMENSION_EXPERIMENTS.get(name)
        if not template:
            continue
        experiments.append(
            {
                "id": f"planner-kaizen-{name}",
                "dimension": name,
                "priority": _priority(status, score),
                "status": "planned",
                "current_score": score,
                "current_status": status,
                "title": template["title"],
                "hypothesis": template["hypothesis"],
                "success_metric": template["success_metric"],
                "next_action": template["next_action"],
                "evidence": dimension.get("evidence") or {},
                "pdca": {
                    "plan": template["hypothesis"],
                    "do": template["next_action"],
                    "check": template["success_metric"],
                    "act": "Keep the change only if the next scorecard improves without creating failed dimensions.",
                },
            }
        )

    priority_counts: dict[str, int] = {}
    for experiment in experiments:
        priority = str(experiment["priority"])
        priority_counts[priority] = priority_counts.get(priority, 0) + 1

    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "source_scorecard_schema": scorecard.get("schema"),
        "source_scorecard_summary": scorecard_summary,
        "summary": {
            "experiment_count": len(experiments),
            "blocker_experiment_count": priority_counts.get("blocker", 0),
            "high_priority_experiment_count": priority_counts.get("high", 0),
            "medium_priority_experiment_count": priority_counts.get("medium", 0),
            "low_priority_experiment_count": priority_counts.get("low", 0),
            "kaizen_active": bool(experiments),
            "gate": "fail" if priority_counts.get("blocker", 0) else "pass",
        },
        "experiments": experiments,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Planner Kaizen Loop",
        "",
        f"- Dry run only: `{str(report.get('dry_run_only')).lower()}`",
        f"- Model calls executed: `{report.get('model_calls_executed')}`",
        f"- Experiments: `{summary['experiment_count']}`",
        f"- High priority: `{summary['high_priority_experiment_count']}`",
        f"- Gate: `{summary['gate']}`",
        "",
        "| Priority | Dimension | Score | Experiment | Success metric |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for experiment in report.get("experiments") or []:
        lines.append(
            "| {priority} | `{dimension}` | {score} | {title} | {metric} |".format(
                priority=experiment.get("priority") or "",
                dimension=experiment.get("dimension") or "",
                score=experiment.get("current_score") or 0,
                title=experiment.get("title") or "",
                metric=experiment.get("success_metric") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorecard-json", type=Path, default=DEFAULT_SCORECARD_JSON)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(load_json(args.scorecard_json))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
