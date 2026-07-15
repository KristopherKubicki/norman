#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.services.codex_role_policy import codex_role_value, load_codex_role_policy
from gaphelp_ticket_loop_shadow import build_report as build_gaphelp_report
from ticket_token_cost_ledger import (
    DEFAULT_LEDGER_JSONL as DEFAULT_TICKET_COST_LEDGER_JSONL,
)
from ticket_token_cost_ledger import estimate_usage_usd, load_records


DEFAULT_ARTIFACT_DIR = Path("/tmp/norman_tui_benchmarks")
DEFAULT_KPI_BENCHMARK_JSON = (
    DEFAULT_ARTIFACT_DIR / "kpis_weekly_model_benchmark_20260611T190439Z.json"
)
DEFAULT_KPI_STATUS_JSON = Path("/tmp/kpis_status_fresh.json")
DEFAULT_SKILL_MATRIX_JSON = DEFAULT_ARTIFACT_DIR / "work_domain_skill_matrix.json"
DEFAULT_CUTOVER_READINESS_JSON = DEFAULT_ARTIFACT_DIR / "tui_cutover_readiness.json"
CODEX_ROLE_POLICY = load_codex_role_policy()
CODEX_CLOUD_DEFAULT_MODEL = codex_role_value(
    "work_standard", "model", policy=CODEX_ROLE_POLICY
)


@dataclass(frozen=True)
class UsageShape:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    duration_seconds: int

    @property
    def billable_output_tokens(self) -> int:
        return self.output_tokens + self.reasoning_output_tokens


@dataclass(frozen=True)
class CostScenario:
    scenario_id: str
    label: str
    input_multiplier: float
    cache_retention: float
    output_multiplier: float
    call_multiplier: float
    duration_multiplier: float
    notes: str


@dataclass(frozen=True)
class ModeSpec:
    mode_id: str
    label: str
    runtime: str
    model: str
    service_tier: str
    optimization_mode: str
    route: str
    price_basis: str
    kind: str
    input_scale_quick: float
    input_scale_deep: float
    output_scale_quick: float
    output_scale_deep: float
    duration_scale_quick: float
    duration_scale_deep: float
    reliability_quick: float
    reliability_deep: float
    notes: str


@dataclass(frozen=True)
class KpiOperation:
    operation_id: str
    label: str
    timebox_minutes: int
    source_shape: str
    notes: str


KPI_OPERATIONS: tuple[KpiOperation, ...] = (
    KpiOperation(
        "kpi_weekly_3_bullet_quick",
        "KPI weekly 3-bullet executive summary",
        5,
        "bedrock_5_5",
        "Operator-facing quick answer. Should stop at 3 bullets with evidence and no broad exploration.",
    ),
    KpiOperation(
        "kpi_weekly_deep_verify",
        "KPI weekly stats with deeper evidence verification",
        30,
        "bedrock_5_5",
        "Evidence-heavy variant. Allows more audit-file inspection and tool calls.",
    ),
)


COST_SCENARIOS: tuple[CostScenario, ...] = (
    CostScenario(
        "observed_rate_card",
        "Observed rate-card",
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        "Uses observed/projected token shape directly. This is the optimistic floor, not the planning number.",
    ),
    CostScenario(
        "expected_guarded",
        "Expected guarded",
        1.20,
        0.80,
        1.15,
        1.15,
        1.25,
        "Adds normal overhead for extra readback, verifier passes, and partial cache misses.",
    ),
    CostScenario(
        "p95_guardrail",
        "P95 guardrail",
        1.65,
        0.35,
        1.50,
        2.00,
        2.00,
        "Conservative planning band for retries, cache misses, longer tool traces, and reruns.",
    ),
)

GAPHELP_POLICY_BANDS: dict[str, tuple[float, float, str]] = {
    "watch_only": (1.0, 1.0, "high"),
    "local_prefilter_hybrid_top": (2.5, 6.0, "medium-low"),
    "cheap_triage_top5": (2.0, 5.0, "medium-low"),
    "cheap_triage_top10": (2.0, 5.0, "medium-low"),
    "full_5_5_all_safe": (1.6, 3.0, "medium"),
    "full_bedrock_5_5_all_safe": (1.6, 3.0, "medium"),
    "batch_replay_all_safe": (1.8, 4.0, "low"),
}


MODE_SPECS: tuple[ModeSpec, ...] = (
    ModeSpec(
        "watch_only",
        "Watch-only status/KPI health",
        "local",
        "none",
        "none",
        "auto",
        "local status/api reads",
        "none",
        "watch",
        0.0,
        0.0,
        0.0,
        0.0,
        0.05,
        0.05,
        0.35,
        0.20,
        "Zero model spend; useful for freshness, not enough to generate the executive summary.",
    ),
    ModeSpec(
        "auto_bedrock_role_default",
        "Auto route -> role-policy cloud default, optimized",
        "codex",
        "openai.gpt-5.4",
        "auto",
        "auto",
        "Auto resolves to Bedrock profile when configured",
        "bedrock-us-east-2",
        "single",
        0.42,
        0.64,
        0.56,
        0.78,
        0.55,
        0.78,
        0.92,
        0.94,
        "Default target for work-special TUIs after the Auto refresh.",
    ),
    ModeSpec(
        "auto_flex_fallback_5_5",
        "Auto route -> Flex fallback, optimized",
        "codex",
        "gpt-5.5",
        "auto",
        "auto",
        "Auto resolves to Flex when Bedrock profile is unavailable",
        "openai-direct-flex",
        "single",
        0.42,
        0.64,
        0.56,
        0.78,
        0.65,
        0.90,
        0.86,
        0.88,
        "Good fallback; cheaper than direct standard, but latency/resource variability remains.",
    ),
    ModeSpec(
        "bedrock_raw_5_5",
        "Bedrock 5.5 raw baseline",
        "codex",
        "openai.gpt-5.5",
        "default",
        "raw",
        "Bedrock Standard",
        "bedrock-us-east-2",
        "single",
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.90,
        0.93,
        "Baseline for before/after tests; disables optional spend optimizations.",
    ),
    ModeSpec(
        "flex_raw_5_5",
        "OpenAI Flex 5.5 raw baseline",
        "codex",
        "gpt-5.5",
        "flex",
        "raw",
        "OpenAI direct Flex",
        "openai-direct-flex",
        "single",
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.82,
        0.86,
        "Real prior KPI run completed, but carried much larger context.",
    ),
    ModeSpec(
        "bedrock_5_4_auto",
        "Bedrock 5.4 optimized",
        "codex",
        "openai.gpt-5.4",
        "default",
        "auto",
        "Bedrock Standard 5.4",
        "bedrock-us-east-2",
        "single",
        0.42,
        0.64,
        0.56,
        0.78,
        0.55,
        0.78,
        0.82,
        0.84,
        "Cheaper than 5.5; prior route requested 5.4 but recorded 5.5, so route proof still needs a strict canary.",
    ),
    ModeSpec(
        "mini_auto_triage",
        "5.4-mini optimized triage/draft",
        "codex",
        "gpt-5.4-mini",
        "flex",
        "auto",
        "OpenAI direct Flex mini",
        "openai-direct-flex",
        "single",
        0.35,
        0.48,
        0.45,
        0.60,
        0.40,
        0.60,
        0.66,
        0.58,
        "Very cheap triage/drafting lane; should not be trusted as final KPI answer without verifier.",
    ),
    ModeSpec(
        "hybrid_auto_bedrock",
        "Hybrid Auto: 5.5 planner/verifier + mini worker",
        "mixed",
        "mixed:gpt-5.5+gpt-5.4-mini",
        "auto",
        "auto",
        "Bedrock 5.4 planner/verifier, Flex mini worker, 5.5 final only if gated",
        "mixed",
        "hybrid",
        0.68,
        0.78,
        0.72,
        0.84,
        0.60,
        0.82,
        0.89,
        0.91,
        "Best shape for cheap repeated work when verifier gates are required.",
    ),
    ModeSpec(
        "claude_bedrock_broker",
        "Claude Bedrock broker",
        "claude",
        "global.anthropic.claude-opus-4-8",
        "default",
        "auto",
        "Bedrock Claude broker",
        "unknown",
        "observed",
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.55,
        0.42,
        "Prior configured Claude KPI run hit the brokered tool budget before final answer.",
    ),
)


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _provider_path_key(price_basis: Any, model: Any) -> str:
    basis = _clean_str(price_basis)
    clean_model = _clean_str(model)
    if (
        not basis
        or basis in {"none", "unknown"}
        or not clean_model
        or clean_model == "mixed"
    ):
        return ""
    return f"{basis}:{clean_model}"


