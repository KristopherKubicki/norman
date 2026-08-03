from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from app.services.console_runtime.adapters.base import ModelAdapter
from app.services.console_runtime.events import ConsoleRuntimeEvent, utc_now_iso
from app.services.console_runtime.planner import (
    planner_receipt_artifacts,
    planner_receipt_payload,
    planner_receipt_summary,
)
from app.services.console_runtime.types import (
    ConsoleArtifact,
    ConsoleArtifactRequirement,
    ConsoleCheckpointCapsule,
    ConsoleEffect,
    ConsoleJob,
    ConsoleJobContract,
    ConsoleJobLease,
    ConsoleJobStatus,
    ConsoleVerificationReceipt,
    ModelRequest,
    ModelResult,
    ModelUsage,
    RetryClass,
    RouteDecision,
    RuntimeModeState,
)
from app.services.norllama.specialist_lanes import evaluate_specialist_cascade
from app.services.norllama.fast_lane_outcomes import evaluate_fast_lane_outcome
from app.services.norllama.route_proof import audit_route_receipt


class ConsoleRuntimeError(RuntimeError):
    """Base error raised by the Norman console runtime."""


class JobNotFoundError(ConsoleRuntimeError):
    """Raised when a job id is unknown to the runtime."""


class InvalidTransitionError(ConsoleRuntimeError):
    """Raised when a job state transition would violate the job contract."""


class EffectReconciliationRequiredError(ConsoleRuntimeError):
    """Raised when a reserved external effect cannot be safely replayed."""


_TERMINAL_STATES = {
    ConsoleJobStatus.BLOCKED,
    ConsoleJobStatus.CANCELED,
    ConsoleJobStatus.DONE,
    ConsoleJobStatus.FAILED,
}


