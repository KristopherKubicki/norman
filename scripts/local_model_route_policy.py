#!/usr/bin/env python3
"""Build a dry-run local-first route policy from sensed models and skill floors."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.local-model-route-policy.v1"
DEFAULT_SKILL_FLOORS_JSON = Path("tmp/local_model_skill_floors.json")
DEFAULT_SKILL_MATRIX_JSON = Path("tmp/work_domain_skill_matrix.json")
DEFAULT_PRESSURE_GUARD_JSON = Path(
    os.environ.get(
        "NORMAN_TUI_HOST_PRESSURE_GUARD_JSON",
        "/home/kristopher/.local/state/norman/tui-host-pressure-guard.json",
    )
)
DEFAULT_RUNTIME_HEALTH_JSON = Path("tmp/local_runtime_health.json")
DEFAULT_OUTPUT_JSON = Path("tmp/local_model_route_policy.json")
DEFAULT_OUTPUT_MD = Path("tmp/local_model_route_policy.md")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if default is None else default


def _num(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _pct(value: float) -> float:
    return round(value * 100.0, 2)


def _round_usd(value: float) -> float:
    return round(max(0.0, value), 6)


def _matrix_by_skill(skill_matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = skill_matrix.get("rows") if isinstance(skill_matrix, dict) else []
    return {
        str(row.get("skill_id") or ""): row
        for row in rows or []
        if isinstance(row, dict) and str(row.get("skill_id") or "").strip()
    }


def _pressure_admission(pressure_guard: dict[str, Any]) -> dict[str, Any]:
    admission = (
        pressure_guard.get("admission") if isinstance(pressure_guard, dict) else {}
    )
    if not isinstance(admission, dict):
        admission = {}
    return {
        "status": str(pressure_guard.get("status") or "unknown"),
        "action": str(admission.get("action") or "unknown"),
        "reason": str(admission.get("reason") or ""),
    }


def _cloud_heavy_deferred(pressure_guard: dict[str, Any]) -> bool:
    action = _pressure_admission(pressure_guard)["action"]
    return action in {"defer_heavy_work", "block_new_work"}


def _runtime_health_rows(runtime_health: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = runtime_health.get("runtimes") if isinstance(runtime_health, dict) else []
    if not isinstance(rows, list):
        rows = []
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        runtime = str(row.get("runtime_class") or "").strip()
        provider = str(row.get("provider") or "").strip()
        if runtime:
            indexed[f"runtime:{runtime}"] = row
        if provider:
            indexed[f"provider:{provider}"] = row
    return indexed


def _runtime_health_for(
    *,
    runtime_class: str,
    provider: str,
    runtime_health: dict[str, Any],
) -> dict[str, Any]:
    if not runtime_health:
        return {
            "status": "not_checked",
            "routeable": True,
            "reason": "runtime health artifact not supplied",
        }
    rows = _runtime_health_rows(runtime_health)
    health = rows.get(f"runtime:{runtime_class}") or rows.get(f"provider:{provider}")
    if not health:
        return {
            "status": "unknown",
            "routeable": False,
            "reason": "runtime missing from health artifact",
        }
    status = str(health.get("status") or "unknown")
    routeable = bool(health.get("routeable")) and status == "healthy"
    return {
        "status": status,
        "routeable": routeable,
        "reason": str(health.get("reason") or ""),
        "endpoint": str(health.get("endpoint") or ""),
    }


def _route_kind(floor_row: dict[str, Any]) -> tuple[str, str]:
    status = str(floor_row.get("local_floor_status") or "")
    role = str(floor_row.get("allowed_role") or "")
    if status == "local_no_model" or role == "deterministic_only":
        return "deterministic_only", "local_deterministic"
    if status == "local_validator_bounded_final_candidate":
        return "local_first", "local_final_with_validator"
    if status == "local_worker_with_bedrock_5_4_verifier":
        return "local_then_5_4_verifier", "local_worker_cloud_verifier"
    if status == "local_draft_only_final_authority_hold":
        return "local_draft_final_hold", "cloud_final_authority"
    if status == "no_local_candidate":
        return "cloud_only", "cloud_required"
    return "shadow_only", "local_shadow"


def _case_label(floor_row: dict[str, Any]) -> str:
    family = str(floor_row.get("family") or "").strip()
    final_authority = bool(floor_row.get("final_authority_required"))
    if final_authority:
        return "final authority or governed action"
    if family in {"retrieval", "status", "classification"}:
        return "bounded lookup or classification"
    if family in {"code", "runbook", "deployment"}:
        return "draft with tests or verifier"
    if family:
        return f"{family} workflow"
    return "general bounded workflow"


def _network_priority(
    *,
    route_kind: str,
    runtime_class: str,
    provider: str,
    pressure_guard: dict[str, Any],
) -> str:
    if _cloud_heavy_deferred(pressure_guard) and route_kind in {
        "cloud_only",
        "local_draft_final_hold",
    }:
        return "defer_cloud_heavy"
    if route_kind == "deterministic_only":
        return "offline_deterministic"
    if route_kind in {"local_first", "local_then_5_4_verifier"}:
        if runtime_class == "spark_vllm":
            return "offline_spark_vllm_preferred"
        if provider == "ollama":
            return "offline_ollama_fallback"
        return "offline_local_fallback"
    if route_kind == "local_draft_final_hold":
        if runtime_class == "spark_vllm":
            return "spark_vllm_draft_cloud_final"
        if provider == "ollama":
            return "ollama_draft_cloud_final"
    return "cloud_required"


def build_policy_row(
    floor_row: dict[str, Any],
    matrix_row: dict[str, Any],
    *,
    pressure_guard: dict[str, Any],
    runtime_health: dict[str, Any],
) -> dict[str, Any]:
    route_kind, route_role = _route_kind(floor_row)
    selected_runtime_class = str(floor_row.get("selected_local_runtime_class") or "")
    selected_provider = str(floor_row.get("selected_local_provider") or "")
    health = _runtime_health_for(
        runtime_class=selected_runtime_class,
        provider=selected_provider,
        runtime_health=runtime_health,
    )
    local_runtime_routeable = bool(health["routeable"])
    runtime_gate = str(health["status"])
    runtime_gate_reason = str(health["reason"])
    if (
        route_kind in {"local_first", "local_then_5_4_verifier"}
        and not local_runtime_routeable
    ):
        route_kind = "cloud_only"
        route_role = "cloud_required"
    baseline_5_5_cost = _num(matrix_row.get("all_bedrock_5_5_xhigh_cost_usd"))
    baseline_5_4_cost = _num(matrix_row.get("bedrock_5_4_xhigh_cost_usd"))
    recommended_cost = _num(matrix_row.get("recommended_pipeline_cost_usd"))
    verifier_cost = baseline_5_4_cost or recommended_cost
    if route_kind in {"deterministic_only", "local_first"}:
        estimated_cloud_cost = 0.0
        estimated_cloud_cost_vs_5_4 = 0.0
        estimated_cloud_cost_vs_recommended = 0.0
        counted_savings_reason = "local/LAN model replaces cloud model call"
    elif route_kind == "local_then_5_4_verifier":
        estimated_cloud_cost = verifier_cost or recommended_cost
        estimated_cloud_cost_vs_5_4 = estimated_cloud_cost
        estimated_cloud_cost_vs_recommended = estimated_cloud_cost
        counted_savings_reason = (
            "local/LAN worker replaces 5.5 heavy lift; 5.4 verifies"
        )
    elif route_kind == "local_draft_final_hold":
        estimated_cloud_cost = baseline_5_5_cost
        estimated_cloud_cost_vs_5_4 = baseline_5_5_cost
        estimated_cloud_cost_vs_recommended = baseline_5_5_cost
        counted_savings_reason = "not counted; 5.5 final authority still required"
    elif route_kind == "cloud_only":
        estimated_cloud_cost = baseline_5_5_cost
        estimated_cloud_cost_vs_5_4 = baseline_5_4_cost
        estimated_cloud_cost_vs_recommended = recommended_cost
        counted_savings_reason = "not counted; no local candidate"
    else:
        estimated_cloud_cost = baseline_5_5_cost
        estimated_cloud_cost_vs_5_4 = baseline_5_4_cost
        estimated_cloud_cost_vs_recommended = recommended_cost
        counted_savings_reason = "not counted until shadow verifier accepts"
    savings = max(0.0, baseline_5_5_cost - estimated_cloud_cost)
    savings_vs_5_4 = max(0.0, baseline_5_4_cost - estimated_cloud_cost_vs_5_4)
    savings_vs_recommended = max(
        0.0, recommended_cost - estimated_cloud_cost_vs_recommended
    )
    savings_rate = savings / baseline_5_5_cost if baseline_5_5_cost else 0.0
    savings_vs_5_4_rate = (
        savings_vs_5_4 / baseline_5_4_cost if baseline_5_4_cost else 0.0
    )
    savings_vs_recommended_rate = (
        savings_vs_recommended / recommended_cost if recommended_cost else 0.0
    )
    authority_premium_vs_5_4 = max(0.0, estimated_cloud_cost_vs_5_4 - baseline_5_4_cost)
    if (
        route_kind == "cloud_only"
        and selected_runtime_class
        and not local_runtime_routeable
    ):
        network_priority = "local_runtime_unavailable_cloud_required"
    else:
        network_priority = _network_priority(
            route_kind=route_kind,
            runtime_class=selected_runtime_class,
            provider=selected_provider,
            pressure_guard=pressure_guard,
        )
    offline_first_route = route_kind in {
        "deterministic_only",
        "local_first",
        "local_then_5_4_verifier",
    }
    return {
        "skill_id": floor_row.get("skill_id"),
        "domain": floor_row.get("domain"),
        "family": floor_row.get("family"),
        "label": floor_row.get("label"),
        "case": _case_label(floor_row),
        "route_kind": route_kind,
        "route_role": route_role,
        "network_priority": network_priority,
        "offline_first_route": offline_first_route,
        "selected_local_model": floor_row.get("selected_local_model") or "",
        "selected_local_endpoint": floor_row.get("selected_local_endpoint") or "",
        "selected_local_model_family": floor_row.get("selected_local_model_family")
        or "",
        "selected_local_provider": selected_provider,
        "selected_local_runtime_class": selected_runtime_class,
        "local_runtime_routeable": local_runtime_routeable,
        "local_runtime_health_status": runtime_gate,
        "local_runtime_health_reason": runtime_gate_reason,
        "local_runtime_health_endpoint": health.get("endpoint") or "",
        "selected_local_source_schema": floor_row.get("selected_local_source_schema")
        or "",
        "selected_local_endpoint_scope": floor_row.get("selected_local_endpoint_scope")
        or "",
        "spark_vllm_candidate_count": int(
            floor_row.get("spark_vllm_candidate_count") or 0
        ),
        "ollama_candidate_count": int(floor_row.get("ollama_candidate_count") or 0),
        "offline_optimizer_state": floor_row.get("offline_optimizer_state") or "",
        "validator_gate": floor_row.get("validator_gate") or "",
        "final_authority_required": bool(floor_row.get("final_authority_required")),
        "baseline_all_bedrock_5_5_xhigh_cost_usd": _round_usd(baseline_5_5_cost),
        "baseline_all_bedrock_5_4_xhigh_cost_usd": _round_usd(baseline_5_4_cost),
        "baseline_recommended_pipeline_cost_usd": _round_usd(recommended_cost),
        "estimated_policy_cloud_cost_usd": _round_usd(estimated_cloud_cost),
        "estimated_policy_cloud_cost_vs_bedrock_5_4_usd": _round_usd(
            estimated_cloud_cost_vs_5_4
        ),
        "estimated_policy_cloud_cost_vs_recommended_usd": _round_usd(
            estimated_cloud_cost_vs_recommended
        ),
        "estimated_cloud_savings_usd": _round_usd(savings),
        "estimated_cloud_savings_pct": _pct(savings_rate),
        "estimated_cloud_savings_vs_bedrock_5_4_usd": _round_usd(savings_vs_5_4),
        "estimated_cloud_savings_vs_bedrock_5_4_pct": _pct(savings_vs_5_4_rate),
        "estimated_cloud_savings_vs_recommended_usd": _round_usd(
            savings_vs_recommended
        ),
        "estimated_cloud_savings_vs_recommended_pct": _pct(savings_vs_recommended_rate),
        "estimated_5_5_authority_premium_vs_bedrock_5_4_usd": _round_usd(
            authority_premium_vs_5_4
        ),
        "counted_savings_reason": counted_savings_reason,
        "escalate_to_5_4_when": floor_row.get("escalate_to_5_4_when") or [],
        "escalate_to_5_5_when": floor_row.get("escalate_to_5_5_when") or [],
    }


def _sum_by(rows: list[dict[str, Any]], key: str, value_key: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        totals[label] = totals.get(label, 0.0) + _num(row.get(value_key))
    return {key: _round_usd(value) for key, value in sorted(totals.items())}


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def build_report(
    skill_floors: dict[str, Any],
    skill_matrix: dict[str, Any],
    *,
    pressure_guard: dict[str, Any] | None = None,
    runtime_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pressure_guard = pressure_guard or {}
    runtime_health = runtime_health or {}
    matrix_rows = _matrix_by_skill(skill_matrix)
    rows = [
        build_policy_row(
            floor_row,
            matrix_rows.get(str(floor_row.get("skill_id") or ""), {}),
            pressure_guard=pressure_guard,
            runtime_health=runtime_health,
        )
        for floor_row in skill_floors.get("rows") or []
        if isinstance(floor_row, dict)
    ]
    baseline_total = sum(
        _num(row.get("baseline_all_bedrock_5_5_xhigh_cost_usd")) for row in rows
    )
    baseline_5_4_total = sum(
        _num(row.get("baseline_all_bedrock_5_4_xhigh_cost_usd")) for row in rows
    )
    recommended_baseline_total = sum(
        _num(row.get("baseline_recommended_pipeline_cost_usd")) for row in rows
    )
    policy_total = sum(_num(row.get("estimated_policy_cloud_cost_usd")) for row in rows)
    policy_vs_5_4_total = sum(
        _num(row.get("estimated_policy_cloud_cost_vs_bedrock_5_4_usd")) for row in rows
    )
    policy_vs_recommended_total = sum(
        _num(row.get("estimated_policy_cloud_cost_vs_recommended_usd")) for row in rows
    )
    savings_total = sum(_num(row.get("estimated_cloud_savings_usd")) for row in rows)
    savings_vs_5_4_total = sum(
        _num(row.get("estimated_cloud_savings_vs_bedrock_5_4_usd")) for row in rows
    )
    savings_vs_recommended_total = sum(
        _num(row.get("estimated_cloud_savings_vs_recommended_usd")) for row in rows
    )
    authority_premium_vs_5_4_total = sum(
        _num(row.get("estimated_5_5_authority_premium_vs_bedrock_5_4_usd"))
        for row in rows
    )
    top_savings = sorted(
        rows,
        key=lambda row: (
            -_num(row.get("estimated_cloud_savings_usd")),
            str(row.get("skill_id") or ""),
        ),
    )[:12]
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "source_skill_floor_schema": skill_floors.get("schema"),
        "source_skill_matrix_schema": skill_matrix.get("schema"),
        "pressure_admission": _pressure_admission(pressure_guard),
        "summary": {
            "skill_count": len(rows),
            "baseline_all_bedrock_5_5_xhigh_cost_usd": _round_usd(baseline_total),
            "baseline_all_bedrock_5_4_xhigh_cost_usd": _round_usd(baseline_5_4_total),
            "baseline_recommended_pipeline_cost_usd": _round_usd(
                recommended_baseline_total
            ),
            "estimated_policy_cloud_cost_usd": _round_usd(policy_total),
            "estimated_policy_cloud_cost_vs_bedrock_5_4_usd": _round_usd(
                policy_vs_5_4_total
            ),
            "estimated_policy_cloud_cost_vs_recommended_usd": _round_usd(
                policy_vs_recommended_total
            ),
            "estimated_cloud_savings_usd": _round_usd(savings_total),
            "estimated_cloud_savings_pct": _pct(
                savings_total / baseline_total if baseline_total else 0.0
            ),
            "estimated_cloud_savings_vs_bedrock_5_4_usd": _round_usd(
                savings_vs_5_4_total
            ),
            "estimated_cloud_savings_vs_bedrock_5_4_pct": _pct(
                savings_vs_5_4_total / baseline_5_4_total if baseline_5_4_total else 0.0
            ),
            "estimated_cloud_savings_vs_recommended_usd": _round_usd(
                savings_vs_recommended_total
            ),
            "estimated_cloud_savings_vs_recommended_pct": _pct(
                savings_vs_recommended_total / recommended_baseline_total
                if recommended_baseline_total
                else 0.0
            ),
            "estimated_5_5_authority_premium_vs_bedrock_5_4_usd": _round_usd(
                authority_premium_vs_5_4_total
            ),
            "route_counts": _count_by(rows, "route_kind"),
            "network_priority_counts": _count_by(rows, "network_priority"),
            "selected_runtime_counts": _count_by(rows, "selected_local_runtime_class"),
            "selected_provider_counts": _count_by(rows, "selected_local_provider"),
            "offline_optimizer_state_counts": _count_by(
                rows, "offline_optimizer_state"
            ),
            "local_runtime_health_status_counts": _count_by(
                rows, "local_runtime_health_status"
            ),
            "local_runtime_unavailable_count": sum(
                1
                for row in rows
                if row.get("selected_local_runtime_class")
                and not row.get("local_runtime_routeable")
            ),
            "offline_first_route_count": sum(
                1 for row in rows if row.get("offline_first_route")
            ),
            "spark_vllm_route_count": sum(
                1
                for row in rows
                if row.get("selected_local_runtime_class") == "spark_vllm"
                and row.get("local_runtime_routeable")
            ),
            "ollama_fallback_route_count": sum(
                1
                for row in rows
                if row.get("network_priority") == "offline_ollama_fallback"
            ),
            "savings_by_route_kind_usd": _sum_by(
                rows, "route_kind", "estimated_cloud_savings_usd"
            ),
            "savings_vs_bedrock_5_4_by_route_kind_usd": _sum_by(
                rows, "route_kind", "estimated_cloud_savings_vs_bedrock_5_4_usd"
            ),
            "savings_by_domain_usd": _sum_by(
                rows, "domain", "estimated_cloud_savings_usd"
            ),
        },
        "top_savings": top_savings,
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    pressure = report.get("pressure_admission") or {}
    lines = [
        "# Local-First Route Policy",
        "",
        f"- Dry run only: `{str(report.get('dry_run_only')).lower()}`",
        f"- Model calls executed: `{report.get('model_calls_executed')}`",
        f"- Skills covered: `{summary['skill_count']}`",
        f"- Baseline all-Bedrock-5.5-xhigh cost: `${summary['baseline_all_bedrock_5_5_xhigh_cost_usd']:.6f}`",
        f"- Baseline all-Bedrock-5.4-xhigh cost: `${summary['baseline_all_bedrock_5_4_xhigh_cost_usd']:.6f}`",
        f"- Baseline recommended pipeline cost: `${summary['baseline_recommended_pipeline_cost_usd']:.6f}`",
        f"- Estimated policy cloud cost: `${summary['estimated_policy_cloud_cost_usd']:.6f}`",
        f"- Estimated cloud savings vs all-5.5: `${summary['estimated_cloud_savings_usd']:.6f}` ({summary['estimated_cloud_savings_pct']:.2f}%)",
        f"- Estimated cloud savings vs all-5.4: `${summary['estimated_cloud_savings_vs_bedrock_5_4_usd']:.6f}` ({summary['estimated_cloud_savings_vs_bedrock_5_4_pct']:.2f}%)",
        f"- Estimated cloud savings vs recommended: `${summary['estimated_cloud_savings_vs_recommended_usd']:.6f}` ({summary['estimated_cloud_savings_vs_recommended_pct']:.2f}%)",
        f"- Estimated 5.5 authority premium vs all-5.4: `${summary['estimated_5_5_authority_premium_vs_bedrock_5_4_usd']:.6f}`",
        f"- Pressure admission: `{pressure.get('action')}` ({pressure.get('status')})",
        f"- Offline-first routes: `{summary['offline_first_route_count']}`",
        f"- Spark/vLLM routes: `{summary['spark_vllm_route_count']}`",
        f"- Ollama fallback routes: `{summary['ollama_fallback_route_count']}`",
        "",
        "## Route Counts",
        "",
    ]
    for route, count in summary["route_counts"].items():
        lines.append(f"- `{route}`: {count}")
    lines.extend(["", "## Runtime Counts", ""])
    for runtime, count in summary["selected_runtime_counts"].items():
        lines.append(f"- `{runtime}`: {count}")
    lines.extend(["", "## Offline Optimizer States", ""])
    for state, count in summary["offline_optimizer_state_counts"].items():
        lines.append(f"- `{state}`: {count}")
    lines.extend(["", "## Runtime Health", ""])
    for status, count in summary["local_runtime_health_status_counts"].items():
        lines.append(f"- `{status}`: {count}")
    lines.append(
        f"- Local runtime unavailable rows: `{summary['local_runtime_unavailable_count']}`"
    )
    lines.extend(["", "## Why This Saves Money", ""])
    lines.extend(
        [
            "- Local-first validator-bounded work avoids the cloud model call entirely.",
            "- Local-worker plus Bedrock 5.4 verification keeps cloud spend on the cheaper verifier lane instead of 5.5 doing all reasoning.",
            "- Final-authority work can still use local drafts, but savings are not counted until context-shrink evidence proves the 5.5 final pass is smaller.",
            "- Pressure-aware routing can defer cloud-heavy work while still allowing local/status work.",
            "",
            "## Top Savings Cases",
            "",
            "| Skill | Case | Route | Runtime | Local model | Savings | Why |",
            "| --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for row in report.get("top_savings") or []:
        lines.append(
            "| {skill} | {case} | {route} | {runtime} | {model} | ${savings:.6f} | {why} |".format(
                skill=row.get("skill_id") or "",
                case=row.get("case") or "",
                route=row.get("route_kind") or "",
                runtime=row.get("selected_local_runtime_class") or "-",
                model=row.get("selected_local_model") or "",
                savings=_num(row.get("estimated_cloud_savings_usd")),
                why=row.get("counted_savings_reason") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-floors-json", type=Path, default=DEFAULT_SKILL_FLOORS_JSON
    )
    parser.add_argument(
        "--skill-matrix-json", type=Path, default=DEFAULT_SKILL_MATRIX_JSON
    )
    parser.add_argument(
        "--pressure-guard-json", type=Path, default=DEFAULT_PRESSURE_GUARD_JSON
    )
    parser.add_argument(
        "--runtime-health-json", type=Path, default=DEFAULT_RUNTIME_HEALTH_JSON
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        load_json(args.skill_floors_json),
        load_json(args.skill_matrix_json),
        pressure_guard=load_json(args.pressure_guard_json, {}),
        runtime_health=load_json(args.runtime_health_json, {}),
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