def _record_invoice_reconciled(record: dict[str, Any]) -> bool:
    billing = record.get("billing") if isinstance(record.get("billing"), dict) else {}
    status = _clean_str(billing.get("charge_status")).lower()
    return status in {
        "invoice_reconciled",
        "invoice_matched",
        "actual",
        "actual_charge",
        "reconciled",
    }


def _active_provider_paths(
    kpi_matrix: list[dict[str, Any]], kpi_rows: list[dict[str, Any]]
) -> list[str]:
    active: set[str] = set()
    candidate_modes = {
        _clean_str(row.get("candidate_mode_id"))
        for row in kpi_rows
        if row.get("candidate_mode_id")
    }
    for row in kpi_matrix:
        if _clean_str(row.get("mode_id")) not in candidate_modes:
            continue
        if _clean_str(row.get("mode_id")) == "hybrid_auto_bedrock":
            for line in row.get("cost_lines") or []:
                if not isinstance(line, dict):
                    continue
                key = _provider_path_key(line.get("price_basis"), line.get("model"))
                if key:
                    active.add(key)
            continue
        key = _provider_path_key(row.get("price_basis"), row.get("model"))
        if key:
            active.add(key)
    return sorted(active)


def _cutover_alignment(cutover_readiness: dict[str, Any], path: Path) -> dict[str, Any]:
    if cutover_readiness.get("schema") != "norman.tui-cutover-readiness.v1":
        return {
            "configured": False,
            "path": str(path),
            "readiness": "missing",
            "ready_targets": [],
            "promotion_ready_targets": [],
            "route_receipt_count": 0,
            "wave_1_ready_target_count": 0,
            "promotion_ready_target_count": 0,
            "ready_for_live_default": False,
            "ready_for_broad_optimization": False,
            "blockers": [f"missing or invalid cutover readiness artifact: {path}"],
        }
    summary = (
        cutover_readiness.get("summary")
        if isinstance(cutover_readiness.get("summary"), dict)
        else {}
    )
    ready_targets = [
        str(item)
        for item in cutover_readiness.get("ready_targets") or []
        if str(item or "").strip()
    ]
    promotion_ready_targets = [
        str(item)
        for item in cutover_readiness.get("promotion_ready_targets") or []
        if str(item or "").strip()
    ]
    blockers: list[str] = []
    if not ready_targets:
        blockers.append(
            "no wave-1 route-receipt-backed target is ready for limited cutover"
        )
    return {
        "configured": True,
        "path": str(path),
        "readiness": _clean_str(cutover_readiness.get("readiness")) or "unknown",
        "ready_targets": ready_targets,
        "promotion_ready_targets": promotion_ready_targets,
        "route_receipt_count": _coerce_int(summary.get("receipt_count")),
        "wave_1_ready_target_count": len(ready_targets),
        "promotion_ready_target_count": len(promotion_ready_targets),
        "ready_for_live_default": bool(ready_targets),
        "ready_for_broad_optimization": bool(ready_targets)
        and bool(promotion_ready_targets),
        "blockers": blockers,
    }


def _priority_focus_alignment(
    skill_matrix: dict[str, Any], path: Path
) -> dict[str, Any]:
    if skill_matrix.get("schema") != "norman.work-domain-skill-benchmark.v1":
        return {
            "configured": False,
            "path": str(path),
            "domains": [],
            "owners": [],
            "domain_skill_count": 0,
            "owner_skill_count": 0,
            "ready": False,
            "blockers": [
                f"missing or invalid work-domain skill matrix artifact: {path}"
            ],
        }
    focus = (
        skill_matrix.get("priority_focus")
        if isinstance(skill_matrix.get("priority_focus"), dict)
        else {}
    )
    domains = [
        str(item) for item in focus.get("domains") or [] if str(item or "").strip()
    ]
    owners = [
        str(item) for item in focus.get("owners") or [] if str(item or "").strip()
    ]
    expected_domains = {"control-plane", "runbook-governance", "gold-book"}
    expected_owners = {"control-plane", "gold-book"}
    missing_domains = sorted(expected_domains.difference(domains))
    missing_owners = sorted(expected_owners.difference(owners))
    blockers: list[str] = []
    if missing_domains:
        blockers.append(
            "priority focus is missing domain coverage for "
            + ", ".join(missing_domains)
        )
    if missing_owners:
        blockers.append(
            "priority focus is missing owner coverage for " + ", ".join(missing_owners)
        )
    return {
        "configured": True,
        "path": str(path),
        "domains": domains,
        "owners": owners,
        "domain_skill_count": _coerce_int(focus.get("domain_skill_count")),
        "owner_skill_count": _coerce_int(focus.get("owner_skill_count")),
        "ready": not blockers,
        "blockers": blockers,
    }


def _invoice_reconciliation_summary(
    records: list[dict[str, Any]], active_provider_paths: list[str], path: Path
) -> dict[str, Any]:
    observed_paths: set[str] = set()
    reconciled_paths: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        billing = (
            record.get("billing") if isinstance(record.get("billing"), dict) else {}
        )
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        path_key = _provider_path_key(billing.get("price_basis"), usage.get("model"))
        if not path_key:
            continue
        observed_paths.add(path_key)
        if _record_invoice_reconciled(record):
            reconciled_paths.add(path_key)
    missing_paths = [
        key for key in active_provider_paths if key not in reconciled_paths
    ]
    blockers: list[str] = []
    if not active_provider_paths:
        blockers.append(
            "optimizer active provider paths could not be derived from the current recommendations"
        )
    elif not records:
        blockers.append(
            f"missing ticket cost ledger sample for active provider paths: {path}"
        )
    elif missing_paths:
        blockers.append(
            "invoice-reconciled ledger sample still missing for "
            + ", ".join(missing_paths)
        )
    return {
        "path": str(path),
        "ledger_exists": path.exists(),
        "record_count": len(records),
        "active_provider_paths": active_provider_paths,
        "observed_provider_paths": sorted(observed_paths),
        "invoice_reconciled_provider_paths": sorted(reconciled_paths),
        "missing_invoice_reconciled_provider_paths": missing_paths,
        "ready": not blockers,
        "blockers": blockers,
    }


def _route_proof_summary(observed_checks: list[dict[str, Any]]) -> dict[str, Any]:
    default_aliases = {
        CODEX_CLOUD_DEFAULT_MODEL,
        CODEX_CLOUD_DEFAULT_MODEL.removeprefix("openai."),
    }
    qualifying_passes = [
        row
        for row in observed_checks
        if _clean_str(row.get("effective_runtime")) == "codex"
        and _clean_str(row.get("effective_model")) in default_aliases
        and bool(row.get("did_right_thing"))
    ]
    blockers: list[str] = []
    if not qualifying_passes:
        blockers.append(
            f"no observed codex {CODEX_CLOUD_DEFAULT_MODEL} route-proof KPI pass is recorded yet"
        )
    return {
        "pass_count": len(qualifying_passes),
        "ready": bool(qualifying_passes),
        "blockers": blockers,
    }


