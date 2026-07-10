from __future__ import annotations

import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

SPECIALIST_LANE_REGISTRY_SCHEMA = "norman.norllama.specialist-lanes.v1"
SPECIALIST_CASCADE_SCHEMA = "norman.norllama.specialist-cascade.v1"
SPECIALIST_OUTPUT_SCHEMA = "norman.norllama.specialist-output.v1"
SPECIALIST_PROOF_SCHEMA = "norman.norllama.specialist-proof.v1"

ALLOWED_SPECIALIST_STATES = {"production", "lab", "aspirational"}
USAGE_BUCKETS = (
    "offline_local",
    "openai_codex",
    "bedrock_amazon",
    "perplexity_web",
    "other_cloud",
)
SPECIALIST_ROUTE_LANE_MAP = {
    "receipt_auditor": ("judge", "verifier", "safety"),
    "tool_call_risk_classifier": ("safety", "prompt_injection", "coder"),
    "difficulty_estimator": ("planner", "scout"),
    "regret_predictor": ("judge", "verifier"),
    "browser_trace_compressor": ("summarizer", "filter"),
    "screenshot_state_classifier": ("gui_ground", "doc_parse"),
    "non_answer_detector": ("verifier", "filter"),
    "patch_blast_radius_estimator": ("coder", "safety"),
    "memory_write_gate": ("safety", "prompt_injection", "embedding"),
    "local_hallucination_firewall": ("judge", "verifier", "rerank"),
}
DETERMINISTIC_SMOKE_LANES = {
    "receipt_auditor",
    "difficulty_estimator",
    "regret_predictor",
    "non_answer_detector",
}
SPECIALIST_ROUTE_RECEIPT_FIELDS = (
    "request_id",
    "job_id",
    "phase",
    "task_kind",
    "selected_provider",
    "selected_model",
    "target_model",
    "effective_runtime_model",
    "selected_worker",
    "target_worker",
    "observed_worker",
    "frontdoor",
    "peer_path",
    "route_reason",
    "policy_mode",
    "cloud_proxy",
    "benchmark_packet_id",
    "benchmark_fresh",
    "benchmark_score",
    "coverage_ratio",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "usage_bucket",
    "fallback_used",
    "fallback_reason",
    "verifier_result",
    "output_shape",
    "receipt_audit",
    "specialist_cascade",
)
SPECIALIST_REQUIRED_OUTPUT_PATHS = (
    "lane",
    "verdict",
    "confidence",
    "evidence",
    "schema_valid",
    "benchmark_evidence.source",
    "benchmark_evidence.fresh",
    "worker_attribution.selected_provider",
    "worker_attribution.selected_model",
    "worker_attribution.selected_worker",
    "usage.offline_local",
    "usage.openai_codex",
    "usage.bedrock_amazon",
    "usage.perplexity_web",
    "usage.other_cloud",
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _state(value: str) -> str:
    clean = _clean(value).lower()
    return clean if clean in ALLOWED_SPECIALIST_STATES else "aspirational"


def _path_get(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current


def _truthy_presence(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _usage_template() -> dict[str, int]:
    return {bucket: 0 for bucket in USAGE_BUCKETS}


def _which_command(command: str) -> str:
    command = _clean(command)
    if not command:
        return ""
    path_parts: list[str] = []
    executable_dir = Path(sys.executable).resolve().parent
    if executable_dir.exists():
        path_parts.append(str(executable_dir))
    virtual_env = _clean(os.environ.get("VIRTUAL_ENV"))
    if virtual_env:
        venv_bin = Path(virtual_env) / "bin"
        if venv_bin.exists():
            path_parts.append(str(venv_bin))
    env_path = _clean(os.environ.get("PATH"))
    if env_path:
        path_parts.append(env_path)
    return shutil.which(command, path=os.pathsep.join(path_parts)) or ""


def _float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _output_schema(*, result_field: str) -> dict[str, Any]:
    return {
        "schema": SPECIALIST_OUTPUT_SCHEMA,
        "type": "object",
        "required": list(SPECIALIST_REQUIRED_OUTPUT_PATHS) + [result_field],
        "properties": {
            "lane": {"type": "string"},
            "verdict": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array"},
            "schema_valid": {"type": "boolean"},
            "benchmark_evidence": {
                "type": "object",
                "required": ["source", "fresh"],
            },
            "worker_attribution": {
                "type": "object",
                "required": [
                    "selected_provider",
                    "selected_model",
                    "selected_worker",
                ],
            },
            "usage": {
                "type": "object",
                "required": list(USAGE_BUCKETS),
            },
            result_field: {"type": ["object", "array", "string", "number", "boolean"]},
        },
    }


def _gates(*, benchmark_name: str, smoke_test_name: str) -> dict[str, Any]:
    return {
        "live_smoke_test": {
            "required": True,
            "status_field": "live_smoke_test.status",
            "name": smoke_test_name,
        },
        "schema_checked_output": {
            "required": True,
            "validator": "validate_specialist_output",
            "schema": SPECIALIST_OUTPUT_SCHEMA,
        },
        "benchmark_evidence": {
            "required": True,
            "source": "uplink_lane_benchmark",
            "name": benchmark_name,
        },
        "route_receipt_fields": {
            "required": True,
            "fields": list(SPECIALIST_ROUTE_RECEIPT_FIELDS),
        },
        "worker_attribution": {
            "required": True,
            "fields": [
                "selected_provider",
                "selected_model",
                "selected_worker",
                "frontdoor",
                "peer_path",
            ],
        },
        "usage_accounting": {
            "required": True,
            "buckets": list(USAGE_BUCKETS),
            "cloud_proxy_counts_as_cloud": True,
            "perplexity_counts_as_search_not_cloud_llm": True,
        },
        "declared_state": {
            "required": True,
            "allowed": sorted(ALLOWED_SPECIALIST_STATES),
        },
    }


def _lane(
    lane: str,
    *,
    purpose: str,
    phase: str,
    result_field: str,
    model_floor: str,
    state: str = "lab",
    deterministic_experts: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "lane": lane,
        "state": _state(state),
        "phase": phase,
        "purpose": purpose,
        "model_floor": model_floor,
        "default_model_policy": (
            "Qwen3.6/Qwen3.5-class remains the floor for general reasoning, "
            "coding, and VLM work."
        ),
        "older_baseline_defaults_allowed": False,
        "older_baseline_exception": (
            "Older models are eligible only as narrow specialists after they beat "
            "the Qwen path on this lane's benchmark."
        ),
        "deterministic_experts": list(deterministic_experts or []),
        "output_schema": _output_schema(result_field=result_field),
        "required_output_paths": list(SPECIALIST_REQUIRED_OUTPUT_PATHS)
        + [result_field],
        "gates": _gates(
            benchmark_name=f"{lane}.benchmark",
            smoke_test_name=f"{lane}.smoke",
        ),
    }


SPECIALIST_LANES: tuple[dict[str, Any], ...] = (
    _lane(
        "receipt_auditor",
        purpose="Audit route receipts for missing proof, stale fields, and accounting drift.",
        phase="receipt_audit",
        result_field="receipt_findings",
        model_floor="qwen3.5:122b-a10b-q4_K_M",
        state="production",
        deterministic_experts=["xgrammar"],
    ),
    _lane(
        "tool_call_risk_classifier",
        purpose="Classify shell, browser, and file tool calls before execution.",
        phase="tool_risk",
        result_field="risk_classification",
        model_floor="qwen3.6:35b-a3b-q4_K_M",
        deterministic_experts=["semgrep", "gitleaks", "trufflehog"],
    ),
    _lane(
        "difficulty_estimator",
        purpose="Estimate task difficulty and choose local, judge, or cloud escalation budget.",
        phase="difficulty",
        result_field="difficulty",
        model_floor="qwen3.6:35b-a3b-q4_K_M",
        state="production",
    ),
    _lane(
        "regret_predictor",
        purpose="Predict whether the proposed route or action is likely to require repair.",
        phase="regret",
        result_field="regret",
        model_floor="qwen3.5:122b-a10b-q4_K_M",
        state="production",
        deterministic_experts=["pytest", "mypy", "ruff"],
    ),
    _lane(
        "browser_trace_compressor",
        purpose="Compress browser traces into cited evidence before planner or judge calls.",
        phase="browser_trace",
        result_field="compressed_trace",
        model_floor="qwen3.6:35b-a3b-q4_K_M",
    ),
    _lane(
        "screenshot_state_classifier",
        purpose="Classify screenshot/UI state and decide whether GUI grounding is needed.",
        phase="screenshot_state",
        result_field="screen_state",
        model_floor="qwen3-vl:30b-a3b-instruct-q4_K_M",
    ),
    _lane(
        "non_answer_detector",
        purpose="Reject empty, progress-only, or plan-only outputs when execution was requested.",
        phase="non_answer",
        result_field="answer_shape",
        model_floor="qwen3.6:35b-a3b-q4_K_M",
        state="production",
    ),
    _lane(
        "patch_blast_radius_estimator",
        purpose="Measure changed files, affected dependencies, and security/package risk.",
        phase="patch_blast_radius",
        result_field="blast_radius",
        model_floor="qwen3.6:27b",
        deterministic_experts=[
            "codeql",
            "semgrep",
            "syft",
            "grype",
            "osv_scanner",
            "pytest",
            "mypy",
            "ruff",
        ],
    ),
    _lane(
        "memory_write_gate",
        purpose="Decide whether a memory write is useful, grounded, and non-sensitive.",
        phase="memory_write",
        result_field="memory_gate",
        model_floor="qwen3.6:35b-a3b-q4_K_M",
        deterministic_experts=["gitleaks", "trufflehog"],
    ),
    _lane(
        "local_hallucination_firewall",
        purpose="Check local model outputs against retrieved evidence before final or cloud escalation.",
        phase="hallucination_firewall",
        result_field="grounding_check",
        model_floor="qwen3.5:122b-a10b-q4_K_M",
        deterministic_experts=["xgrammar"],
    ),
)

DETERMINISTIC_EXPERTS: tuple[dict[str, Any], ...] = (
    {
        "expert": "codeql",
        "command": "codeql",
        "purpose": "semantic code security analysis",
        "lanes": ["patch_blast_radius_estimator"],
    },
    {
        "expert": "semgrep",
        "command": "semgrep",
        "purpose": "fast static analysis and policy pattern checks",
        "lanes": ["tool_call_risk_classifier", "patch_blast_radius_estimator"],
    },
    {
        "expert": "gitleaks",
        "command": "gitleaks",
        "purpose": "secret leak detection in patches and memory candidates",
        "lanes": ["tool_call_risk_classifier", "memory_write_gate"],
    },
    {
        "expert": "trufflehog",
        "command": "trufflehog",
        "purpose": "verified secret detection in repos and proposed writes",
        "lanes": ["tool_call_risk_classifier", "memory_write_gate"],
    },
    {
        "expert": "syft",
        "command": "syft",
        "purpose": "software bill of materials generation",
        "lanes": ["patch_blast_radius_estimator"],
    },
    {
        "expert": "grype",
        "command": "grype",
        "purpose": "SBOM and dependency vulnerability scanning",
        "lanes": ["patch_blast_radius_estimator"],
    },
    {
        "expert": "osv_scanner",
        "command": "osv-scanner",
        "purpose": "open source vulnerability checks",
        "lanes": ["patch_blast_radius_estimator"],
    },
    {
        "expert": "xgrammar",
        "command": "xgrammar",
        "purpose": "structured output and grammar validation",
        "lanes": ["receipt_auditor", "local_hallucination_firewall"],
    },
    {
        "expert": "pytest",
        "command": "pytest",
        "purpose": "Python test execution",
        "lanes": ["regret_predictor", "patch_blast_radius_estimator"],
    },
    {
        "expert": "mypy",
        "command": "mypy",
        "purpose": "Python type checking",
        "lanes": ["regret_predictor", "patch_blast_radius_estimator"],
    },
    {
        "expert": "ruff",
        "command": "ruff",
        "purpose": "Python lint and formatting checks",
        "lanes": ["regret_predictor", "patch_blast_radius_estimator"],
    },
)


def deterministic_expert_registry() -> dict[str, Any]:
    experts: list[dict[str, Any]] = []
    for expert in DETERMINISTIC_EXPERTS:
        command = _clean(expert.get("command"))
        binary = _which_command(command)
        experts.append(
            {
                **deepcopy(expert),
                "state": "production" if binary else "aspirational",
                "availability": "installed" if binary else "missing",
                "binary": binary,
                "route_receipt_required": True,
                "usage_bucket": "offline_local",
            }
        )
    return {
        "schema": f"{SPECIALIST_LANE_REGISTRY_SCHEMA}.deterministic-experts",
        "experts": experts,
        "count": len(experts),
        "available_count": sum(1 for expert in experts if expert["binary"]),
    }


def specialist_lane_registry() -> dict[str, Any]:
    lanes = [deepcopy(lane) for lane in SPECIALIST_LANES]
    return {
        "schema": SPECIALIST_LANE_REGISTRY_SCHEMA,
        "states": sorted(ALLOWED_SPECIALIST_STATES),
        "route_receipt_fields": list(SPECIALIST_ROUTE_RECEIPT_FIELDS),
        "usage_buckets": list(USAGE_BUCKETS),
        "policy": {
            "qwen_floor": "Qwen3.6/Qwen3.5-class for reasoning, coding, and VLM",
            "older_baseline_defaults_allowed": False,
            "older_baseline_exception": (
                "Only narrow specialists may use older models, and only after "
                "lane-specific benchmark evidence beats the Qwen path."
            ),
            "catalog_is_desired_state_not_proof": True,
        },
        "lanes": lanes,
        "count": len(lanes),
    }


def specialist_registry_payload() -> dict[str, Any]:
    return {
        **specialist_lane_registry(),
        "deterministic_experts": deterministic_expert_registry(),
    }


def _route_lane_models(
    warm_policy_payload: dict[str, Any],
    route_lanes: tuple[str, ...],
) -> list[dict[str, Any]]:
    route_guardrails = (
        warm_policy_payload.get("route_guardrails")
        if isinstance(warm_policy_payload.get("route_guardrails"), dict)
        else {}
    )
    guardrail_lanes = (
        route_guardrails.get("lanes")
        if isinstance(route_guardrails.get("lanes"), dict)
        else {}
    )
    models: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for route_lane in route_lanes:
        lane_payload = guardrail_lanes.get(route_lane)
        if not isinstance(lane_payload, dict):
            continue
        for bucket in ("eligible_models", "canary_models", "blocked_models"):
            for item in lane_payload.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                model = _clean(item.get("model"))
                if not model:
                    continue
                key = (route_lane, model)
                if key in seen:
                    continue
                seen.add(key)
                models.append(
                    {
                        "route_lane": route_lane,
                        "model": model,
                        "bucket": bucket,
                        "authority": _clean(item.get("authority")),
                        "action": _clean(item.get("action")),
                        "target_worker": _clean(item.get("target_worker")),
                        "benchmark_quality": dict(
                            item.get("benchmark_quality")
                            if isinstance(item.get("benchmark_quality"), dict)
                            else {}
                        ),
                    }
                )
    return models


def _best_model_evidence(items: list[dict[str, Any]]) -> dict[str, Any]:
    def _rank(item: dict[str, Any]) -> tuple[int, float, float]:
        quality = item.get("benchmark_quality")
        if not isinstance(quality, dict):
            quality = {}
        bucket = _clean(item.get("bucket"))
        bucket_rank = {"eligible_models": 0, "canary_models": 1}.get(bucket, 2)
        score = _float(quality.get("score")) or 0.0
        coverage = _float(quality.get("coverage_ratio")) or 0.0
        return (bucket_rank, -score, -coverage)

    if not items:
        return {}
    return sorted(items, key=_rank)[0]


def specialist_lane_proof_from_warm_policy(
    warm_policy_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Convert warm-policy route evidence into lane-level production proof."""

    warm_policy_payload = (
        warm_policy_payload if isinstance(warm_policy_payload, dict) else {}
    )
    benchmark = (
        warm_policy_payload.get("benchmark")
        if isinstance(warm_policy_payload.get("benchmark"), dict)
        else {}
    )
    benchmark_loaded = _clean(benchmark.get("status")) in {"loaded", "provided"}
    lane_items: list[dict[str, Any]] = []
    for lane in SPECIALIST_LANES:
        lane_name = lane["lane"]
        route_lanes = SPECIALIST_ROUTE_LANE_MAP.get(lane_name, ())
        candidates = _route_lane_models(warm_policy_payload, route_lanes)
        best = _best_model_evidence(candidates)
        quality = (
            best.get("benchmark_quality")
            if isinstance(best.get("benchmark_quality"), dict)
            else {}
        )
        eligible = best.get("bucket") == "eligible_models"
        fresh = bool(benchmark_loaded and quality.get("eligible"))
        if lane_name in DETERMINISTIC_SMOKE_LANES:
            smoke_status = "passed"
            proof_state = "production"
            smoke_source = "deterministic_evaluator"
        elif eligible:
            smoke_status = "ready"
            proof_state = "production" if fresh else "lab"
            smoke_source = "warm_policy_route_guardrail"
        elif best:
            smoke_status = "blocked"
            proof_state = "lab"
            smoke_source = "warm_policy_route_guardrail"
        else:
            smoke_status = "missing"
            proof_state = "aspirational"
            smoke_source = "warm_policy_route_guardrail"
        lane_items.append(
            {
                "lane": lane_name,
                "state": lane["state"],
                "proof_state": proof_state,
                "route_lanes": list(route_lanes),
                "live_smoke_test": {
                    "name": lane["gates"]["live_smoke_test"]["name"],
                    "status": smoke_status,
                    "source": smoke_source,
                    "model": _clean(best.get("model")),
                    "worker": _clean(best.get("target_worker")),
                },
                "benchmark_evidence": {
                    "source": "uplink_lane_benchmark"
                    if benchmark_loaded
                    else _clean(benchmark.get("source")) or "warm_policy",
                    "fresh": fresh,
                    "model": _clean(best.get("model")),
                    "score": _float(quality.get("score")),
                    "coverage_ratio": _float(quality.get("coverage_ratio")),
                    "state": _clean(quality.get("state")),
                    "reason": _clean(quality.get("reason")),
                    "route_lane": _clean(best.get("route_lane")),
                    "candidate_count": len(candidates),
                },
            }
        )
    by_state: dict[str, int] = {}
    smoke_statuses: dict[str, int] = {}
    for item in lane_items:
        by_state[item["proof_state"]] = by_state.get(item["proof_state"], 0) + 1
        smoke = _clean(item.get("live_smoke_test", {}).get("status")) or "unknown"
        smoke_statuses[smoke] = smoke_statuses.get(smoke, 0) + 1
    return {
        "schema": SPECIALIST_PROOF_SCHEMA,
        "benchmark": dict(benchmark),
        "lane_count": len(lane_items),
        "lanes": lane_items,
        "by_state": by_state,
        "live_smoke_statuses": smoke_statuses,
        "production_ready_count": by_state.get("production", 0),
    }


def specialist_lane_proof_from_route_receipt(
    route_receipt: dict[str, Any],
) -> dict[str, Any]:
    benchmark = {
        "status": "provided" if route_receipt.get("benchmark_packet_id") else "",
        "source": _clean(route_receipt.get("benchmark_packet_id")) or "route_receipt",
    }
    fresh = bool(route_receipt.get("benchmark_fresh"))
    score = _float(route_receipt.get("benchmark_score"))
    coverage = _float(route_receipt.get("coverage_ratio"))
    lane_items: list[dict[str, Any]] = []
    for lane in SPECIALIST_LANES:
        lane_name = lane["lane"]
        deterministic = lane_name in DETERMINISTIC_SMOKE_LANES
        proof_state = "production" if deterministic else "lab"
        lane_items.append(
            {
                "lane": lane_name,
                "state": lane["state"],
                "proof_state": proof_state,
                "route_lanes": list(SPECIALIST_ROUTE_LANE_MAP.get(lane_name, ())),
                "live_smoke_test": {
                    "name": lane["gates"]["live_smoke_test"]["name"],
                    "status": "passed" if deterministic else "receipt_only",
                    "source": "route_receipt",
                    "model": _clean(route_receipt.get("selected_model")),
                    "worker": _clean(route_receipt.get("selected_worker")),
                },
                "benchmark_evidence": {
                    "source": benchmark["source"],
                    "fresh": fresh,
                    "model": _clean(route_receipt.get("selected_model")),
                    "score": score,
                    "coverage_ratio": coverage,
                    "state": "route_selected",
                    "reason": _clean(route_receipt.get("route_reason")),
                    "route_lane": _clean(route_receipt.get("task_kind")),
                    "candidate_count": 1 if route_receipt.get("selected_model") else 0,
                },
            }
        )
    by_state: dict[str, int] = {}
    smoke_statuses: dict[str, int] = {}
    for item in lane_items:
        by_state[item["proof_state"]] = by_state.get(item["proof_state"], 0) + 1
        smoke = _clean(item.get("live_smoke_test", {}).get("status")) or "unknown"
        smoke_statuses[smoke] = smoke_statuses.get(smoke, 0) + 1
    return {
        "schema": SPECIALIST_PROOF_SCHEMA,
        "benchmark": benchmark,
        "lane_count": len(lane_items),
        "lanes": lane_items,
        "by_state": by_state,
        "live_smoke_statuses": smoke_statuses,
        "production_ready_count": by_state.get("production", 0),
    }


def validate_specialist_output(
    lane: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    registry = {item["lane"]: item for item in SPECIALIST_LANES}
    lane_payload = registry.get(_clean(lane))
    if not lane_payload:
        return {
            "schema": f"{SPECIALIST_OUTPUT_SCHEMA}.validation",
            "lane": _clean(lane),
            "valid": False,
            "missing_fields": [],
            "error": "unknown specialist lane",
        }
    required_paths = list(lane_payload["required_output_paths"])
    missing = [
        path for path in required_paths if not _truthy_presence(_path_get(output, path))
    ]
    output_lane = _clean(output.get("lane"))
    if output_lane and output_lane != lane_payload["lane"]:
        missing.append("lane_matches_registry")
    return {
        "schema": f"{SPECIALIST_OUTPUT_SCHEMA}.validation",
        "lane": lane_payload["lane"],
        "valid": not missing,
        "missing_fields": missing,
        "checked_schema": lane_payload["output_schema"]["schema"],
    }


def specialist_output_template(lane: str) -> dict[str, Any]:
    registry = {item["lane"]: item for item in SPECIALIST_LANES}
    lane_payload = registry.get(_clean(lane))
    if not lane_payload:
        return {}
    result_field = next(
        path
        for path in lane_payload["required_output_paths"]
        if path not in SPECIALIST_REQUIRED_OUTPUT_PATHS
    )
    return {
        "lane": lane_payload["lane"],
        "verdict": "pending",
        "confidence": 0.0,
        "evidence": [],
        "schema_valid": False,
        "benchmark_evidence": {"source": "", "fresh": False},
        "worker_attribution": {
            "selected_provider": "",
            "selected_model": "",
            "selected_worker": "",
        },
        "usage": _usage_template(),
        result_field: {},
    }


def specialist_cascade_template(
    *,
    phase: str = "",
    selected_provider: str = "",
    selected_model: str = "",
    selected_worker: str = "",
    usage_bucket: str = "offline_local",
    lanes: list[str] | None = None,
    deterministic_experts: list[str] | None = None,
) -> dict[str, Any]:
    selected_lanes = set(lanes or [])
    selected_experts = set(deterministic_experts or [])
    lane_items = []
    for lane in SPECIALIST_LANES:
        enabled = not selected_lanes or lane["lane"] in selected_lanes
        lane_items.append(
            {
                "lane": lane["lane"],
                "state": lane["state"],
                "proof_state": "aspirational",
                "phase": lane["phase"],
                "status": "pending" if enabled else "not_requested",
                "live_smoke_test_required": True,
                "schema_checked_output_required": True,
                "benchmark_evidence_required": True,
                "route_receipt_required": True,
                "worker_attribution_required": True,
                "usage_accounting_required": True,
                "worker_attribution": {
                    "selected_provider": selected_provider,
                    "selected_model": selected_model,
                    "selected_worker": selected_worker,
                },
                "usage": _usage_template(),
                "benchmark_evidence": {"source": "", "fresh": False},
                "live_smoke_test": {
                    "name": lane["gates"]["live_smoke_test"]["name"],
                    "status": "pending" if enabled else "not_requested",
                    "source": "",
                    "model": selected_model,
                    "worker": selected_worker,
                },
                "route_lanes": list(SPECIALIST_ROUTE_LANE_MAP.get(lane["lane"], ())),
                "required_route_receipt_fields": list(SPECIALIST_ROUTE_RECEIPT_FIELDS),
            }
        )
    expert_registry = deterministic_expert_registry()["experts"]
    expert_items = []
    for expert in expert_registry:
        enabled = not selected_experts or expert["expert"] in selected_experts
        expert_items.append(
            {
                "expert": expert["expert"],
                "state": expert["state"],
                "availability": expert["availability"],
                "status": "pending" if enabled else "not_requested",
                "command": expert["command"],
                "usage_bucket": "offline_local",
            }
        )
    usage = _usage_template()
    if usage_bucket in usage:
        usage[usage_bucket] = 0
    return {
        "schema": SPECIALIST_CASCADE_SCHEMA,
        "phase": _clean(phase),
        "status": "pending",
        "lanes": lane_items,
        "deterministic_experts": expert_items,
        "usage_accounting": usage,
        "route_receipt_fields": list(SPECIALIST_ROUTE_RECEIPT_FIELDS),
    }


def summarize_specialist_cascade(cascade: dict[str, Any]) -> dict[str, Any]:
    lanes = cascade.get("lanes") if isinstance(cascade, dict) else []
    experts = cascade.get("deterministic_experts") if isinstance(cascade, dict) else []
    lane_items = [item for item in lanes if isinstance(item, dict)]
    expert_items = [item for item in experts if isinstance(item, dict)]
    active_lane_items = [
        item for item in lane_items if _clean(item.get("status")) != "not_requested"
    ]
    active_expert_items = [
        item for item in expert_items if _clean(item.get("status")) != "not_requested"
    ]
    smoke_statuses: dict[str, int] = {}
    proof_states: dict[str, int] = {}
    benchmark_fresh_count = 0
    for item in active_lane_items:
        smoke = _clean(item.get("live_smoke_test", {}).get("status"))
        if smoke:
            smoke_statuses[smoke] = smoke_statuses.get(smoke, 0) + 1
        proof_state = _clean(item.get("proof_state"))
        if proof_state:
            proof_states[proof_state] = proof_states.get(proof_state, 0) + 1
        benchmark = item.get("benchmark_evidence")
        if isinstance(benchmark, dict) and benchmark.get("fresh"):
            benchmark_fresh_count += 1
    return {
        "schema": f"{SPECIALIST_CASCADE_SCHEMA}.summary",
        "lane_count": len(active_lane_items),
        "expert_count": len(active_expert_items),
        "lanes": [
            _clean(item.get("lane")) for item in active_lane_items if item.get("lane")
        ],
        "deterministic_experts": [
            _clean(item.get("expert"))
            for item in active_expert_items
            if item.get("expert")
        ],
        "completed_lanes": [
            _clean(item.get("lane"))
            for item in active_lane_items
            if _clean(item.get("status")) in {"complete", "pass", "passed"}
        ],
        "failed_lanes": [
            _clean(item.get("lane"))
            for item in active_lane_items
            if _clean(item.get("status")) in {"fail", "failed", "error"}
        ],
        "live_smoke_statuses": smoke_statuses,
        "proof_states": proof_states,
        "benchmark_fresh_count": benchmark_fresh_count,
        "production_ready_count": proof_states.get("production", 0),
    }


def _cascade_lanes(cascade: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _clean(item.get("lane")): item
        for item in cascade.get("lanes") or []
        if isinstance(item, dict) and _clean(item.get("lane"))
    }


def _set_lane_result(
    lane: dict[str, Any],
    *,
    status: str,
    verdict: str,
    confidence: float = 1.0,
    evidence: list[dict[str, Any]] | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    lane["status"] = status
    lane["verdict"] = verdict
    lane["confidence"] = confidence
    lane["evidence"] = list(evidence or [])
    lane["schema_valid"] = True
    if result is not None:
        lane["result"] = dict(result)


def _has_any(payload: dict[str, Any], *keys: str) -> bool:
    return any(bool(payload.get(key)) for key in keys)


def _specialist_proof_from_metadata(
    metadata: dict[str, Any],
    route_receipt: dict[str, Any],
) -> dict[str, Any]:
    proof = metadata.get("specialist_lane_proof")
    if isinstance(proof, dict) and proof.get("schema") == SPECIALIST_PROOF_SCHEMA:
        return proof
    warm_policy = metadata.get("warm_policy")
    if isinstance(warm_policy, dict):
        return specialist_lane_proof_from_warm_policy(warm_policy)
    receipt_proof = route_receipt.get("specialist_lane_proof")
    if isinstance(receipt_proof, dict) and receipt_proof.get("schema") == (
        SPECIALIST_PROOF_SCHEMA
    ):
        return receipt_proof
    return specialist_lane_proof_from_route_receipt(route_receipt)


def _apply_lane_proof(
    lanes: dict[str, dict[str, Any]],
    proof: dict[str, Any],
) -> None:
    proof_lanes = {
        _clean(item.get("lane")): item
        for item in proof.get("lanes") or []
        if isinstance(item, dict) and _clean(item.get("lane"))
    }
    for lane_name, lane in lanes.items():
        item = proof_lanes.get(lane_name)
        if not item:
            continue
        lane["proof_state"] = _clean(item.get("proof_state")) or lane.get("state")
        lane["route_lanes"] = list(item.get("route_lanes") or [])
        live_smoke = item.get("live_smoke_test")
        if isinstance(live_smoke, dict):
            lane["live_smoke_test"] = dict(live_smoke)
        benchmark = item.get("benchmark_evidence")
        if isinstance(benchmark, dict):
            lane["benchmark_evidence"] = dict(benchmark)


def evaluate_specialist_cascade(
    cascade: dict[str, Any],
    *,
    route_receipt: dict[str, Any],
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic local specialist checks that do not require a model call.

    Model-backed lanes still need live smoke tests and benchmarked serving paths;
    this evaluator makes the receipt honest by marking no-input lanes as skipped
    and by producing immediate local evidence for shape/accounting checks.
    """

    cascade = deepcopy(cascade)
    output = output or {}
    metadata = metadata or {}
    lanes = _cascade_lanes(cascade)
    lane_proof = _specialist_proof_from_metadata(metadata, route_receipt)
    missing_receipt_fields = [
        field
        for field in SPECIALIST_ROUTE_RECEIPT_FIELDS
        if field not in {"specialist_cascade", "receipt_audit"}
        and field not in route_receipt
    ]
    benchmark_evidence = {
        "source": _clean(route_receipt.get("benchmark_packet_id")) or "route_receipt",
        "fresh": bool(route_receipt.get("benchmark_fresh")),
        "score": route_receipt.get("benchmark_score") or 0.0,
        "coverage_ratio": route_receipt.get("coverage_ratio") or 0.0,
    }
    for lane in lanes.values():
        lane.setdefault("benchmark_evidence", dict(benchmark_evidence))
        lane["usage"] = {
            bucket: int(route_receipt.get("total_tokens") or 0)
            if bucket == route_receipt.get("usage_bucket")
            else 0
            for bucket in USAGE_BUCKETS
        }
    _apply_lane_proof(lanes, lane_proof)

    if lane := lanes.get("receipt_auditor"):
        _set_lane_result(
            lane,
            status="fail" if missing_receipt_fields else "pass",
            verdict="missing_fields" if missing_receipt_fields else "complete",
            evidence=[{"missing_fields": missing_receipt_fields}],
            result={"missing_fields": missing_receipt_fields},
        )

    output_shape = _clean(route_receipt.get("output_shape")) or "unknown"
    if lane := lanes.get("non_answer_detector"):
        bad_shapes = {"empty", "progress_only", "timeout", "error"}
        _set_lane_result(
            lane,
            status="fail" if output_shape in bad_shapes else "pass",
            verdict=output_shape,
            evidence=[{"output_shape": output_shape}],
            result={"output_shape": output_shape},
        )

    task_kind = _clean(route_receipt.get("task_kind"))
    total_tokens = int(route_receipt.get("total_tokens") or 0)
    difficulty = "low"
    if task_kind in {"code", "judge", "verify", "gui_ground", "doc_parse"}:
        difficulty = "medium"
    if total_tokens > 8000 or task_kind in {"judge", "verify"}:
        difficulty = "high"
    if lane := lanes.get("difficulty_estimator"):
        _set_lane_result(
            lane,
            status="pass",
            verdict=difficulty,
            confidence=0.7,
            evidence=[{"task_kind": task_kind, "total_tokens": total_tokens}],
            result={"difficulty": difficulty},
        )

    regret = "low"
    regret_reasons: list[str] = []
    if output_shape in {"empty", "progress_only", "timeout", "error"}:
        regret = "high"
        regret_reasons.append(f"output_shape={output_shape}")
    if route_receipt.get("fallback_used"):
        regret = "medium" if regret == "low" else regret
        regret_reasons.append("fallback_used")
    if not route_receipt.get("benchmark_fresh"):
        regret = "medium" if regret == "low" else regret
        regret_reasons.append("benchmark_not_fresh")
    if lane := lanes.get("regret_predictor"):
        _set_lane_result(
            lane,
            status="pass",
            verdict=regret,
            confidence=0.65,
            evidence=[{"reasons": regret_reasons}],
            result={"regret": regret, "reasons": regret_reasons},
        )

    conditional_lanes = {
        "tool_call_risk_classifier": (
            "tool_calls",
            _has_any(output, "tool_calls", "tool_call")
            or _has_any(metadata, "tool_calls"),
        ),
        "browser_trace_compressor": (
            "browser_trace",
            _has_any(output, "browser_trace") or _has_any(metadata, "browser_trace"),
        ),
        "screenshot_state_classifier": (
            "screenshot",
            _has_any(output, "screenshot", "image")
            or _has_any(metadata, "screenshot", "image"),
        ),
        "patch_blast_radius_estimator": (
            "patch",
            _has_any(output, "patch", "changed_files")
            or _has_any(metadata, "patch", "changed_files"),
        ),
        "memory_write_gate": (
            "memory_write",
            _has_any(output, "memory_write")
            or _has_any(metadata, "memory_write", "memory_candidate"),
        ),
        "local_hallucination_firewall": (
            "evidence",
            _has_any(output, "evidence", "citations")
            or _has_any(metadata, "evidence", "citations"),
        ),
    }
    for lane_name, (required_input, present) in conditional_lanes.items():
        lane = lanes.get(lane_name)
        if not lane or _clean(lane.get("status")) != "pending":
            continue
        if present:
            _set_lane_result(
                lane,
                status="pending",
                verdict="needs_model_lane",
                confidence=0.0,
                evidence=[{"required_input": required_input}],
                result={"required_input": required_input},
            )
        else:
            _set_lane_result(
                lane,
                status="skipped_no_input",
                verdict=f"no_{required_input}",
                confidence=1.0,
                evidence=[{"required_input": required_input}],
                result={"required_input": required_input},
            )

    for expert in cascade.get("deterministic_experts") or []:
        if not isinstance(expert, dict):
            continue
        status = _clean(expert.get("status"))
        if status != "pending":
            continue
        if expert.get("availability") != "installed":
            expert["status"] = "unavailable"
        else:
            expert["status"] = "available_not_run"

    cascade["status"] = "evaluated"
    cascade["specialist_lane_proof"] = lane_proof
    cascade["summary"] = summarize_specialist_cascade(cascade)
    return cascade
