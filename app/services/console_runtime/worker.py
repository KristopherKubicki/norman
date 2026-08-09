from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.console_runtime.adapters.base import ModelAdapter
from app.services.console_runtime.adapters.bedrock import BedrockModelAdapter
from app.services.console_runtime.adapters.fake import FakeModelAdapter
from app.services.console_runtime.adapters.norllama import NorllamaModelAdapter
from app.services.console_runtime.adapters.shell import (
    ShellPolicyError,
    ShellRequest,
    ShellRuntimeAdapter,
)
from app.services.console_runtime.policy import (
    route_decision,
    resolve_runtime_mode,
    with_local_first_catalog_defaults,
)
from app.services.console_runtime.store import DbConsoleRuntimeStore
from app.services.console_runtime.types import (
    ConsoleCheckpointCapsule,
    ConsoleJobStatus,
    ConsoleVerificationReceipt,
    ModelBudget,
    ModelRequest,
    ModelResult,
    RetryClass,
)
from app.services.prompt_load_balancer import classify_prompt
from app.services.reasoning_orchestrator import (
    build_reasoning_receipt,
    plan_reasoning_turn,
)
from app.services.work_classification import (
    classify_work,
    sanitize_work_classification,
)
from app.services.norllama.routing import build_task_receipt, route_task
from app.services.norllama.route_proof import (
    audit_route_receipt,
    normalize_route_receipt_for_completion_gate,
    receipt_completion_gate_passes,
)
from app.services.norllama.fast_lane_outcomes import evaluate_fast_lane_outcome
from app.services.norllama.specialist_lanes import evaluate_specialist_cascade
from app.services.norllama.types import NorllamaTaskRequest