def _scale_shape(
    shape: UsageShape, *, input_scale: float, output_scale: float, duration_scale: float
) -> UsageShape:
    return UsageShape(
        input_tokens=max(0, round(shape.input_tokens * input_scale)),
        cached_input_tokens=max(
            0,
            min(
                round(shape.input_tokens * input_scale),
                round(shape.cached_input_tokens * input_scale),
            ),
        ),
        output_tokens=max(0, round(shape.output_tokens * output_scale)),
        reasoning_output_tokens=max(
            0, round(shape.reasoning_output_tokens * output_scale)
        ),
        duration_seconds=max(1, round(shape.duration_seconds * duration_scale)),
    )


def _scenario_shape(shape: UsageShape, scenario: CostScenario) -> UsageShape:
    input_tokens = max(
        0,
        round(
            shape.input_tokens * scenario.input_multiplier * scenario.call_multiplier
        ),
    )
    cached_input_tokens = max(
        0,
        min(
            input_tokens,
            round(
                shape.cached_input_tokens
                * scenario.cache_retention
                * scenario.call_multiplier
            ),
        ),
    )
    return UsageShape(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=max(
            0,
            round(
                shape.output_tokens
                * scenario.output_multiplier
                * scenario.call_multiplier
            ),
        ),
        reasoning_output_tokens=max(
            0,
            round(
                shape.reasoning_output_tokens
                * scenario.output_multiplier
                * scenario.call_multiplier
            ),
        ),
        duration_seconds=max(
            1, round(shape.duration_seconds * scenario.duration_multiplier)
        ),
    )


def _usage_from_run(run: dict[str, Any]) -> UsageShape:
    usage = run.get("usage") if isinstance(run.get("usage"), dict) else {}
    return UsageShape(
        input_tokens=_coerce_int(usage.get("input_tokens")),
        cached_input_tokens=_coerce_int(usage.get("cached_input_tokens")),
        output_tokens=_coerce_int(usage.get("output_tokens")),
        reasoning_output_tokens=_coerce_int(usage.get("reasoning_output_tokens")),
        duration_seconds=_coerce_int(usage.get("duration_seconds")),
    )


def _observed_kpi_shapes(kpi_benchmark: dict[str, Any]) -> dict[str, UsageShape]:
    shapes: dict[str, UsageShape] = {}
    for run in kpi_benchmark.get("runs") or []:
        if not isinstance(run, dict):
            continue
        model = str(run.get("model") or "")
        runtime = str(run.get("runtime") or "")
        service_tier = str(run.get("service_tier") or "")
        run_id = str(run.get("run_id") or "")
        shape = _usage_from_run(run)
        if "codex_bedrock_5_5" in run_id:
            shapes["bedrock_5_5"] = shape
        elif "codex_openai_flex_5_5" in run_id:
            shapes["flex_5_5"] = shape
        elif run_id.endswith("forced-claude"):
            shapes["claude_broker"] = shape
        elif (
            runtime == "codex"
            and model == "openai.gpt-5.4"
            and service_tier == "default"
        ):
            shapes["bedrock_5_4_requested"] = shape
    shapes.setdefault("bedrock_5_5", UsageShape(480_000, 218_000, 5_500, 2_150, 136))
    shapes.setdefault("flex_5_5", UsageShape(1_063_000, 975_000, 9_300, 3_322, 147))
    shapes.setdefault("claude_broker", UsageShape(125_000, 0, 1_800, 0, 37))
    shapes.setdefault("bedrock_5_4_requested", shapes["bedrock_5_5"])
    return shapes


def _estimate_single_cost(
    mode: ModeSpec, shape: UsageShape
) -> tuple[float | None, bool]:
    if mode.price_basis == "unknown":
        return None, False
    if mode.price_basis == "none":
        return 0.0, True
    return estimate_usage_usd(
        model=mode.model,
        price_basis=mode.price_basis,
        input_tokens=shape.input_tokens,
        cached_input_tokens=shape.cached_input_tokens,
        output_tokens=shape.billable_output_tokens,
    )


def _estimate_hybrid_cost(
    shape: UsageShape,
) -> tuple[float | None, bool, list[dict[str, Any]]]:
    fractions = (
        ("planner", "openai.gpt-5.5", "bedrock-us-east-2", 0.18, 0.18),
        ("worker", "gpt-5.4-mini", "openai-direct-flex", 0.38, 0.42),
        ("verifier", "openai.gpt-5.5", "bedrock-us-east-2", 0.12, 0.12),
    )
    total = 0.0
    known = True
    lines: list[dict[str, Any]] = []
    for lane, model, basis, input_fraction, output_fraction in fractions:
        input_tokens = round(shape.input_tokens * input_fraction)
        cached_tokens = round(shape.cached_input_tokens * input_fraction)
        output_tokens = round(shape.billable_output_tokens * output_fraction)
        cost, line_known = estimate_usage_usd(
            model=model,
            price_basis=basis,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
        )
        known = known and line_known and cost is not None
        total += float(cost or 0.0)
        lines.append(
            {
                "lane": lane,
                "model": model,
                "price_basis": basis,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "output_tokens": output_tokens,
                "estimated_usd": cost,
                "cost_known": line_known,
            }
        )
    return round(total, 6), known, lines


def _mode_shape(
    mode: ModeSpec, operation: KpiOperation, shapes: dict[str, UsageShape]
) -> UsageShape:
    if mode.mode_id == "flex_raw_5_5":
        source = shapes["flex_5_5"]
    elif mode.mode_id == "claude_bedrock_broker":
        source = shapes["claude_broker"]
    elif mode.mode_id == "bedrock_5_4_auto":
        source = shapes["bedrock_5_4_requested"]
    else:
        source = shapes[operation.source_shape]
    is_deep = operation.operation_id.endswith("deep_verify")
    return _scale_shape(
        source,
        input_scale=mode.input_scale_deep if is_deep else mode.input_scale_quick,
        output_scale=mode.output_scale_deep if is_deep else mode.output_scale_quick,
        duration_scale=mode.duration_scale_deep
        if is_deep
        else mode.duration_scale_quick,
    )


def _cost_confidence(mode: ModeSpec, cost_known: bool) -> str:
    if mode.mode_id == "watch_only":
        return "high"
    if not cost_known:
        return "unknown"
    if mode.optimization_mode == "raw" and mode.mode_id in {
        "bedrock_raw_5_5",
        "flex_raw_5_5",
    }:
        return "medium-high"
    if mode.kind == "hybrid" or mode.optimization_mode == "auto":
        return "medium-low"
    return "medium"


def _scenario_costs(
    mode: ModeSpec, base_shape: UsageShape
) -> tuple[float | None, bool, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    all_known = True
    primary: float | None = None
    for scenario in COST_SCENARIOS:
        scenario_shape = _scenario_shape(base_shape, scenario)
        cost_lines: list[dict[str, Any]] = []
        if mode.kind == "hybrid":
            cost, known, cost_lines = _estimate_hybrid_cost(scenario_shape)
        else:
            cost, known = _estimate_single_cost(mode, scenario_shape)
        all_known = all_known and known
        if scenario.scenario_id == "expected_guarded":
            primary = cost
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "label": scenario.label,
                "input_tokens": scenario_shape.input_tokens,
                "cached_input_tokens": scenario_shape.cached_input_tokens,
                "output_tokens": scenario_shape.output_tokens,
                "reasoning_output_tokens": scenario_shape.reasoning_output_tokens,
                "billable_output_tokens": scenario_shape.billable_output_tokens,
                "duration_seconds": scenario_shape.duration_seconds,
                "estimated_usd": cost,
                "cost_known": known,
                "cost_lines": cost_lines,
                "notes": scenario.notes,
            }
        )
    return primary, all_known, rows


