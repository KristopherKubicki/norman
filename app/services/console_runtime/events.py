from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def event_category(event_type: str) -> str:
    prefix = str(event_type or "").split(".", 1)[0].strip().lower()
    if prefix in {
        "behavior",
        "checkpoint",
        "goal",
        "job",
        "model",
        "planner",
        "policy",
        "route",
        "shell",
        "tool",
        "turn",
        "verification",
    }:
        return prefix
    if prefix in {"artifact", "approval"}:
        return prefix
    return "runtime"


@dataclass
class ConsoleRuntimeEvent:
    event_type: str
    job_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    category: str = ""
    summary: str = ""
    detail: str = ""
    visibility: str = "timeline"
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.event_type = str(self.event_type or "").strip().lower()
        self.job_id = str(self.job_id or "").strip()
        self.payload = dict(self.payload or {})
        self.sequence = max(0, int(self.sequence or 0))
        self.category = str(self.category or "").strip().lower() or event_category(
            self.event_type
        )
        self.summary = str(self.summary or "").strip()
        self.detail = str(self.detail or "").strip()
        self.visibility = str(self.visibility or "timeline").strip() or "timeline"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