GOAL_LOOP_TERMINAL_STATUSES = {
    ConsoleJobStatus.BLOCKED.value,
    ConsoleJobStatus.CANCELED.value,
    ConsoleJobStatus.DONE.value,
    ConsoleJobStatus.FAILED.value,
    ConsoleJobStatus.WAITING_APPROVAL.value,
}
DEFAULT_GOAL_PHASE_SEQUENCE = ["plan", "work", "verify"]
DEFAULT_WORKSPACE_PREFLIGHT_COMMANDS = [
    "pwd",
    "git status --short",
    "git branch --show-current",
]
CLOUD_TOKEN_REQUEST_OVERHEAD = 32
ADVISORY_EXECUTION_MODE = "advisory"
ADVISORY_ROUTE_POLICY = {
    "provider": "norllama",
    "preferred_provider": "norllama",
    "runtime": "norllama",
    "local_first": True,
    "cloud_llm_disabled": True,
    "allow_cloud_proxy": False,
    "allow_cloud_tool_proxy": False,
    "task_kind": "chat",
    "planner_kind": "chat",
    "goal_phase_sequence": ["chat"],
    "route_proof_required": False,
    "require_route_proof": False,
    "require_verifier_for_completion": False,
    "verification_required": False,
    "verifier_can_stop": False,
}
GOAL_PHASE_TASK_KIND = {
    "chat": "chat",
    "compact": "compact",
    "draft": "chat",
    "execute": "chat",
    "filter": "filter",
    "literal_response": "chat",
    "plan": "plan",
    "preflight": "shell",
    "scout": "scout",
    "shell": "shell",
    "summarize": "summarize",
    "tool": "shell",
    "tools": "shell",
    "verify": "verify",
    "work": "chat",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _merge_dicts(*values: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    for item in values:
        clean = _clean(item).lower()
        if clean and clean not in result:
            result.append(clean)
    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.splitlines() if "\n" in value else [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    for item in values:
        clean = _clean(item)
        if clean and clean not in result:
            result.append(clean)
    return result


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    clean = _clean(value).lower()
    if not clean:
        return default
    if clean in {"1", "true", "yes", "on", "enabled", "force"}:
        return True
    if clean in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _verification_signal(text: Any) -> str:
    lower = " ".join(_clean(text).lower().replace("_", " ").split())
    if not lower:
        return ""
    if "no remaining work" in lower:
        return "complete"
    if any(
        marker in lower
        for marker in (
            "status: needs more work",
            "status needs more work",
            "needs more work",
            "not complete",
            "incomplete",
            "not done",
            "another local step",
        )
    ):
        return "needs_more_work"
    if any(
        marker in lower
        for marker in (
            "status: complete",
            "status complete",
            "goal complete",
            "verified complete",
            "done when satisfied",
            "done_when satisfied",
            "no remaining work",
            "complete.",
        )
    ):
        return "complete"
    return ""


def _durable_verification_signal(text: Any) -> str:
    """Parse the explicit status contract required to close durable work."""

    match = re.search(
        r"(?im)^\s*STATUS\s*:\s*(COMPLETE|NEEDS_MORE_WORK)\s*$",
        _clean(text),
    )
    if not match:
        return ""
    return "complete" if match.group(1).upper() == "COMPLETE" else "needs_more_work"


def _progress_fingerprint(text: Any, phase: Any) -> str:
    """Return a stable, phase-aware fingerprint for model progress detection."""

    normalized_text = " ".join(_clean(text).lower().split())
    normalized_phase = _clean(phase).lower()
    if not normalized_text:
        return ""
    value = f"{normalized_phase}\n{normalized_text}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _literal_response_expected(objective: Any) -> str:
    text = _clean(objective)
    lower = text.lower()
    marker = "reply exactly:"
    index = lower.rfind(marker)
    if index < 0:
        return ""
    expected = text[index + len(marker) :].strip()
    return expected.strip("`\"'")


def _literal_response_signal(objective: Any, text: Any) -> str:
    expected = _literal_response_expected(objective)
    if not expected:
        return ""
    return "complete" if _clean(text) == expected else "needs_more_work"


def _structured_response_signal(objective: Any, text: Any) -> str:
    objective_text = _clean(objective).lower()
    response_text = _clean(text)
    if not response_text or "json" not in objective_text:
        return ""
    if "return" not in objective_text and "reply" not in objective_text:
        return ""
    key_match = re.search(
        r"\bkeys?\s+([a-z0-9_,\s-]+?)(?:\.|$)",
        objective_text,
    )
    required_keys: list[str] = []
    if key_match:
        required_keys = [
            re.sub(r"\s+value\s+.*$", "", key.strip().strip("`\"'")).strip()
            for key in re.split(r",|\band\b", key_match.group(1))
            if key.strip()
        ]
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return "needs_more_work"
    if not isinstance(parsed, dict):
        return "needs_more_work"
    parsed_keys = {str(key).lower() for key in parsed}
    if required_keys and not all(key in parsed_keys for key in required_keys):
        return "needs_more_work"
    nonce_match = re.search(r"\bnonce value\s+([a-z0-9_.:-]+)", objective_text)
    if nonce_match:
        expected_nonce = nonce_match.group(1).strip("`\"'.,;:")
        if expected_nonce and expected_nonce not in response_text.lower():
            return "needs_more_work"
    return "complete"


def _goal_phase_sequence(value: Any, planner_kind: str) -> list[str]:
    phases = [
        phase
        for phase in _clean_list(value)
        if phase in GOAL_PHASE_TASK_KIND or phase in GOAL_PHASE_TASK_KIND.values()
    ]
    if phases:
        return phases
    clean_kind = _clean(planner_kind).lower()
    if clean_kind and clean_kind != "plan":
        return [clean_kind]
    return list(DEFAULT_GOAL_PHASE_SEQUENCE)


def _goal_phase_for_step(sequence: list[str], step_index: int, max_steps: int) -> str:
    phases = sequence or list(DEFAULT_GOAL_PHASE_SEQUENCE)
    step = max(1, int(step_index or 1))
    if max_steps >= 3 and step == max_steps and "verify" in phases:
        return "verify"
    if step <= len(phases):
        return phases[step - 1]
    if len(phases) == 1:
        return phases[0]
    return phases[1 + ((step - len(phases) - 1) % (len(phases) - 1))]


def _goal_task_kind(phase: str, fallback: str) -> str:
    clean = _clean(phase).lower()
    return GOAL_PHASE_TASK_KIND.get(clean) or clean or (_clean(fallback) or "plan")


def _route_policy_has_runner(policy: dict[str, Any]) -> bool:
    return any(
        _clean(policy.get(key))
        for key in ("provider", "preferred_provider", "provider_surface", "runtime")
    )


def _local_first_route_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return with_local_first_catalog_defaults(policy)


def _preview(text: str, limit: int = 600) -> str:
    value = _clean(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."


def _route_receipt_from_result(result: ModelResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    receipt = (
        metadata.get("norllama_receipt")
        if isinstance(metadata.get("norllama_receipt"), dict)
        else {}
    )
    route_receipt = (
        receipt.get("route_receipt")
        if isinstance(receipt.get("route_receipt"), dict)
        else {}
    )
    return dict(route_receipt)


def _runtime_reasoning_plan(
    *,
    job,
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
    task_kind: str = "",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    classification = classify_prompt(job.contract.objective)
    if task_kind:
        classification = {**classification, "task_kind": task_kind}
    context = _merge_dicts(
        job.metadata,
        job.contract.metadata,
        options.metadata,
        {
            "console_runtime_job_id": job.job_id,
            "worker_id": options.worker_id,
            "dry_run": options.dry_run,
            "runtime": route_policy.get("runtime"),
            "provider": route_policy.get("provider"),
            "route_proof_required": route_policy.get("route_proof_required"),
            "background_loop": route_policy.get("background_loop"),
        },
    )
    work_classification = _runtime_work_classification(
        classification=classification,
        route_policy=route_policy,
        options=options,
        context=context,
        task_kind=task_kind,
    )
    plan = plan_reasoning_turn(
        prompt=job.contract.objective,
        classification=classification,
        context=context,
        source=_clean(context.get("source")) or "console_runtime",
        session=_clean(
            context.get("session")
            or context.get("session_name")
            or context.get("console_runtime_session")
        ),
        work_classification=work_classification,
    )
    return classification, work_classification, plan, build_reasoning_receipt(plan)


def _runtime_work_classification(
    *,
    classification: dict[str, Any],
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
    context: dict[str, Any],
    task_kind: str,
    selected_provider: str = "",
) -> dict[str, Any]:
    requested_runtime = _clean(
        options.metadata.get("requested_runtime")
        or route_policy.get("runtime")
        or route_policy.get("provider")
    )
    active_work = bool(
        context.get("active_job_count")
        or context.get("active_job_id")
        or context.get("pending_action_kind")
    )
    return classify_work(
        prompt_classification=classification,
        active_work=active_work,
        route_locked=_route_lock_enabled(route_policy, options),
        force_requested_runtime=(
            _flag(options.metadata.get("force_requested_runtime"))
            or _flag(route_policy.get("force_requested_runtime"))
        ),
        requested_runtime=requested_runtime,
        effective_runtime=selected_provider,
        selected_provider=selected_provider,
        task_kind=task_kind,
    )


def _receipt_audit(route_receipt: dict[str, Any]) -> dict[str, Any]:
    return audit_route_receipt(route_receipt)


def _route_proof_required(
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
) -> bool:
    if options.execution_mode == ADVISORY_EXECUTION_MODE:
        return False
    return (
        not options.dry_run
        or _flag(route_policy.get("route_proof_required"))
        or _flag(route_policy.get("require_route_proof"))
    )


def _advisory_sources(
    job: Any, options: "ConsoleRuntimeRunOptions"
) -> list[dict[str, Any]]:
    contract = getattr(job, "contract", None)
    return [
        value
        for value in (
            getattr(contract, "route_policy", {}),
            getattr(contract, "metadata", {}),
            getattr(job, "metadata", {}),
            options.route_policy,
            options.metadata,
        )
        if isinstance(value, dict)
    ]


def _advisory_invalid_reason(job: Any, options: "ConsoleRuntimeRunOptions") -> str:
    """Reject execution-shaped state before an advisory job can be leased."""

    for source in _advisory_sources(job, options):
        for key, expected in (
            ("cloud_token_budget", 0),
            ("max_steps", 1),
        ):
            value = source.get(key)
            if value in (None, ""):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return f"advisory execution cannot include invalid {key}"
            if parsed != expected:
                return f"advisory execution requires {key}={expected}"

        for key in (
            "continuous",
            "dry_run",
            "include_capabilities",
            "live_execution_approved",
        ):
            if _flag(source.get(key)):
                return f"advisory execution cannot enable {key}"

        for key in ("execution_mode", "mode", "task_mode"):
            value = _clean(source.get(key)).lower().replace("-", "_")
            if value and value not in {ADVISORY_EXECUTION_MODE, "static_advice"}:
                return f"advisory execution cannot use {key}={value!r}"

        for key in ("provider", "preferred_provider", "runtime"):
            value = _clean(source.get(key)).lower().replace("_", "-")
            if value and value != "norllama":
                return f"advisory execution cannot use {key}={value!r}"

        for key in (
            "command",
            "shell_command",
            "commands",
            "shell_commands",
            "preflight_commands",
            "kernel_preflight_commands",
        ):
            if _string_list(source.get(key)):
                return f"advisory execution cannot include {key}"

        for key in ("route_lock", "strict_route", "operator_model_override"):
            if _flag(source.get(key)):
                return f"advisory execution cannot include {key}"

        for key in (
            "route_proof_required",
            "require_route_proof",
            "require_verifier_for_completion",
            "verification_required",
            "verifier_can_stop",
            "kernel_verifier_can_stop",
            "require_verification_receipt",
            "reasoning_tool_gate_required",
            "require_reasoning_tool_gate",
        ):
            if _flag(source.get(key)):
                return f"advisory execution cannot include {key}"

        for key in (
            "allow_cloud_proxy",
            "allow_cloud_tool_proxy",
            "cloud_proxy",
            "cloud_tool_proxy",
            "cloud_execution",
            "use_capability_catalog",
            "include_capabilities",
            "tool_lane",
            "workspace_preflight",
            "kernel_workspace_preflight",
            "kernel_preflight",
            "live_execution_approved",
            "live_execution",
            "executable",
        ):
            if _flag(source.get(key)):
                return f"advisory execution cannot enable {key}"

        for key in (
            "required_tools",
            "verification_tools",
            "tools",
            "tool_plan",
            "capabilities",
            "capability_catalog",
            "capability_contracts",
        ):
            value = source.get(key)
            if isinstance(value, (dict, list, tuple, set)):
                if value:
                    return f"advisory execution cannot include {key}"
            elif _clean(value):
                return f"advisory execution cannot include {key}"

        mode = _clean(
            source.get("execution_mode")
            or source.get("mode")
            or source.get("task_mode")
        ).lower()
        if mode and mode not in {"advisory", "static_advice"}:
            return f"advisory execution cannot include mode={mode!r}"
    return ""


def _canonical_advisory_route_policy() -> dict[str, Any]:
    return {
        **ADVISORY_ROUTE_POLICY,
        "goal_phase_sequence": list(ADVISORY_ROUTE_POLICY["goal_phase_sequence"]),
    }


def _route_lock_enabled(
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
) -> bool:
    return (
        _flag(options.metadata.get("route_lock"))
        or _flag(options.metadata.get("strict_route"))
        or _flag(route_policy.get("route_lock"))
        or _flag(route_policy.get("strict_route"))
        or _flag(route_policy.get("operator_model_override"))
    )


def _route_requested_model(
    route_model: str,
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
) -> tuple[str, bool, str]:
    selected = _clean(route_model)
    requested = _clean(options.model)
    if (
        requested
        and requested != selected
        and _route_lock_enabled(route_policy, options)
    ):
        return requested, True, "operator_route_lock"
    return selected, False, ""


def _verifier_required_for_completion(
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
) -> bool:
    return (
        _route_proof_required(route_policy, options)
        or _flag(route_policy.get("require_verifier_for_completion"))
        or _flag(options.metadata.get("require_verifier_for_completion"))
    )


def _receipt_completion_summary(
    *,
    route_receipt: dict[str, Any],
    audit: dict[str, Any],
    require_proof: bool,
    require_verifier: bool,
    verification_signal: str,
) -> dict[str, Any]:
    if not route_receipt:
        return {
            "gate_passed": not require_proof,
            "reason": "missing_route_receipt" if require_proof else "not_required",
        }
    if not require_proof and not require_verifier:
        return {
            "gate_passed": True,
            "reason": "not_required",
            "audit_status": _clean(audit.get("status")),
            "audit_failures": list(audit.get("failures") or []),
            "audit_warnings": list(audit.get("warnings") or []),
            "output_shape": _clean(route_receipt.get("output_shape")),
            "verifier_result": _clean(route_receipt.get("verifier_result")),
            "require_proof": require_proof,
            "require_verifier": require_verifier,
            "verification_signal": verification_signal,
        }
    gate_passed = receipt_completion_gate_passes(
        route_receipt,
        audit=audit,
        require_verifier=require_verifier,
    )
    return {
        "gate_passed": gate_passed,
        "reason": "pass" if gate_passed else "route_proof_gate_failed",
        "audit_status": _clean(audit.get("status")),
        "audit_failures": list(audit.get("failures") or []),
        "audit_warnings": list(audit.get("warnings") or []),
        "output_shape": _clean(route_receipt.get("output_shape")),
        "verifier_result": _clean(route_receipt.get("verifier_result")),
        "require_proof": require_proof,
        "require_verifier": require_verifier,
        "verification_signal": verification_signal,
    }


def _reasoning_tool_gate_required(
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
) -> bool:
    return (
        _flag(route_policy.get("reasoning_tool_gate_required"))
        or _flag(route_policy.get("require_reasoning_tool_gate"))
        or _flag(options.metadata.get("reasoning_tool_gate_required"))
        or _flag(options.metadata.get("require_reasoning_tool_gate"))
    )


def _reasoning_tool_gate_summary(
    *,
    reasoning_plan: dict[str, Any],
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
    invocation_id: str,
    adapter_name: str,
    model: str,
    route_receipt: dict[str, Any],
    receipt_audit: dict[str, Any],
    completion_gate: dict[str, Any],
    verification_signal: str,
) -> dict[str, Any]:
    tool_plan = (
        dict(reasoning_plan.get("tool_plan"))
        if isinstance(reasoning_plan.get("tool_plan"), dict)
        else {}
    )
    required_tools = [
        _clean(tool) for tool in list(tool_plan.get("required_tools") or []) if tool
    ]
    observed: list[dict[str, Any]] = [
        {
            "tool": "model_adapter.invoke",
            "status": "pass",
            "provider": adapter_name,
            "model": model,
            "invocation_id": invocation_id,
        }
    ]
    if route_receipt:
        observed.append(
            {
                "tool": "route_receipt_ledger",
                "status": "pass",
                "request_id": route_receipt.get("request_id"),
                "invocation_id": route_receipt.get("invocation_id") or invocation_id,
            }
        )
        if route_receipt.get("output_shape"):
            observed.append(
                {
                    "tool": "output_shape_validator",
                    "status": "pass"
                    if route_receipt.get("output_shape") == "complete"
                    else "fail",
                    "output_shape": route_receipt.get("output_shape"),
                }
            )
        if route_receipt.get("verifier_result") or verification_signal:
            observed.append(
                {
                    "tool": "verifier_result_normalizer",
                    "status": "pass",
                    "verifier_result": route_receipt.get("verifier_result"),
                    "verification_signal": verification_signal,
                }
            )
    if receipt_audit:
        observed.append(
            {
                "tool": "route_receipt_auditor",
                "status": "pass" if receipt_audit.get("pass") else "fail",
                "audit_status": receipt_audit.get("status"),
            }
        )
    if completion_gate:
        observed.append(
            {
                "tool": "completion_gate",
                "status": "pass" if completion_gate.get("gate_passed") else "fail",
                "reason": completion_gate.get("reason"),
            }
        )
    observed_names = {_clean(item.get("tool")) for item in observed}
    missing_required = [
        tool for tool in required_tools if tool and tool not in observed_names
    ]
    enforcement_required = _reasoning_tool_gate_required(route_policy, options)
    gate_passed = not missing_required
    completion_allowed = gate_passed or not enforcement_required
    verifier_result = "pass" if gate_passed else "missing_required_tools"
    return {
        "schema": "norman.reasoning-tool-gate.v1",
        "plan_id": reasoning_plan.get("plan_id"),
        "registry_version": reasoning_plan.get("registry_version"),
        "selected_skill_ids": list(reasoning_plan.get("selected_skill_ids") or []),
        "required_tools": required_tools,
        "observed_tools": observed,
        "observed_tool_names": sorted(observed_names),
        "missing_required_tools": missing_required,
        "enforcement_required": enforcement_required,
        "gate_passed": gate_passed,
        "completion_allowed": completion_allowed,
        "reason": "pass"
        if gate_passed
        else "missing_required_tools_required"
        if enforcement_required
        else "missing_required_tools_advisory",
        "reasoning_receipt": build_reasoning_receipt(
            reasoning_plan,
            executed_tools=observed,
            verifier_result=verifier_result,
        )
        if reasoning_plan
        else {},
    }


def _completion_requested_for_step(options: "ConsoleRuntimeRunOptions") -> bool:
    return bool(options.complete)


def _cloud_input_token_reserve(messages: list[dict[str, Any]]) -> int:
    """Return a conservative upper bound for text sent to a cloud provider."""

    text = "\n".join(str(message.get("content") or "") for message in messages)
    return len(text.encode("utf-8")) + CLOUD_TOKEN_REQUEST_OVERHEAD


def _cloud_budget_plan(
    *,
    route: Any,
    options: "ConsoleRuntimeRunOptions",
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    if options.dry_run or not bool(getattr(route, "cloud_proxy", False)):
        return {}

    configured_total = max(0, int(options.cloud_token_budget or 0))
    input_reserve = _cloud_input_token_reserve(messages)
    remaining_output = configured_total - input_reserve
    plan = {
        "configured_total_tokens": configured_total,
        "input_reserve_tokens": input_reserve,
        "request_overhead_tokens": CLOUD_TOKEN_REQUEST_OVERHEAD,
        "reserve_strategy": "utf8_bytes_plus_request_overhead",
    }
    if configured_total <= 0:
        return {
            **plan,
            "blocked": True,
            "reason": "cloud_token_budget_zero",
        }
    if remaining_output <= 0:
        return {
            **plan,
            "blocked": True,
            "reason": "cloud_token_budget_below_input_reserve",
            "remaining_output_tokens": 0,
        }
    return {
        **plan,
        "blocked": False,
        "remaining_output_tokens": remaining_output,
        "max_output_tokens": min(
            max(1, int(options.max_output_tokens or 1)),
            remaining_output,
        ),
    }


@dataclass
class ConsoleRuntimeRunOptions:
    worker_id: str = "runtime-api-worker"
    execution_mode: str = "standard"
    dry_run: bool = True
    complete: bool = True
    continuous: bool = False
    durable_workstream: bool = False
    max_steps: int = 1
    max_runtime_seconds: int = 0
    local_token_budget: int = 0
    cloud_token_budget: int = 0
    goal_phase_sequence: list[str] = field(default_factory=list)
    planner_kind: str = "plan"
    model: str = ""
    max_output_tokens: int = 1024
    route_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    include_capabilities: bool = True
    live_execution_approved: bool = False

    def __post_init__(self) -> None:
        self.worker_id = _clean(self.worker_id) or "runtime-api-worker"
        self.execution_mode = _clean(self.execution_mode).lower() or "standard"
        if self.execution_mode not in {"standard", ADVISORY_EXECUTION_MODE}:
            raise ValueError("execution_mode must be standard or advisory")
        self.durable_workstream = bool(self.durable_workstream)
        self.planner_kind = _clean(self.planner_kind) or "plan"
        self.model = _clean(self.model)
        self.max_steps = max(1, min(int(self.max_steps or 1), 50))
        self.max_runtime_seconds = max(0, int(self.max_runtime_seconds or 0))
        self.local_token_budget = max(0, int(self.local_token_budget or 0))
        self.cloud_token_budget = max(0, int(self.cloud_token_budget or 0))
        self.goal_phase_sequence = _goal_phase_sequence(
            self.goal_phase_sequence, self.planner_kind
        )
        self.max_output_tokens = max(1, int(self.max_output_tokens or 1))
        self.route_policy = dict(self.route_policy or {})
        self.metadata = dict(self.metadata or {})
        if self.execution_mode == ADVISORY_EXECUTION_MODE:
            if self.dry_run:
                raise ValueError("advisory execution cannot be dry_run")
            if self.live_execution_approved:
                raise ValueError(
                    "advisory execution cannot request live execution approval"
                )
            if self.continuous:
                raise ValueError("advisory execution cannot be continuous")
            if self.durable_workstream:
                raise ValueError("advisory execution cannot be a durable workstream")
            if self.max_steps != 1:
                raise ValueError("advisory execution requires max_steps=1")
            if self.include_capabilities:
                raise ValueError(
                    "advisory execution cannot include capability discovery"
                )
            if self.cloud_token_budget != 0:
                raise ValueError("advisory execution requires cloud_token_budget=0")
            if self.planner_kind != "chat":
                raise ValueError("advisory execution requires planner_kind=chat")
            if self.goal_phase_sequence != ["chat"]:
                raise ValueError(
                    "advisory execution requires goal_phase_sequence=['chat']"
                )
            self.dry_run = False
            self.complete = True
            self.continuous = False
            self.durable_workstream = False
            self.max_steps = 1
            self.cloud_token_budget = 0
            self.planner_kind = "chat"
            self.goal_phase_sequence = ["chat"]
            self.include_capabilities = False
            self.live_execution_approved = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DbConsoleRuntimeWorker:
    """Run one DB-backed console runtime work step."""

    def __init__(self, store: DbConsoleRuntimeStore | None = None) -> None:
        self.store = store or DbConsoleRuntimeStore()

    @staticmethod
    def _attempt_tokens(job: Any) -> tuple[str, int | None]:
        lease = getattr(job, "lease", None)
        attempt_id = _clean(getattr(lease, "attempt_id", ""))
        if not attempt_id:
            return "", None
        return attempt_id, max(0, int(getattr(lease, "lease_epoch", 0) or 0))

    @staticmethod
    def _requires_verification_receipt(job: Any) -> bool:
        contract = getattr(job, "contract", None)
        values = (
            getattr(contract, "route_policy", {}),
            getattr(contract, "metadata", {}),
            getattr(contract, "authority_flags", {}),
            getattr(job, "metadata", {}),
        )
        return any(
            _flag(value.get(key))
            for value in values
            if isinstance(value, dict)
            for key in (
                "require_verification_receipt",
                "require_verifier_for_completion",
                "verification_required",
            )
        )

    @staticmethod
    def _is_durable_workstream(
        job: Any, options: ConsoleRuntimeRunOptions | None = None
    ) -> bool:
        """Return whether this run must finish through an explicit verifier."""

        if options is not None and options.durable_workstream:
            return True
        contract = getattr(job, "contract", None)
        if bool(getattr(contract, "durable_workstream", False)):
            return True
        values = (
            getattr(contract, "route_policy", {}),
            getattr(contract, "metadata", {}),
            getattr(contract, "authority_flags", {}),
            getattr(job, "metadata", {}),
        )
        return any(
            _flag(value.get("durable_workstream"))
            for value in values
            if isinstance(value, dict)
        )

    @staticmethod
    def _checkpoint_facts(
        job: Any,
        *,
        phase: str,
        durable_workstream: bool,
        verification_signal: str,
    ) -> list[str]:
        """Build durable checkpoint facts from the active work state."""

        facts = [
            "A bounded runtime attempt completed.",
            f"Worker: {_clean(getattr(getattr(job, 'lease', None), 'worker_id', ''))}",
        ]
        if phase:
            facts.append(f"Phase: {phase}")
        if durable_workstream:
            verifier_state = verification_signal or "pending"
            facts.append(f"Verifier state: {verifier_state}")
        return facts

    @staticmethod
    def _checkpoint_next_safe_action(*, phase: str, durable_workstream: bool) -> str:
        """Describe the safe next action for a checkpointed work item."""

        if not durable_workstream:
            return "Resume from this checkpoint with the active route policy."
        if phase == "verify":
            return (
                "Resolve remaining verification criteria, then emit "
                "STATUS: COMPLETE from the verifier."
            )
        return (
            "Continue the durable workstream from the recorded phase; do not "
            "mark it done before verifier completion."
        )

    @staticmethod
    def _checkpoint_capsule(
        job: Any,
        *,
        summary: str,
        attempt_id: str,
        lease_epoch: int | None,
        route_receipt: dict[str, Any] | None = None,
        completed_clauses: list[str] | None = None,
        goal_phase: str = "",
        verification_signal: str = "",
        progress_fingerprint: str = "",
        durable_workstream: bool | None = None,
    ) -> ConsoleCheckpointCapsule:
        receipt = dict(route_receipt or {})
        receipt_ref = _clean(
            receipt.get("request_id")
            or receipt.get("client_request_id")
            or receipt.get("invocation_id")
        )
        durable_workstream = (
            DbConsoleRuntimeWorker._is_durable_workstream(job)
            if durable_workstream is None
            else durable_workstream
        )
        phase = _clean(goal_phase)
        verifier_state = _clean(verification_signal) or "pending"
        remaining_clauses = list(getattr(job.contract, "done_when", []) or [])
        return ConsoleCheckpointCapsule(
            summary=summary,
            facts=DbConsoleRuntimeWorker._checkpoint_facts(
                job,
                phase=phase,
                durable_workstream=durable_workstream,
                verification_signal=verifier_state,
            ),
            evidence_refs=[receipt_ref] if receipt_ref else [],
            completed_clauses=list(completed_clauses or []),
            remaining_clauses=remaining_clauses,
            next_safe_action=DbConsoleRuntimeWorker._checkpoint_next_safe_action(
                phase=phase,
                durable_workstream=durable_workstream,
            ),
            route_receipt_ref=receipt_ref,
            approval_state=getattr(getattr(job, "status", None), "value", "")
            or _clean(getattr(job, "status", "")),
            attempt_id=attempt_id,
            lease_epoch=lease_epoch or 0,
            trace_id=_clean(getattr(job, "metadata", {}).get("trace_id")),
            progress_fingerprint=progress_fingerprint,
        )

    def _finalize_cancellation_if_requested(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        options: ConsoleRuntimeRunOptions,
        reason: str,
        effect_key: str = "",
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> dict[str, Any] | None:
        job = self.store.get_job(db, user_id=user_id, job_id=job_id)
        status = getattr(job.status, "value", job.status)
        if status != ConsoleJobStatus.CANCELED.value and not job.cancel_requested_at:
            return None
        normalized_effect_key = _clean(effect_key)
        if normalized_effect_key:
            effect = self.store.get_effect(
                db,
                user_id=user_id,
                job_id=job_id,
                effect_key=normalized_effect_key,
            )
            if effect is not None and effect.state in {"planned", "started"}:
                self.store.fail_effect(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    effect_key=normalized_effect_key,
                    error=reason or "Cancellation requested before effect invocation",
                    attempt_id=(
                        attempt_id if status != ConsoleJobStatus.CANCELED.value else ""
                    ),
                    lease_epoch=(
                        lease_epoch
                        if status != ConsoleJobStatus.CANCELED.value
                        else None
                    ),
                )
        finalized = self.store.finalize_cancel_requested(
            db,
            user_id=user_id,
            job_id=job_id,
            reason=reason,
        )
        finalized_status = getattr(finalized.status, "value", finalized.status)
        if finalized_status != ConsoleJobStatus.CANCELED.value:
            return None
        snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        return {
            "job": finalized.as_dict(),
            "model_result": None,
            "snapshot": snapshot,
            "dry_run": options.dry_run,
            "worker_id": options.worker_id,
            "canceled": True,
        }

    def run_once(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        options: ConsoleRuntimeRunOptions | None = None,
        adapter: ModelAdapter | None = None,
    ) -> dict[str, Any]:
        opts = options or ConsoleRuntimeRunOptions()
        job = self.store.get_job(db, user_id=user_id, job_id=job_id)
        if opts.execution_mode == ADVISORY_EXECUTION_MODE:
            invalid_reason = _advisory_invalid_reason(job, opts)
            if invalid_reason:
                raise ValueError(invalid_reason)
        canceled = self._finalize_cancellation_if_requested(
            db,
            user_id=user_id,
            job_id=job_id,
            options=opts,
            reason="Cancellation requested before runtime execution",
        )
        if canceled is not None:
            return canceled
        if job.status in {ConsoleJobStatus.QUEUED, ConsoleJobStatus.CHECKPOINTED}:
            job = self.store.lease_job(
                db,
                user_id=user_id,
                job_id=job_id,
                worker_id=opts.worker_id,
                lease_seconds=job.contract.checkpoint_interval_seconds,
            )
            canceled = self._finalize_cancellation_if_requested(
                db,
                user_id=user_id,
                job_id=job_id,
                options=opts,
                reason="Cancellation requested after runtime lease",
            )
            if canceled is not None:
                return canceled
        if job.status in {ConsoleJobStatus.LEASED, ConsoleJobStatus.CHECKPOINTED}:
            attempt_id, lease_epoch = self._attempt_tokens(job)
            job = self.store.start_job(
                db,
                user_id=user_id,
                job_id=job_id,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            canceled = self._finalize_cancellation_if_requested(
                db,
                user_id=user_id,
                job_id=job_id,
                options=opts,
                reason="Cancellation requested after runtime start",
            )
            if canceled is not None:
                return canceled
        attempt_id, lease_epoch = self._attempt_tokens(job)
        if opts.execution_mode == ADVISORY_EXECUTION_MODE:
            return self._run_advisory_once(
                db,
                user_id=user_id,
                job_id=job_id,
                job=job,
                options=opts,
                adapter=adapter,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )

        route_policy = _local_first_route_policy(
            _merge_dicts(job.contract.route_policy, opts.route_policy)
        )
        initial_task_kind = _goal_task_kind(
            _clean(opts.metadata.get("goal_task_kind"))
            or _clean(opts.metadata.get("goal_phase"))
            or opts.planner_kind,
            opts.planner_kind,
        )
        (
            reasoning_classification,
            work_classification,
            reasoning_plan,
            reasoning_receipt,
        ) = _runtime_reasoning_plan(
            job=job,
            route_policy=route_policy,
            options=opts,
            task_kind=initial_task_kind,
        )
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="behavior.observed",
            payload={
                "phase": "runtime_worker",
                "goal_phase": _clean(opts.metadata.get("goal_phase")),
                "goal_task_kind": _clean(opts.metadata.get("goal_task_kind"))
                or opts.planner_kind,
                "worker_id": opts.worker_id,
                "dry_run": opts.dry_run,
                "reasoning_classification": reasoning_classification,
                "work_classification": work_classification,
                "reasoning_orchestration": reasoning_plan,
                "reasoning_receipt": reasoning_receipt,
            },
            summary="Runtime worker accepted job.",
            detail=job.contract.objective,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )

        if "recent_route_outcomes" not in route_policy:
            route_policy["recent_route_outcomes"] = self.store.route_outcomes(
                db,
                user_id=user_id,
                limit=200,
            )
        policy_state = resolve_runtime_mode(route_policy)
        self.store.record_policy_state(
            db,
            user_id=user_id,
            job_id=job_id,
            policy_state=policy_state,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )

        if not opts.dry_run and not self._live_execution_allowed(opts):
            reason = (
                "Live console-runtime execution requires explicit operator approval."
            )
            held = self.store.require_approval(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                requested_by=opts.worker_id,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": held.as_dict(),
                "model_result": None,
                "snapshot": snapshot,
                "dry_run": opts.dry_run,
                "worker_id": opts.worker_id,
                "approval_required": True,
                "approval_reason": reason,
            }

        if self._wants_shell(route_policy, opts):
            return self._run_shell_once(
                db,
                user_id=user_id,
                job_id=job_id,
                job=job,
                options=opts,
                route_policy=route_policy,
                policy_state=policy_state,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )

        task_kind = initial_task_kind
        task = NorllamaTaskRequest(
            kind=task_kind,
            input_text=job.contract.objective,
            route_policy=route_policy,
            metadata={
                "console_runtime_job_id": job_id,
                "worker_id": opts.worker_id,
                "goal_task_kind": task_kind,
                **opts.metadata,
            },
        )
        route = route_task(task)
        work_classification = _runtime_work_classification(
            classification=reasoning_classification,
            route_policy=route_policy,
            options=opts,
            context=_merge_dicts(
                job.metadata,
                job.contract.metadata,
                opts.metadata,
            ),
            task_kind=task_kind,
            selected_provider=route.provider,
        )
        reasoning_plan = {
            **reasoning_plan,
            "work_classification": work_classification,
        }
        reasoning_receipt = build_reasoning_receipt(reasoning_plan)
        receipt = build_task_receipt(
            task,
            route,
            status="accepted",
            metadata={
                "worker_id": opts.worker_id,
                "goal_phase": _clean(opts.metadata.get("goal_phase")),
                **opts.metadata,
            },
        )

        model_adapter = adapter or self._default_adapter(
            opts,
            job.contract.objective,
            route=route,
        )
        capabilities = {}
        if opts.include_capabilities:
            try:
                capabilities = model_adapter.capabilities.as_dict()
            except Exception as exc:
                capabilities = {
                    "provider": getattr(model_adapter, "name", ""),
                    "error": str(exc),
                }

        decision = route_decision(
            task_kind=task_kind,
            route=route,
            policy_state=policy_state,
            runner=getattr(model_adapter, "name", ""),
            capabilities=capabilities,
            metadata={
                "source": "runtime_worker",
                "worker_id": opts.worker_id,
                "route_policy": route_policy,
                "goal_phase": _clean(opts.metadata.get("goal_phase")),
                "goal_task_kind": _clean(opts.metadata.get("goal_task_kind"))
                or task_kind,
                "model_family": self._model_family(route.model),
                "reasoning_plan_id": reasoning_plan.get("plan_id"),
                "selected_skill_ids": list(
                    reasoning_plan.get("selected_skill_ids") or []
                ),
                "tool_plan": reasoning_plan.get("tool_plan") or {},
                "work_classification": work_classification,
            },
        )
        self.store.record_route_decision(
            db,
            user_id=user_id,
            job_id=job_id,
            decision=decision,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        if not decision.allowed:
            reason = "; ".join(decision.blocked_reasons) or "runtime route blocked"
            self.store.record_policy_block(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                policy_state=policy_state,
                metadata={"decision_id": decision.decision_id},
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            blocked = self.store.block_job(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": blocked.as_dict(),
                "model_result": None,
                "snapshot": snapshot,
                "dry_run": opts.dry_run,
                "worker_id": opts.worker_id,
                "route_blocked": True,
                "blocked_reason": reason,
            }

        self.store.record_planner_receipt(
            db,
            user_id=user_id,
            job_id=job_id,
            receipt=receipt.as_dict(),
            capabilities=capabilities,
            metadata={"source": "runtime_worker", "worker_id": opts.worker_id},
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )

        goal_phase = _clean(opts.metadata.get("goal_phase")) or opts.planner_kind
        goal_step = _clean(opts.metadata.get("goal_step")) or "1"
        invocation_id = ":".join(
            part
            for part in (
                opts.worker_id,
                job_id,
                goal_phase,
                goal_step,
                "model",
            )
            if part
        )
        session_name = _clean(
            opts.metadata.get("session_name")
            or opts.metadata.get("console_runtime_session")
            or job.metadata.get("session_name")
            or job.contract.metadata.get("session_name")
            or job.contract.authority_flags.get("session_name")
        )
        completion_requested = _completion_requested_for_step(opts)
        durable_workstream = self._is_durable_workstream(job, opts)
        verifier_required = bool(
            completion_requested
            and _verifier_required_for_completion(route_policy, opts)
        )
        requested_model, model_override_used, model_override_reason = (
            _route_requested_model(route.model, route_policy, opts)
        )
        route_payload = route.as_dict()
        messages = [
            {
                "role": "system",
                "content": self._system_prompt_for_phase(goal_phase),
            },
            {
                "role": "user",
                "content": self._phase_user_prompt(
                    db,
                    user_id=user_id,
                    job=job,
                    phase=goal_phase,
                    durable_workstream=durable_workstream,
                ),
            },
        ]
        cloud_budget = _cloud_budget_plan(
            route=route,
            options=opts,
            messages=messages,
        )
        if cloud_budget.get("blocked"):
            reason = (
                "Cloud token budget blocked provider invocation: "
                f"{cloud_budget['reason']}"
            )
            self.store.record_policy_block(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                policy_state=policy_state,
                metadata={
                    "decision_id": decision.decision_id,
                    "cloud_budget": cloud_budget,
                },
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="policy.cloud_budget_blocked",
                payload={
                    "reason": cloud_budget["reason"],
                    "cloud_budget": cloud_budget,
                    "route": route_payload,
                },
                summary="Cloud token budget blocked provider invocation.",
                detail=reason,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            blocked = self.store.block_job(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": blocked.as_dict(),
                "model_result": None,
                "snapshot": snapshot,
                "dry_run": opts.dry_run,
                "worker_id": opts.worker_id,
                "route_blocked": True,
                "blocked_reason": reason,
                "cloud_budget": cloud_budget,
            }

        request = ModelRequest(
            messages=messages,
            model=requested_model,
            route_key=route.lane,
            budget=ModelBudget(
                max_runtime_seconds=opts.max_runtime_seconds
                or job.contract.max_runtime_seconds,
                max_output_tokens=cloud_budget.get(
                    "max_output_tokens", opts.max_output_tokens
                ),
            ),
            metadata={
                **opts.metadata,
                "route_policy": route_policy,
                "norllama_route": route_payload,
                "norllama_task_kind": task_kind,
                "route_selected_model": route.model,
                "requested_model": requested_model,
                "model_override_used": model_override_used,
                "model_override_reason": model_override_reason,
                "route_source": "runtime_worker",
                "route_decision_id": decision.decision_id,
                "reasoning_plan_id": reasoning_plan.get("plan_id"),
                "reasoning_orchestration": reasoning_plan,
                "work_classification": work_classification,
                "selected_skill_ids": list(
                    reasoning_plan.get("selected_skill_ids") or []
                ),
                "required_tools": list(
                    (reasoning_plan.get("tool_plan") or {}).get("required_tools") or []
                ),
                "verification_tools": list(
                    (reasoning_plan.get("tool_plan") or {}).get("verification_tools")
                    or []
                ),
                "runtime_job_id": job_id,
                "console_runtime_job_id": job_id,
                "trace_id": _clean(job.metadata.get("trace_id")),
                "attempt_id": attempt_id,
                "lease_epoch": lease_epoch or 0,
                "worker_id": opts.worker_id,
                "invocation_id": invocation_id,
                "request_id": invocation_id,
                "console_runtime_session": session_name,
                "session_name": session_name,
                "execution_mode": "dry_run" if opts.dry_run else "live",
                "model_timeout_seconds": route_policy.get("model_timeout_seconds")
                or route_policy.get("provider_timeout_seconds"),
                "completion_requested": completion_requested,
                "require_verifier_for_completion": verifier_required,
                "cloud_budget": cloud_budget,
            },
        )
        effect_key = f"{attempt_id}:{invocation_id}"
        effect, should_invoke = self.store.begin_effect(
            db,
            user_id=user_id,
            job_id=job_id,
            effect_key=effect_key,
            kind="model.invoke",
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
            preconditions={
                "provider": model_adapter.name,
                "model": request.model,
                "route_key": request.route_key,
                "invocation_id": invocation_id,
            },
        )
        if not should_invoke:
            reconciliation_summary = (
                "Runtime worker checkpointed because a model invocation was "
                "already reserved for this attempt."
            )
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="effect.reconciliation_required",
                payload={
                    "effect": effect.as_dict(),
                    "invocation_id": invocation_id,
                    "reason": "duplicate model invocation reservation",
                },
                summary="Model effect reconciliation required",
                detail=effect.state,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            checkpointed = self.store.checkpoint_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary=reconciliation_summary,
                capsule=self._checkpoint_capsule(
                    job,
                    summary=reconciliation_summary,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                    route_receipt={"invocation_id": invocation_id},
                    durable_workstream=self._is_durable_workstream(job, opts),
                ),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": checkpointed.as_dict(),
                "model_result": None,
                "snapshot": snapshot,
                "dry_run": opts.dry_run,
                "worker_id": opts.worker_id,
                "effect_reconciliation_required": True,
                "effect": effect.as_dict(),
            }
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="tool.started",
            payload={
                "invocation_id": invocation_id,
                "tool_name": "model_adapter.invoke",
                "provider": model_adapter.name,
                "model": request.model,
                "reasoning_plan_id": reasoning_plan.get("plan_id"),
                "selected_skill_ids": list(
                    reasoning_plan.get("selected_skill_ids") or []
                ),
                "required_tools": list(
                    (reasoning_plan.get("tool_plan") or {}).get("required_tools") or []
                ),
                "verification_tools": list(
                    (reasoning_plan.get("tool_plan") or {}).get("verification_tools")
                    or []
                ),
                "work_classification": work_classification,
            },
            summary=f"Started {model_adapter.name}",
            detail=request.route_key,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="model.requested",
            payload={
                "provider": model_adapter.name,
                "model": request.model,
                "route_key": request.route_key,
                "cloud_budget": cloud_budget,
                "reasoning_plan_id": reasoning_plan.get("plan_id"),
                "selected_skill_ids": list(
                    reasoning_plan.get("selected_skill_ids") or []
                ),
                "max_tool_iterations": (reasoning_plan.get("tool_plan") or {}).get(
                    "max_tool_iterations"
                ),
                "work_classification": work_classification,
            },
            summary=f"Requested {model_adapter.name}",
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )

        canceled = self._finalize_cancellation_if_requested(
            db,
            user_id=user_id,
            job_id=job_id,
            options=opts,
            reason="Cancellation requested before model invocation",
            effect_key=effect_key,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        if canceled is not None:
            return canceled
        try:
            result = model_adapter.invoke(request)
        except Exception as exc:
            error = str(exc)
            self.store.fail_effect(
                db,
                user_id=user_id,
                job_id=job_id,
                effect_key=effect_key,
                error=error,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            failed_receipt = build_task_receipt(
                task,
                route,
                status="failed",
                error=error,
                metadata={
                    "invocation_id": invocation_id,
                    "worker_id": opts.worker_id,
                    "failure_class": "model_adapter_failed",
                },
            )
            failed_route_receipt = failed_receipt.metadata["route_receipt"]
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="model.failed",
                payload={
                    "provider": model_adapter.name,
                    "error": error,
                    "route": route_payload,
                    "route_receipt": failed_route_receipt,
                    "work_classification": work_classification,
                },
                summary=f"{model_adapter.name} failed",
                detail=error,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="tool.failed",
                payload={
                    "invocation_id": invocation_id,
                    "tool_name": "model_adapter.invoke",
                    "error": error,
                    "work_classification": work_classification,
                },
                summary="Model adapter failed",
                detail=error,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            failed_job = self.store.fail_job(
                db,
                user_id=user_id,
                job_id=job_id,
                error=error,
                retry_class=RetryClass.TRANSIENT_TRANSPORT,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": failed_job.as_dict(),
                "model_result": None,
                "snapshot": snapshot,
                "dry_run": opts.dry_run,
                "worker_id": opts.worker_id,
                "model_failed": True,
                "error": error,
                "failure_class": "model_adapter_failed",
                "route_receipt": failed_route_receipt,
            }

        goal_phase = (
            _clean(opts.metadata.get("goal_phase")) or opts.planner_kind
        ).lower()
        verification_signal = ""
        if goal_phase == "literal_response" and not durable_workstream:
            verification_signal = _literal_response_signal(
                job.contract.objective,
                result.text,
            )
        elif (
            self._verifier_can_stop(job, route_policy, opts) and goal_phase == "verify"
        ):
            if durable_workstream:
                verification_signal = _durable_verification_signal(result.text)
            else:
                verification_signal = _verification_signal(result.text)
                structured_signal = _structured_response_signal(
                    job.contract.objective,
                    result.text,
                )
                if structured_signal == "needs_more_work":
                    structured_candidate = self._structured_candidate_from_history(
                        db,
                        user_id=user_id,
                        job_id=job_id,
                        objective=job.contract.objective,
                    )
                    if structured_candidate:
                        result.text = structured_candidate
                        verification_signal = "complete"
                    else:
                        verification_signal = "needs_more_work"
                elif not verification_signal:
                    verification_signal = structured_signal
        result_route_receipt = _route_receipt_from_result(result)
        self.store.complete_effect(
            db,
            user_id=user_id,
            job_id=job_id,
            effect_key=effect_key,
            receipt={
                "invocation_id": invocation_id,
                "provider": result.provider or model_adapter.name,
                "model": result.model or request.model,
                "stop_reason": result.stop_reason,
                "usage": result.usage.as_dict(),
                "route_receipt": result_route_receipt,
            },
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        self._record_model_result(
            db,
            user_id=user_id,
            job_id=job_id,
            invocation_id=invocation_id,
            adapter_name=model_adapter.name,
            result=result,
            verification_signal=verification_signal,
            reasoning_plan=reasoning_plan,
            task_contract=job.contract.as_dict(),
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        route_receipt = result_route_receipt
        if route_receipt:
            route_receipt = {
                **route_receipt,
                "invocation_id": route_receipt.get("invocation_id") or invocation_id,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "total_tokens": result.usage.total_tokens,
            }
        require_proof = durable_workstream or _route_proof_required(route_policy, opts)
        require_verifier = verifier_required

        if verification_signal:
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="verification.completed"
                if verification_signal == "complete"
                else "verification.needs_more_work",
                payload={
                    "signal": verification_signal,
                    "phase": goal_phase,
                    "output_preview": _preview(result.text, 800),
                    "worker_id": opts.worker_id,
                },
                summary="Verifier marked goal complete"
                if verification_signal == "complete"
                else "Verifier requested more local work",
                detail=_preview(result.text, 800),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        if route_receipt:
            route_receipt = normalize_route_receipt_for_completion_gate(
                route_receipt,
                verification_signal=verification_signal,
            )
            receipt_audit = _receipt_audit(route_receipt)
            route_receipt["receipt_audit"] = receipt_audit
            route_receipt["fast_lane_outcome"] = evaluate_fast_lane_outcome(
                route_receipt,
                task_contract=job.contract.as_dict(),
                audit=receipt_audit,
            )
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="route.receipt_audited",
                payload={
                    "route_receipt": route_receipt,
                    "receipt_audit": receipt_audit,
                    "fast_lane_outcome": route_receipt["fast_lane_outcome"],
                    "request_id": route_receipt.get("request_id"),
                    "client_request_id": route_receipt.get("client_request_id"),
                    "gateway_request_id": route_receipt.get("gateway_request_id"),
                    "invocation_id": route_receipt.get("invocation_id"),
                    "selected_provider": route_receipt.get("selected_provider"),
                    "selected_model": route_receipt.get("selected_model"),
                    "target_model": route_receipt.get("target_model"),
                    "effective_runtime_model": route_receipt.get(
                        "effective_runtime_model"
                    ),
                    "selected_worker": route_receipt.get("selected_worker"),
                    "observed_worker": route_receipt.get("observed_worker"),
                    "usage_bucket": route_receipt.get("usage_bucket"),
                    "output_shape": route_receipt.get("output_shape"),
                    "verifier_result": route_receipt.get("verifier_result"),
                    "route_proof_required": require_proof,
                    "verifier_required": require_verifier,
                },
                summary=(
                    "Route receipt audit passed"
                    if receipt_audit.get("pass")
                    else "Route receipt audit failed"
                ),
                detail="; ".join(receipt_audit.get("failures") or []),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        else:
            receipt_audit = {}

        refreshed = self.store.get_job(db, user_id=user_id, job_id=job_id)
        missing = [
            artifact
            for artifact in refreshed.contract.required_artifacts
            if artifact not in set(refreshed.artifacts)
        ]
        completion_gate = _receipt_completion_summary(
            route_receipt=route_receipt,
            audit=receipt_audit,
            require_proof=require_proof,
            require_verifier=require_verifier,
            verification_signal=verification_signal,
        )
        if route_receipt or require_proof:
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="route.completion_gate",
                payload={
                    "route_receipt": route_receipt,
                    "receipt_audit": receipt_audit,
                    "completion_gate": completion_gate,
                    "fast_lane_outcome": (
                        route_receipt.get("fast_lane_outcome")
                        if isinstance(route_receipt, dict)
                        else {}
                    ),
                    "request_id": route_receipt.get("request_id")
                    if isinstance(route_receipt, dict)
                    else "",
                    "client_request_id": route_receipt.get("client_request_id")
                    if isinstance(route_receipt, dict)
                    else "",
                    "gateway_request_id": route_receipt.get("gateway_request_id")
                    if isinstance(route_receipt, dict)
                    else "",
                    "invocation_id": route_receipt.get("invocation_id")
                    if isinstance(route_receipt, dict)
                    else "",
                    "route_proof_required": require_proof,
                    "verifier_required": require_verifier,
                },
                summary=(
                    "Route proof completion gate passed"
                    if completion_gate.get("gate_passed")
                    else "Route proof completion gate failed"
                ),
                detail=completion_gate.get("reason", ""),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        reasoning_tool_gate = _reasoning_tool_gate_summary(
            reasoning_plan=reasoning_plan,
            route_policy=route_policy,
            options=opts,
            invocation_id=invocation_id,
            adapter_name=model_adapter.name,
            model=result.model,
            route_receipt=route_receipt if isinstance(route_receipt, dict) else {},
            receipt_audit=receipt_audit,
            completion_gate=completion_gate,
            verification_signal=verification_signal,
        )
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="reasoning.tool_gate",
            payload=reasoning_tool_gate,
            summary=(
                "Reasoning tool gate passed"
                if reasoning_tool_gate["gate_passed"]
                else "Reasoning tool gate missing required evidence"
            ),
            detail=reasoning_tool_gate["reason"],
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        canceled = self._finalize_cancellation_if_requested(
            db,
            user_id=user_id,
            job_id=job_id,
            options=opts,
            reason="Cancellation requested before runtime finalization",
        )
        if canceled is not None:
            return canceled
        verification_receipt_ready = (
            not self._requires_verification_receipt(job)
            or verification_signal == "complete"
        )
        should_complete_from_verifier = (
            verification_signal == "complete"
            and not missing
            and completion_gate["gate_passed"]
            and reasoning_tool_gate["completion_allowed"]
            and verification_receipt_ready
        )
        should_complete_from_step = (
            opts.complete
            and not durable_workstream
            and not missing
            and verification_signal != "needs_more_work"
            and completion_gate["gate_passed"]
            and reasoning_tool_gate["completion_allowed"]
            and verification_receipt_ready
        )
        if (self._requires_verification_receipt(job) or durable_workstream) and (
            should_complete_from_verifier or should_complete_from_step
        ):
            evidence_refs = [invocation_id]
            if isinstance(route_receipt, dict):
                route_reference = _clean(
                    route_receipt.get("request_id")
                    or route_receipt.get("client_request_id")
                    or route_receipt.get("gateway_request_id")
                )
                if route_reference:
                    evidence_refs.append(route_reference)
            self.store.record_verification(
                db,
                user_id=user_id,
                job_id=job_id,
                receipt=ConsoleVerificationReceipt(
                    verifier="runtime_worker",
                    status="pass",
                    evidence_refs=evidence_refs,
                    metadata={
                        "verification_signal": verification_signal,
                        "completion_gate": completion_gate,
                        "reasoning_tool_gate": reasoning_tool_gate,
                    },
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch or 0,
                    trace_id=_clean(job.metadata.get("trace_id")),
                ),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        if should_complete_from_verifier:
            final_job = self.store.complete_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary="Runtime verifier marked goal complete.",
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        elif should_complete_from_step:
            final_job = self.store.complete_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary="Runtime worker completed one model step.",
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        else:
            if durable_workstream:
                checkpoint_reason = (
                    "Durable workstream checkpointed pending explicit verifier "
                    "completion."
                )
            elif not reasoning_tool_gate["completion_allowed"]:
                checkpoint_reason = (
                    "Runtime worker checkpointed after reasoning tool gate."
                )
            elif not completion_gate["gate_passed"] and (
                require_proof or route_receipt
            ):
                checkpoint_reason = (
                    "Runtime worker checkpointed after route-proof gate."
                )
            else:
                checkpoint_reason = "Runtime worker checkpointed after one model step."
            final_job = self.store.checkpoint_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary=checkpoint_reason,
                capsule=self._checkpoint_capsule(
                    job,
                    summary=checkpoint_reason,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                    route_receipt=route_receipt,
                    completed_clauses=(
                        list(job.contract.done_when)
                        if verification_signal == "complete"
                        else []
                    ),
                    goal_phase=goal_phase,
                    verification_signal=verification_signal,
                    progress_fingerprint=_progress_fingerprint(result.text, goal_phase),
                    durable_workstream=durable_workstream,
                ),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )

        snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        return {
            "job": final_job.as_dict(),
            "model_result": result.as_dict(),
            "snapshot": snapshot,
            "dry_run": opts.dry_run,
            "worker_id": opts.worker_id,
            "durable_workstream": durable_workstream,
            "verification_signal": verification_signal,
            "route_proof": completion_gate,
            "reasoning_orchestration": reasoning_plan,
            "reasoning_receipt": reasoning_receipt,
            "reasoning_tool_gate": reasoning_tool_gate,
        }

    def run_continuous(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        options: ConsoleRuntimeRunOptions | None = None,
        adapter: ModelAdapter | None = None,
    ) -> dict[str, Any]:
        opts = options or ConsoleRuntimeRunOptions(continuous=True)
        if opts.execution_mode == ADVISORY_EXECUTION_MODE:
            raise ValueError("advisory execution cannot run continuously")
        opts = replace(opts, continuous=True)
        job = self.store.get_job(db, user_id=user_id, job_id=job_id)
        durable_workstream = self._is_durable_workstream(job, opts)
        max_runtime_seconds = (
            opts.max_runtime_seconds or job.contract.max_runtime_seconds
        )
        started = time.monotonic()
        stop_reason = ""
        steps: list[dict[str, Any]] = []
        local_tokens = 0
        cloud_tokens = 0
        cloud_evidence = self._cloud_evidence_count(
            self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        )

        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="goal.started",
            payload={
                "worker_id": opts.worker_id,
                "dry_run": opts.dry_run,
                "max_steps": opts.max_steps,
                "max_runtime_seconds": max_runtime_seconds,
                "local_token_budget": opts.local_token_budget,
                "cloud_token_budget": opts.cloud_token_budget,
                "goal_phase_sequence": list(opts.goal_phase_sequence),
                "durable_workstream": durable_workstream,
                "local_first": True,
            },
            summary="Goal loop started",
            detail=job.contract.objective,
        )

        last_result: dict[str, Any] | None = None
        previous_progress_fingerprint = ""
        previous_verification_signal = ""
        for step_index in range(1, opts.max_steps + 1):
            canceled = self._finalize_cancellation_if_requested(
                db,
                user_id=user_id,
                job_id=job_id,
                options=opts,
                reason="Cancellation requested during goal loop",
            )
            if canceled is not None:
                last_result = canceled
                stop_reason = ConsoleJobStatus.CANCELED.value
                break
            if time.monotonic() - started > max_runtime_seconds:
                stop_reason = "runtime_budget"
                break

            current = self.store.get_job(db, user_id=user_id, job_id=job_id)
            current_status = str(
                current.status.value
                if hasattr(current.status, "value")
                else current.status
            )
            if current_status in GOAL_LOOP_TERMINAL_STATUSES:
                stop_reason = current_status
                break

            goal_phase = _goal_phase_for_step(
                opts.goal_phase_sequence, step_index, opts.max_steps
            )
            goal_task_kind = _goal_task_kind(goal_phase, opts.planner_kind)
            remaining_cloud_budget = (
                max(0, opts.cloud_token_budget - cloud_tokens)
                if opts.cloud_token_budget
                else 0
            )
            step_options = replace(
                opts,
                complete=bool(
                    opts.complete
                    and not durable_workstream
                    and step_index >= opts.max_steps
                ),
                continuous=False,
                planner_kind=goal_task_kind,
                cloud_token_budget=remaining_cloud_budget,
                metadata={
                    **opts.metadata,
                    "goal_loop": True,
                    "goal_step": step_index,
                    "goal_max_steps": opts.max_steps,
                    "goal_phase": goal_phase,
                    "goal_task_kind": goal_task_kind,
                },
            )
            result = self.run_once(
                db,
                user_id=user_id,
                job_id=job_id,
                options=step_options,
                adapter=adapter,
            )
            last_result = result
            usage = self._result_usage(result)
            snapshot = result.get("snapshot") if isinstance(result, dict) else {}
            latest_cloud_evidence = self._cloud_evidence_count(snapshot)
            step_cloud = latest_cloud_evidence > cloud_evidence
            cloud_evidence = latest_cloud_evidence
            if step_cloud:
                cloud_tokens += usage
            else:
                local_tokens += usage

            status = str((result.get("job") or {}).get("status", ""))
            result_text = str((result.get("model_result") or {}).get("text") or "")
            progress_fingerprint = _progress_fingerprint(result_text, goal_phase)
            verification_signal = _clean(result.get("verification_signal"))
            repeated_output = bool(
                progress_fingerprint
                and progress_fingerprint == previous_progress_fingerprint
            )
            repeated_needs_more_work = (
                verification_signal == "needs_more_work"
                and previous_verification_signal == "needs_more_work"
            )
            no_progress = durable_workstream and (
                repeated_output or repeated_needs_more_work
            )
            step_summary = {
                "step": step_index,
                "phase": goal_phase,
                "task_kind": goal_task_kind,
                "status": status,
                "progress_fingerprint": progress_fingerprint,
                "verification_signal": verification_signal,
                "stop_flags": {
                    "approval_required": bool(result.get("approval_required")),
                    "route_blocked": bool(result.get("route_blocked")),
                    "cloud_evidence": step_cloud,
                    "no_progress": no_progress,
                },
                "usage": {
                    "step_tokens": usage,
                    "local_tokens": local_tokens,
                    "cloud_tokens": cloud_tokens,
                },
            }
            steps.append(step_summary)
            current_after_step = self.store.get_job(db, user_id=user_id, job_id=job_id)
            step_attempt_id, step_lease_epoch = self._attempt_tokens(current_after_step)
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="goal.step_completed",
                payload=step_summary,
                summary=f"Goal loop step {step_index} completed",
                detail=status,
                attempt_id=step_attempt_id,
                lease_epoch=step_lease_epoch,
            )

            if no_progress:
                self.store.append_event(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="goal.no_progress",
                    payload={
                        "step": step_index,
                        "phase": goal_phase,
                        "progress_fingerprint": progress_fingerprint,
                        "verification_signal": verification_signal,
                        "reason": (
                            "repeated_needs_more_work"
                            if repeated_needs_more_work
                            else "repeated_model_output"
                        ),
                    },
                    summary="Durable workstream paused after no progress.",
                    detail="Resume with a different safe action or updated evidence.",
                    attempt_id=step_attempt_id,
                    lease_epoch=step_lease_epoch,
                )
                stop_reason = "no_progress"
                break
            if result.get("approval_required"):
                stop_reason = "approval_required"
                break
            if result.get("route_blocked"):
                stop_reason = "route_blocked"
                break
            if status in GOAL_LOOP_TERMINAL_STATUSES:
                stop_reason = status
                break
            if opts.cloud_token_budget == 0 and step_cloud:
                stop_reason = "cloud_budget"
                break
            if opts.cloud_token_budget and cloud_tokens >= opts.cloud_token_budget:
                stop_reason = "cloud_budget"
                break
            if opts.local_token_budget and local_tokens >= opts.local_token_budget:
                stop_reason = "local_budget"
                break
            previous_progress_fingerprint = progress_fingerprint
            if verification_signal:
                previous_verification_signal = verification_signal

        if not stop_reason:
            stop_reason = "max_steps"

        final_job = self.store.get_job(db, user_id=user_id, job_id=job_id)
        final_attempt_id, final_lease_epoch = self._attempt_tokens(final_job)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="goal.stopped",
            payload={
                "worker_id": opts.worker_id,
                "stop_reason": stop_reason,
                "steps_completed": len(steps),
                "max_steps": opts.max_steps,
                "elapsed_ms": elapsed_ms,
                "job_status": final_job.status.value,
                "goal_phase_sequence": list(opts.goal_phase_sequence),
                "durable_workstream": durable_workstream,
                "usage": {
                    "local_tokens": local_tokens,
                    "cloud_tokens": cloud_tokens,
                    "cloud_evidence_count": cloud_evidence,
                },
            },
            summary=f"Goal loop stopped: {stop_reason}",
            detail=f"{len(steps)}/{opts.max_steps} steps in {elapsed_ms} ms",
            attempt_id=final_attempt_id,
            lease_epoch=final_lease_epoch,
        )
        snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        return {
            "job": final_job.as_dict(),
            "last_result": last_result,
            "snapshot": snapshot,
            "dry_run": opts.dry_run,
            "worker_id": opts.worker_id,
            "continuous": True,
            "durable_workstream": durable_workstream,
            "steps": steps,
            "steps_completed": len(steps),
            "stop_reason": stop_reason,
            "usage": {
                "local_tokens": local_tokens,
                "cloud_tokens": cloud_tokens,
                "cloud_evidence_count": cloud_evidence,
            },
        }

    def _run_advisory_once(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        job: Any,
        options: ConsoleRuntimeRunOptions,
        adapter: ModelAdapter | None,
        attempt_id: str,
        lease_epoch: int | None,
    ) -> dict[str, Any]:
        """Run the deliberately non-executing static-advice lane."""

        route_policy = _canonical_advisory_route_policy()
        model = options.model or _clean(getattr(settings, "llm_offline_model", ""))
        invocation_id = ":".join(
            part for part in (options.worker_id, job_id, "advisory", "model") if part
        )
        route = {
            "lane": "chat",
            "provider": "norllama",
            "provider_kind": "llm",
            "capability": "text_chat",
            "model": model,
            "endpoint": _clean(getattr(settings, "llm_offline_base_url", "")),
            "mode": "offline_local",
            "local": True,
            "cloud_proxy": False,
            "tool_lane": False,
            "requires_receipt": False,
            "reason": "static advisory response",
        }
        request = ModelRequest(
            messages=[
                {"role": "system", "content": self._advisory_system_prompt()},
                {"role": "user", "content": job.contract.objective},
            ],
            model=model,
            route_key="chat",
            budget=ModelBudget(
                max_runtime_seconds=options.max_runtime_seconds
                or job.contract.max_runtime_seconds,
                max_output_tokens=options.max_output_tokens,
            ),
            metadata={
                "execution_mode": ADVISORY_EXECUTION_MODE,
                "advisory_only": True,
                "route_policy": route_policy,
                "norllama_route": route,
                "norllama_task_kind": "chat",
                "required_tools": [],
                "verification_tools": [],
                "runtime_job_id": job_id,
                "console_runtime_job_id": job_id,
                "attempt_id": attempt_id,
                "lease_epoch": lease_epoch or 0,
                "worker_id": options.worker_id,
                "invocation_id": invocation_id,
                "request_id": invocation_id,
            },
        )
        model_adapter = adapter or self._default_adapter(
            options, job.contract.objective
        )
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="execution.advisory_only",
            payload={
                "execution_mode": ADVISORY_EXECUTION_MODE,
                "provider": "norllama",
                "model": model,
                "invocation_id": invocation_id,
                "tool_access": False,
                "current_state_access": False,
            },
            summary="Started local static advisory response.",
            detail="No shell, tool, capability, route-proof, or verifier access.",
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        effect_key = f"{attempt_id}:{invocation_id}"
        effect, should_invoke = self.store.begin_effect(
            db,
            user_id=user_id,
            job_id=job_id,
            effect_key=effect_key,
            kind="model.invoke",
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
            preconditions={
                "provider": "norllama",
                "model": request.model,
                "route_key": request.route_key,
                "invocation_id": invocation_id,
                "execution_mode": ADVISORY_EXECUTION_MODE,
            },
        )
        if not should_invoke:
            summary = (
                "Static advisory checkpointed because its one model invocation "
                "was already reserved."
            )
            checkpointed = self.store.checkpoint_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary=summary,
                capsule=self._checkpoint_capsule(
                    job,
                    summary=summary,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                    route_receipt={},
                ),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": checkpointed.as_dict(),
                "model_result": None,
                "snapshot": snapshot,
                "dry_run": False,
                "worker_id": options.worker_id,
                "advisory_only": True,
                "effect_reconciliation_required": True,
                "effect": effect.as_dict(),
            }
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="model.requested",
            payload={
                "provider": "norllama",
                "model": request.model,
                "route_key": request.route_key,
                "execution_mode": ADVISORY_EXECUTION_MODE,
            },
            summary="Requested Norllama static advice.",
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        canceled = self._finalize_cancellation_if_requested(
            db,
            user_id=user_id,
            job_id=job_id,
            options=options,
            reason="Cancellation requested before static advisory invocation",
            effect_key=effect_key,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        if canceled is not None:
            return canceled
        try:
            result = model_adapter.invoke(request)
        except Exception as exc:
            error = str(exc)
            self.store.fail_effect(
                db,
                user_id=user_id,
                job_id=job_id,
                effect_key=effect_key,
                error=error,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="model.failed",
                payload={
                    "provider": "norllama",
                    "error": error,
                    "execution_mode": ADVISORY_EXECUTION_MODE,
                },
                summary="Norllama static advice failed.",
                detail=error,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            failed = self.store.fail_job(
                db,
                user_id=user_id,
                job_id=job_id,
                error=error,
                retry_class=RetryClass.TRANSIENT_TRANSPORT,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": failed.as_dict(),
                "model_result": None,
                "snapshot": snapshot,
                "dry_run": False,
                "worker_id": options.worker_id,
                "advisory_only": True,
                "model_failed": True,
                "error": error,
                "failure_class": "model_adapter_failed",
            }

        # The adapter may internally construct a Norllama receipt; it is not a
        # runtime route receipt in this non-executing lane and is not persisted.
        result = ModelResult(
            provider=result.provider or "norllama",
            model=result.model or model,
            text=result.text,
            stop_reason=result.stop_reason,
            usage=result.usage,
            metadata={
                "execution_mode": ADVISORY_EXECUTION_MODE,
                "advisory_only": True,
            },
        )
        self.store.complete_effect(
            db,
            user_id=user_id,
            job_id=job_id,
            effect_key=effect_key,
            receipt={
                "invocation_id": invocation_id,
                "provider": result.provider,
                "model": result.model,
                "stop_reason": result.stop_reason,
                "usage": result.usage.as_dict(),
                "execution_mode": ADVISORY_EXECUTION_MODE,
            },
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        self._record_model_result(
            db,
            user_id=user_id,
            job_id=job_id,
            invocation_id=invocation_id,
            adapter_name="norllama",
            result=result,
            task_contract={},
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
            advisory_only=True,
        )
        final_job = self.store.complete_job(
            db,
            user_id=user_id,
            job_id=job_id,
            summary="Static advisory response completed.",
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        return {
            "job": final_job.as_dict(),
            "model_result": result.as_dict(),
            "snapshot": snapshot,
            "dry_run": False,
            "worker_id": options.worker_id,
            "advisory_only": True,
        }

    def _run_shell_once(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        job,
        options: ConsoleRuntimeRunOptions,
        route_policy: dict[str, Any],
        policy_state,
        attempt_id: str,
        lease_epoch: int | None,
    ) -> dict[str, Any]:
        if self._is_delegated_read_only_subtask(job, route_policy):
            reason = (
                "Delegated read-only subtasks require explicit approval before "
                "shell execution."
            )
            self.store.record_policy_block(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                policy_state=policy_state,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            held = self.store.require_approval(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                requested_by=options.worker_id,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": held.as_dict(),
                "model_result": None,
                "shell_result": None,
                "snapshot": snapshot,
                "dry_run": options.dry_run,
                "worker_id": options.worker_id,
                "approval_required": True,
                "approval_reason": reason,
            }

        commands = self._shell_commands(route_policy, options)
        if not commands:
            reason = "Shell runtime requires route_policy.command or preflight commands"
            self.store.record_policy_block(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                policy_state=policy_state,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            blocked = self.store.block_job(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": blocked.as_dict(),
                "model_result": None,
                "shell_result": None,
                "snapshot": snapshot,
                "dry_run": options.dry_run,
                "worker_id": options.worker_id,
                "route_blocked": True,
                "blocked_reason": reason,
            }

        decision = route_decision(
            task_kind="shell",
            route={
                "lane": "kernel_shell",
                "provider": "shell",
                "capability": "shell",
                "model": "",
                "endpoint": "local",
                "local": True,
                "cloud_proxy": False,
                "reason": "job requested kernel shell runtime",
            },
            policy_state=policy_state,
            runner="shell",
            capabilities={
                "provider": "shell",
                "supports_streaming": True,
                "supports_tools": True,
            },
            metadata={"source": "runtime_worker", "worker_id": options.worker_id},
        )
        self.store.record_route_decision(
            db,
            user_id=user_id,
            job_id=job_id,
            decision=decision,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        if not decision.allowed:
            reason = "; ".join(decision.blocked_reasons) or "shell route blocked"
            self.store.record_policy_block(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                policy_state=policy_state,
                metadata={"decision_id": decision.decision_id},
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            blocked = self.store.block_job(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": blocked.as_dict(),
                "model_result": None,
                "shell_result": None,
                "snapshot": snapshot,
                "dry_run": options.dry_run,
                "worker_id": options.worker_id,
                "route_blocked": True,
                "blocked_reason": reason,
            }

        shell = ShellRuntimeAdapter()
        results = []
        for index, command in enumerate(commands, start=1):
            request = ShellRequest(
                command=command,
                cwd=_clean(route_policy.get("cwd")),
                timeout_seconds=int(route_policy.get("timeout_seconds") or 60),
                allow_shell_metachar=bool(route_policy.get("allow_shell_metachar")),
                policy_profile=route_policy.get("command_policy")
                if isinstance(route_policy.get("command_policy"), dict)
                else {},
            )
            policy_decision = shell.evaluate(request)
            invocation_id = f"{options.worker_id}:{job_id}:shell:{index}"
            if policy_decision.decision != "allow":
                reason = (
                    f"Shell command {policy_decision.decision}: "
                    f"{policy_decision.reason}"
                )
                held = self.store.require_approval(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    reason=reason,
                    requested_by=options.worker_id,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                snapshot = self.store.activity_snapshot(
                    db, user_id=user_id, job_id=job_id
                )
                return {
                    "job": held.as_dict(),
                    "model_result": None,
                    "shell_result": None,
                    "shell_results": results,
                    "snapshot": snapshot,
                    "dry_run": options.dry_run,
                    "worker_id": options.worker_id,
                    "approval_required": True,
                    "approval_reason": reason,
                }

            effect_key = f"{attempt_id}:{invocation_id}"
            effect, should_run = self.store.begin_effect(
                db,
                user_id=user_id,
                job_id=job_id,
                effect_key=effect_key,
                kind="shell.run",
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
                preconditions={
                    "command": command,
                    "cwd": request.cwd,
                    "timeout_seconds": request.timeout_seconds,
                    "invocation_id": invocation_id,
                },
            )
            if not should_run:
                reconciliation_summary = (
                    "Runtime worker checkpointed because a shell command was "
                    "already reserved for this attempt."
                )
                self.store.append_event(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="effect.reconciliation_required",
                    payload={
                        "effect": effect.as_dict(),
                        "invocation_id": invocation_id,
                        "command": command,
                        "reason": "duplicate shell invocation reservation",
                    },
                    summary="Shell effect reconciliation required",
                    detail=effect.state,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                checkpointed = self.store.checkpoint_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    summary=reconciliation_summary,
                    capsule=self._checkpoint_capsule(
                        job,
                        summary=reconciliation_summary,
                        attempt_id=attempt_id,
                        lease_epoch=lease_epoch,
                        route_receipt={"invocation_id": invocation_id},
                    ),
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                snapshot = self.store.activity_snapshot(
                    db, user_id=user_id, job_id=job_id
                )
                return {
                    "job": checkpointed.as_dict(),
                    "model_result": None,
                    "shell_result": None,
                    "shell_results": results,
                    "snapshot": snapshot,
                    "dry_run": options.dry_run,
                    "worker_id": options.worker_id,
                    "effect_reconciliation_required": True,
                    "effect": effect.as_dict(),
                }
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="shell.started",
                payload={
                    "invocation_id": invocation_id,
                    "command": command,
                    "index": index,
                    "count": len(commands),
                    "policy": policy_decision.__dict__,
                },
                summary="Shell command started",
                detail=command,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            canceled = self._finalize_cancellation_if_requested(
                db,
                user_id=user_id,
                job_id=job_id,
                options=options,
                reason="Cancellation requested before shell invocation",
                effect_key=effect_key,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            if canceled is not None:
                return {
                    **canceled,
                    "shell_result": None,
                    "shell_results": results,
                }
            try:
                result = shell.run(request)
            except ShellPolicyError as exc:
                error = str(exc)
                self.store.append_event(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="shell.failed",
                    payload={
                        "invocation_id": invocation_id,
                        "command": command,
                        "error": error,
                        "policy": exc.decision.__dict__,
                    },
                    summary="Shell command failed policy",
                    detail=error,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                self.store.fail_effect(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    effect_key=effect_key,
                    error=error,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                self.store.fail_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    error=error,
                    retry_class=RetryClass.POLICY_DENIED,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                raise
            except Exception as exc:
                error = str(exc)
                self.store.fail_effect(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    effect_key=effect_key,
                    error=error,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                self.store.append_event(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="shell.failed",
                    payload={
                        "invocation_id": invocation_id,
                        "command": command,
                        "error": error,
                    },
                    summary="Shell command execution failed",
                    detail=error,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                self.store.fail_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    error=error,
                    retry_class=RetryClass.TRANSIENT_TRANSPORT,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                raise

            if result.stdout:
                self.store.append_event(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="shell.output",
                    payload={
                        "invocation_id": invocation_id,
                        "stream": "stdout",
                        "text": _preview(result.stdout, 4000),
                    },
                    summary="Shell stdout",
                    detail=_preview(result.stdout, 800),
                    visibility="stream",
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
            if result.stderr:
                self.store.append_event(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="shell.output",
                    payload={
                        "invocation_id": invocation_id,
                        "stream": "stderr",
                        "text": _preview(result.stderr, 4000),
                    },
                    summary="Shell stderr",
                    detail=_preview(result.stderr, 800),
                    visibility="stream",
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="shell.completed",
                payload={
                    "invocation_id": invocation_id,
                    "command": command,
                    "index": index,
                    "count": len(commands),
                    "returncode": result.returncode,
                    "output_preview": result.output_preview,
                    "policy": result.policy,
                    "timed_out": result.timed_out,
                },
                summary="Shell command completed",
                detail=result.output_preview,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            results.append(result.as_dict())
            effect_receipt = {
                "invocation_id": invocation_id,
                "command": command,
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "output_preview": result.output_preview,
                "policy": result.policy,
            }
            if result.timed_out:
                self.store.mark_effect_unknown(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    effect_key=effect_key,
                    reason="Shell command timed out; external effects are unknown.",
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                final_job = self.store.fail_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    error="Shell command timed out; external effects are unknown.",
                    retry_class=RetryClass.PARTIAL_EFFECT,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                snapshot = self.store.activity_snapshot(
                    db, user_id=user_id, job_id=job_id
                )
                return {
                    "job": final_job.as_dict(),
                    "model_result": None,
                    "shell_result": result.as_dict(),
                    "shell_results": results,
                    "snapshot": snapshot,
                    "dry_run": options.dry_run,
                    "worker_id": options.worker_id,
                    "failure_class": RetryClass.PARTIAL_EFFECT.value,
                    "effect": self.store.get_effect(
                        db,
                        user_id=user_id,
                        job_id=job_id,
                        effect_key=effect_key,
                    ).as_dict(),
                }

            self.store.complete_effect(
                db,
                user_id=user_id,
                job_id=job_id,
                effect_key=effect_key,
                receipt=effect_receipt,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            if result.returncode != 0:
                final_job = self.store.fail_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    error=f"Shell command exited {result.returncode}",
                    retry_class=RetryClass.PARTIAL_EFFECT,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                snapshot = self.store.activity_snapshot(
                    db, user_id=user_id, job_id=job_id
                )
                return {
                    "job": final_job.as_dict(),
                    "model_result": None,
                    "shell_result": result.as_dict(),
                    "shell_results": results,
                    "snapshot": snapshot,
                    "dry_run": options.dry_run,
                    "worker_id": options.worker_id,
                }

        if not results:
            reason = "Shell runtime had no commands to run"
            blocked = self.store.block_job(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
            return {
                "job": blocked.as_dict(),
                "model_result": None,
                "shell_result": None,
                "shell_results": [],
                "snapshot": snapshot,
                "dry_run": options.dry_run,
                "worker_id": options.worker_id,
                "route_blocked": True,
                "blocked_reason": reason,
            }

        canceled = self._finalize_cancellation_if_requested(
            db,
            user_id=user_id,
            job_id=job_id,
            options=options,
            reason="Cancellation requested before shell finalization",
        )
        if canceled is not None:
            return {
                **canceled,
                "shell_result": results[-1],
                "shell_results": results,
            }
        finalized = self.store.get_job(db, user_id=user_id, job_id=job_id)
        has_verification_receipt = any(
            isinstance(receipt, dict) and receipt.get("status") == "pass"
            for receipt in finalized.verification_receipts
        )
        durable_workstream = self._is_durable_workstream(finalized, options)
        completion_blocked_by_verification = options.complete and (
            durable_workstream
            or (
                self._requires_verification_receipt(finalized)
                and not has_verification_receipt
            )
        )
        if options.complete and not completion_blocked_by_verification:
            final_job = self.store.complete_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary="Runtime worker completed shell step.",
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        else:
            checkpoint_summary = (
                "Durable workstream checkpointed shell step pending explicit "
                "verifier completion."
                if durable_workstream
                else "Runtime worker checkpointed shell step pending verification "
                "receipt."
                if completion_blocked_by_verification
                else "Runtime worker checkpointed after shell step."
            )
            final_job = self.store.checkpoint_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary=checkpoint_summary,
                capsule=self._checkpoint_capsule(
                    finalized,
                    summary=checkpoint_summary,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                    route_receipt={
                        "invocation_id": f"{options.worker_id}:{job_id}:shell:"
                        f"{len(results)}"
                    },
                    completed_clauses=(
                        list(finalized.contract.done_when)
                        if not completion_blocked_by_verification
                        else []
                    ),
                    durable_workstream=durable_workstream,
                ),
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        return {
            "job": final_job.as_dict(),
            "model_result": None,
            "shell_result": results[-1],
            "shell_results": results,
            "snapshot": snapshot,
            "dry_run": options.dry_run,
            "worker_id": options.worker_id,
            "durable_workstream": durable_workstream,
        }

    def _is_delegated_read_only_subtask(
        self,
        job,
        route_policy: dict[str, Any],
    ) -> bool:
        if not _clean(getattr(job, "parent_job_id", "")):
            return False
        contract = getattr(job, "contract", None)
        values = (
            route_policy,
            getattr(contract, "metadata", {}),
            getattr(contract, "authority_flags", {}),
            getattr(job, "metadata", {}),
        )
        for value in values:
            if not isinstance(value, dict):
                continue
            write_mode = _clean(value.get("write_mode")).lower()
            if write_mode:
                return write_mode == "read_only"
        return False

    def _shell_commands(
        self, route_policy: dict[str, Any], options: ConsoleRuntimeRunOptions
    ) -> list[str]:
        direct = _clean(route_policy.get("command")) or _clean(
            route_policy.get("shell_command")
        )
        if direct:
            return [direct]
        commands: list[str] = []
        for key in (
            "commands",
            "shell_commands",
            "preflight_commands",
            "kernel_preflight_commands",
        ):
            commands.extend(_string_list(route_policy.get(key)))
        if commands:
            return commands
        goal_phase = _clean(options.metadata.get("goal_phase")).lower()
        goal_task_kind = (
            _clean(options.metadata.get("goal_task_kind"))
            or _clean(options.planner_kind)
        ).lower()
        if goal_phase in {"preflight", "shell", "tool", "tools"} or (
            goal_task_kind == "shell"
        ):
            if (
                _flag(route_policy.get("workspace_preflight"))
                or _flag(route_policy.get("kernel_workspace_preflight"))
                or _flag(route_policy.get("kernel_preflight"))
            ):
                return list(DEFAULT_WORKSPACE_PREFLIGHT_COMMANDS)
        return []

    def _wants_shell(
        self, route_policy: dict[str, Any], options: ConsoleRuntimeRunOptions
    ) -> bool:
        if options.execution_mode == ADVISORY_EXECUTION_MODE:
            return False
        runtime = _clean(route_policy.get("runtime")).lower()
        provider = _clean(route_policy.get("provider")).lower()
        if runtime == "shell" or provider == "shell":
            return True
        goal_phase = _clean(options.metadata.get("goal_phase")).lower()
        goal_task_kind = (
            _clean(options.metadata.get("goal_task_kind"))
            or _clean(options.planner_kind)
        ).lower()
        return goal_phase in {"preflight", "shell", "tool", "tools"} or (
            goal_task_kind == "shell"
        )

    def _verifier_can_stop(
        self,
        job: Any,
        route_policy: dict[str, Any],
        options: ConsoleRuntimeRunOptions,
    ) -> bool:
        return self._is_durable_workstream(job, options) or (
            _flag(route_policy.get("verifier_can_stop"))
            or _flag(route_policy.get("kernel_verifier_can_stop"))
            or _flag(options.metadata.get("verifier_can_stop"))
        )

    def _model_family(self, model: str) -> str:
        clean = _clean(model).lower()
        if "qwen" in clean:
            return "qwen"
        if "gemma" in clean:
            return "gemma"
        if "codex" in clean:
            return "codex"
        if "gpt" in clean or "openai" in clean:
            return "openai"
        if "claude" in clean:
            return "claude"
        if "llama" in clean:
            return "llama"
        return clean.split(":", 1)[0].split("/", 1)[0] if clean else ""

    def _system_prompt_for_phase(self, phase: str) -> str:
        clean = _clean(phase).lower()
        if clean == "plan":
            return (
                "You are Norman's local-first runtime planner. Produce a concise "
                "plan, risks, needed evidence, and the next concrete action."
            )
        if clean in {"work", "chat", "execute", "draft"}:
            return (
                "You are Norman's local-first runtime worker. Do the next useful "
                "step, keep it bounded, and report what changed or what remains."
            )
        if clean == "literal_response":
            return (
                "You are Norman's literal-response worker. Return only the exact "
                "literal answer requested by the operator. Do not add a plan, "
                "preamble, checklist, or verification note."
            )
        if clean == "verify":
            return (
                "You are Norman's verifier. Check whether the goal is complete, "
                "identify gaps, and state whether another local step is needed. "
                "Begin with STATUS: COMPLETE when the goal is done, or "
                "STATUS: NEEDS_MORE_WORK when another local work step should run."
            )
        if clean == "filter":
            return (
                "You are Norman's local filter. Reduce the input to the smallest "
                "useful context needed for the next step."
            )
        if clean == "scout":
            return (
                "You are Norman's local scout. Identify what should be researched, "
                "what can be answered locally, and what evidence is missing."
            )
        return (
            "You are Norman's runtime worker. Return a concise execution note "
            "for this phase."
        )

    @staticmethod
    def _advisory_system_prompt() -> str:
        return (
            "You are Norman's static command advisor. Answer only from general "
            "knowledge. You have no shell, tools, files, network, history, or "
            "current-state access. Do not claim that you inspected, ran, "
            "verified, or changed anything. Give a concise command suggestion "
            "and any essential generic caveat."
        )

    def _prior_model_output_context(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        limit: int = 12,
    ) -> str:
        try:
            snapshot = self.store.activity_snapshot(
                db,
                user_id=user_id,
                job_id=job_id,
                limit=120,
            )
        except Exception:
            return ""
        events = snapshot.get("events") if isinstance(snapshot, dict) else []
        outputs: list[str] = []
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict) or event.get("event_type") != "model.delta":
                continue
            payload = (
                event.get("payload") if isinstance(event.get("payload"), dict) else {}
            )
            text = _clean(payload.get("text") or event.get("detail"))
            if not text:
                continue
            lower = " ".join(text.lower().replace("_", " ").split())
            if lower.startswith("status: needs more work"):
                continue
            outputs.append(_preview(text, 1400))
        return "\n\n".join(outputs[-limit:])

    def _structured_candidate_from_history(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        objective: str,
        limit: int = 80,
    ) -> str:
        try:
            snapshot = self.store.activity_snapshot(
                db,
                user_id=user_id,
                job_id=job_id,
                limit=limit,
            )
        except Exception:
            return ""
        events = snapshot.get("events") if isinstance(snapshot, dict) else []
        candidates: list[str] = []
        for event in events if isinstance(events, list) else []:
            if (
                not isinstance(event, dict)
                or event.get("event_type") != "model.completed"
            ):
                continue
            payload = (
                event.get("payload") if isinstance(event.get("payload"), dict) else {}
            )
            receipt = (
                payload.get("route_receipt")
                if isinstance(payload.get("route_receipt"), dict)
                else {}
            )
            text = _clean(
                payload.get("output_preview")
                or payload.get("text")
                or payload.get("response_preview")
                or receipt.get("response_preview")
            )
            if not text:
                continue
            if _structured_response_signal(objective, text) == "complete":
                candidates.append(text)
        if not candidates:
            return ""
        latest = candidates[-1]
        try:
            return json.dumps(json.loads(latest), separators=(",", ":"))
        except Exception:
            return latest

    def _phase_user_prompt(
        self,
        db: Session,
        *,
        user_id: int,
        job,
        phase: str,
        durable_workstream: bool = False,
    ) -> str:
        contract = job.contract
        clean_phase = _clean(phase).lower()
        if clean_phase == "literal_response":
            return (
                "Return only the exact literal response requested here:\n\n"
                f"{contract.objective}"
            )
        parts = [
            f"Phase: {_clean(phase) or 'work'}",
            f"Objective: {contract.objective}",
        ]
        if contract.done_when:
            parts.append("Done when:\n- " + "\n- ".join(contract.done_when))
        if contract.success_metrics:
            parts.append("Success metrics:\n- " + "\n- ".join(contract.success_metrics))
        if contract.required_artifacts:
            parts.append(
                "Required artifacts:\n- " + "\n- ".join(contract.required_artifacts)
            )
        if clean_phase == "verify":
            prior_output = self._prior_model_output_context(
                db,
                user_id=user_id,
                job_id=job.job_id,
            )
            json_only = "json" in contract.objective.lower() and (
                "return" in contract.objective.lower()
                or "reply" in contract.objective.lower()
            )
            if durable_workstream:
                completion_instruction = (
                    "This is a durable workstream. Make an explicit verifier "
                    "decision. If the candidate output satisfies the operator "
                    "objective and done-when criteria for this JSON-only task, "
                    "begin with a standalone line `STATUS: COMPLETE`, then "
                    "return the final JSON document. Do not return bare JSON. "
                    "If not, begin with a standalone line "
                    "`STATUS: NEEDS_MORE_WORK` and name the missing evidence."
                    if json_only
                    else "This is a durable workstream. Make an explicit verifier "
                    "decision. If a candidate output satisfies the operator "
                    "objective and done-when criteria, begin with a standalone "
                    "line `STATUS: COMPLETE` and include the final answer with "
                    "every required field and literal value. If not, begin with "
                    "a standalone line `STATUS: NEEDS_MORE_WORK` and name the "
                    "missing evidence."
                )
            else:
                completion_instruction = (
                    "If a candidate output satisfies the operator objective and "
                    "done-when criteria for a JSON-only task, return only the "
                    "final JSON document. Do not add STATUS, prose, markdown, "
                    "or a wrapper around the JSON. If not, begin with "
                    "STATUS: NEEDS_MORE_WORK and name the missing evidence."
                    if json_only
                    else "If a candidate output satisfies the operator objective and "
                    "done-when criteria, begin with STATUS: COMPLETE and include "
                    "the final answer with every required field and literal value. "
                    "If not, begin with STATUS: NEEDS_MORE_WORK and name the "
                    "missing evidence."
                )
            if prior_output:
                parts.append(
                    "Prior local candidate outputs to verify:\n\n"
                    f"{prior_output}\n\n"
                    f"{completion_instruction}"
                )
            elif durable_workstream:
                parts.append(completion_instruction)
        return "\n\n".join(parts)

    def _default_adapter(
        self,
        options: ConsoleRuntimeRunOptions,
        objective: str,
        *,
        route: Any | None = None,
    ) -> ModelAdapter:
        if options.execution_mode == ADVISORY_EXECUTION_MODE:
            return NorllamaModelAdapter()
        if options.dry_run:
            return FakeModelAdapter(
                responses=[
                    "Runtime worker dry-run completed for objective: "
                    + _preview(objective, 240)
                ],
                name="runtime-dry-run",
                model=options.model or "runtime-dry-run",
            )
        route_payload = (
            route.as_dict()
            if hasattr(route, "as_dict")
            else route
            if isinstance(route, dict)
            else {}
        )
        provider = _clean(route_payload.get("provider")).lower().replace("_", "-")
        cloud_proxy = _flag(route_payload.get("cloud_proxy"))
        if (
            provider in {"bedrock", "aws-bedrock"}
            and cloud_proxy
            and not _flag(route_payload.get("local"))
            and not _flag(route_payload.get("tool_lane"))
        ):
            return BedrockModelAdapter()
        return NorllamaModelAdapter()

    def _live_execution_allowed(self, options: ConsoleRuntimeRunOptions) -> bool:
        return bool(options.live_execution_approved) or bool(
            getattr(settings, "console_runtime_worker_live_execution_enabled", False)
        )

    def _result_usage(self, result: dict[str, Any]) -> int:
        model_result = result.get("model_result") if isinstance(result, dict) else {}
        usage = (
            model_result.get("usage")
            if isinstance(model_result, dict)
            and isinstance(model_result.get("usage"), dict)
            else {}
        )
        return max(0, int(usage.get("total_tokens") or 0))

    def _cloud_evidence_count(self, snapshot: dict[str, Any]) -> int:
        summary = snapshot.get("route_summary") if isinstance(snapshot, dict) else {}
        if not isinstance(summary, dict):
            return 0
        return max(0, int(summary.get("cloud_evidence_count") or 0))

    def _record_model_result(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        invocation_id: str,
        adapter_name: str,
        result: ModelResult,
        verification_signal: str = "",
        reasoning_plan: dict[str, Any] | None = None,
        task_contract: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
        advisory_only: bool = False,
    ) -> None:
        preview = _preview(result.text)
        metadata = dict(result.metadata or {})
        reasoning_plan = dict(reasoning_plan or {})
        work_classification = sanitize_work_classification(
            reasoning_plan.get("work_classification")
        )
        if result.provider and result.provider != "norllama":
            result_classification = classify_work(
                prompt_classification={
                    "risk_class": reasoning_plan.get("risk_class"),
                    "risk_level": reasoning_plan.get("risk_level"),
                },
                effective_runtime=result.provider,
                selected_provider=result.provider,
                task_kind=_clean(reasoning_plan.get("task_kind")),
            )
            if result_classification["work_class"] == "frontier":
                work_classification = result_classification
                reasoning_plan["work_classification"] = work_classification
        reasoning_receipt = (
            build_reasoning_receipt(
                reasoning_plan,
                executed_tools=[
                    {
                        "tool": "model_adapter.invoke",
                        "status": "pass",
                        "provider": adapter_name,
                        "model": result.model,
                        "invocation_id": invocation_id,
                    }
                ],
                verifier_result=verification_signal or "observed",
            )
            if reasoning_plan
            else {}
        )
        route = (
            dict(metadata.get("norllama_route"))
            if isinstance(metadata.get("norllama_route"), dict)
            else {}
        )
        receipt = (
            dict(metadata.get("norllama_receipt"))
            if isinstance(metadata.get("norllama_receipt"), dict)
            else {}
        )
        route_receipt = (
            dict(receipt.get("route_receipt"))
            if isinstance(receipt.get("route_receipt"), dict)
            else {}
        )
        attribution = (
            dict(route.get("attribution"))
            if isinstance(route.get("attribution"), dict)
            else {}
        )
        payload = {
            "provider": result.provider,
            "model": result.model,
            "stop_reason": result.stop_reason,
            "usage": result.usage.as_dict(),
            "metadata": metadata,
            "output_preview": preview,
        }
        if advisory_only:
            payload["execution_mode"] = ADVISORY_EXECUTION_MODE
            payload["advisory_only"] = True
        if reasoning_plan:
            payload["reasoning_plan_id"] = reasoning_plan.get("plan_id")
            payload["work_classification"] = work_classification
            payload["selected_skill_ids"] = list(
                reasoning_plan.get("selected_skill_ids") or []
            )
            payload["required_tools"] = list(
                (reasoning_plan.get("tool_plan") or {}).get("required_tools") or []
            )
            payload["verification_tools"] = list(
                (reasoning_plan.get("tool_plan") or {}).get("verification_tools") or []
            )
            payload["reasoning_receipt"] = reasoning_receipt
        if route_receipt and not advisory_only:
            route_receipt = {
                **route_receipt,
                "invocation_id": route_receipt.get("invocation_id") or invocation_id,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "total_tokens": result.usage.total_tokens,
            }
            route_receipt = normalize_route_receipt_for_completion_gate(
                route_receipt,
                verification_signal=verification_signal,
            )
            if isinstance(route_receipt.get("specialist_cascade"), dict):
                route_receipt["specialist_cascade"] = evaluate_specialist_cascade(
                    route_receipt["specialist_cascade"],
                    route_receipt=route_receipt,
                    output={
                        "text": result.text,
                        "usage": result.usage.as_dict(),
                    },
                    metadata=metadata,
                )
            route_receipt["receipt_audit"] = audit_route_receipt(route_receipt)
            route_receipt["fast_lane_outcome"] = evaluate_fast_lane_outcome(
                route_receipt,
                task_contract=task_contract,
                audit=route_receipt["receipt_audit"],
            )
            payload["route_receipt"] = route_receipt
            payload["fast_lane_outcome"] = route_receipt["fast_lane_outcome"]
            payload["usage_bucket"] = route_receipt.get("usage_bucket")
            payload["output_shape"] = route_receipt.get("output_shape")
            payload["verifier_result"] = route_receipt.get("verifier_result")
            payload["request_id"] = route_receipt.get("request_id")
            payload["client_request_id"] = route_receipt.get("client_request_id")
            payload["gateway_request_id"] = route_receipt.get("gateway_request_id")
            payload["invocation_id"] = route_receipt.get("invocation_id")
        if route and not advisory_only:
            payload["route"] = route
            payload["attribution"] = attribution
            payload["local"] = bool(route.get("local"))
            payload["cloud_proxy"] = bool(route.get("cloud_proxy"))
            payload["egress_class"] = "lan" if route.get("local") else "cloud_llm"
        self.store.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="model.completed",
            payload=payload,
            summary=f"{result.provider or adapter_name} completed",
            detail=result.stop_reason,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )
        if preview:
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="model.delta",
                payload={
                    "text": preview,
                    "provider": result.provider,
                    "model": result.model,
                    "execution_mode": ADVISORY_EXECUTION_MODE if advisory_only else "",
                    "reasoning_plan_id": reasoning_plan.get("plan_id")
                    if reasoning_plan
                    else "",
                    "work_classification": work_classification,
                },
                summary="Model output",
                detail=preview,
                visibility="stream",
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
        if not advisory_only:
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="tool.completed",
                payload={
                    "invocation_id": invocation_id,
                    "tool_name": "model_adapter.invoke",
                    "provider": adapter_name,
                    "output_preview": preview,
                    "reasoning_plan_id": reasoning_plan.get("plan_id")
                    if reasoning_plan
                    else "",
                    "reasoning_receipt": reasoning_receipt,
                    "work_classification": work_classification,
                },
                summary="Model adapter completed",
                detail=preview,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
