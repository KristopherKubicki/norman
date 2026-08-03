from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List

from app.services.console_runtime.events import utc_now_iso


class ConsoleJobStatus(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    PLANNING = "planning"
    RUNNING = "running"
    VERIFYING = "verifying"
    CHECKPOINTED = "checkpointed"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELED = "canceled"
    FAILED = "failed"


_SUBTASK_WRITE_MODES = {"read_only", "patch_only", "isolated_worktree"}


def _clean_list(values: List[Any] | None) -> List[str]:
    clean: List[str] = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            clean.append(text)
    return clean


def _clean_dict(value: Dict[str, Any] | None) -> Dict[str, Any]:
    return dict(value or {})


@dataclass
class ConsoleArtifact:
    """A durable, typed output that another runtime job may consume."""

    artifact_id: str = ""
    name: str = ""
    ref: str = ""
    sha256: str = ""
    schema_name: str = ""
    schema_version: str = ""
    produced_by_attempt: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.artifact_id = str(self.artifact_id or "").strip()
        self.name = str(self.name or "").strip()
        self.ref = str(self.ref or "").strip()
        self.sha256 = str(self.sha256 or "").strip().lower()
        self.schema_name = str(self.schema_name or "").strip()
        self.schema_version = str(self.schema_version or "").strip()
        self.produced_by_attempt = str(self.produced_by_attempt or "").strip()
        self.metadata = _clean_dict(self.metadata)
        self.created_at = str(self.created_at or utc_now_iso()).strip()
        if not self.artifact_id:
            self.artifact_id = self.name or self.ref
        if not self.name:
            self.name = self.artifact_id or self.ref
        if not self.artifact_id:
            raise ValueError("Console artifact requires an artifact_id, name, or ref")

    @classmethod
    def from_value(cls, value: Any) -> "ConsoleArtifact":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(artifact_id=value, name=value, ref=value)
        if isinstance(value, dict):
            payload = dict(value)
            if "uri" in payload and "ref" not in payload:
                payload["ref"] = payload.pop("uri")
            if "digest" in payload and "sha256" not in payload:
                payload["sha256"] = payload.pop("digest")
            return cls(**payload)
        raise ValueError("Console artifact must be a string, dict, or ConsoleArtifact")

    @property
    def legacy_name(self) -> str:
        return self.name or self.ref or self.artifact_id

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleArtifactRequirement:
    """An artifact contract for a dependency edge."""

    name: str
    schema_name: str = ""
    schema_version: str = ""
    sha256: str = ""

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        self.schema_name = str(self.schema_name or "").strip()
        self.schema_version = str(self.schema_version or "").strip()
        self.sha256 = str(self.sha256 or "").strip().lower()
        if not self.name:
            raise ValueError("Console artifact requirement name is required")

    @classmethod
    def from_value(cls, value: Any) -> "ConsoleArtifactRequirement":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(name=value)
        if isinstance(value, dict):
            payload = dict(value)
            if "artifact_id" in payload and "name" not in payload:
                payload["name"] = payload.pop("artifact_id")
            if "digest" in payload and "sha256" not in payload:
                payload["sha256"] = payload.pop("digest")
            return cls(**payload)
        raise ValueError(
            "Console artifact requirement must be a string, dict, or "
            "ConsoleArtifactRequirement"
        )

    def matches(self, artifact: ConsoleArtifact) -> bool:
        if self.name not in {
            artifact.artifact_id,
            artifact.name,
            artifact.ref,
            artifact.legacy_name,
        }:
            return False
        if self.schema_name and self.schema_name != artifact.schema_name:
            return False
        if self.schema_version and self.schema_version != artifact.schema_version:
            return False
        if self.sha256 and self.sha256 != artifact.sha256:
            return False
        return True

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleCheckpointCapsule:
    """Enough verified context to resume a job without replaying its full turn."""

    summary: str = ""
    facts: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    completed_clauses: List[str] = field(default_factory=list)
    remaining_clauses: List[str] = field(default_factory=list)
    next_safe_action: str = ""
    artifact_digests: List[str] = field(default_factory=list)
    route_receipt_ref: str = ""
    unresolved_questions: List[str] = field(default_factory=list)
    approval_state: str = ""
    attempt_id: str = ""
    lease_epoch: int = 0
    trace_id: str = ""
    schema: str = "norman.console-runtime.checkpoint-capsule.v1"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.summary = str(self.summary or "").strip()
        self.facts = _clean_list(self.facts)
        self.evidence_refs = _clean_list(self.evidence_refs)
        self.completed_clauses = _clean_list(self.completed_clauses)
        self.remaining_clauses = _clean_list(self.remaining_clauses)
        self.next_safe_action = str(self.next_safe_action or "").strip()
        self.artifact_digests = _clean_list(self.artifact_digests)
        self.route_receipt_ref = str(self.route_receipt_ref or "").strip()
        self.unresolved_questions = _clean_list(self.unresolved_questions)
        self.approval_state = str(self.approval_state or "").strip()
        self.attempt_id = str(self.attempt_id or "").strip()
        self.lease_epoch = max(0, int(self.lease_epoch or 0))
        self.trace_id = str(self.trace_id or "").strip()
        self.schema = str(self.schema or "").strip() or (
            "norman.console-runtime.checkpoint-capsule.v1"
        )
        self.created_at = str(self.created_at or utc_now_iso()).strip()

    @classmethod
    def from_value(cls, value: Any) -> "ConsoleCheckpointCapsule":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(summary=value)
        if isinstance(value, dict):
            return cls(**dict(value))
        raise ValueError(
            "Console checkpoint capsule must be a string, dict, or "
            "ConsoleCheckpointCapsule"
        )

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleVerificationReceipt:
    verifier: str
    status: str
    evidence_refs: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    artifact_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    attempt_id: str = ""
    lease_epoch: int = 0
    trace_id: str = ""
    verified_at: str = field(default_factory=utc_now_iso)
    schema: str = "norman.console-runtime.verification-receipt.v1"

    def __post_init__(self) -> None:
        self.verifier = str(self.verifier or "").strip()
        self.status = str(self.status or "").strip().lower()
        if not self.verifier:
            raise ValueError("Console verification receipt verifier is required")
        if self.status not in {"pass", "fail", "unknown"}:
            raise ValueError(
                "Console verification receipt status must be pass, fail, or unknown"
            )
        self.evidence_refs = _clean_list(self.evidence_refs)
        self.failures = _clean_list(self.failures)
        self.artifact_refs = _clean_list(self.artifact_refs)
        self.metadata = _clean_dict(self.metadata)
        self.attempt_id = str(self.attempt_id or "").strip()
        self.lease_epoch = max(0, int(self.lease_epoch or 0))
        self.trace_id = str(self.trace_id or "").strip()
        self.verified_at = str(self.verified_at or utc_now_iso()).strip()
        self.schema = str(self.schema or "").strip() or (
            "norman.console-runtime.verification-receipt.v1"
        )

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RetryClass(str, Enum):
    TRANSIENT_TRANSPORT = "transient_transport"
    CAPACITY = "capacity"
    MALFORMED_RESPONSE = "malformed_response"
    POLICY_DENIED = "policy_denied"
    CANCELED = "canceled"
    PARTIAL_EFFECT = "partial_effect"
    VALIDATION_FAILED = "validation_failed"
    UNKNOWN = "unknown"

    @classmethod
    def normalize(cls, value: Any) -> "RetryClass":
        if isinstance(value, cls):
            return value
        clean = str(value or "").strip().lower().replace("-", "_")
        try:
            return cls(clean)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class ConsoleEffect:
    effect_key: str
    kind: str
    state: str = "planned"
    attempt_id: str = ""
    lease_epoch: int = 0
    approval_ref: str = ""
    preconditions: Dict[str, Any] = field(default_factory=dict)
    receipt: Dict[str, Any] = field(default_factory=dict)
    artifact_refs: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.effect_key = str(self.effect_key or "").strip()
        self.kind = str(self.kind or "").strip()
        self.state = str(self.state or "planned").strip().lower()
        if not self.effect_key or not self.kind:
            raise ValueError("Console effect requires an effect_key and kind")
        if self.state not in {"planned", "started", "completed", "failed", "unknown"}:
            raise ValueError("Console effect state is invalid")
        self.attempt_id = str(self.attempt_id or "").strip()
        self.lease_epoch = max(0, int(self.lease_epoch or 0))
        self.approval_ref = str(self.approval_ref or "").strip()
        self.preconditions = _clean_dict(self.preconditions)
        self.receipt = _clean_dict(self.receipt)
        self.artifact_refs = _clean_list(self.artifact_refs)
        self.created_at = str(self.created_at or utc_now_iso()).strip()
        self.updated_at = str(self.updated_at or utc_now_iso()).strip()

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleJobContract:
    objective: str
    done_when: List[str] = field(default_factory=list)
    success_metrics: List[str] = field(default_factory=list)
    required_artifacts: List[str] = field(default_factory=list)
    max_runtime_seconds: int = 7200
    checkpoint_interval_seconds: int = 900
    question_budget: int = 1
    approval_required_for: List[str] = field(default_factory=list)
    authority_flags: Dict[str, Any] = field(default_factory=dict)
    route_policy: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.objective = str(self.objective or "").strip()
        if not self.objective:
            raise ValueError("Console job objective is required")
        self.done_when = _clean_list(self.done_when)
        self.success_metrics = _clean_list(self.success_metrics)
        self.required_artifacts = _clean_list(self.required_artifacts)
        self.approval_required_for = _clean_list(self.approval_required_for)
        self.max_runtime_seconds = max(1, int(self.max_runtime_seconds or 1))
        self.checkpoint_interval_seconds = max(
            1, int(self.checkpoint_interval_seconds or 1)
        )
        self.question_budget = max(0, int(self.question_budget or 0))
        self.authority_flags = _clean_dict(self.authority_flags)
        self.route_policy = _clean_dict(self.route_policy)
        self.metadata = _clean_dict(self.metadata)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleSubtaskContract:
    objective: str
    title: str = ""
    job_id: str = ""
    done_when: List[str] = field(default_factory=list)
    success_metrics: List[str] = field(default_factory=list)
    required_artifacts: List[str] = field(default_factory=list)
    max_runtime_seconds: int = 1800
    checkpoint_interval_seconds: int = 300
    question_budget: int = 0
    approval_required_for: List[str] = field(default_factory=list)
    authority_flags: Dict[str, Any] = field(default_factory=dict)
    route_policy: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    write_mode: str = "read_only"
    depends_on: List[str] = field(default_factory=list)
    dependency_artifacts: Dict[str, List[Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.objective = str(self.objective or "").strip()
        if not self.objective:
            raise ValueError("Console subtask objective is required")
        self.title = str(self.title or "").strip()
        self.job_id = str(self.job_id or "").strip()
        self.done_when = _clean_list(self.done_when)
        self.success_metrics = _clean_list(self.success_metrics)
        self.required_artifacts = _clean_list(self.required_artifacts)
        self.approval_required_for = _clean_list(self.approval_required_for)
        self.max_runtime_seconds = max(1, int(self.max_runtime_seconds or 1))
        self.checkpoint_interval_seconds = max(
            1, int(self.checkpoint_interval_seconds or 1)
        )
        self.question_budget = max(0, int(self.question_budget or 0))
        self.authority_flags = _clean_dict(self.authority_flags)
        self.route_policy = _clean_dict(self.route_policy)
        self.metadata = _clean_dict(self.metadata)
        self.write_mode = str(self.write_mode or "read_only").strip().lower()
        if self.write_mode not in _SUBTASK_WRITE_MODES:
            raise ValueError(
                "Console subtask write_mode must be one of: "
                + ", ".join(sorted(_SUBTASK_WRITE_MODES))
            )
        self.depends_on = _clean_list(self.depends_on)
        normalized_requirements: Dict[str, List[Dict[str, Any]]] = {}
        for dependency_id, requirements in _clean_dict(
            self.dependency_artifacts
        ).items():
            clean_dependency_id = str(dependency_id or "").strip()
            if not clean_dependency_id:
                continue
            values: Iterable[Any]
            if isinstance(requirements, (list, tuple)):
                values = requirements
            else:
                values = [requirements]
            normalized_requirements[clean_dependency_id] = [
                ConsoleArtifactRequirement.from_value(requirement).as_dict()
                for requirement in values
            ]
        unknown_requirements = set(normalized_requirements) - set(self.depends_on)
        if unknown_requirements:
            raise ValueError(
                "Console dependency_artifacts keys must be listed in depends_on: "
                + ", ".join(sorted(unknown_requirements))
            )
        self.dependency_artifacts = normalized_requirements

    def as_job_contract(self) -> ConsoleJobContract:
        authority_flags = {
            **self.authority_flags,
            "write_mode": self.write_mode,
            "delegated_subtask": True,
        }
        route_policy = {
            **self.route_policy,
            "write_mode": self.write_mode,
            "delegated_subtask": True,
        }
        metadata = {
            **self.metadata,
            "write_mode": self.write_mode,
            "delegated_subtask": True,
        }
        return ConsoleJobContract(
            objective=self.objective,
            done_when=self.done_when,
            success_metrics=self.success_metrics,
            required_artifacts=self.required_artifacts,
            max_runtime_seconds=self.max_runtime_seconds,
            checkpoint_interval_seconds=self.checkpoint_interval_seconds,
            question_budget=self.question_budget,
            approval_required_for=self.approval_required_for,
            authority_flags=authority_flags,
            route_policy=route_policy,
            metadata=metadata,
        )

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleJobLease:
    worker_id: str
    leased_at: str
    expires_at: str
    attempt_id: str = ""
    lease_epoch: int = 0

    def __post_init__(self) -> None:
        self.worker_id = str(self.worker_id or "").strip()
        self.leased_at = str(self.leased_at or "").strip()
        self.expires_at = str(self.expires_at or "").strip()
        self.attempt_id = str(self.attempt_id or "").strip()
        self.lease_epoch = max(0, int(self.lease_epoch or 0))

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleJob:
    job_id: str
    contract: ConsoleJobContract
    status: ConsoleJobStatus = ConsoleJobStatus.QUEUED
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    lease: ConsoleJobLease | None = None
    checkpoints: List[str] = field(default_factory=list)
    checkpoint_capsules: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    artifact_records: List[Dict[str, Any]] = field(default_factory=list)
    verification_receipts: List[Dict[str, Any]] = field(default_factory=list)
    last_error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    workstream_id: str = ""
    parent_job_id: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    cancel_requested_at: str = ""

    @classmethod
    def new(
        cls, *, contract: ConsoleJobContract, job_id: str | None = None
    ) -> "ConsoleJob":
        return cls(
            job_id=job_id or f"job_{uuid.uuid4().hex}",
            contract=contract,
        )

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class ConsoleTaskResult:
    status: str
    summary: str = ""
    detail: str = ""
    artifacts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.status = str(self.status or "").strip().lower()
        if not self.status:
            raise ValueError("Console task result status is required")
        self.summary = str(self.summary or "").strip()
        self.detail = str(self.detail or "").strip()
        self.artifacts = _clean_list(self.artifacts)
        self.metadata = _clean_dict(self.metadata)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsoleWorkstream:
    workstream_id: str
    coordinator_job_id: str
    title: str = ""
    status: str = "active"
    metadata: Dict[str, Any] = field(default_factory=dict)
    max_concurrency: int = 10
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.workstream_id = str(self.workstream_id or "").strip()
        self.coordinator_job_id = str(self.coordinator_job_id or "").strip()
        if not self.workstream_id or not self.coordinator_job_id:
            raise ValueError("Console workstream and coordinator job IDs are required")
        self.title = str(self.title or "").strip()
        self.status = str(self.status or "active").strip().lower()
        self.metadata = _clean_dict(self.metadata)
        self.max_concurrency = max(1, min(int(self.max_concurrency or 1), 10))

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelBudget:
    max_model_calls: int = 1
    max_runtime_seconds: int = 900
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        self.max_model_calls = max(1, int(self.max_model_calls or 1))
        self.max_runtime_seconds = max(1, int(self.max_runtime_seconds or 1))
        self.max_output_tokens = max(1, int(self.max_output_tokens or 1))

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelRequest:
    messages: List[Dict[str, Any]]
    model: str = ""
    route_key: str = ""
    system: str = ""
    temperature: float | None = None
    budget: ModelBudget = field(default_factory=ModelBudget)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.messages = [dict(message) for message in self.messages or []]
        self.model = str(self.model or "").strip()
        self.route_key = str(self.route_key or "").strip()
        self.system = str(self.system or "")
        self.metadata = _clean_dict(self.metadata)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        self.input_tokens = max(0, int(self.input_tokens or 0))
        self.output_tokens = max(0, int(self.output_tokens or 0))
        self.total_tokens = max(
            int(self.total_tokens or 0), self.input_tokens + self.output_tokens
        )

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelResult:
    provider: str
    model: str
    text: str
    stop_reason: str = ""
    usage: ModelUsage = field(default_factory=ModelUsage)
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "").strip()
        self.model = str(self.model or "").strip()
        self.text = str(self.text or "")
        self.stop_reason = str(self.stop_reason or "")
        self.metadata = _clean_dict(self.metadata)
        self.raw = _clean_dict(self.raw)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelCapabilities:
    provider: str
    models: List[str] = field(default_factory=list)
    supports_tools: bool = False
    supports_streaming: bool = False
    supports_files: bool = False
    local: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "").strip()
        self.models = _clean_list(self.models)
        self.metadata = _clean_dict(self.metadata)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeModeState:
    active_mode: str = "primary_online"
    llm_plane: str = "cloud_ok"
    runner_plane: str = "kernel_shell"
    network_plane: str = "internet_ok"
    tool_plane: str = "full_tools"
    egress_policy: str = "normal"
    cloud_llm_allowed: bool = True
    codex_allowed: bool = True
    web_allowed: bool = True
    lan_allowed: bool = True
    shell_allowed: bool = True
    degraded: bool = False
    notices: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.active_mode = str(self.active_mode or "primary_online").strip()
        self.llm_plane = str(self.llm_plane or "cloud_ok").strip()
        self.runner_plane = str(self.runner_plane or "kernel_shell").strip()
        self.network_plane = str(self.network_plane or "internet_ok").strip()
        self.tool_plane = str(self.tool_plane or "full_tools").strip()
        self.egress_policy = str(self.egress_policy or "normal").strip()
        self.cloud_llm_allowed = bool(self.cloud_llm_allowed)
        self.codex_allowed = bool(self.codex_allowed)
        self.web_allowed = bool(self.web_allowed)
        self.lan_allowed = bool(self.lan_allowed)
        self.shell_allowed = bool(self.shell_allowed)
        self.degraded = bool(self.degraded)
        self.notices = _clean_list(self.notices)
        self.reasons = _clean_list(self.reasons)
        self.metadata = _clean_dict(self.metadata)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RouteDecision:
    task_kind: str
    selected_lane: str
    selected_provider: str
    selected_runner: str = ""
    selected_model: str = ""
    selected_endpoint: str = ""
    local: bool = False
    cloud_proxy: bool = False
    egress_class: str = "unknown_external"
    cost_basis: str = "unknown"
    allowed: bool = True
    reasons: List[str] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)
    fallback_order: List[str] = field(default_factory=list)
    capability_snapshot: Dict[str, Any] = field(default_factory=dict)
    policy_state: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    decision_id: str = field(default_factory=lambda: f"route_{uuid.uuid4().hex}")

    def __post_init__(self) -> None:
        self.task_kind = str(self.task_kind or "").strip()
        self.selected_lane = str(self.selected_lane or "").strip()
        self.selected_provider = str(self.selected_provider or "").strip()
        self.selected_runner = str(self.selected_runner or "").strip()
        self.selected_model = str(self.selected_model or "").strip()
        self.selected_endpoint = str(self.selected_endpoint or "").strip()
        self.local = bool(self.local)
        self.cloud_proxy = bool(self.cloud_proxy)
        self.egress_class = str(self.egress_class or "unknown_external").strip()
        self.cost_basis = str(self.cost_basis or "unknown").strip()
        self.allowed = bool(self.allowed)
        self.reasons = _clean_list(self.reasons)
        self.blocked_reasons = _clean_list(self.blocked_reasons)
        self.fallback_order = _clean_list(self.fallback_order)
        self.capability_snapshot = _clean_dict(self.capability_snapshot)
        self.policy_state = _clean_dict(self.policy_state)
        self.metadata = _clean_dict(self.metadata)
        self.decision_id = str(self.decision_id or f"route_{uuid.uuid4().hex}").strip()

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
