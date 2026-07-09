from __future__ import annotations

import threading
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
    ConsoleJob,
    ConsoleJobContract,
    ConsoleJobLease,
    ConsoleJobStatus,
    ModelRequest,
    ModelResult,
    RouteDecision,
    RuntimeModeState,
)
from app.services.norllama.specialist_lanes import evaluate_specialist_cascade


class ConsoleRuntimeError(RuntimeError):
    """Base error raised by the Norman console runtime."""


class JobNotFoundError(ConsoleRuntimeError):
    """Raised when a job id is unknown to the runtime."""


class InvalidTransitionError(ConsoleRuntimeError):
    """Raised when a job state transition would violate the job contract."""


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
        self._next_sequence = 1

    def create_job(
        self, contract: ConsoleJobContract, *, job_id: str | None = None
    ) -> ConsoleJob:
        job = ConsoleJob.new(contract=contract, job_id=job_id)
        with self._lock:
            if job.job_id in self._jobs:
                raise InvalidTransitionError(f"Job already exists: {job.job_id}")
            self._jobs[job.job_id] = job
            self._append_event_locked(
                job.job_id,
                "job.created",
                {
                    "objective": contract.objective,
                    "done_when": list(contract.done_when),
                    "required_artifacts": list(contract.required_artifacts),
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
            job.lease = ConsoleJobLease(
                worker_id=worker_id,
                leased_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
            )
            self._set_status_locked(job, ConsoleJobStatus.LEASED)
            self._append_event_locked(
                job.job_id,
                "job.leased",
                {
                    "worker_id": worker_id,
                    "expires_at": job.lease.expires_at,
                },
                summary=f"Leased to {worker_id}",
            )
            return job

    def start_job(self, job_id: str) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
        artifacts: Iterable[str] | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            if job.status not in {
                ConsoleJobStatus.LEASED,
                ConsoleJobStatus.RUNNING,
                ConsoleJobStatus.VERIFYING,
                ConsoleJobStatus.WAITING_APPROVAL,
            }:
                raise InvalidTransitionError(
                    f"Cannot checkpoint job {job_id} from state {job.status.value}"
                )
            added_artifacts = self._record_artifacts_locked(job, artifacts or [])
            job.checkpoints.append(summary)
            self._set_status_locked(job, ConsoleJobStatus.CHECKPOINTED)
            self._append_event_locked(
                job.job_id,
                "job.checkpointed",
                {"summary": summary, "artifacts": added_artifacts},
                summary=summary,
            )
            return job

    def require_approval(
        self, job_id: str, *, reason: str, requested_by: str = ""
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
        artifacts: Iterable[str] | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            added_artifacts = self._record_artifacts_locked(job, artifacts or [])
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
            self._set_status_locked(job, ConsoleJobStatus.DONE)
            self._append_event_locked(
                job.job_id,
                "job.completed",
                {"summary": summary, "artifacts": added_artifacts},
                summary=summary or "Job completed",
            )
            return job

    def block_job(self, job_id: str, *, reason: str) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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

    def fail_job(self, job_id: str, *, error: str) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            job.last_error = error
            self._set_status_locked(job, ConsoleJobStatus.FAILED)
            self._append_event_locked(
                job.job_id,
                "job.failed",
                {"error": error},
                summary="Job failed",
                detail=error,
            )
            return job

    def cancel_job(self, job_id: str, *, reason: str = "") -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            if job.status == ConsoleJobStatus.DONE:
                raise InvalidTransitionError("Completed jobs cannot be canceled")
            if job.status in {ConsoleJobStatus.CANCELED, ConsoleJobStatus.FAILED}:
                return job
            self._set_status_locked(job, ConsoleJobStatus.CANCELED)
            self._append_event_locked(
                job.job_id,
                "job.canceled",
                {"reason": reason},
                summary="Job canceled",
                detail=reason,
            )
            return job

    def record_behavior(
        self,
        job_id: str,
        *,
        phase: str,
        summary: str,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
    ) -> str:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
    ) -> str:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
        artifacts: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            added_artifacts = self._record_artifacts_locked(job, artifacts or [])
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
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
        artifacts: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            added_artifacts = self._record_artifacts_locked(job, artifacts or [])
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
    ) -> ConsoleJob:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
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
        artifacts: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConsoleRuntimeEvent:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            artifact_list = planner_receipt_artifacts(receipt, list(artifacts or []))
            added_artifacts = self._record_artifacts_locked(job, artifact_list)
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
    ) -> ModelResult:
        with self._lock:
            job = self._job_locked(job_id)
            self._ensure_not_terminal(job)
            if job.status in {
                ConsoleJobStatus.QUEUED,
                ConsoleJobStatus.LEASED,
                ConsoleJobStatus.CHECKPOINTED,
            }:
                self._set_status_locked(job, ConsoleJobStatus.RUNNING)
            self._append_event_locked(
                job.job_id,
                "model.requested",
                {
                    "provider": adapter.name,
                    "model": request.model,
                    "route_key": request.route_key,
                },
                summary=f"Requested {adapter.name}",
            )

        try:
            result = adapter.invoke(request)
        except Exception as exc:
            with self._lock:
                job = self._job_locked(job_id)
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
                completed_payload["route_receipt"] = route_receipt
                completed_payload["usage_bucket"] = route_receipt.get("usage_bucket")
                completed_payload["output_shape"] = route_receipt.get("output_shape")
                completed_payload["verifier_result"] = route_receipt.get(
                    "verifier_result"
                )
            if route:
                completed_payload["route"] = route
                completed_payload["attribution"] = attribution
                completed_payload["local"] = bool(route.get("local"))
                completed_payload["cloud_proxy"] = bool(route.get("cloud_proxy"))
                completed_payload["egress_class"] = (
                    "lan" if route.get("local") else "cloud_llm"
                )
            self._append_event_locked(
                job.job_id,
                "model.completed",
                completed_payload,
                summary=f"{result.provider} completed",
                detail=result.stop_reason,
            )
        return result

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
        event = ConsoleRuntimeEvent(
            job_id=job_id,
            event_type=event_type,
            payload=payload,
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

    def _record_artifacts_locked(
        self, job: ConsoleJob, artifacts: Iterable[str]
    ) -> List[str]:
        added: List[str] = []
        for artifact in artifacts:
            value = str(artifact or "").strip()
            if value and value not in job.artifacts:
                job.artifacts.append(value)
                added.append(value)
        return added
