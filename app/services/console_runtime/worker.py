from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.console_runtime.adapters.base import ModelAdapter
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
    ConsoleJobStatus,
    ModelBudget,
    ModelRequest,
    ModelResult,
)
from app.services.norllama.routing import build_task_receipt, route_task
from app.services.norllama.route_proof import (
    audit_route_receipt,
    normalize_route_receipt_for_completion_gate,
    receipt_completion_gate_passes,
)
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


def _receipt_audit(route_receipt: dict[str, Any]) -> dict[str, Any]:
    return audit_route_receipt(route_receipt)


def _route_proof_required(
    route_policy: dict[str, Any],
    options: "ConsoleRuntimeRunOptions",
) -> bool:
    return (
        not options.dry_run
        or _flag(route_policy.get("route_proof_required"))
        or _flag(route_policy.get("require_route_proof"))
    )


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


def _completion_requested_for_step(options: "ConsoleRuntimeRunOptions") -> bool:
    return bool(options.complete)


@dataclass
class ConsoleRuntimeRunOptions:
    worker_id: str = "runtime-api-worker"
    dry_run: bool = True
    complete: bool = True
    continuous: bool = False
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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DbConsoleRuntimeWorker:
    """Run one DB-backed console runtime work step."""

    def __init__(self, store: DbConsoleRuntimeStore | None = None) -> None:
        self.store = store or DbConsoleRuntimeStore()

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
        if job.status in {ConsoleJobStatus.QUEUED, ConsoleJobStatus.CHECKPOINTED}:
            job = self.store.lease_job(
                db,
                user_id=user_id,
                job_id=job_id,
                worker_id=opts.worker_id,
                lease_seconds=job.contract.checkpoint_interval_seconds,
            )
        if job.status in {ConsoleJobStatus.LEASED, ConsoleJobStatus.CHECKPOINTED}:
            job = self.store.start_job(db, user_id=user_id, job_id=job_id)

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
            },
            summary="Runtime worker accepted job.",
            detail=job.contract.objective,
        )

        route_policy = _local_first_route_policy(
            _merge_dicts(job.contract.route_policy, opts.route_policy)
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
            )

        task_kind = _goal_task_kind(
            _clean(opts.metadata.get("goal_task_kind"))
            or _clean(opts.metadata.get("goal_phase"))
            or opts.planner_kind,
            opts.planner_kind,
        )
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

        model_adapter = adapter or self._default_adapter(opts, job.contract.objective)
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
            },
        )
        self.store.record_route_decision(
            db,
            user_id=user_id,
            job_id=job_id,
            decision=decision,
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
            )
            blocked = self.store.block_job(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
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
        verifier_required = bool(
            completion_requested
            and _verifier_required_for_completion(route_policy, opts)
        )
        requested_model, model_override_used, model_override_reason = (
            _route_requested_model(route.model, route_policy, opts)
        )
        route_payload = route.as_dict()
        request = ModelRequest(
            messages=[
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
                    ),
                },
            ],
            model=requested_model,
            route_key=route.lane,
            budget=ModelBudget(
                max_runtime_seconds=opts.max_runtime_seconds
                or job.contract.max_runtime_seconds,
                max_output_tokens=opts.max_output_tokens,
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
                "runtime_job_id": job_id,
                "console_runtime_job_id": job_id,
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
            },
        )
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
            },
            summary=f"Started {model_adapter.name}",
            detail=request.route_key,
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
            },
            summary=f"Requested {model_adapter.name}",
        )

        try:
            result = model_adapter.invoke(request)
        except Exception as exc:
            error = str(exc)
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="model.failed",
                payload={"provider": model_adapter.name, "error": error},
                summary=f"{model_adapter.name} failed",
                detail=error,
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
                },
                summary="Model adapter failed",
                detail=error,
            )
            failed_job = self.store.fail_job(
                db, user_id=user_id, job_id=job_id, error=error
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
            }

        goal_phase = (
            _clean(opts.metadata.get("goal_phase")) or opts.planner_kind
        ).lower()
        verification_signal = ""
        if goal_phase == "literal_response":
            verification_signal = _literal_response_signal(
                job.contract.objective,
                result.text,
            )
        elif self._verifier_can_stop(route_policy, opts) and goal_phase == "verify":
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
        self._record_model_result(
            db,
            user_id=user_id,
            job_id=job_id,
            invocation_id=invocation_id,
            adapter_name=model_adapter.name,
            result=result,
            verification_signal=verification_signal,
        )
        route_receipt = _route_receipt_from_result(result)
        if route_receipt:
            route_receipt = {
                **route_receipt,
                "invocation_id": route_receipt.get("invocation_id") or invocation_id,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "total_tokens": result.usage.total_tokens,
            }
        require_proof = _route_proof_required(route_policy, opts)
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
            )
        if route_receipt:
            route_receipt = normalize_route_receipt_for_completion_gate(
                route_receipt,
                verification_signal=verification_signal,
            )
            receipt_audit = _receipt_audit(route_receipt)
            route_receipt["receipt_audit"] = receipt_audit
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="route.receipt_audited",
                payload={
                    "route_receipt": route_receipt,
                    "receipt_audit": receipt_audit,
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
            )
        if (
            verification_signal == "complete"
            and not missing
            and completion_gate["gate_passed"]
        ):
            final_job = self.store.complete_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary="Runtime verifier marked goal complete.",
            )
        elif (
            opts.complete
            and not missing
            and verification_signal != "needs_more_work"
            and completion_gate["gate_passed"]
        ):
            final_job = self.store.complete_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary="Runtime worker completed one model step.",
            )
        else:
            checkpoint_reason = (
                "Runtime worker checkpointed after route-proof gate."
                if not completion_gate["gate_passed"]
                and (require_proof or route_receipt)
                else "Runtime worker checkpointed after one model step."
            )
            final_job = self.store.checkpoint_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary=checkpoint_reason,
            )

        snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        return {
            "job": final_job.as_dict(),
            "model_result": result.as_dict(),
            "snapshot": snapshot,
            "dry_run": opts.dry_run,
            "worker_id": opts.worker_id,
            "route_proof": completion_gate,
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
        opts = replace(opts, continuous=True)
        job = self.store.get_job(db, user_id=user_id, job_id=job_id)
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
                "local_first": True,
            },
            summary="Goal loop started",
            detail=job.contract.objective,
        )

        last_result: dict[str, Any] | None = None
        for step_index in range(1, opts.max_steps + 1):
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
            step_options = replace(
                opts,
                complete=bool(opts.complete and step_index >= opts.max_steps),
                continuous=False,
                planner_kind=goal_task_kind,
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
            step_summary = {
                "step": step_index,
                "phase": goal_phase,
                "task_kind": goal_task_kind,
                "status": status,
                "stop_flags": {
                    "approval_required": bool(result.get("approval_required")),
                    "route_blocked": bool(result.get("route_blocked")),
                    "cloud_evidence": step_cloud,
                },
                "usage": {
                    "step_tokens": usage,
                    "local_tokens": local_tokens,
                    "cloud_tokens": cloud_tokens,
                },
            }
            steps.append(step_summary)
            self.store.append_event(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="goal.step_completed",
                payload=step_summary,
                summary=f"Goal loop step {step_index} completed",
                detail=status,
            )

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

        if not stop_reason:
            stop_reason = "max_steps"

        final_job = self.store.get_job(db, user_id=user_id, job_id=job_id)
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
                "usage": {
                    "local_tokens": local_tokens,
                    "cloud_tokens": cloud_tokens,
                    "cloud_evidence_count": cloud_evidence,
                },
            },
            summary=f"Goal loop stopped: {stop_reason}",
            detail=f"{len(steps)}/{opts.max_steps} steps in {elapsed_ms} ms",
        )
        snapshot = self.store.activity_snapshot(db, user_id=user_id, job_id=job_id)
        return {
            "job": final_job.as_dict(),
            "last_result": last_result,
            "snapshot": snapshot,
            "dry_run": opts.dry_run,
            "worker_id": opts.worker_id,
            "continuous": True,
            "steps": steps,
            "steps_completed": len(steps),
            "stop_reason": stop_reason,
            "usage": {
                "local_tokens": local_tokens,
                "cloud_tokens": cloud_tokens,
                "cloud_evidence_count": cloud_evidence,
            },
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
    ) -> dict[str, Any]:
        commands = self._shell_commands(route_policy, options)
        if not commands:
            reason = "Shell runtime requires route_policy.command or preflight commands"
            self.store.record_policy_block(
                db,
                user_id=user_id,
                job_id=job_id,
                reason=reason,
                policy_state=policy_state,
            )
            blocked = self.store.block_job(
                db, user_id=user_id, job_id=job_id, reason=reason
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
            )
            blocked = self.store.block_job(
                db, user_id=user_id, job_id=job_id, reason=reason
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
            )
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
                )
                self.store.fail_job(db, user_id=user_id, job_id=job_id, error=error)
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
            )
            results.append(result.as_dict())
            if result.returncode != 0:
                final_job = self.store.fail_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    error=f"Shell command exited {result.returncode}",
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
                db, user_id=user_id, job_id=job_id, reason=reason
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

        if options.complete:
            final_job = self.store.complete_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary="Runtime worker completed shell step.",
            )
        else:
            final_job = self.store.checkpoint_job(
                db,
                user_id=user_id,
                job_id=job_id,
                summary="Runtime worker checkpointed after shell step.",
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
        }

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
        self, route_policy: dict[str, Any], options: ConsoleRuntimeRunOptions
    ) -> bool:
        return (
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
            if prior_output:
                json_only = "json" in contract.objective.lower() and (
                    "return" in contract.objective.lower()
                    or "reply" in contract.objective.lower()
                )
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
                parts.append(
                    "Prior local candidate outputs to verify:\n\n"
                    f"{prior_output}\n\n"
                    f"{completion_instruction}"
                )
        return "\n\n".join(parts)

    def _default_adapter(
        self, options: ConsoleRuntimeRunOptions, objective: str
    ) -> ModelAdapter:
        if options.dry_run:
            return FakeModelAdapter(
                responses=[
                    "Runtime worker dry-run completed for objective: "
                    + _preview(objective, 240)
                ],
                name="runtime-dry-run",
                model=options.model or "runtime-dry-run",
            )
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
    ) -> None:
        preview = _preview(result.text)
        metadata = dict(result.metadata or {})
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
        if route_receipt:
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
            payload["route_receipt"] = route_receipt
            payload["usage_bucket"] = route_receipt.get("usage_bucket")
            payload["output_shape"] = route_receipt.get("output_shape")
            payload["verifier_result"] = route_receipt.get("verifier_result")
            payload["request_id"] = route_receipt.get("request_id")
            payload["client_request_id"] = route_receipt.get("client_request_id")
            payload["gateway_request_id"] = route_receipt.get("gateway_request_id")
            payload["invocation_id"] = route_receipt.get("invocation_id")
        if route:
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
                },
                summary="Model output",
                detail=preview,
                visibility="stream",
            )
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
            },
            summary="Model adapter completed",
            detail=preview,
        )