def _reliability(
    mode: ModeSpec, operation: KpiOperation, shape: UsageShape, cost_known: bool
) -> tuple[float, list[str]]:
    is_deep = operation.operation_id.endswith("deep_verify")
    score = mode.reliability_deep if is_deep else mode.reliability_quick
    notes: list[str] = []
    if mode.mode_id == "watch_only":
        notes.append("cannot produce final executive summary without model")
    if not cost_known and mode.price_basis != "none":
        score -= 0.04
        notes.append("cost unknown in local rate card")
    if shape.duration_seconds > operation.timebox_minutes * 60:
        score -= 0.10
        notes.append("projected runtime exceeds selected timebox")
    if mode.mode_id == "claude_bedrock_broker":
        notes.append("observed brokered tool-budget checkpoint on prior KPI run")
        if is_deep:
            score -= 0.08
    if mode.mode_id == "bedrock_5_4_auto":
        notes.append("prior strict route proof requested 5.4 but recorded 5.5")
    return max(0.0, min(0.99, round(score, 2))), notes


def _observed_kpi_checks(kpi_benchmark: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for run in kpi_benchmark.get("runs") or []:
        if not isinstance(run, dict):
            continue
        usage = run.get("usage") if isinstance(run.get("usage"), dict) else {}
        requested_runtime = str(run.get("runtime") or "")
        requested_model = str(run.get("model") or "")
        requested_tier = str(run.get("service_tier") or "")
        effective_runtime = str(usage.get("runtime") or requested_runtime)
        effective_model = str(usage.get("model") or requested_model)
        effective_tier = str(usage.get("service_tier") or requested_tier)
        route_proven = effective_runtime == requested_runtime and (
            effective_model == requested_model
            or effective_model == requested_model.removeprefix("openai.")
            or effective_model.removeprefix("openai.") == requested_model
        )
        response = str(run.get("response") or "")
        bullet_lines = [
            line for line in response.splitlines() if line.strip().startswith("- ")
        ]
        has_week = "2026-06-01" in response and "2026-06-07" in response
        has_evidence = "Evidence:" in response or "audit/" in response
        blocked = response.strip().startswith("BLOCKED")
        content_pass = bool(
            not blocked and len(bullet_lines) >= 3 and has_week and has_evidence
        )
        checks.append(
            {
                "run_id": run.get("run_id"),
                "runtime": requested_runtime,
                "model": requested_model,
                "service_tier": requested_tier,
                "effective_runtime": effective_runtime,
                "effective_model": effective_model,
                "effective_service_tier": effective_tier,
                "route_proven": route_proven,
                "state": run.get("state"),
                "bullet_count": len(bullet_lines),
                "has_closed_week": has_week,
                "has_evidence": has_evidence,
                "blocked": blocked,
                "content_pass": content_pass,
                "did_right_thing": content_pass and route_proven,
            }
        )
    return checks


def _build_kpi_matrix(
    kpi_benchmark: dict[str, Any], kpi_status: dict[str, Any]
) -> list[dict[str, Any]]:
    shapes = _observed_kpi_shapes(kpi_benchmark)
    rows: list[dict[str, Any]] = []
    for operation in KPI_OPERATIONS:
        for mode in MODE_SPECS:
            shape = _mode_shape(mode, operation, shapes)
            observed_usd, observed_known = (
                _estimate_hybrid_cost(shape)[:2]
                if mode.kind == "hybrid"
                else _estimate_single_cost(mode, shape)
            )
            estimated_usd, cost_known, scenario_estimates = _scenario_costs(mode, shape)
            observed_scenario = next(
                item
                for item in scenario_estimates
                if item["scenario_id"] == "observed_rate_card"
            )
            p95_scenario = next(
                item
                for item in scenario_estimates
                if item["scenario_id"] == "p95_guardrail"
            )
            reliability, reliability_notes = _reliability(
                mode, operation, shape, cost_known
            )
            rows.append(
                {
                    "operation_id": operation.operation_id,
                    "operation": operation.label,
                    "timebox_minutes": operation.timebox_minutes,
                    "mode_id": mode.mode_id,
                    "mode": mode.label,
                    "runtime": mode.runtime,
                    "model": mode.model,
                    "service_tier": mode.service_tier,
                    "optimization_mode": mode.optimization_mode,
                    "route": mode.route,
                    "price_basis": mode.price_basis,
                    "input_tokens": shape.input_tokens,
                    "cached_input_tokens": shape.cached_input_tokens,
                    "output_tokens": shape.output_tokens,
                    "reasoning_output_tokens": shape.reasoning_output_tokens,
                    "billable_output_tokens": shape.billable_output_tokens,
                    "total_tokens": shape.input_tokens
                    + shape.output_tokens
                    + shape.reasoning_output_tokens,
                    "duration_seconds": shape.duration_seconds,
                    "estimated_usd": estimated_usd,
                    "observed_rate_card_usd": observed_usd,
                    "expected_usd": estimated_usd,
                    "p95_usd": p95_scenario["estimated_usd"],
                    "cost_known": cost_known,
                    "observed_cost_known": observed_known
                    and bool(observed_scenario["cost_known"]),
                    "cost_confidence": _cost_confidence(mode, cost_known),
                    "cost_scenario_estimates": scenario_estimates,
                    "reliability_score": reliability,
                    "reliability_notes": reliability_notes,
                    "notes": mode.notes,
                    "cost_lines": observed_scenario["cost_lines"],
                }
            )
    if kpi_status:
        for row in rows:
            if row["mode_id"] == "auto_bedrock_role_default":
                row["live_auto_route_check"] = {
                    "ui_version": kpi_status.get("ui_version"),
                    "default_optimization_mode": kpi_status.get(
                        "default_optimization_mode"
                    ),
                    "default_service_tier": kpi_status.get("default_service_tier"),
                    "auto_option_present": any(
                        item.get("key") == "auto"
                        for item in kpi_status.get("service_tier_options") or []
                        if isinstance(item, dict)
                    ),
                }
    return rows


def _top_rows(
    rows: list[dict[str, Any]], operation_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row["operation_id"] == operation_id and row["mode_id"] != "watch_only"
    ]
    candidates.sort(
        key=lambda row: (
            -float(row["reliability_score"]),
            float(row["estimated_usd"] if row["estimated_usd"] is not None else 999),
            int(row["duration_seconds"]),
        )
    )
    return candidates[:limit]


def _augment_gaphelp_cost_bands(report: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(json.dumps(report))
    for row in data.get("policies") or []:
        policy_id = str(row.get("policy_id") or "")
        expected_multiplier, p95_multiplier, confidence = GAPHELP_POLICY_BANDS.get(
            policy_id, (2.0, 5.0, "low")
        )
        observed = float(row.get("estimated_usd") or 0.0)
        expected = round(observed * expected_multiplier, 6)
        p95 = round(observed * p95_multiplier, 6)
        completed = max(1, _coerce_int(row.get("completed_shadow")))
        row["observed_rate_card_usd"] = observed
        row["expected_usd"] = expected
        row["p95_usd"] = p95
        row["cost_confidence"] = confidence
        row["effective_expected_usd_per_completion"] = (
            0.0
            if _coerce_int(row.get("completed_shadow")) == 0
            else round(expected / completed, 6)
        )
        row["expected_usd_if_hourly"] = round(expected * 24, 6)
        row["p95_usd_if_hourly"] = round(p95 * 24, 6)

    rows_by_policy = {
        str(row.get("policy_id") or ""): row for row in data.get("policies") or []
    }
    for key in ("recommendation", "offline_recommendation"):
        rec = data.get(key)
        if not isinstance(rec, dict):
            continue
        policy_row = rows_by_policy.get(str(rec.get("policy_id") or ""))
        if not policy_row:
            continue
        rec["observed_rate_card_usd"] = policy_row["observed_rate_card_usd"]
        rec["expected_usd"] = policy_row["expected_usd"]
        rec["p95_usd"] = policy_row["p95_usd"]
        rec["cost_confidence"] = policy_row["cost_confidence"]
        rec["effective_expected_usd_per_completion"] = policy_row[
            "effective_expected_usd_per_completion"
        ]
    data["cost_band_notes"] = [
        "observed_rate_card_usd is the deterministic token-rate floor",
        "expected_usd adds overhead for cache misses, retries, verification, and readback",
        "p95_usd is the budget guardrail for changed-ticket loops",
        "steady-state unchanged watch loops remain zero model spend",
    ]
    return data


def _pct_savings(baseline: Any, candidate: Any) -> float | None:
    if baseline is None or candidate is None:
        return None
    baseline_float = float(baseline)
    if baseline_float <= 0:
        return None
    return round((baseline_float - float(candidate)) / baseline_float, 4)


def _ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator is None:
        return None
    denominator_float = float(denominator)
    if denominator_float <= 0:
        return None
    return round(float(numerator) / denominator_float, 4)


def _row_by_mode(
    rows: list[dict[str, Any]], operation_id: str, mode_id: str
) -> dict[str, Any]:
    for row in rows:
        if row["operation_id"] == operation_id and row["mode_id"] == mode_id:
            return row
    return {}


def _policy_by_id(report: dict[str, Any], policy_id: str) -> dict[str, Any]:
    for row in report.get("policies") or []:
        if str(row.get("policy_id") or "") == policy_id:
            return row
    return {}


def _optimizer_efficiency_gate(
    *,
    kpi_matrix: list[dict[str, Any]],
    observed_kpi_checks: list[dict[str, Any]],
    easy_gaphelp: dict[str, Any],
    backlog_gaphelp: dict[str, Any],
    kpi_status: dict[str, Any],
    cutover_alignment: dict[str, Any],
    priority_focus_alignment: dict[str, Any],
    invoice_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    kpi_rows: list[dict[str, Any]] = []
    for operation in KPI_OPERATIONS:
        operation_id = operation.operation_id
        raw = _row_by_mode(kpi_matrix, operation_id, "bedrock_raw_5_5")
        auto = _row_by_mode(kpi_matrix, operation_id, "auto_bedrock_role_default")
        hybrid = _row_by_mode(kpi_matrix, operation_id, "hybrid_auto_bedrock")
        if raw and auto:
            kpi_rows.append(
                {
                    "operation_id": operation_id,
                    "candidate_mode_id": "auto_bedrock_role_default",
                    "baseline_mode_id": "bedrock_raw_5_5",
                    "expected_savings_rate": _pct_savings(
                        raw.get("expected_usd"), auto.get("expected_usd")
                    ),
                    "p95_savings_rate": _pct_savings(
                        raw.get("p95_usd"), auto.get("p95_usd")
                    ),
                    "expected_usd": auto.get("expected_usd"),
                    "baseline_expected_usd": raw.get("expected_usd"),
                    "p95_usd": auto.get("p95_usd"),
                    "baseline_p95_usd": raw.get("p95_usd"),
                    "p95_to_expected_ratio": _ratio(
                        auto.get("p95_usd"), auto.get("expected_usd")
                    ),
                    "reliability_score": auto.get("reliability_score"),
                }
            )
        if raw and hybrid:
            kpi_rows.append(
                {
                    "operation_id": operation_id,
                    "candidate_mode_id": "hybrid_auto_bedrock",
                    "baseline_mode_id": "bedrock_raw_5_5",
                    "expected_savings_rate": _pct_savings(
                        raw.get("expected_usd"), hybrid.get("expected_usd")
                    ),
                    "p95_savings_rate": _pct_savings(
                        raw.get("p95_usd"), hybrid.get("p95_usd")
                    ),
                    "expected_usd": hybrid.get("expected_usd"),
                    "baseline_expected_usd": raw.get("expected_usd"),
                    "p95_usd": hybrid.get("p95_usd"),
                    "baseline_p95_usd": raw.get("p95_usd"),
                    "p95_to_expected_ratio": _ratio(
                        hybrid.get("p95_usd"), hybrid.get("expected_usd")
                    ),
                    "reliability_score": hybrid.get("reliability_score"),
                }
            )

    gaphelp_rows: list[dict[str, Any]] = []
    for label, report in (
        ("interactive", easy_gaphelp),
        ("backlog", backlog_gaphelp),
    ):
        rec = report.get("recommendation") if isinstance(report, dict) else {}
        if not isinstance(rec, dict):
            rec = {}
        baseline = _policy_by_id(report, "full_bedrock_5_5_all_safe") or _policy_by_id(
            report, "full_5_5_all_safe"
        )
        budget_usd = float(report.get("budget_usd") or 0.0)
        gaphelp_rows.append(
            {
                "scope": label,
                "candidate_policy_id": rec.get("policy_id"),
                "baseline_policy_id": baseline.get("policy_id"),
                "completed_shadow": _coerce_int(rec.get("completed_shadow")),
                "expected_usd": rec.get("expected_usd"),
                "baseline_expected_usd": baseline.get("expected_usd"),
                "expected_savings_rate": _pct_savings(
                    baseline.get("expected_usd"), rec.get("expected_usd")
                ),
                "p95_usd": rec.get("p95_usd"),
                "budget_usd": budget_usd,
                "p95_budget_margin_usd": round(
                    budget_usd - float(rec.get("p95_usd") or 0.0), 6
                ),
                "p95_to_budget_ratio": _ratio(rec.get("p95_usd"), budget_usd),
                "p95_to_expected_ratio": _ratio(
                    rec.get("p95_usd"), rec.get("expected_usd")
                ),
            }
        )

    expected_savings_rates = [
        float(row["expected_savings_rate"])
        for row in kpi_rows + gaphelp_rows
        if row.get("expected_savings_rate") is not None
    ]
    p95_budget_overruns = [
        row
        for row in gaphelp_rows
        if row.get("p95_to_budget_ratio") is not None
        and float(row["p95_to_budget_ratio"]) > 1.0
    ]
    auto_default_ready = kpi_status.get(
        "default_optimization_mode"
    ) == "auto" and kpi_status.get("state") in {"ok", "ready", None}
    shadow_ready = bool(expected_savings_rates) and min(expected_savings_rates) > 0
    route_proof = _route_proof_summary(observed_kpi_checks)

    live_default_blockers: list[str] = []
    if not auto_default_ready:
        live_default_blockers.append(
            "live KPI TUI is not currently configured with auto optimization as the default"
        )
    if not shadow_ready:
        live_default_blockers.append(
            "expected savings are not positive across the measured KPI/GAPHELP rows"
        )
    if p95_budget_overruns:
        live_default_blockers.append(
            "at least one recommended GAPHELP policy still exceeds budget at p95"
        )
    live_default_blockers.extend(route_proof.get("blockers") or [])
    live_default_blockers.extend(cutover_alignment.get("blockers") or [])
    live_default_blockers.extend(invoice_reconciliation.get("blockers") or [])
    live_default_ready = not live_default_blockers

    fully_optimized_blockers = list(live_default_blockers)
    if not priority_focus_alignment.get("ready"):
        fully_optimized_blockers.extend(priority_focus_alignment.get("blockers") or [])
    if not cutover_alignment.get("ready_for_broad_optimization"):
        fully_optimized_blockers.append(
            "wave-2 verifier promotion evidence is not ready yet"
        )
    fully_optimized = not fully_optimized_blockers

    if fully_optimized:
        status = "fully_optimized"
    elif live_default_ready:
        status = "live_default_ready"
    elif shadow_ready and p95_budget_overruns:
        status = "shadow_ready_budget_guarded"
    elif shadow_ready:
        status = "shadow_ready_pending_evidence"
    else:
        status = "not_ready"

    risk_register = [
        {
            "risk": "invoice-reconciliation-gap",
            "detail": "Cost estimates still use local rate cards, not invoice-reconciled provider charges.",
            "mitigation": "Append actual usage/cost ledger receipts before expanding live volume.",
        },
        {
            "risk": "verifier-overhead",
            "detail": "Hybrid can erase savings if verifier/readback/retry calls multiply.",
            "mitigation": "Enforce p95 budgets, max retries, and escalation-rate ceilings.",
        },
        {
            "risk": "authority-overreach",
            "detail": "Cheap workers must not own deploy, restart, keys, billing, BBS terminal writes, or live external writes.",
            "mitigation": "Keep 5.5 final authority and explicit approval boundaries.",
        },
    ]
    if p95_budget_overruns:
        risk_register.append(
            {
                "risk": "p95-budget-edge",
                "detail": "At least one recommended policy exceeds its configured budget at p95.",
                "mitigation": "Lower max-do, tighten changed-ticket filter, or require approval when p95 crosses budget.",
            }
        )

    return {
        "schema": "norman.tui.optimizer-efficiency-gate.v1",
        "status": status,
        "fully_optimized": fully_optimized,
        "shadow_ready": shadow_ready,
        "live_default_ready": live_default_ready,
        "auto_default_ready": auto_default_ready,
        "route_proof": route_proof,
        "cutover_alignment": cutover_alignment,
        "priority_focus_alignment": priority_focus_alignment,
        "invoice_reconciliation": invoice_reconciliation,
        "zero_model_watch_loop": {
            "estimated_usd": 0.0,
            "model_calls_executed": 0,
            "covered_moves": [
                "status",
                "queue depth",
                "BBS summary",
                "route inventory",
                "changed-item prefilter",
            ],
        },
        "minimum_expected_savings_rate": round(min(expected_savings_rates), 4)
        if expected_savings_rates
        else None,
        "kpi_savings_rows": kpi_rows,
        "gaphelp_savings_rows": gaphelp_rows,
        "p95_budget_overrun_count": len(p95_budget_overruns),
        "live_default_blockers": live_default_blockers,
        "fully_optimized_blockers": fully_optimized_blockers,
        "risk_register": risk_register,
        "promotion_requirements": [
            "invoice-reconciled ledger sample for each active provider path",
            "paired live canary receipts for each first-wave TUI",
            "zero unapproved authority uses",
            "p95 estimate stays under configured budget or blocks for approval",
            "worker escalation rate stays at or below the configured ceiling",
            "5.4 verifier owns normal acceptance; 5.5 final authority owns high-risk operator-facing decisions",
        ],
        "recommended_architecture": (
            "local no-model prefilter -> bounded cheap worker for changed safe work "
            "-> 5.4/5.5 verifier -> 5.5 authority/final when needed"
        ),
    }


def build_report(
    *,
    kpi_benchmark_json: Path = DEFAULT_KPI_BENCHMARK_JSON,
    kpi_status_json: Path = DEFAULT_KPI_STATUS_JSON,
    skill_matrix_json: Path = DEFAULT_SKILL_MATRIX_JSON,
    cutover_readiness_json: Path = DEFAULT_CUTOVER_READINESS_JSON,
    ticket_cost_ledger_jsonl: Path = DEFAULT_TICKET_COST_LEDGER_JSONL,
    gaphelp_ticket_count: int = 30,
    gaphelp_max_do: int = 5,
    gaphelp_budget_usd: float = 25.0,
    gaphelp_backlog_ticket_count: int = 100,
    gaphelp_backlog_max_do: int = 10,
    gaphelp_backlog_budget_usd: float = 5.0,
) -> dict[str, Any]:
    kpi_benchmark = _safe_json(kpi_benchmark_json)
    kpi_status = _safe_json(kpi_status_json)
    skill_matrix = _safe_json(skill_matrix_json)
    cutover_readiness = _safe_json(cutover_readiness_json)
    ticket_cost_records = load_records(ticket_cost_ledger_jsonl)
    kpi_matrix = _build_kpi_matrix(kpi_benchmark, kpi_status)
    observed_kpi_checks = _observed_kpi_checks(kpi_benchmark)
    easy_gaphelp = _augment_gaphelp_cost_bands(
        build_gaphelp_report(
            ticket_count=gaphelp_ticket_count,
            max_do=gaphelp_max_do,
            budget_usd=gaphelp_budget_usd,
        )
    )
    backlog_gaphelp = _augment_gaphelp_cost_bands(
        build_gaphelp_report(
            ticket_count=gaphelp_backlog_ticket_count,
            max_do=gaphelp_backlog_max_do,
            budget_usd=gaphelp_backlog_budget_usd,
        )
    )
    baseline_kpi_rows: list[dict[str, Any]] = []
    for operation in KPI_OPERATIONS:
        operation_id = operation.operation_id
        raw = _row_by_mode(kpi_matrix, operation_id, "bedrock_raw_5_5")
        auto = _row_by_mode(kpi_matrix, operation_id, "auto_bedrock_role_default")
        hybrid = _row_by_mode(kpi_matrix, operation_id, "hybrid_auto_bedrock")
        if raw and auto:
            baseline_kpi_rows.append(
                {
                    "operation_id": operation_id,
                    "candidate_mode_id": "auto_bedrock_role_default",
                }
            )
        if raw and hybrid:
            baseline_kpi_rows.append(
                {
                    "operation_id": operation_id,
                    "candidate_mode_id": "hybrid_auto_bedrock",
                }
            )
    active_provider_paths = _active_provider_paths(kpi_matrix, baseline_kpi_rows)
    cutover_alignment = _cutover_alignment(cutover_readiness, cutover_readiness_json)
    priority_focus_alignment = _priority_focus_alignment(
        skill_matrix, skill_matrix_json
    )
    invoice_reconciliation = _invoice_reconciliation_summary(
        ticket_cost_records, active_provider_paths, ticket_cost_ledger_jsonl
    )
    optimizer_gate = _optimizer_efficiency_gate(
        kpi_matrix=kpi_matrix,
        observed_kpi_checks=observed_kpi_checks,
        easy_gaphelp=easy_gaphelp,
        backlog_gaphelp=backlog_gaphelp,
        kpi_status=kpi_status,
        cutover_alignment=cutover_alignment,
        priority_focus_alignment=priority_focus_alignment,
        invoice_reconciliation=invoice_reconciliation,
    )
    return {
        "schema": "norman.tui-auto-mode-benchmark.v1",
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "live_writes_executed": 0,
        "sources": {
            "kpi_benchmark_json": str(kpi_benchmark_json),
            "kpi_status_json": str(kpi_status_json) if kpi_status_json.exists() else "",
            "skill_matrix_json": str(skill_matrix_json)
            if skill_matrix_json.exists()
            else "",
            "cutover_readiness_json": str(cutover_readiness_json)
            if cutover_readiness_json.exists()
            else "",
            "ticket_cost_ledger_jsonl": str(ticket_cost_ledger_jsonl)
            if ticket_cost_ledger_jsonl.exists()
            else "",
            "rate_card": "scripts/ticket_token_cost_ledger.py local rate card; not invoice-reconciled",
            "openai_price_source": "https://openai.com/api/pricing/",
            "bedrock_price_source": "https://aws.amazon.com/bedrock/pricing/",
            "rate_card_checked_on": "2026-06-12",
        },
        "cost_scenarios": {item.scenario_id: asdict(item) for item in COST_SCENARIOS},
        "kpi_status": {
            "ui_version": kpi_status.get("ui_version"),
            "state": kpi_status.get("state"),
            "pending": kpi_status.get("pending"),
            "default_service_tier": kpi_status.get("default_service_tier"),
            "default_optimization_mode": kpi_status.get("default_optimization_mode"),
        },
        "observed_kpi_checks": observed_kpi_checks,
        "kpi_matrix": kpi_matrix,
        "kpi_recommendations": {
            operation.operation_id: _top_rows(kpi_matrix, operation.operation_id)
            for operation in KPI_OPERATIONS
        },
        "priority_focus_alignment": priority_focus_alignment,
        "cutover_alignment": cutover_alignment,
        "invoice_reconciliation": invoice_reconciliation,
        "optimizer_efficiency_gate": optimizer_gate,
        "gaphelp_easy": easy_gaphelp,
        "gaphelp_backlog": backlog_gaphelp,
        "summary": {
            "default_live_mode": "auto_bedrock_role_default",
            "best_interactive_ticket_policy": easy_gaphelp["recommendation"],
            "best_backlog_policy": backlog_gaphelp["recommendation"],
            "optimizer_status": optimizer_gate["status"],
            "optimizer_shadow_ready": optimizer_gate["shadow_ready"],
            "optimizer_live_default_ready": optimizer_gate["live_default_ready"],
            "optimizer_fully_optimized": optimizer_gate["fully_optimized"],
            "optimizer_minimum_expected_savings_rate": optimizer_gate[
                "minimum_expected_savings_rate"
            ],
            "optimizer_p95_budget_overrun_count": optimizer_gate[
                "p95_budget_overrun_count"
            ],
            "optimizer_wave_1_ready_target_count": optimizer_gate["cutover_alignment"][
                "wave_1_ready_target_count"
            ],
            "optimizer_wave_2_promotion_ready_target_count": optimizer_gate[
                "cutover_alignment"
            ]["promotion_ready_target_count"],
            "optimizer_invoice_reconciled_provider_path_count": len(
                optimizer_gate["invoice_reconciliation"][
                    "invoice_reconciled_provider_paths"
                ]
            ),
            "watch_loop_cost": 0.0,
            "cost_caveat": "All USD values are local API-rate-card estimates, not invoice-reconciled charges.",
        },
    }


def _money(value: Any) -> str:
    if value is None:
        return "unknown"
    return f"${float(value):.4f}"


def _compact_tokens(value: Any) -> str:
    amount = _coerce_int(value)
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M"
    if amount >= 1000:
        return f"{amount / 1000:.0f}k"
    return str(amount)


def render_markdown(report: dict[str, Any]) -> str:
    optimizer_gate = report["optimizer_efficiency_gate"]
    lines = [
        "# TUI Auto Mode Shadow Benchmark",
        "",
        "Dry-run/shadow only. This report does not call models, update tickets, ACK BBS, deploy, restart, or commit code.",
        "",
        "## Live KPI TUI Check",
        "",
        f"- UI version: `{report['kpi_status'].get('ui_version') or 'unknown'}`",
        f"- State: `{report['kpi_status'].get('state')}`; pending: `{report['kpi_status'].get('pending')}`",
        f"- Default service tier: `{report['kpi_status'].get('default_service_tier')}`",
        f"- Default optimizer: `{report['kpi_status'].get('default_optimization_mode')}`",
        "",
        "## Cost Model",
        "",
        "- `observed` is the deterministic rate-card floor from the captured/projected token shape.",
        "- `expected` is the primary planning estimate with normal cache-miss, retry, verifier, and readback overhead.",
        "- `p95` is the guardrail estimate for reruns, longer traces, and weak cache reuse.",
        "- Reasoning tokens are counted as billable output in these estimates.",
        "- USD values are not invoice-reconciled.",
        "",
        "## Optimizer Efficiency Gate",
        "",
        f"- Status: `{optimizer_gate['status']}`",
        f"- Fully optimized: `{optimizer_gate['fully_optimized']}`",
        f"- Shadow-ready: `{optimizer_gate['shadow_ready']}`; live default ready: `{optimizer_gate['live_default_ready']}`; auto default ready: `{optimizer_gate['auto_default_ready']}`",
        f"- Minimum expected savings across measured rows: {float(optimizer_gate['minimum_expected_savings_rate'] or 0.0):.1%}",
        f"- P95 budget overruns: `{optimizer_gate['p95_budget_overrun_count']}`",
        f"- Route-proof KPI passes: `{optimizer_gate['route_proof']['pass_count']}`",
        f"- Wave-1 cutover-ready targets: `{optimizer_gate['cutover_alignment']['wave_1_ready_target_count']}`; wave-2 promotion-ready targets: `{optimizer_gate['cutover_alignment']['promotion_ready_target_count']}`",
        f"- Invoice-reconciled active provider paths: `{len(optimizer_gate['invoice_reconciliation']['invoice_reconciled_provider_paths'])}` / `{len(optimizer_gate['invoice_reconciliation']['active_provider_paths'])}`",
        f"- Priority-focus coverage ready: `{optimizer_gate['priority_focus_alignment']['ready']}`",
        f"- Recommended architecture: {optimizer_gate['recommended_architecture']}",
        "",
        "### Live Default Blockers",
        "",
    ]
    if optimizer_gate["live_default_blockers"]:
        lines.extend(f"- {item}" for item in optimizer_gate["live_default_blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "### Full Optimization Blockers",
            "",
        ]
    )
    if optimizer_gate["fully_optimized_blockers"]:
        lines.extend(f"- {item}" for item in optimizer_gate["fully_optimized_blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "### Evidence Alignment",
            "",
            f"- Cutover artifact: `{optimizer_gate['cutover_alignment']['path']}` -> `{optimizer_gate['cutover_alignment']['readiness']}`",
            f"- Priority focus artifact: `{optimizer_gate['priority_focus_alignment']['path']}`",
            f"- Ticket cost ledger: `{optimizer_gate['invoice_reconciliation']['path']}`",
            "",
            "### Optimizer Savings Rows",
            "",
            "| Scope | Candidate | Baseline | Expected | Baseline expected | Expected savings | P95 | Guardrail |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in optimizer_gate["kpi_savings_rows"]:
        lines.append(
            "| KPI `{op}` | `{candidate}` | `{baseline}` | {expected} | {base_expected} | {savings} | {p95} | p95/expected `{ratio}` |".format(
                op=row["operation_id"],
                candidate=row["candidate_mode_id"],
                baseline=row["baseline_mode_id"],
                expected=_money(row["expected_usd"]),
                base_expected=_money(row["baseline_expected_usd"]),
                savings="n/a"
                if row["expected_savings_rate"] is None
                else f"{float(row['expected_savings_rate']):.1%}",
                p95=_money(row["p95_usd"]),
                ratio=row["p95_to_expected_ratio"],
            )
        )
    for row in optimizer_gate["gaphelp_savings_rows"]:
        lines.append(
            "| GAPHELP `{scope}` | `{candidate}` | `{baseline}` | {expected} | {base_expected} | {savings} | {p95} | p95/budget `{ratio}` |".format(
                scope=row["scope"],
                candidate=row["candidate_policy_id"],
                baseline=row["baseline_policy_id"],
                expected=_money(row["expected_usd"]),
                base_expected=_money(row["baseline_expected_usd"]),
                savings="n/a"
                if row["expected_savings_rate"] is None
                else f"{float(row['expected_savings_rate']):.1%}",
                p95=_money(row["p95_usd"]),
                ratio=row["p95_to_budget_ratio"],
            )
        )
    lines.extend(
        [
            "",
            "### Optimizer Holds",
            "",
        ]
    )
    for item in optimizer_gate["risk_register"]:
        lines.append(
            f"- `{item['risk']}`: {item['detail']} Mitigation: {item['mitigation']}"
        )
    lines.extend(
        [
            "",
            "## KPI Model/Mode Matrix",
            "",
            "| Operation | Mode | Route | Opt | Tokens | Cached | Out+Rsn | Time | Observed | Expected | P95 | Cost confidence | Reliability | Notes |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|",
        ]
    )
    for row in report["kpi_matrix"]:
        note = "; ".join(row.get("reliability_notes") or []) or str(
            row.get("notes") or ""
        )
        lines.append(
            "| {op} | {mode} | {route} | {opt} | {tokens} | {cached} | {out} | {secs}s | {observed} | {expected} | {p95} | {confidence} | {rel:.0%} | {note} |".format(
                op=row["operation_id"].replace("kpi_weekly_", ""),
                mode=row["mode"],
                route=row["route"],
                opt=row["optimization_mode"],
                tokens=_compact_tokens(row["total_tokens"]),
                cached=_compact_tokens(row["cached_input_tokens"]),
                out=_compact_tokens(row["billable_output_tokens"]),
                secs=row["duration_seconds"],
                observed=_money(row["observed_rate_card_usd"]),
                expected=_money(row["expected_usd"]),
                p95=_money(row["p95_usd"]),
                confidence=row["cost_confidence"],
                rel=float(row["reliability_score"]),
                note=note.replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Observed KPI Answer Checks",
            "",
            "| Run | Requested route | Effective route | State | Bullets | Closed week | Evidence | Route proof | Result |",
            "|---|---|---|---|---:|---|---|---|---|",
        ]
    )
    for row in report["observed_kpi_checks"]:
        lines.append(
            "| {run} | {runtime}/{model}/{tier} | {eruntime}/{emodel}/{etier} | {state} | {bullets} | {week} | {evidence} | {route} | {result} |".format(
                run=row["run_id"],
                runtime=row["runtime"],
                model=row["model"],
                tier=row["service_tier"],
                eruntime=row["effective_runtime"],
                emodel=row["effective_model"],
                etier=row["effective_service_tier"],
                state=row["state"],
                bullets=row["bullet_count"],
                week="yes" if row["has_closed_week"] else "no",
                evidence="yes" if row["has_evidence"] else "no",
                route="yes" if row["route_proven"] else "no",
                result="pass"
                if row["did_right_thing"]
                else (
                    "content pass / route mismatch"
                    if row["content_pass"]
                    else "fail/block"
                ),
            )
        )
    lines.extend(
        [
            "",
            "## GAPHELP Easy Ticket Loop",
            "",
            _gaphelp_board(report["gaphelp_easy"]),
            "",
            "## GAPHELP Backlog Loop",
            "",
            _gaphelp_board(report["gaphelp_backlog"]),
            "",
            "## Recommendation",
            "",
            "- Default live TUI mode should be `Auto` service tier plus `Auto` optimizer.",
            "- Use `Raw` only for baselines and before/after tests.",
            "- Always-on loops should run watch-only at zero model cost, then spend only on changed safe tickets.",
            "- Claude broker needs a larger tool budget or narrower prompt before it is reliable for KPI weekly summaries.",
            "",
            f"Cost caveat: {report['summary']['cost_caveat']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _gaphelp_board(report: dict[str, Any]) -> str:
    lines = [
        f"Tickets `{report['ticket_count']}`, max-do `{report['max_do']}`, budget `${float(report['budget_usd']):.2f}`.",
        "",
        "| Policy | Triaged | Done | Stops | Tokens | Observed | Expected | P95 | Exp. hourly/day | Reliability shape |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    max_do = max(1, _coerce_int(report.get("max_do")))
    for row in report["policies"]:
        stops = _coerce_int(row["approval_stops"]) + _coerce_int(row["blocked_stops"])
        tokens = _coerce_int(row["total_input_tokens"]) + _coerce_int(
            row["total_output_tokens"]
        )
        done = _coerce_int(row["completed_shadow"])
        reliability = done / max_do
        if row["policy_id"] == "watch_only":
            reliability_label = "freshness only"
        elif reliability >= 1:
            reliability_label = "all selected safe work"
        elif reliability > 0:
            reliability_label = f"{reliability:.0%} selected safe work"
        else:
            reliability_label = "no model work"
        policy_label = f"{row['label']} (`{row['policy_id']}`)"
        lines.append(
            "| {label} | {triaged} | {done} | {stops} | {tokens} | {observed} | {expected} | {p95} | {daily} | {rel} |".format(
                label=policy_label,
                triaged=row["triaged"],
                done=done,
                stops=stops,
                tokens=_compact_tokens(tokens),
                observed=_money(row["observed_rate_card_usd"]),
                expected=_money(row["expected_usd"]),
                p95=_money(row["p95_usd"]),
                daily=_money(row["expected_usd_if_hourly"]),
                rel=reliability_label,
            )
        )
    rec = report["recommendation"]
    lines.append("")
    lines.append(
        f"Recommended interactive policy: `{rec['policy_id']}` at {_money(rec['expected_usd'])} expected / {_money(rec['p95_usd'])} p95 for {rec['completed_shadow']} shadow completions."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a TUI Auto/Raw mode shadow benchmark matrix."
    )
    parser.add_argument(
        "--kpi-benchmark-json", type=Path, default=DEFAULT_KPI_BENCHMARK_JSON
    )
    parser.add_argument("--kpi-status-json", type=Path, default=DEFAULT_KPI_STATUS_JSON)
    parser.add_argument(
        "--skill-matrix-json", type=Path, default=DEFAULT_SKILL_MATRIX_JSON
    )
    parser.add_argument(
        "--cutover-readiness-json", type=Path, default=DEFAULT_CUTOVER_READINESS_JSON
    )
    parser.add_argument(
        "--ticket-cost-ledger-jsonl",
        type=Path,
        default=DEFAULT_TICKET_COST_LEDGER_JSONL,
    )
    parser.add_argument("--gaphelp-ticket-count", type=int, default=30)
    parser.add_argument("--gaphelp-max-do", type=int, default=5)
    parser.add_argument("--gaphelp-budget-usd", type=float, default=25.0)
    parser.add_argument("--gaphelp-backlog-ticket-count", type=int, default=100)
    parser.add_argument("--gaphelp-backlog-max-do", type=int, default=10)
    parser.add_argument("--gaphelp-backlog-budget-usd", type=float, default=5.0)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_ARTIFACT_DIR / "tui_auto_mode_benchmark.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=DEFAULT_ARTIFACT_DIR / "tui_auto_mode_benchmark.md",
    )
    parser.add_argument("--print-md", action="store_true")
    args = parser.parse_args()

    report = build_report(
        kpi_benchmark_json=args.kpi_benchmark_json,
        kpi_status_json=args.kpi_status_json,
        skill_matrix_json=args.skill_matrix_json,
        cutover_readiness_json=args.cutover_readiness_json,
        ticket_cost_ledger_jsonl=args.ticket_cost_ledger_jsonl,
        gaphelp_ticket_count=args.gaphelp_ticket_count,
        gaphelp_max_do=args.gaphelp_max_do,
        gaphelp_budget_usd=args.gaphelp_budget_usd,
        gaphelp_backlog_ticket_count=args.gaphelp_backlog_ticket_count,
        gaphelp_backlog_max_do=args.gaphelp_backlog_max_do,
        gaphelp_backlog_budget_usd=args.gaphelp_backlog_budget_usd,
    )
    markdown = render_markdown(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.print_md:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
