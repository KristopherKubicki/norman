"""Strict, sanitized contracts for the Kaizen control-plane phases."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, confloat, constr, validator


TUI_KPI_SCHEMA = "norman.kaizen-tui-snapshot.v1"
KAIZEN_KPI_SCHEMA = "norman.kaizen-kpi-observation.v1"
KAIZEN_REPORT_SCHEMA = "norman.kaizen-report.v1"
KAIZEN_BROKER_SCHEMA = "norman.kaizen-broker-decision.v1"
KAIZEN_CANDIDATE_SCHEMA = "norman.kaizen-candidate.v1"
KAIZEN_EVIDENCE_SCHEMA = "norman.kaizen-candidate-evidence.v1"
TUI_SNAPSHOT_KPI_ID = "tui_snapshot_state"

RealmValue = constr(regex=r"^[a-z0-9][a-z0-9/_-]{1,95}$")
TuiIdentifier = constr(regex=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CandidateTargetRef = constr(regex=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
ObservationReference = constr(regex=r"^observation:[1-9][0-9]*$")
CandidateText = constr(strip_whitespace=True, min_length=1, max_length=1200)
CandidateShortText = constr(strip_whitespace=True, min_length=1, max_length=600)


class TuiState(str, Enum):
    """Allowed aggregate TUI operating states."""

    BLOCKED = "blocked"
    DEGRADED = "degraded"
    IDLE = "idle"
    WAITING = "waiting"
    WEDGED = "wedged"
    WORKING = "working"


class TuiActivityState(str, Enum):
    """Allowed aggregate TUI activity states."""

    IDLE = "idle"
    STALLED = "stalled"
    WAITING = "waiting"
    WORKING = "working"
    UNKNOWN = "unknown"


class TuiHealthState(str, Enum):
    """Allowed aggregate TUI health states."""

    BLOCKED = "blocked"
    DEGRADED = "degraded"
    OK = "ok"
    UNKNOWN = "unknown"
    WEDGED = "wedged"


class KaizenCandidateLane(str, Enum):
    """The only candidate lanes allowed in shadow mode."""

    RUNBOOK = "runbook"
    SKILL = "skill"
    MCP_DOCS = "mcp_docs"
    REPORTING = "reporting"
    CONTROL_PLANE = "control_plane"


class KaizenCandidateTargetType(str, Enum):
    """The only non-code targets a shadow candidate may describe."""

    RUNBOOK = "runbook"
    SKILL = "skill"
    MCP = "mcp"
    KAIZEN_POLICY = "kaizen_policy"


class KaizenCandidateSeverity(str, Enum):
    """Stable operator-facing severity values for a candidate."""

    INFO = "info"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


class KaizenCandidateRiskTier(str, Enum):
    """Shadow mode may only retain read-only or proposal-only candidates."""

    READ_ONLY = "read_only"
    PROPOSAL_ONLY = "proposal_only"
    APPROVAL_REQUIRED = "approval_required"


class KaizenCandidateAction(str, Enum):
    """Actions a candidate can request for a later, human-controlled phase."""

    REPORT = "report"
    PREPARE_DIFF = "prepare_diff"
    ADJUST_CONTROL_PLANE = "adjust_control_plane"


class KaizenCandidateStatus(str, Enum):
    """The lifecycle state introduced by the candidate shadow phase."""

    SHADOW = "shadow"


class TuiKpiMetrics(BaseModel):
    """Bounded numeric fields accepted from a TUI KPI producer."""

    turns: confloat(ge=0, le=10_000_000)
    successful_turns: confloat(ge=0, le=10_000_000)
    failed_turns: confloat(ge=0, le=10_000_000)
    avg_turn_seconds: confloat(ge=0, le=604_800)
    last_turn_at: confloat(ge=0, le=4_102_444_800)
    pending_seconds: confloat(ge=0, le=604_800)
    queue_depth: confloat(ge=0, le=100_000)
    wedge_count: confloat(ge=0, le=10_000_000)
    blocked_count: confloat(ge=0, le=10_000_000)
    degraded_count: confloat(ge=0, le=10_000_000)
    state_changes: confloat(ge=0, le=10_000_000)

    class Config:
        extra = "forbid"


class TuiKpiSnapshot(BaseModel):
    """The only TUI payload accepted by the Kaizen ingestion route."""

    schema_: str = Field(TUI_KPI_SCHEMA, alias="schema", const=True)
    realm: RealmValue
    source_tui: TuiIdentifier
    observed_at: datetime
    state: TuiState
    activity_state: TuiActivityState
    health_state: TuiHealthState
    prompt_visible: bool
    waiting_visible: bool
    state_entered_at: datetime
    metrics: TuiKpiMetrics

    @validator("observed_at", "state_entered_at", pre=True)
    def normalize_timestamp(cls, value: Any) -> datetime:
        """Require an explicit timestamp and normalize it to UTC."""
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            value = value.replace("Z", "+00:00")
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            raise ValueError("timestamp must be RFC 3339 or Unix seconds")
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    class Config:
        allow_population_by_field_name = True
        anystr_strip_whitespace = True
        extra = "forbid"

    def sanitized_payload(self) -> dict[str, Any]:
        """Return the fixed aggregate shape that may be persisted."""
        return {
            "schema": self.schema_,
            "realm": self.realm,
            "source_tui": self.source_tui,
            "observed_at": utc_iso(self.observed_at),
            "state": self.state.value,
            "activity_state": self.activity_state.value,
            "health_state": self.health_state.value,
            "prompt_visible": self.prompt_visible,
            "waiting_visible": self.waiting_visible,
            "state_entered_at": utc_iso(self.state_entered_at),
            "metrics": self.metrics.dict(),
        }


class KaizenCandidateProposalPayload(BaseModel):
    """The bounded proposal portion of a model-produced shadow candidate."""

    summary: CandidateShortText
    allowed_action: KaizenCandidateAction
    verification_plan: list[CandidateShortText] = Field(min_items=1, max_items=5)
    expiry_at: datetime

    @validator("expiry_at", pre=True)
    def normalize_expiry(cls, value: Any) -> datetime:
        return normalize_utc_timestamp(value)

    @validator("verification_plan")
    def require_distinct_verification_steps(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if len({item.lower() for item in normalized}) != len(normalized):
            raise ValueError("verification_plan must not repeat a step")
        return normalized

    class Config:
        anystr_strip_whitespace = True
        extra = "forbid"


class KaizenShadowCandidatePayload(BaseModel):
    """The exact JSON object accepted from the local Norllama shadow lane."""

    schema_: str = Field(KAIZEN_CANDIDATE_SCHEMA, alias="schema", const=True)
    lane: KaizenCandidateLane
    target_type: KaizenCandidateTargetType
    target_ref: CandidateTargetRef
    severity: KaizenCandidateSeverity
    risk_tier: KaizenCandidateRiskTier
    impact_score: confloat(ge=0, le=1)
    confidence_score: confloat(ge=0, le=1)
    evidence_refs: list[ObservationReference] = Field(min_items=1, max_items=8)
    evidence_summary: CandidateText
    proposal: KaizenCandidateProposalPayload

    @validator("evidence_refs")
    def require_distinct_evidence_refs(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("evidence_refs must not repeat a reference")
        return value

    class Config:
        allow_population_by_field_name = True
        anystr_strip_whitespace = True
        extra = "forbid"


@dataclass(frozen=True)
class KaizenConfig:
    """The fail-closed settings used by Kaizen services."""

    enabled: bool = False
    observe_only: bool = True
    auto_actions_enabled: bool = False
    candidate_shadow_enabled: bool = False
    pilot_tui_ids: tuple[str, ...] = ()
    allowed_realms: tuple[str, ...] = ("personal/home",)
    idle_grace_seconds: int = 900
    snapshot_max_age_seconds: int = 300
    candidate_evidence_max_age_seconds: int = 300
    daily_norllama_token_budget: int = 0
    candidate_shadow_max_tokens: int = 0
    candidate_shadow_max_concurrency: int = 0
    report_timezone: str = "America/Chicago"

    @classmethod
    def from_settings(cls, settings: Any) -> "KaizenConfig":
        """Build a small immutable config snapshot from application settings."""
        return cls(
            enabled=bool(getattr(settings, "kaizen_enabled", False)),
            observe_only=bool(getattr(settings, "kaizen_observe_only", True)),
            auto_actions_enabled=bool(
                getattr(settings, "kaizen_auto_actions_enabled", False)
            ),
            candidate_shadow_enabled=bool(
                getattr(settings, "kaizen_candidate_shadow_enabled", False)
            ),
            pilot_tui_ids=tuple(getattr(settings, "kaizen_pilot_tui_ids", []) or []),
            allowed_realms=tuple(getattr(settings, "kaizen_allowed_realms", []) or []),
            idle_grace_seconds=max(
                0, int(getattr(settings, "kaizen_idle_grace_seconds", 900) or 0)
            ),
            snapshot_max_age_seconds=max(
                1,
                int(getattr(settings, "kaizen_snapshot_max_age_seconds", 300) or 1),
            ),
            candidate_evidence_max_age_seconds=max(
                1,
                min(
                    int(
                        getattr(
                            settings, "kaizen_candidate_evidence_max_age_seconds", 300
                        )
                        or 1
                    ),
                    86_400,
                ),
            ),
            daily_norllama_token_budget=max(
                0,
                int(getattr(settings, "kaizen_daily_norllama_token_budget", 0) or 0),
            ),
            candidate_shadow_max_tokens=max(
                0,
                min(
                    int(
                        getattr(settings, "kaizen_candidate_shadow_max_tokens", 0) or 0
                    ),
                    1024,
                ),
            ),
            candidate_shadow_max_concurrency=max(
                0,
                min(
                    int(
                        getattr(settings, "kaizen_candidate_shadow_max_concurrency", 0)
                        or 0
                    ),
                    1,
                ),
            ),
            report_timezone=str(
                getattr(settings, "kaizen_report_timezone", "America/Chicago")
                or "America/Chicago"
            ),
        )

    def scope_failure(self, *, realm: str, source_tui: str) -> Optional[str]:
        """Return the first fail-closed scope reason, if one applies."""
        if not self.enabled:
            return "kaizen_disabled"
        if not self.observe_only:
            return "observe_only_required"
        if realm not in self.allowed_realms:
            return "realm_rejected"
        if source_tui not in self.pilot_tui_ids:
            return "pilot_rejected"
        return None

    def candidate_shadow_failure(self) -> Optional[str]:
        """Return the first additional gate that blocks a shadow model call."""
        if not self.candidate_shadow_enabled:
            return "candidate_shadow_disabled"
        if self.daily_norllama_token_budget <= 0:
            return "candidate_shadow_budget_disabled"
        if self.candidate_shadow_max_tokens <= 0:
            return "candidate_shadow_token_limit_disabled"
        if self.candidate_shadow_max_concurrency <= 0:
            return "candidate_shadow_concurrency_disabled"
        return None


@dataclass(frozen=True)
class KpiObservation:
    """A deterministic KPI value and its sanitized supporting details."""

    kpi_id: str
    realm: str
    source_tui: str
    definition_version: str
    source_type: str
    value_numeric: Optional[float]
    unit: str
    state: str
    confidence: float
    window_start: datetime
    window_end: datetime
    observed_at: datetime
    details: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialize an observation for API and report consumers."""
        return {
            "schema": KAIZEN_KPI_SCHEMA,
            "kpi_id": self.kpi_id,
            "realm": self.realm,
            "source_tui": self.source_tui,
            "definition_version": self.definition_version,
            "source_type": self.source_type,
            "value_numeric": self.value_numeric,
            "unit": self.unit,
            "state": self.state,
            "confidence": round(float(self.confidence), 4),
            "window_start": utc_iso(self.window_start),
            "window_end": utc_iso(self.window_end),
            "observed_at": utc_iso(self.observed_at),
            "details": dict(self.details),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class BrokerDecision:
    """The deterministic, no-effect result of one broker evaluation."""

    realm: str
    source_tui: str
    result: str
    reason: str
    decided_at: datetime
    snapshot_observed_at: Optional[datetime] = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize a broker decision without exposing source contents."""
        return {
            "schema": KAIZEN_BROKER_SCHEMA,
            "realm": self.realm,
            "source_tui": self.source_tui,
            "result": self.result,
            "reason": self.reason,
            "decided_at": utc_iso(self.decided_at),
            "snapshot_observed_at": (
                utc_iso(self.snapshot_observed_at)
                if self.snapshot_observed_at is not None
                else None
            ),
            "effect": "none",
        }


def utc_now() -> datetime:
    """Return the current UTC time with timezone information."""
    return datetime.now(timezone.utc)


def normalize_utc_timestamp(value: Any) -> datetime:
    """Require a timezone-aware RFC 3339 or Unix timestamp in UTC."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        value = value.replace("Z", "+00:00")
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be RFC 3339 or Unix seconds")
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    """Render a timezone-aware value in a stable UTC representation."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def as_utc(value: datetime) -> datetime:
    """Normalize values read from database drivers that drop timezone info."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
