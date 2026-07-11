from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List

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
class ConsoleJobLease:
    worker_id: str
    leased_at: str
    expires_at: str

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
    artifacts: List[str] = field(default_factory=list)
    last_error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

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
