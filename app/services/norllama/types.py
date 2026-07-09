from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _clean_list(values: list[Any] | None) -> list[Any]:
    return [value for value in values or [] if value is not None]


class NorllamaTaskKind(str, Enum):
    CHAT = "chat"
    CODE = "code"
    SCOUT = "scout"
    PLAN = "plan"
    FILTER = "filter"
    SUMMARIZE = "summarize"
    COMPACT = "compact"
    VERIFY = "verify"
    JUDGE = "judge"
    OCR = "ocr"
    DOC_PARSE = "doc_parse"
    STT = "stt"
    ASR = "asr"
    TTS = "tts"
    EMBED = "embed"
    RERANK = "rerank"
    SAFETY = "safety"
    PROMPT_INJECTION = "prompt_injection"
    GUI_GROUND = "gui_ground"
    FORECAST = "forecast"
    GRAPH = "graph"
    NETWORK = "network"
    WORLD = "world"
    IMAGE_GENERATE = "image_generate"


@dataclass
class NorllamaTaskRequest:
    kind: NorllamaTaskKind | str
    input_text: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    query: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    route_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    task_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NorllamaTaskKind):
            self.kind = NorllamaTaskKind(_clean(self.kind).lower())
        self.input_text = _clean(self.input_text)
        self.query = _clean(self.query)
        self.messages = [dict(message) for message in self.messages or []]
        self.candidates = [dict(candidate) for candidate in self.candidates or []]
        self.artifacts = [dict(artifact) for artifact in self.artifacts or []]
        self.route_policy = _clean_dict(self.route_policy)
        self.metadata = _clean_dict(self.metadata)
        self.task_id = _clean(self.task_id) or f"norllama_task_{uuid.uuid4().hex}"
        if not (
            self.input_text
            or self.messages
            or self.query
            or self.candidates
            or self.artifacts
        ):
            raise ValueError(
                "Norllama task requires input text, messages, query, candidates, or artifacts"
            )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True)
class NorllamaRoute:
    lane: str
    provider: str
    provider_kind: str
    capability: str
    model: str = ""
    endpoint: str = ""
    mode: str = "offline_local"
    local: bool = True
    cloud_proxy: bool = False
    tool_lane: bool = False
    requires_receipt: bool = False
    reason: str = ""
    attribution: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NorllamaReceipt:
    task_id: str
    task_kind: NorllamaTaskKind | str
    route: NorllamaRoute
    status: str = "planned"
    output: dict[str, Any] = field(default_factory=dict)
    evidence_paths: list[str] = field(default_factory=list)
    confidence: float | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    schema: str = "norman.norllama.task-receipt.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.task_kind, NorllamaTaskKind):
            self.task_kind = NorllamaTaskKind(_clean(self.task_kind).lower())
        self.status = _clean(self.status) or "planned"
        self.output = _clean_dict(self.output)
        self.evidence_paths = [
            _clean(value) for value in _clean_list(self.evidence_paths)
        ]
        self.error = _clean(self.error)
        self.metadata = _clean_dict(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_kind": self.task_kind.value,
            "status": self.status,
            "route": self.route.as_dict(),
            "output": self.output,
            "evidence_paths": self.evidence_paths,
            "confidence": self.confidence,
            "error": self.error,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
        route_receipt = self.metadata.get("route_receipt")
        if isinstance(route_receipt, dict):
            payload["route_receipt"] = dict(route_receipt)
        return payload