class ConsoleRuntimeKernel:
    """Small in-memory kernel for provider-neutral console jobs.

    The first production target is to preserve this behavior while replacing the
    in-memory dictionaries with Norman's durable store and worker leases.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, ConsoleJob] = {}
        self._events: List[ConsoleRuntimeEvent] = []
        self._effects: Dict[tuple[str, str], ConsoleEffect] = {}
        self._lease_epochs: Dict[str, int] = {}
        self._next_sequence = 1

    def create_job(
        self, contract: ConsoleJobContract, *, job_id: str | None = None
    ) -> ConsoleJob:
        job = ConsoleJob.new(contract=contract, job_id=job_id)
        with self._lock:
            if job.job_id in self._jobs:
                raise InvalidTransitionError(f"Job already exists: {job.job_id}")
            trace_id = str(
                contract.metadata.get("trace_id")
                or contract.authority_flags.get("trace_id")
                or f"trace_{uuid.uuid4().hex}"
            ).strip()
            job.metadata["trace_id"] = trace_id
            self._jobs[job.job_id] = job
            self._append_event_locked(
                job.job_id,
                "job.created",
                {
                    "objective": contract.objective,
                    "done_when": list(contract.done_when),
                    "required_artifacts": list(contract.required_artifacts),
                    "trace_id": trace_id,
                },
                summary="Job created",
            )
            return job

    def get_job(self, job_id: str) -> ConsoleJob:
        with self._lock:
            return self._job_locked(job_id)

    def list_jobs(self) -> List[ConsoleJob]:
        with self._lock:
            return list(self._jobs.values())

    def events(self, job_id: str | None = None) -> List[ConsoleRuntimeEvent]:
        with self._lock:
            if job_id is None:
                return list(self._events)
            return [event for event in self._events if event.job_id == job_id]

    def events_after(
        self,
        *,
        job_id: str | None = None,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> List[ConsoleRuntimeEvent]:
        after = max(0, int(after_sequence or 0))
        capped_limit = max(1, min(int(limit or 200), 1000))
        with self._lock:
            events = [
                event
                for event in self._events
                if event.sequence > after and (job_id is None or event.job_id == job_id)
            ]
            return events[:capped_limit]

    def activity_snapshot(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        with self._lock:
            job = self._job_locked(job_id)
            events = self.events_after(
                job_id=job_id,
                after_sequence=after_sequence,
                limit=limit,
            )
            all_events = [event for event in self._events if event.job_id == job_id]
            category_counts: dict[str, int] = {}
            for event in all_events:
                category_counts[event.category] = (
                    category_counts.get(event.category, 0) + 1
                )
            next_after = events[-1].sequence if events else int(after_sequence or 0)
            latest_event = all_events[-1].as_dict() if all_events else None
            return {
                "job": job.as_dict(),
                "events": [event.as_dict() for event in events],
                "event_count": len(all_events),
                "category_counts": category_counts,
                "latest_event": latest_event,
                "next_after": next_after,
            }

    def lease_job(
        self, job_id: str, *, worker_id: str, lease_seconds: int = 900
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            if job.status not in {
                ConsoleJobStatus.QUEUED,
                ConsoleJobStatus.CHECKPOINTED,
            }:
                raise InvalidTransitionError(
                    f"Cannot lease job {job_id} from state {job.status.value}"
                )
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
            lease_epoch = self._lease_epochs.get(job.job_id, 0) + 1
            self._lease_epochs[job.job_id] = lease_epoch
            job.lease = ConsoleJobLease(
                worker_id=worker_id,
                leased_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
                attempt_id=f"attempt_{uuid.uuid4().hex}",
                lease_epoch=lease_epoch,
            )
            self._set_status_locked(job, ConsoleJobStatus.LEASED)
            self._append_event_locked(
                job.job_id,
                "job.leased",
                {
                    "worker_id": worker_id,
                    "expires_at": job.lease.expires_at,
                    "attempt_id": job.lease.attempt_id,
                    "lease_epoch": job.lease.lease_epoch,
                },
                summary=f"Leased to {worker_id}",
            )
            return job

    def start_job(
        self,
        job_id: str,
        *,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            if job.status not in {
                ConsoleJobStatus.LEASED,
                ConsoleJobStatus.CHECKPOINTED,
            }:
                raise InvalidTransitionError(
                    f"Cannot start job {job_id} from state {job.status.value}"
                )
            self._set_status_locked(job, ConsoleJobStatus.RUNNING)
            self._append_event_locked(
                job.job_id,
                "job.started",
                {},
                summary="Job started",
            )
            return job

    def checkpoint_job(
        self,
        job_id: str,
        *,
        summary: str,
        artifacts: Iterable[Any] | None = None,
        capsule: ConsoleCheckpointCapsule | dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            if job.status not in {
                ConsoleJobStatus.LEASED,
                ConsoleJobStatus.RUNNING,
                ConsoleJobStatus.VERIFYING,
                ConsoleJobStatus.WAITING_APPROVAL,
            }:
                raise InvalidTransitionError(
                    f"Cannot checkpoint job {job_id} from state {job.status.value}"
                )
            added_artifacts = self._record_artifacts_locked(
                job,
                artifacts or [],
                produced_by_attempt=attempt_id,
            )
            checkpoint_capsule = self._checkpoint_capsule_locked(
                job,
                summary=summary,
                capsule=capsule,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            job.checkpoints.append(summary)
            job.checkpoint_capsules.append(checkpoint_capsule.as_dict())
            self._set_status_locked(job, ConsoleJobStatus.CHECKPOINTED)
            self._append_event_locked(
                job.job_id,
                "job.checkpointed",
                {
                    "summary": summary,
                    "artifacts": added_artifacts,
                    "checkpoint_capsule": checkpoint_capsule.as_dict(),
                },
                summary=summary,
            )
            return job

    def require_approval(
        self,
        job_id: str,
        *,
        reason: str,
        requested_by: str = "",
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            self._set_status_locked(job, ConsoleJobStatus.WAITING_APPROVAL)
            self._append_event_locked(
                job.job_id,
                "job.approval_required",
                {"reason": reason, "requested_by": requested_by},
                summary="Approval required",
                detail=reason,
            )
            return job

    def complete_job(
        self,
        job_id: str,
        *,
        summary: str = "",
        artifacts: Iterable[Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            added_artifacts = self._record_artifacts_locked(
                job,
                artifacts or [],
                produced_by_attempt=attempt_id,
            )
            missing = [
                artifact
                for artifact in job.contract.required_artifacts
                if artifact not in set(job.artifacts)
            ]
            if missing:
                raise InvalidTransitionError(
                    "Cannot complete job before required artifacts exist: "
                    + ", ".join(missing)
                )
            if self._verification_required_locked(job) and not any(
                receipt.get("status") == "pass"
                for receipt in job.verification_receipts
                if isinstance(receipt, dict)
            ):
                raise InvalidTransitionError(
                    "Cannot complete job before a passing verification receipt exists"
                )
            self._set_status_locked(job, ConsoleJobStatus.DONE)
            self._append_event_locked(
                job.job_id,
                "job.completed",
                {"summary": summary, "artifacts": added_artifacts},
                summary=summary or "Job completed",
            )
            return job

    def block_job(
        self,
        job_id: str,
        *,
        reason: str,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            job.last_error = reason
            self._set_status_locked(job, ConsoleJobStatus.BLOCKED)
            self._append_event_locked(
                job.job_id,
                "job.blocked",
                {"reason": reason},
                summary="Job blocked",
                detail=reason,
            )
            return job

    def fail_job(
        self,
        job_id: str,
        *,
        error: str,
        retry_class: RetryClass | str = RetryClass.UNKNOWN,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            if job.status in {ConsoleJobStatus.CANCELED, ConsoleJobStatus.DONE}:
                raise InvalidTransitionError(
                    f"Cannot fail job {job_id} from state {job.status.value}"
                )
            job.last_error = error
            normalized_retry_class = RetryClass.normalize(retry_class)
            job.metadata["last_retry_class"] = normalized_retry_class.value
            self._set_status_locked(job, ConsoleJobStatus.FAILED)
            self._append_event_locked(
                job.job_id,
                "job.failed",
                {"error": error, "retry_class": normalized_retry_class.value},
                summary="Job failed",
                detail=error,
            )
            return job

    def cancel_job(
        self,
        job_id: str,
        *,
        reason: str = "",
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            if job.status == ConsoleJobStatus.DONE:
                raise InvalidTransitionError("Completed jobs cannot be canceled")
            if job.status in {ConsoleJobStatus.CANCELED, ConsoleJobStatus.FAILED}:
                return job
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            self._set_status_locked(job, ConsoleJobStatus.CANCELED)
            self._append_event_locked(
                job.job_id,
                "job.canceled",
                {"reason": reason},
                summary="Job canceled",
                detail=reason,
            )
            return job

    def append_event(
        self,
        job_id: str,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        summary: str = "",
        detail: str = "",
        visibility: str = "timeline",
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        """Append a fenced runtime event for adapter-specific activity."""

        with self._lock:
            job = self._job_locked(job_id)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            return self._append_event_locked(
                job.job_id,
                event_type,
                dict(payload or {}),
                summary=summary,
                detail=detail,
                visibility=visibility,
            )

    def retry_job(self, job_id: str, *, override: bool = False) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            if job.status not in _TERMINAL_STATES:
                raise InvalidTransitionError(
                    f"Cannot retry job {job_id} from state {job.status.value}"
                )
            retry_class = RetryClass.normalize(job.metadata.get("last_retry_class"))
            if (
                retry_class
                in {
                    RetryClass.PARTIAL_EFFECT,
                    RetryClass.POLICY_DENIED,
                    RetryClass.VALIDATION_FAILED,
                }
                and not override
            ):
                raise InvalidTransitionError(
                    "Retry requires explicit override for retry class "
                    f"{retry_class.value}"
                )
            job.lease = None
            job.last_error = ""
            self._set_status_locked(job, ConsoleJobStatus.QUEUED)
            self._append_event_locked(
                job.job_id,
                "job.retried",
                {
                    "previous_retry_class": retry_class.value,
                    "override": bool(override),
                },
                summary="Job requeued",
            )
            return job

    def record_verification(
        self,
        job_id: str,
        *,
        receipt: ConsoleVerificationReceipt | dict[str, Any],
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleVerificationReceipt:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            normalized = (
                receipt
                if isinstance(receipt, ConsoleVerificationReceipt)
                else ConsoleVerificationReceipt(**dict(receipt))
            )
            lease = job.lease
            normalized.attempt_id = (
                normalized.attempt_id
                or attempt_id
                or (lease.attempt_id if lease else "")
            )
            normalized.lease_epoch = normalized.lease_epoch or int(
                lease_epoch
                if lease_epoch is not None
                else (lease.lease_epoch if lease else 0)
            )
            normalized.trace_id = normalized.trace_id or str(
                job.metadata.get("trace_id") or ""
            )
            job.verification_receipts.append(normalized.as_dict())
            self._set_status_locked(job, job.status)
            self._append_event_locked(
                job.job_id,
                "verification.receipt",
                {"receipt": normalized.as_dict()},
                summary=(
                    "Verification receipt passed"
                    if normalized.status == "pass"
                    else "Verification receipt recorded"
                ),
                detail="; ".join(normalized.failures),
            )
            return normalized

    def begin_effect(
        self,
        job_id: str,
        *,
        effect_key: str,
        kind: str,
        attempt_id: str = "",
        lease_epoch: int | None = None,
        approval_ref: str = "",
        preconditions: dict[str, Any] | None = None,
    ) -> tuple[ConsoleEffect, bool]:
        with self._lock:
            job = self._job_locked(job_id)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            normalized_key = str(effect_key or "").strip()
            if not normalized_key:
                raise ValueError("Effect key is required")
            key = (job_id, normalized_key)
            existing = self._effects.get(key)
            if existing is not None:
                return existing, False
            lease = job.lease
            effect = ConsoleEffect(
                effect_key=normalized_key,
                kind=kind,
                state="started",
                attempt_id=attempt_id or (lease.attempt_id if lease else ""),
                lease_epoch=(
                    lease_epoch
                    if lease_epoch is not None
                    else (lease.lease_epoch if lease else 0)
                ),
                approval_ref=approval_ref,
                preconditions=dict(preconditions or {}),
            )
            self._effects[key] = effect
            return effect, True

    def get_effect(self, job_id: str, *, effect_key: str) -> ConsoleEffect | None:
        with self._lock:
            self._job_locked(job_id)
            return self._effects.get((job_id, str(effect_key or "").strip()))

    def complete_effect(
        self,
        job_id: str,
        *,
        effect_key: str,
        receipt: dict[str, Any] | None = None,
        artifacts: Iterable[Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleEffect:
        return self._finish_effect(
            job_id,
            effect_key=effect_key,
            state="completed",
            receipt=receipt,
            artifacts=artifacts,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )

    def fail_effect(
        self,
        job_id: str,
        *,
        effect_key: str,
        error: str,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleEffect:
        return self._finish_effect(
            job_id,
            effect_key=effect_key,
            state="failed",
            receipt={"error": str(error or "").strip()},
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )

    def mark_effect_unknown(
        self,
        job_id: str,
        *,
        effect_key: str,
        reason: str,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleEffect:
        return self._finish_effect(
            job_id,
            effect_key=effect_key,
            state="unknown",
            receipt={"reason": str(reason or "").strip()},
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
        )

    def record_behavior(
        self,
        job_id: str,
        *,
        phase: str,
        summary: str,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            return self._append_event_locked(
                job.job_id,
                "behavior.observed",
                {
                    "phase": str(phase or "").strip(),
                    "summary": summary,
                    "detail": detail,
                    "metadata": dict(metadata or {}),
                },
                summary=summary,
                detail=detail,
            )

    def record_policy_state(
        self,
        job_id: str,
        *,
        policy_state: RuntimeModeState | dict[str, Any],
        summary: str = "",
        detail: str = "",
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        payload = (
            policy_state.as_dict()
            if hasattr(policy_state, "as_dict")
            else dict(policy_state or {})
        )
        mode = str(payload.get("active_mode") or "").strip()
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            return self._append_event_locked(
                job.job_id,
                "policy.mode_selected",
                payload,
                summary=summary
                or (f"Runtime mode: {mode}" if mode else "Runtime mode selected"),
                detail=detail,
            )

    def record_policy_block(
        self,
        job_id: str,
        *,
        reason: str,
        policy_state: RuntimeModeState | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        payload: dict[str, Any] = {"reason": reason, "metadata": dict(metadata or {})}
        if policy_state is not None:
            payload["policy_state"] = (
                policy_state.as_dict()
                if hasattr(policy_state, "as_dict")
                else dict(policy_state or {})
            )
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            return self._append_event_locked(
                job.job_id,
                "policy.egress_blocked",
                payload,
                summary="Runtime policy blocked route",
                detail=reason,
            )

    def record_route_decision(
        self,
        job_id: str,
        *,
        decision: RouteDecision | dict[str, Any],
        event_type: str = "route.decided",
        summary: str = "",
        detail: str = "",
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        payload = (
            decision.as_dict() if hasattr(decision, "as_dict") else dict(decision or {})
        )
        provider = str(payload.get("selected_provider") or "").strip()
        model = str(payload.get("selected_model") or "").strip()
        route_summary = "Route decided"
        if provider or model:
            route_summary = "Route decided: " + " ".join(
                part for part in (provider, model) if part
            )
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            return self._append_event_locked(
                job.job_id,
                event_type,
                payload,
                summary=summary or route_summary,
                detail=detail or "; ".join(payload.get("blocked_reasons") or []),
            )

    def start_tool(
        self,
        job_id: str,
        *,
        tool_name: str,
        invocation_id: str = "",
        args_summary: str = "",
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> str:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            tool_id = invocation_id or f"tool_{self._next_sequence}"
            tool = str(tool_name or "").strip()
            self._append_event_locked(
                job.job_id,
                "tool.started",
                {
                    "invocation_id": tool_id,
                    "tool_name": tool,
                    "args_summary": args_summary,
                    "metadata": dict(metadata or {}),
                },
                summary=f"Started {tool}" if tool else "Tool started",
                detail=args_summary,
            )
            return tool_id

    def start_shell(
        self,
        job_id: str,
        *,
        command: str,
        invocation_id: str = "",
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> str:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            shell_id = invocation_id or f"shell_{self._next_sequence}"
            self._append_event_locked(
                job.job_id,
                "shell.started",
                {
                    "invocation_id": shell_id,
                    "command": command,
                    "metadata": dict(metadata or {}),
                },
                summary="Shell command started",
                detail=command,
            )
            return shell_id

    def record_shell_output(
        self,
        job_id: str,
        *,
        invocation_id: str,
        text: str,
        stream: str = "stdout",
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            return self._append_event_locked(
                job.job_id,
                "shell.output",
                {
                    "invocation_id": invocation_id,
                    "stream": stream,
                    "text": text,
                    "metadata": dict(metadata or {}),
                },
                summary="Shell output",
                detail=text,
                visibility="stream",
            )

    def complete_shell(
        self,
        job_id: str,
        *,
        invocation_id: str,
        command: str = "",
        summary: str = "",
        output_preview: str = "",
        returncode: int = 0,
        artifacts: Iterable[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            added_artifacts = self._record_artifacts_locked(
                job,
                artifacts or [],
                produced_by_attempt=attempt_id,
            )
            self._append_event_locked(
                job.job_id,
                "shell.completed",
                {
                    "invocation_id": invocation_id,
                    "command": command,
                    "returncode": int(returncode or 0),
                    "output_preview": output_preview,
                    "artifacts": added_artifacts,
                    "metadata": dict(metadata or {}),
                },
                summary=summary or "Shell command completed",
                detail=output_preview,
            )
            return job

    def fail_shell(
        self,
        job_id: str,
        *,
        invocation_id: str,
        command: str = "",
        error: str,
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            self._append_event_locked(
                job.job_id,
                "shell.failed",
                {
                    "invocation_id": invocation_id,
                    "command": command,
                    "error": error,
                    "metadata": dict(metadata or {}),
                },
                summary="Shell command failed",
                detail=error,
            )
            return job

    def complete_tool(
        self,
        job_id: str,
        *,
        invocation_id: str,
        tool_name: str = "",
        summary: str = "",
        output_preview: str = "",
        artifacts: Iterable[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            added_artifacts = self._record_artifacts_locked(
                job,
                artifacts or [],
                produced_by_attempt=attempt_id,
            )
            tool = str(tool_name or "").strip()
            event_summary = summary or (
                f"Completed {tool}" if tool else "Tool completed"
            )
            self._append_event_locked(
                job.job_id,
                "tool.completed",
                {
                    "invocation_id": invocation_id,
                    "tool_name": tool,
                    "summary": summary,
                    "output_preview": output_preview,
                    "artifacts": added_artifacts,
                    "metadata": dict(metadata or {}),
                },
                summary=event_summary,
                detail=output_preview,
            )
            return job

    def fail_tool(
        self,
        job_id: str,
        *,
        invocation_id: str,
        tool_name: str = "",
        error: str,
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            tool = str(tool_name or "").strip()
            self._append_event_locked(
                job.job_id,
                "tool.failed",
                {
                    "invocation_id": invocation_id,
                    "tool_name": tool,
                    "error": error,
                    "metadata": dict(metadata or {}),
                },
                summary=f"Failed {tool}" if tool else "Tool failed",
                detail=error,
            )
            return job

    def record_model_delta(
        self,
        job_id: str,
        *,
        text: str,
        provider: str = "",
        model: str = "",
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            return self._append_event_locked(
                job.job_id,
                "model.delta",
                {
                    "text": text,
                    "provider": provider,
                    "model": model,
                    "metadata": dict(metadata or {}),
                },
                summary="Model output",
                detail=text,
                visibility="stream",
            )

    def record_planner_receipt(
        self,
        job_id: str,
        *,
        receipt: dict[str, Any],
        capabilities: dict[str, Any] | None = None,
        summary: str = "",
        detail: str = "",
        artifacts: Iterable[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            artifact_list = planner_receipt_artifacts(receipt, list(artifacts or []))
            added_artifacts = self._record_artifacts_locked(
                job,
                artifact_list,
                produced_by_attempt=attempt_id,
            )
            return self._append_event_locked(
                job.job_id,
                "planner.receipt",
                planner_receipt_payload(
                    receipt,
                    capabilities=capabilities,
                    metadata=metadata,
                    artifacts=added_artifacts,
                ),
                summary=summary or planner_receipt_summary(receipt),
                detail=detail,
            )

    def invoke_model(
        self,
        job_id: str,
        *,
        adapter: ModelAdapter,
        request: ModelRequest,
        attempt_id: str = "",
        lease_epoch: int | None = None,
        effect_key: str = "",
    ) -> ModelResult:
        resolved_effect_key = ""
        invocation_id = ""
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            if job.status in {
                ConsoleJobStatus.QUEUED,
                ConsoleJobStatus.LEASED,
                ConsoleJobStatus.CHECKPOINTED,
            }:
                self._set_status_locked(job, ConsoleJobStatus.RUNNING)
            request = self._correlated_model_request_locked(
                job,
                request=request,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            invocation_id = str(request.metadata.get("invocation_id") or "").strip()
            resolved_effect_key = str(
                effect_key
                or request.metadata.get("effect_key")
                or request.metadata.get("explicit_invocation_id")
                or ""
            ).strip()
            if resolved_effect_key:
                effect, should_invoke = self.begin_effect(
                    job_id,
                    effect_key=resolved_effect_key,
                    kind="model.invoke",
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                    preconditions={
                        "provider": adapter.name,
                        "model": request.model,
                        "route_key": request.route_key,
                        "invocation_id": invocation_id,
                    },
                )
                if not should_invoke:
                    if effect.state == "completed":
                        return self._model_result_from_effect(effect)
                    self._append_event_locked(
                        job.job_id,
                        "effect.reconciliation_required",
                        {
                            "effect": effect.as_dict(),
                            "invocation_id": invocation_id,
                            "reason": "duplicate model invocation reservation",
                        },
                        summary="Model effect reconciliation required",
                        detail=effect.state,
                    )
                    raise EffectReconciliationRequiredError(
                        "Model invocation is already reserved and requires "
                        f"reconciliation: {resolved_effect_key}"
                    )
            self._append_event_locked(
                job.job_id,
                "model.requested",
                {
                    "provider": adapter.name,
                    "model": request.model,
                    "route_key": request.route_key,
                    "invocation_id": invocation_id,
                    "norllama_pool": request.metadata.get("norllama_pool", ""),
                },
                summary=f"Requested {adapter.name}",
            )

        try:
            result = adapter.invoke(request)
        except Exception as exc:
            with self._lock:
                job = self._job_locked(job_id)
                self._assert_current_attempt_locked(
                    job,
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
                if resolved_effect_key:
                    self.fail_effect(
                        job_id,
                        effect_key=resolved_effect_key,
                        error=str(exc),
                        attempt_id=attempt_id,
                        lease_epoch=lease_epoch,
                    )
                job.last_error = str(exc)
                self._set_status_locked(job, ConsoleJobStatus.FAILED)
                self._append_event_locked(
                    job.job_id,
                    "model.failed",
                    {"provider": adapter.name, "error": str(exc)},
                    summary=f"{adapter.name} failed",
                    detail=str(exc),
                )
            raise

        with self._lock:
            job = self._job_locked(job_id)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
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
            completed_payload = {
                "provider": result.provider,
                "model": result.model,
                "stop_reason": result.stop_reason,
                "usage": result.usage.as_dict(),
                "metadata": metadata,
            }
            if route_receipt:
                route_receipt = {
                    **route_receipt,
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "total_tokens": result.usage.total_tokens,
                }
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
                    task_contract=job.contract.as_dict(),
                    audit=route_receipt["receipt_audit"],
                )
                completed_payload["route_receipt"] = route_receipt
                completed_payload["fast_lane_outcome"] = route_receipt[
                    "fast_lane_outcome"
                ]
                completed_payload["usage_bucket"] = route_receipt.get("usage_bucket")
                completed_payload["output_shape"] = route_receipt.get("output_shape")
                completed_payload["verifier_result"] = route_receipt.get(
                    "verifier_result"
                )
                completed_payload["request_id"] = route_receipt.get("request_id")
                completed_payload["client_request_id"] = route_receipt.get(
                    "client_request_id"
                )
                completed_payload["gateway_request_id"] = route_receipt.get(
                    "gateway_request_id"
                )
                completed_payload["invocation_id"] = route_receipt.get("invocation_id")
            if route:
                completed_payload["route"] = route
                completed_payload["attribution"] = attribution
                completed_payload["local"] = bool(route.get("local"))
                completed_payload["cloud_proxy"] = bool(route.get("cloud_proxy"))
                completed_payload["egress_class"] = (
                    "lan" if route.get("local") else "cloud_llm"
                )
            if resolved_effect_key:
                self.complete_effect(
                    job_id,
                    effect_key=resolved_effect_key,
                    receipt={
                        "invocation_id": invocation_id,
                        "result": result.as_dict(),
                    },
                    attempt_id=attempt_id,
                    lease_epoch=lease_epoch,
                )
            self._append_event_locked(
                job.job_id,
                "model.completed",
                completed_payload,
                summary=f"{result.provider} completed",
                detail=result.stop_reason,
            )
        return result

    def artifact_requirements_satisfied(
        self,
        job_id: str,
        *,
        requirements: Iterable[ConsoleArtifactRequirement | dict[str, Any] | str],
    ) -> bool:
        with self._lock:
            job = self._job_locked(job_id)
            normalized = [
                ConsoleArtifactRequirement.from_value(requirement)
                for requirement in requirements
            ]
            return self._artifact_requirements_satisfied_locked(job, normalized)

    def _job_locked(self, job_id: str) -> ConsoleJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFoundError(f"Unknown job: {job_id}") from exc

    def _append_event_locked(
        self,
        job_id: str,
        event_type: str,
        payload: dict,
        *,
        summary: str = "",
        detail: str = "",
        visibility: str = "timeline",
    ) -> ConsoleRuntimeEvent:
        event_payload = dict(payload or {})
        job = self._jobs.get(job_id)
        if job is not None:
            trace_id = str(job.metadata.get("trace_id") or "").strip()
            if trace_id and "trace_id" not in event_payload:
                event_payload["trace_id"] = trace_id
            if job.lease is not None:
                if job.lease.attempt_id and "attempt_id" not in event_payload:
                    event_payload["attempt_id"] = job.lease.attempt_id
                if "lease_epoch" not in event_payload:
                    event_payload["lease_epoch"] = job.lease.lease_epoch
        event = ConsoleRuntimeEvent(
            job_id=job_id,
            event_type=event_type,
            payload=event_payload,
            sequence=self._next_sequence,
            summary=summary,
            detail=detail,
            visibility=visibility,
        )
        self._next_sequence += 1
        self._events.append(event)
        return event

    def _set_status_locked(self, job: ConsoleJob, status: ConsoleJobStatus) -> None:
        job.status = status
        job.updated_at = utc_now_iso()

    def _ensure_not_terminal(self, job: ConsoleJob) -> None:
        if job.status in _TERMINAL_STATES:
            raise InvalidTransitionError(
                f"Job {job.job_id} is already {job.status.value}"
            )

    def _assert_current_attempt_locked(
        self,
        job: ConsoleJob,
        *,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> None:
        if not attempt_id and lease_epoch is None:
            return
        lease = job.lease
        expected_attempt_id = lease.attempt_id if lease is not None else ""
        expected_epoch = lease.lease_epoch if lease is not None else 0
        if (
            not attempt_id
            or lease_epoch is None
            or attempt_id != expected_attempt_id
            or int(lease_epoch) != expected_epoch
        ):
            raise InvalidTransitionError(
                f"Stale runtime attempt cannot mutate job {job.job_id}"
            )

    def _record_artifacts_locked(
        self,
        job: ConsoleJob,
        artifacts: Iterable[Any],
        *,
        produced_by_attempt: str = "",
    ) -> List[str]:
        added: List[str] = []
        for artifact in artifacts:
            normalized = ConsoleArtifact.from_value(artifact)
            if produced_by_attempt and not normalized.produced_by_attempt:
                normalized.produced_by_attempt = produced_by_attempt
            value = normalized.legacy_name
            if value and value not in job.artifacts:
                job.artifacts.append(value)
                added.append(value)
            if not any(
                str(record.get("artifact_id") or "").strip() == normalized.artifact_id
                for record in job.artifact_records
                if isinstance(record, dict)
            ):
                job.artifact_records.append(normalized.as_dict())
        return added

    def _artifact_requirements_satisfied_locked(
        self,
        job: ConsoleJob,
        requirements: Iterable[ConsoleArtifactRequirement],
    ) -> bool:
        artifacts = [
            ConsoleArtifact.from_value(record)
            for record in job.artifact_records
            if isinstance(record, dict)
        ]
        if not artifacts:
            artifacts = [ConsoleArtifact.from_value(item) for item in job.artifacts]
        return all(
            any(requirement.matches(artifact) for artifact in artifacts)
            for requirement in requirements
        )

    def _checkpoint_capsule_locked(
        self,
        job: ConsoleJob,
        *,
        summary: str,
        capsule: ConsoleCheckpointCapsule | dict[str, Any] | None,
        attempt_id: str,
        lease_epoch: int | None,
    ) -> ConsoleCheckpointCapsule:
        value = (
            ConsoleCheckpointCapsule.from_value(capsule)
            if capsule is not None
            else ConsoleCheckpointCapsule(summary=summary or "Checkpointed")
        )
        if not value.summary:
            value.summary = summary or "Checkpointed"
        lease = job.lease
        value.attempt_id = (
            value.attempt_id or attempt_id or (lease.attempt_id if lease else "")
        )
        value.lease_epoch = value.lease_epoch or int(
            lease_epoch
            if lease_epoch is not None
            else (lease.lease_epoch if lease else 0)
        )
        value.trace_id = value.trace_id or str(job.metadata.get("trace_id") or "")
        if not value.artifact_digests:
            value.artifact_digests = [
                artifact.sha256
                for artifact in (
                    ConsoleArtifact.from_value(record)
                    for record in job.artifact_records
                    if isinstance(record, dict)
                )
                if artifact.sha256
            ]
        return value

    def _verification_required_locked(self, job: ConsoleJob) -> bool:
        values = (job.contract.route_policy, job.contract.metadata, job.metadata)
        return any(
            self._policy_flag(value.get(key))
            for value in values
            if isinstance(value, dict)
            for key in (
                "require_verification_receipt",
                "require_verifier_for_completion",
                "verification_required",
            )
        )

    @staticmethod
    def _policy_flag(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "enabled",
            "force",
        }

    def _finish_effect(
        self,
        job_id: str,
        *,
        effect_key: str,
        state: str,
        receipt: dict[str, Any] | None = None,
        artifacts: Iterable[Any] | None = None,
        attempt_id: str = "",
        lease_epoch: int | None = None,
    ) -> ConsoleEffect:
        if state not in {"completed", "failed", "unknown"}:
            raise ValueError(f"Invalid terminal effect state: {state}")
        with self._lock:
            job = self._job_locked(job_id)
            self._assert_current_attempt_locked(
                job,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
            )
            normalized_key = str(effect_key or "").strip()
            effect = self._effects.get((job_id, normalized_key))
            if effect is None:
                raise InvalidTransitionError(f"Unknown runtime effect: {effect_key}")
            if effect.state == state:
                return effect
            if effect.state not in {"planned", "started"}:
                raise InvalidTransitionError(
                    f"Cannot mark effect {effect_key} {state} from state {effect.state}"
                )
            effect.state = state
            effect.receipt = dict(receipt or {})
            if artifacts is not None:
                refs: list[str] = []
                for artifact in artifacts:
                    normalized = ConsoleArtifact.from_value(artifact)
                    ref = normalized.ref or normalized.artifact_id or normalized.name
                    if ref and ref not in refs:
                        refs.append(ref)
                effect.artifact_refs = refs
            effect.updated_at = utc_now_iso()
            return effect

    def _correlated_model_request_locked(
        self,
        job: ConsoleJob,
        *,
        request: ModelRequest,
        attempt_id: str,
        lease_epoch: int | None,
    ) -> ModelRequest:
        original_metadata = dict(request.metadata or {})
        request_policy = original_metadata.get("route_policy")
        route_policy = {
            **dict(job.contract.route_policy or {}),
            **(dict(request_policy) if isinstance(request_policy, dict) else {}),
        }
        provider = (
            str(
                route_policy.get("provider")
                or route_policy.get("preferred_provider")
                or ""
            )
            .strip()
            .lower()
        )
        norllama_pool = str(
            original_metadata.get("norllama_pool")
            or route_policy.get("norllama_pool")
            or ("default" if provider == "norllama" else "")
        ).strip()
        if norllama_pool:
            route_policy["norllama_pool"] = norllama_pool
        lease = job.lease
        resolved_attempt_id = attempt_id or (lease.attempt_id if lease else "")
        resolved_lease_epoch = (
            lease_epoch
            if lease_epoch is not None
            else (lease.lease_epoch if lease else 0)
        )
        explicit_invocation_id = str(
            original_metadata.get("invocation_id") or ""
        ).strip()
        invocation_id = explicit_invocation_id or (
            f"kernel:{job.job_id}:{self._next_sequence}:model"
        )
        metadata = {
            **original_metadata,
            "route_policy": route_policy,
            "runtime_job_id": job.job_id,
            "console_runtime_job_id": job.job_id,
            "job_id": job.job_id,
            "trace_id": str(job.metadata.get("trace_id") or "").strip(),
            "attempt_id": resolved_attempt_id,
            "lease_epoch": resolved_lease_epoch,
            "invocation_id": invocation_id,
            "explicit_invocation_id": explicit_invocation_id,
        }
        if norllama_pool:
            metadata["norllama_pool"] = norllama_pool
        return ModelRequest(
            messages=request.messages,
            model=request.model,
            route_key=request.route_key,
            system=request.system,
            temperature=request.temperature,
            budget=request.budget,
            metadata=metadata,
        )

    @staticmethod
    def _model_result_from_effect(effect: ConsoleEffect) -> ModelResult:
        result = effect.receipt.get("result")
        if not isinstance(result, dict):
            raise EffectReconciliationRequiredError(
                f"Completed model effect has no replayable result: {effect.effect_key}"
            )
        usage = result.get("usage")
        return ModelResult(
            provider=str(result.get("provider") or ""),
            model=str(result.get("model") or ""),
            text=str(result.get("text") or ""),
            stop_reason=str(result.get("stop_reason") or ""),
            usage=ModelUsage(**dict(usage or {})),
            metadata=dict(result.get("metadata") or {}),
            raw=dict(result.get("raw") or {}),
        )
