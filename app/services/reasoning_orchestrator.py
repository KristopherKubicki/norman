from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

REASONING_PLAN_SCHEMA = "norman.reasoning-orchestrator.plan.v1"
REASONING_RECEIPT_SCHEMA = "norman.reasoning-orchestrator.receipt.v1"
SKILL_REGISTRY_SCHEMA = "norman.skill-registry.v1"
SKILL_REGISTRY_VERSION = "2026.07.15.reasoning-kpi-v1"

_KPI_WORDS = {
    "avoidance",
    "benchmark",
    "capability",
    "cloud",
    "cohort",
    "cost",
    "cutover",
    "degraded",
    "displacement",
    "kpi",
    "ledger",
    "local-first",
    "operator",
    "packet",
    "proof",
    "receipt",
    "release",
    "route",
    "signed",
    "staging",
}
_CODE_WORDS = {"code", "diff", "fix", "patch", "repo", "test", "tests"}
_TOOL_WORDS = {
    "build",
    "commit",
    "deploy",
    "execute",
    "generate",
    "implement",
    "run",
    "shell",
    "tool",
    "write",
}
_STATUS_INTENTS = {"quick_status", "next_steps"}
_MUTATION_INTENTS = {
    "continue_work",
    "restart_or_recover",
    "retry_last_step",
    "ship_or_release",
    "undo_or_rollback",
}
_TIER_CONFIG = {
    "instant": {
        "max_reasoning_seconds": 2,
        "max_tool_iterations": 1,
        "model_floor": "deterministic_or_tiny_local",
    },
    "standard": {
        "max_reasoning_seconds": 20,
        "max_tool_iterations": 3,
        "model_floor": "spark_local_general",
    },
    "deep": {
        "max_reasoning_seconds": 120,
        "max_tool_iterations": 8,
        "model_floor": "spark_high_reasoning_local",
    },
    "extended": {
        "max_reasoning_seconds": 360,
        "max_tool_iterations": 14,
        "model_floor": "spark_high_reasoning_with_checkpoint",
    },
    "authority": {
        "max_reasoning_seconds": 600,
        "max_tool_iterations": 18,
        "model_floor": "local_first_then_explicit_authority",
    },
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tokens(text: str) -> set[str]:
    normalized = (
        text.lower()
        .replace("/", " ")
        .replace("-", " ")
        .replace("_", " ")
        .replace("?", " ")
        .replace(".", " ")
        .replace(",", " ")
    )
    return {token for token in normalized.split() if token}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        clean = _clean(value)
        if clean and clean not in seen:
            seen.add(clean)
            unique_values.append(clean)
    return unique_values


def _skill(
    skill_id: str,
    *,
    label: str,
    task_classes: list[str],
    reasoning_tier: str,
    required_tools: list[str],
    verification_tools: list[str],
    output_schema: str,
    cadence: str = "on_demand",
    background_safe: bool = False,
    promotion_state: str = "canary",
) -> dict[str, Any]:
    return {
        "schema": "norman.skill-registry.skill.v1",
        "skill_id": skill_id,
        "label": label,
        "skill_family": "kpi" if skill_id.startswith("kpi.") else "runtime",
        "promotion_state": promotion_state,
        "cadence": cadence,
        "task_classes": task_classes,
        "reasoning_tier": reasoning_tier,
        "required_tools": required_tools,
        "verification_tools": verification_tools,
        "output_schema": output_schema,
        "receipt_required": True,
        "background_safe": background_safe,
    }


def build_skill_registry() -> dict[str, Any]:
    """Return the deterministic Norman skill registry for TUI orchestration."""

    skills = [
        _skill(
            "kpi.status_snapshot",
            label="Status Snapshot",
            task_classes=["quick_status", "next_steps", "status"],
            reasoning_tier="instant",
            required_tools=["tui_status_api", "route_receipt_ledger"],
            verification_tools=["output_shape_validator"],
            output_schema="norman.kpi.status-snapshot.v1",
            cadence="every_5_minutes",
            background_safe=True,
            promotion_state="production",
        ),
        _skill(
            "kpi.route_utilization",
            label="Route Utilization",
            task_classes=["route", "local_first", "cloud_displacement"],
            reasoning_tier="deep",
            required_tools=[
                "route_receipt_ledger",
                "local_cloud_search_ledger",
                "gateway_execution_activity",
            ],
            verification_tools=["ledger_consistency_validator"],
            output_schema="norman.kpi.route-utilization.v1",
            cadence="every_15_minutes",
            background_safe=True,
        ),
        _skill(
            "kpi.receipt_integrity",
            label="Receipt Integrity",
            task_classes=["receipt", "audit", "release"],
            reasoning_tier="deep",
            required_tools=[
                "signed_receipt_ledger",
                "route_receipt_auditor",
                "completion_gate",
            ],
            verification_tools=["receipt_schema_validator", "signature_validator"],
            output_schema="norman.kpi.receipt-integrity.v1",
            cadence="every_15_minutes",
            background_safe=True,
        ),
        _skill(
            "kpi.operator_cohort",
            label="Operator Cohort",
            task_classes=["operator", "cohort", "cutover"],
            reasoning_tier="extended",
            required_tools=[
                "signed_receipt_ledger",
                "operator_session_filter",
                "visible_delivery_checker",
            ],
            verification_tools=["cohort_threshold_validator"],
            output_schema="norman.kpi.operator-cohort.v1",
            cadence="hourly",
            background_safe=True,
        ),
        _skill(
            "kpi.benchmark_refresh",
            label="Benchmark Refresh",
            task_classes=["benchmark", "capability", "staging"],
            reasoning_tier="extended",
            required_tools=[
                "norllama_benchmark_packet",
                "capability_packet_validator",
                "route_policy_validator",
            ],
            verification_tools=["packet_hash_validator", "stale_evidence_checker"],
            output_schema="norman.kpi.benchmark-refresh.v1",
            cadence="daily",
            background_safe=True,
        ),
        _skill(
            "kpi.cost_counterfactual",
            label="Cost Counterfactual",
            task_classes=["cost", "cloud", "avoidance"],
            reasoning_tier="deep",
            required_tools=[
                "local_cloud_search_ledger",
                "provider_usage_export",
                "workflow_counterfactual_estimator",
            ],
            verification_tools=["usage_bucket_validator"],
            output_schema="norman.kpi.cost-counterfactual.v1",
            cadence="hourly",
            background_safe=True,
        ),
        _skill(
            "kpi.degraded_matrix",
            label="Degraded Matrix",
            task_classes=["degraded", "failover", "worker"],
            reasoning_tier="extended",
            required_tools=[
                "estate_health_probe",
                "gateway_execution_activity",
                "degraded_scenario_runner",
            ],
            verification_tools=["fallback_receipt_validator"],
            output_schema="norman.kpi.degraded-matrix.v1",
            cadence="on_demand",
            background_safe=False,
        ),
        _skill(
            "kpi.release_packet",
            label="Release Packet",
            task_classes=["release", "packet", "staging"],
            reasoning_tier="extended",
            required_tools=[
                "git_status",
                "test_result_collector",
                "sha256_manifest_builder",
                "secret_scan",
            ],
            verification_tools=["packet_manifest_validator"],
            output_schema="norman.kpi.release-packet.v1",
            cadence="on_demand",
            background_safe=False,
        ),
        _skill(
            "kpi.anomaly_triage",
            label="Anomaly Triage",
            task_classes=["outlier", "alert", "anomaly"],
            reasoning_tier="deep",
            required_tools=[
                "route_receipt_ledger",
                "provider_activity_log",
                "prompt_bad_route_corpus",
            ],
            verification_tools=["outlier_classifier_validator"],
            output_schema="norman.kpi.anomaly-triage.v1",
            cadence="every_15_minutes",
            background_safe=True,
        ),
        _skill(
            "runtime.tool_planner",
            label="Tool Planner",
            task_classes=["code", "tool_use", "repo", "patch"],
            reasoning_tier="deep",
            required_tools=[
                "repo_file_search",
                "command_runner",
                "test_selector",
                "diff_summarizer",
            ],
            verification_tools=["allowed_file_validator", "test_result_validator"],
            output_schema="norman.runtime.tool-plan.v1",
            cadence="on_demand",
            background_safe=False,
            promotion_state="staging",
        ),
        _skill(
            "runtime.approval_guard",
            label="Approval Guard",
            task_classes=["approval", "external_mutation", "destructive"],
            reasoning_tier="authority",
            required_tools=[
                "approval_binding_checker",
                "pending_action_digest_checker",
                "scope_validator",
            ],
            verification_tools=["approval_receipt_validator"],
            output_schema="norman.runtime.approval-guard.v1",
            cadence="on_demand",
            background_safe=False,
            promotion_state="production",
        ),
    ]
    return {
        "schema": SKILL_REGISTRY_SCHEMA,
        "version": SKILL_REGISTRY_VERSION,
        "generated_at": _now_iso(),
        "skills": skills,
        "skill_count": len(skills),
    }


def _skill_score(
    skill: Mapping[str, Any],
    *,
    prompt_tokens: set[str],
    classification: Mapping[str, Any],
    context: Mapping[str, Any],
) -> int:
    task_classes = {_lower(value) for value in skill.get("task_classes") or []}
    intent = _lower(classification.get("intent"))
    task_kind = _lower(classification.get("task_kind"))
    risk_class = _lower(classification.get("risk_class"))
    score = 0
    if intent in task_classes:
        score += 5
    if task_kind in task_classes:
        score += 4
    if risk_class in task_classes:
        score += 4
    score += len(prompt_tokens & task_classes) * 2
    if skill["skill_id"] == "kpi.status_snapshot" and intent in _STATUS_INTENTS:
        score += 8
    if skill["skill_id"] == "runtime.tool_planner" and prompt_tokens & (
        _CODE_WORDS | _TOOL_WORDS
    ):
        score += 6
    if skill["skill_id"] == "runtime.approval_guard" and (
        classification.get("requires_approval")
        or risk_class in {"external_mutation", "destructive"}
        or intent in _MUTATION_INTENTS
    ):
        score += 8
    if skill["skill_id"].startswith("kpi.") and prompt_tokens & _KPI_WORDS:
        score += 2
    if context.get("background_loop") and skill.get("background_safe"):
        score += 2
    return score


def match_skills(
    *,
    prompt: str,
    classification: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    registry = dict(registry or build_skill_registry())
    prompt_tokens = _tokens(prompt)
    context = dict(context or {})
    scored: list[tuple[int, dict[str, Any]]] = []
    for skill in registry.get("skills") or []:
        if not isinstance(skill, Mapping):
            continue
        score = _skill_score(
            skill,
            prompt_tokens=prompt_tokens,
            classification=classification,
            context=context,
        )
        if score > 0:
            item = dict(skill)
            item["match_score"] = score
            scored.append((score, item))
    scored.sort(key=lambda item: (-item[0], item[1]["skill_id"]))
    return [skill for _, skill in scored[:10]]


def _tier_rank(tier: str) -> int:
    order = {"instant": 0, "standard": 1, "deep": 2, "extended": 3, "authority": 4}
    return order.get(tier, 1)


def _tier_from_matches(
    *,
    prompt: str,
    classification: Mapping[str, Any],
    matched_skills: list[Mapping[str, Any]],
) -> str:
    intent = _lower(classification.get("intent"))
    risk_level = _lower(classification.get("risk_level"))
    task_kind = _lower(classification.get("task_kind"))
    word_count = len(_tokens(prompt))
    if classification.get("requires_approval") or risk_level in {"high", "critical"}:
        return "authority"
    if intent in _STATUS_INTENTS and risk_level == "low":
        return "instant"
    tier = "standard"
    if task_kind in {"code", "verify", "judge"} or word_count >= 80:
        tier = "deep"
    for skill in matched_skills:
        skill_tier = _lower(skill.get("reasoning_tier"))
        if _tier_rank(skill_tier) > _tier_rank(tier):
            tier = skill_tier
    return tier


def plan_reasoning_turn(
    *,
    prompt: str,
    classification: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    source: str = "",
    session: str = "",
) -> dict[str, Any]:
    """Build a deterministic tool/reasoning plan for a TUI turn."""

    context = dict(context or {})
    matched_skills = match_skills(
        prompt=prompt,
        classification=classification,
        context=context,
    )
    tier = _tier_from_matches(
        prompt=prompt,
        classification=classification,
        matched_skills=matched_skills,
    )
    tier_config = dict(_TIER_CONFIG[tier])
    required_tools = _unique(
        [
            tool
            for skill in matched_skills
            for tool in list(skill.get("required_tools") or [])
        ]
    )
    verification_tools = _unique(
        [
            tool
            for skill in matched_skills
            for tool in list(skill.get("verification_tools") or [])
        ]
    )
    if not required_tools and tier == "instant":
        required_tools = ["tui_status_api", "route_receipt_ledger"]
    if not verification_tools:
        verification_tools = ["output_shape_validator", "route_receipt_auditor"]
    forbidden_tools = ["unreceipted_cloud_llm"]
    if classification.get("external_side_effects_possible"):
        forbidden_tools.append("unapproved_external_mutation")
    if classification.get("requires_approval"):
        forbidden_tools.append("unbound_approval_action")
    background_candidates = [
        {
            "skill_id": skill["skill_id"],
            "cadence": skill["cadence"],
            "output_schema": skill["output_schema"],
        }
        for skill in matched_skills
        if skill.get("background_safe")
    ]
    return {
        "schema": REASONING_PLAN_SCHEMA,
        "plan_id": f"reasoning_plan_{uuid.uuid4().hex}",
        "registry_version": SKILL_REGISTRY_VERSION,
        "created_at": _now_iso(),
        "source": source,
        "session": session,
        "intent": _clean(classification.get("intent")),
        "task_kind": _clean(classification.get("task_kind")),
        "risk_class": _clean(classification.get("risk_class")),
        "risk_level": _clean(classification.get("risk_level")),
        "reasoning_tier": {
            "tier": tier,
            **tier_config,
            "stop_when_marginal_value_below": (
                "visible_answer_ready_and_verifier_passed"
            ),
            "escalate_when": [
                "required_tool_unavailable",
                "receipt_audit_fails",
                "verifier_rejects_output",
                "operator_risk_requires_authority",
            ],
        },
        "matched_skills": matched_skills,
        "selected_skill_ids": [skill["skill_id"] for skill in matched_skills],
        "tool_plan": {
            "required_tools": required_tools,
            "verification_tools": verification_tools,
            "forbidden_tools": forbidden_tools,
            "max_tool_iterations": tier_config["max_tool_iterations"],
            "continuous_tool_use": tier in {"deep", "extended", "authority"},
            "tool_loop": [
                "gather_context",
                "execute_smallest_safe_tool",
                "record_tool_receipt",
                "verify_observation",
                "decide_continue_or_stop",
            ],
        },
        "execution_loop": [
            "classify_prompt",
            "match_skill",
            "set_reasoning_budget",
            "gather_context",
            "execute_tools_if_required",
            "synthesize_local_first",
            "verify_shape_and_receipt",
            "escalate_only_with_reason",
        ],
        "cloud_policy": {
            "position": "last_resort_after_local_receipt",
            "requires_explicit_reason": True,
            "requires_usage_ledger": True,
            "forbidden_without": [
                "local_attempt_receipt",
                "risk_or_quality_reason",
                "cloud_budget_bucket",
            ],
        },
        "background_loop_candidates": background_candidates,
        "artifacts_observed": len(artifacts or []),
        "receipt_required": True,
    }


def build_reasoning_receipt(
    plan: Mapping[str, Any],
    *,
    executed_tools: list[dict[str, Any]] | None = None,
    verifier_result: str = "planned",
) -> dict[str, Any]:
    executed_tools = [
        dict(item) for item in executed_tools or [] if isinstance(item, Mapping)
    ]
    required_tools = list(
        ((plan.get("tool_plan") or {}).get("required_tools") or [])
        if isinstance(plan.get("tool_plan"), Mapping)
        else []
    )
    executed_names = {_clean(item.get("tool")) for item in executed_tools}
    skipped_required = [
        tool for tool in required_tools if tool and tool not in executed_names
    ]
    return {
        "schema": REASONING_RECEIPT_SCHEMA,
        "receipt_id": f"reasoning_receipt_{uuid.uuid4().hex}",
        "plan_id": plan.get("plan_id"),
        "registry_version": plan.get("registry_version"),
        "created_at": _now_iso(),
        "reasoning_tier": (plan.get("reasoning_tier") or {}).get("tier")
        if isinstance(plan.get("reasoning_tier"), Mapping)
        else "",
        "selected_skill_ids": list(plan.get("selected_skill_ids") or []),
        "required_tools": required_tools,
        "executed_tools": executed_tools,
        "skipped_required_tools": skipped_required,
        "verifier_result": verifier_result,
        "completion_state": "planned" if verifier_result == "planned" else "observed",
        "cloud_policy": plan.get("cloud_policy") or {},
        "receipt_complete": verifier_result != "planned"
        and not skipped_required
        and bool(executed_tools),
    }


def kpi_background_loop_plan() -> dict[str, Any]:
    registry = build_skill_registry()
    candidates = [
        {
            "skill_id": skill["skill_id"],
            "cadence": skill["cadence"],
            "required_tools": skill["required_tools"],
            "output_schema": skill["output_schema"],
        }
        for skill in registry["skills"]
        if skill.get("background_safe")
    ]
    return {
        "schema": "norman.kpi-background-loop.plan.v1",
        "registry_version": registry["version"],
        "generated_at": _now_iso(),
        "model_calls_required": 0,
        "loop_policy": {
            "run_in_background": True,
            "record_signed_receipts": True,
            "cloud_allowed": False,
            "operator_visible_on_anomaly": True,
        },
        "candidates": candidates,
        "candidate_count": len(candidates),
    }
