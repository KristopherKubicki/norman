from __future__ import annotations

import asyncio
import copy
import os
import time
from threading import RLock
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_console_runtime_user, get_db
from app.db import session as db_session
from app.models import User
from app.services.console_runtime import (
    ConsoleJobContract,
    ConsoleRuntimeRunOptions,
    DbConsoleRuntimeWorker,
    InvalidTransitionError,
    JobNotFoundError,
)
from app.services.console_runtime.acceptance import latest_acceptance_gate
from app.services.console_runtime.adapters.norllama import NorllamaModelAdapter
from app.services.console_runtime.store import db_console_runtime_store
from app.services.console_runtime.supervisor import (
    LIVE_EXECUTION_CONFIRMATION,
    console_runtime_worker_service,
)
from app.services.console_runtime.policy import (
    resolve_runtime_mode,
    with_local_first_catalog_defaults,
)
from app.services.console_runtime.streaming import event_to_sse
from app.services.norllama import mesh_cache as norllama_mesh_cache
from app.services.norllama import warm_policy as norllama_warm_policy
from app.services.norllama.capability_catalog import catalog_payload
from app.services.norllama.routing import build_task_receipt, route_task
from app.services.norllama.specialist_lanes import (
    specialist_lane_proof_from_warm_policy,
    specialist_registry_payload,
)
from app.services.norllama.types import NorllamaTaskRequest

router = APIRouter(prefix="/console-runtime", tags=["console_runtime"])

_READ_CACHE_LOCK = RLock()
_READ_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_READ_CACHE_REFRESHING: set[tuple[Any, ...]] = set()
_READ_CACHE_STALE_SECONDS = 60.0
_READ_CACHE_DISABLED_ENV = "NORMAN_CONSOLE_RUNTIME_DISABLE_READ_CACHE"

RUNTIME_EVENT_CATEGORIES = [
    "job",
    "turn",
    "behavior",
    "policy",
    "route",
    "planner",
    "model",
    "tool",
    "shell",
    "approval",
    "checkpoint",
    "goal",
    "artifact",
    "verification",
    "runtime",
]


def _read_cache_enabled() -> bool:
    if os.environ.get(_READ_CACHE_DISABLED_ENV):
        return False
    # Keep test clients isolated; each test builds its own DB/application state.
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _read_cache_get(
    key: tuple[Any, ...],
    *,
    ttl_seconds: float,
    stale_seconds: float = _READ_CACHE_STALE_SECONDS,
) -> dict[str, Any] | None:
    if not _read_cache_enabled():
        return None
    now = time.time()
    with _READ_CACHE_LOCK:
        entry = _READ_CACHE.get(key)
        if not entry:
            return None
        age = now - float(entry.get("stored_at") or 0.0)
        if age <= ttl_seconds or age <= stale_seconds:
            payload = copy.deepcopy(entry.get("payload") or {})
            if isinstance(payload, dict) and age > ttl_seconds:
                payload["_cache"] = {
                    "state": "stale",
                    "age_seconds": round(age, 3),
                }
            return payload
    return None


def _read_cache_set(key: tuple[Any, ...], payload: dict[str, Any]) -> None:
    if not _read_cache_enabled():
        return
    with _READ_CACHE_LOCK:
        _READ_CACHE[key] = {
            "stored_at": time.time(),
            "payload": copy.deepcopy(payload),
        }


def _cached_read(
    key: tuple[Any, ...],
    *,
    ttl_seconds: float,
    loader,
    busy_payload,
) -> dict[str, Any]:
    cached = _read_cache_get(key, ttl_seconds=ttl_seconds, stale_seconds=ttl_seconds)
    if cached is not None:
        return cached
    if _read_cache_enabled():
        with _READ_CACHE_LOCK:
            if key in _READ_CACHE_REFRESHING:
                stale = _read_cache_get(
                    key,
                    ttl_seconds=ttl_seconds,
                    stale_seconds=_READ_CACHE_STALE_SECONDS,
                )
                if stale is not None:
                    return stale
                return busy_payload()
            _READ_CACHE_REFRESHING.add(key)
    try:
        payload = loader()
        if isinstance(payload, dict):
            _read_cache_set(key, payload)
        return payload
    finally:
        if _read_cache_enabled():
            with _READ_CACHE_LOCK:
                _READ_CACHE_REFRESHING.discard(key)


def _local_first_busy_payload() -> dict[str, Any]:
    return {
        "schema": "norman.console-runtime.local-first-proof.v1",
        "session_count": 0,
        "sessions": [],
        "totals": {},
        "release_gate": {
            "route_path_proven": False,
            "latest_session_healthy": False,
            "operational_local_first_ready": False,
        },
        "_cache": {"state": "refresh_busy"},
    }


def _route_outcomes_busy_payload() -> dict[str, Any]:
    return {
        "schema": "norman.norllama.route-outcomes-summary.v1",
        "count": 0,
        "ok": 0,
        "fail": 0,
        "models": [],
        "by_tui": {},
        "by_worker": {},
        "_cache": {"state": "refresh_busy"},
    }


def _kernel_capability_payload() -> dict[str, Any]:
    return {
        "version": "norman-kernel-v1",
        "event_categories": RUNTIME_EVENT_CATEGORIES,
        "adapters": ["norllama", "shell", "runtime-dry-run"],
        "supports": {
            "db_event_stream": True,
            "sse": True,
            "policy_mode": True,
            "route_decisions": True,
            "route_summary": True,
            "route_outcomes": True,
            "usage_ledger": True,
            "usage_by_provider": True,
            "usage_by_job": True,
            "usage_by_day": True,
            "local_first_kpi": True,
            "local_first_proof": True,
            "tui_acceptance_gate": True,
            "dynamic_model_pool": True,
            "route_receipt_pool": True,
            "specialist_lane_registry": True,
            "specialist_route_receipts": True,
            "deterministic_expert_cascade": True,
            "shell_events": True,
            "codex_optional": True,
            "cloud_llm_offline": True,
            "local_first_default": True,
            "explicit_cloud_escalation": True,
            "norllama_frontdoor": True,
            "continuous_goal_loop": True,
            "phased_goal_loop": True,
            "bounded_goal_runs": True,
            "local_token_budget": True,
            "tui_kernel_execution_promotion": True,
            "control_only": True,
        },
        "mode": resolve_runtime_mode().as_dict(),
    }


class _BorrowedConsoleRuntimeDbSession:
    def __init__(self, db: Session):
        self.db = db

    def __getattr__(self, name: str) -> Any:
        return getattr(self.db, name)

    def close(self) -> None:
        return None


def _console_runtime_worker_session(parent_db: Session):
    try:
        bind = parent_db.get_bind()
        url = getattr(bind, "url", None)
        if getattr(url, "get_backend_name", lambda: "")() == "sqlite" and getattr(
            url, "database", None
        ) in (None, "", ":memory:"):
            return _BorrowedConsoleRuntimeDbSession(parent_db)
    except Exception:
        pass
    return db_session.SessionLocal()


class ConsoleRuntimeJobCreate(BaseModel):
    objective: str
    job_id: str = ""
    done_when: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    max_runtime_seconds: int = 7200
    checkpoint_interval_seconds: int = 900
    question_budget: int = 1
    approval_required_for: list[str] = Field(default_factory=list)
    authority_flags: dict[str, Any] = Field(default_factory=dict)
    route_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConsoleRuntimeEventCreate(BaseModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    detail: str = ""
    visibility: str = "timeline"
    artifacts: list[str] = Field(default_factory=list)


class ConsoleRuntimeRouteOutcomeCreate(BaseModel):
    outcome: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    tui: str = ""
    agent: str = ""
    session: str = ""
    host: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"

    def as_outcome(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        outcome = dict(data.pop("outcome") or {})
        metadata = dict(data.pop("metadata") or {})
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if key == "agent":
                if value and not outcome.get("tui"):
                    outcome["tui"] = value
                continue
            if value not in ("", None, [], {}):
                outcome.setdefault(key, value)
        if metadata:
            existing = outcome.get("metadata")
            if not isinstance(existing, dict):
                existing = {}
            outcome["metadata"] = {**metadata, **existing}
        return outcome


class ConsoleRuntimePlannerReceiptCreate(BaseModel):
    kind: str = "plan"
    input_text: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    query: str = ""
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    route_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "planned"
    output: dict[str, Any] = Field(default_factory=dict)
    evidence_paths: list[str] = Field(default_factory=list)
    confidence: float | None = None
    error: str = ""
    include_capabilities: bool = True


class ConsoleRuntimeRunCreate(BaseModel):
    worker_id: str = "runtime-api-worker"
    dry_run: bool = True
    complete: bool = True
    continuous: bool = False
    max_steps: int = 1
    max_runtime_seconds: int = 0
    local_token_budget: int = 0
    cloud_token_budget: int = 0
    goal_phase_sequence: list[str] = Field(default_factory=list)
    planner_kind: str = "plan"
    model: str = ""
    max_output_tokens: int = 1024
    route_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    include_capabilities: bool = True
    live_execution_approved: bool = False
    confirm_live_execution: str = ""


class ConsoleRuntimeWorkerControl(BaseModel):
    enabled: bool | None = None
    dry_run: bool | None = None
    live_execution_enabled: bool | None = None
    continuous_enabled: bool | None = None
    max_steps: int | None = None
    max_runtime_seconds: int | None = None
    goal_phase_sequence: list[str] | None = None
    tick_seconds: float | None = None
    batch_size: int | None = None
    worker_id: str = ""
    confirm_live_execution: str = ""
    reset_counters: bool = False


class ConsoleRuntimeApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"] = "approve"
    reason: str = ""
    confirm_live_execution: str = ""


def _require_live_execution_confirmation(value: str) -> None:
    if value != LIVE_EXECUTION_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail=(
                "Live runtime execution requires confirmation phrase "
                f"{LIVE_EXECUTION_CONFIRMATION!r}"
            ),
        )


def _event_payload(events, *, after: int = 0) -> dict[str, Any]:
    items = [event.as_dict() for event in events]
    return {
        "items": items,
        "count": len(items),
        "next_after": events[-1].sequence if events else int(after or 0),
    }


def _norllama_capability_snapshot() -> dict[str, Any]:
    try:
        capabilities = NorllamaModelAdapter().capabilities.as_dict()
        capabilities["capability_catalog"] = catalog_payload()
        capabilities["mesh"] = norllama_mesh_cache.get_mesh_overview(timeout_seconds=2)
        capabilities["warm_policy"] = norllama_warm_policy.build_warm_policy(
            mesh=capabilities["mesh"]
        )
        capabilities["specialist_lanes"] = {
            **specialist_registry_payload(),
            "proof": specialist_lane_proof_from_warm_policy(
                capabilities["warm_policy"]
            ),
        }
        return capabilities
    except Exception as exc:
        return {"provider": "norllama", "error": str(exc)}


def _norllama_runtime_status_snapshot(
    *, route_outcomes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    try:
        mesh = norllama_mesh_cache.get_mesh_overview(timeout_seconds=2)
        try:
            policy = norllama_warm_policy.build_warm_policy(
                mesh=mesh,
                route_outcomes=route_outcomes or [],
            )
        except TypeError:
            policy = norllama_warm_policy.build_warm_policy(mesh=mesh)
        route_guardrails = (
            policy.get("route_guardrails")
            if isinstance(policy.get("route_guardrails"), dict)
            else {}
        )
        guardrail_lanes = (
            route_guardrails.get("lanes")
            if isinstance(route_guardrails.get("lanes"), dict)
            else {}
        )
        return {
            "provider": "norllama",
            "mesh_status": mesh.get("status"),
            "healthy_worker_count": mesh.get("healthy_worker_count", 0),
            "worker_count": mesh.get("worker_count", 0),
            "route_posture": policy.get("route_posture"),
            "residency_posture": policy.get("residency_posture"),
            "residency": policy.get("residency", {}),
            "route_guardrails": route_guardrails,
            "lane_status": {
                lane: {
                    "status": lane_payload.get("status"),
                    "eligible_count": lane_payload.get("eligible_count", 0),
                    "canary_count": lane_payload.get("canary_count", 0),
                    "blocked_count": lane_payload.get("blocked_count", 0),
                }
                for lane, lane_payload in guardrail_lanes.items()
                if isinstance(lane_payload, dict)
            },
            "prefetch_count": (policy.get("counts") or {}).get("prefetch", 0),
            "degraded_count": (policy.get("residency") or {}).get("degraded", 0),
            "unavailable_count": (policy.get("residency") or {}).get("unavailable", 0),
            "workers": [
                {
                    "id": worker.get("id"),
                    "role": worker.get("role"),
                    "reachable": worker.get("reachable"),
                    "pressure": worker.get("pressure", {}),
                    "desired_model_count": len(worker.get("desired_models") or []),
                    "prefetch_model_count": len(worker.get("prefetch_models") or []),
                }
                for worker in policy.get("workers") or []
                if isinstance(worker, dict)
            ],
        }
    except Exception as exc:
        return {"provider": "norllama", "status": "error", "error": str(exc)[:240]}


def _worker_status_payload(db: Session, *, user_id: int) -> dict[str, Any]:
    runnable_count = len(db_console_runtime_store.list_runnable_jobs(db, limit=100))
    route_summary = db_console_runtime_store.route_activity_summary(
        db,
        user_id=user_id,
        limit=1000,
    )
    outcomes = db_console_runtime_store.route_outcomes(
        db,
        user_id=user_id,
        limit=1000,
    )
    return {
        "runnable_count": runnable_count,
        "route_summary": route_summary,
        "usage_ledger": route_summary.get("usage_ledger", {}),
        "local_first_kpi": route_summary.get("local_first_kpi", {}),
        "local_first_proof": db_console_runtime_store.local_first_proof(
            db,
            user_id=user_id,
            limit=1000,
            session_limit=20,
        ),
        "tui_acceptance": latest_acceptance_gate(),
        "route_outcome_summary": db_console_runtime_store.route_outcome_summary(
            db,
            user_id=user_id,
        ),
        "_route_outcomes": outcomes,
    }


@router.get("/jobs")
async def list_console_runtime_jobs(
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    def load_jobs() -> dict[str, Any]:
        jobs = [
            job.as_dict()
            for job in db_console_runtime_store.list_jobs(
                db,
                user_id=current_user.id,
                limit=limit,
            )
        ]
        return {"items": jobs, "count": len(jobs)}

    return _cached_read(
        ("jobs", current_user.id, int(limit)),
        ttl_seconds=1.5,
        busy_payload=lambda: {
            "items": [],
            "count": 0,
            "_cache": {"state": "refresh_busy"},
        },
        loader=load_jobs,
    )


@router.get("/capabilities")
async def get_console_runtime_capabilities(
    current_user: User = Depends(get_console_runtime_user),
):
    _ = current_user
    return _cached_read(
        ("capabilities", current_user.id),
        ttl_seconds=8.0,
        busy_payload=lambda: {
            "kernel": _kernel_capability_payload(),
            "norllama": {
                "provider": "norllama",
                "status": "refresh_busy",
                "source": "server_read_cache",
            },
            "_cache": {"state": "refresh_busy"},
        },
        loader=lambda: {
            "kernel": _kernel_capability_payload(),
            "norllama": _norllama_capability_snapshot(),
        },
    )


@router.get("/route-summary")
async def get_console_runtime_route_summary(
    job_id: str = Query("", max_length=128),
    limit: int = Query(1000, ge=1, le=10000),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        return _cached_read(
            ("route-summary", current_user.id, job_id or "", int(limit)),
            ttl_seconds=2.0,
            busy_payload=lambda: {
                "schema": "norman.console-runtime.route-summary.v1",
                "_cache": {"state": "refresh_busy"},
            },
            loader=lambda: db_console_runtime_store.route_activity_summary(
                db,
                user_id=current_user.id,
                job_id=job_id or None,
                limit=limit,
            ),
        )
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc


@router.get("/local-first-proof")
async def get_console_runtime_local_first_proof(
    limit: int = Query(1000, ge=1, le=10000),
    session_limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    return _cached_read(
        ("local-first-proof", current_user.id, int(limit), int(session_limit)),
        ttl_seconds=5.0,
        busy_payload=_local_first_busy_payload,
        loader=lambda: db_console_runtime_store.local_first_proof(
            db,
            user_id=current_user.id,
            limit=limit,
            session_limit=session_limit,
        ),
    )


@router.get("/tui-acceptance")
async def get_console_runtime_tui_acceptance(
    current_user: User = Depends(get_console_runtime_user),
):
    _ = current_user
    return latest_acceptance_gate()


@router.get("/route-outcomes")
async def get_console_runtime_route_outcomes(
    limit: int = Query(1000, ge=1, le=10000),
    cooldown_seconds: int = Query(900, ge=0, le=86400),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    return _cached_read(
        ("route-outcomes", current_user.id, int(limit), int(cooldown_seconds)),
        ttl_seconds=3.0,
        busy_payload=_route_outcomes_busy_payload,
        loader=lambda: db_console_runtime_store.route_outcome_summary(
            db,
            user_id=current_user.id,
            limit=limit,
            cooldown_seconds=cooldown_seconds,
        ),
    )


@router.post("/route-outcomes")
async def append_console_runtime_route_outcome(
    payload: ConsoleRuntimeRouteOutcomeCreate,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    event = db_console_runtime_store.append_route_outcome(
        db,
        user_id=current_user.id,
        outcome=payload.as_outcome(),
    )
    summary = db_console_runtime_store.route_outcome_summary(
        db,
        user_id=current_user.id,
    )
    return {
        "event": event.as_dict(),
        "summary": summary,
    }


@router.post("/jobs")
async def create_console_runtime_job(
    payload: ConsoleRuntimeJobCreate,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        contract = ConsoleJobContract(
            objective=payload.objective,
            done_when=payload.done_when,
            success_metrics=payload.success_metrics,
            required_artifacts=payload.required_artifacts,
            max_runtime_seconds=payload.max_runtime_seconds,
            checkpoint_interval_seconds=payload.checkpoint_interval_seconds,
            question_budget=payload.question_budget,
            approval_required_for=payload.approval_required_for,
            authority_flags=payload.authority_flags,
            route_policy=with_local_first_catalog_defaults(payload.route_policy),
            metadata=payload.metadata,
        )
        job = db_console_runtime_store.create_job(
            db,
            user_id=current_user.id,
            contract=contract,
            job_id=payload.job_id or None,
            metadata=payload.metadata,
        )
        return job.as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
async def get_console_runtime_job(
    job_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        if int(after or 0) > 0:
            return db_console_runtime_store.activity_snapshot(
                db,
                user_id=current_user.id,
                job_id=job_id,
                after_sequence=after,
                limit=limit,
            )
        return _cached_read(
            ("job", current_user.id, job_id, int(limit)),
            ttl_seconds=1.0,
            busy_payload=lambda: {
                "job": {"job_id": job_id, "status": "unknown"},
                "events": [],
                "route_summary": {},
                "_cache": {"state": "refresh_busy"},
            },
            loader=lambda: db_console_runtime_store.activity_snapshot(
                db,
                user_id=current_user.id,
                job_id=job_id,
                after_sequence=after,
                limit=limit,
            ),
        )
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc


@router.get("/worker/status")
async def get_console_runtime_worker_status(
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    async def load_status() -> dict[str, Any]:
        status_extra = _worker_status_payload(db, user_id=current_user.id)
        route_outcomes = status_extra.pop("_route_outcomes", [])
        payload = await console_runtime_worker_service.status_payload(
            runnable_count=status_extra.get("runnable_count", 0)
        )
        payload.update(status_extra)
        payload["norllama"] = _norllama_runtime_status_snapshot(
            route_outcomes=route_outcomes,
        )
        return payload

    cached = _read_cache_get(("worker-status", current_user.id), ttl_seconds=3.0)
    if cached is not None:
        return cached
    key = ("worker-status", current_user.id)
    if _read_cache_enabled():
        with _READ_CACHE_LOCK:
            if key in _READ_CACHE_REFRESHING:
                stale = _read_cache_get(
                    key,
                    ttl_seconds=3.0,
                    stale_seconds=_READ_CACHE_STALE_SECONDS,
                )
                if stale is not None:
                    return stale
                return {"status": "refresh_busy", "_cache": {"state": "refresh_busy"}}
            _READ_CACHE_REFRESHING.add(key)
    try:
        payload = await load_status()
        _read_cache_set(key, payload)
        return payload
    finally:
        if _read_cache_enabled():
            with _READ_CACHE_LOCK:
                _READ_CACHE_REFRESHING.discard(key)


@router.post("/worker/control")
async def control_console_runtime_worker(
    payload: ConsoleRuntimeWorkerControl,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        await console_runtime_worker_service.configure(
            enabled=payload.enabled,
            dry_run=payload.dry_run,
            live_execution_enabled=payload.live_execution_enabled,
            continuous_enabled=payload.continuous_enabled,
            max_steps=payload.max_steps,
            max_runtime_seconds=payload.max_runtime_seconds,
            goal_phase_sequence=payload.goal_phase_sequence,
            tick_seconds=payload.tick_seconds,
            batch_size=payload.batch_size,
            worker_id=payload.worker_id,
            confirm_live_execution=payload.confirm_live_execution,
            reset_counters=payload.reset_counters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status_extra = _worker_status_payload(db, user_id=current_user.id)
    route_outcomes = status_extra.pop("_route_outcomes", [])
    response = await console_runtime_worker_service.status_payload(
        runnable_count=status_extra.get("runnable_count", 0)
    )
    response.update(status_extra)
    response["norllama"] = _norllama_runtime_status_snapshot(
        route_outcomes=route_outcomes,
    )
    return response


@router.post("/jobs/{job_id}/planner/receipts")
async def create_console_runtime_planner_receipt(
    job_id: str,
    payload: ConsoleRuntimePlannerReceiptCreate,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        job = db_console_runtime_store.get_job(
            db, user_id=current_user.id, job_id=job_id
        )
        route_policy = with_local_first_catalog_defaults(
            payload.route_policy or dict(job.contract.route_policy)
        )
        if "recent_route_outcomes" not in route_policy:
            route_policy["recent_route_outcomes"] = (
                db_console_runtime_store.route_outcomes(
                    db,
                    user_id=current_user.id,
                    limit=200,
                )
            )
        task = NorllamaTaskRequest(
            kind=payload.kind,
            input_text=payload.input_text or job.contract.objective,
            messages=payload.messages,
            query=payload.query,
            candidates=payload.candidates,
            artifacts=payload.artifacts,
            route_policy=route_policy,
            metadata={
                "console_runtime_job_id": job_id,
                **dict(payload.metadata or {}),
            },
        )
        route = route_task(task)
        receipt = build_task_receipt(
            task,
            route,
            status=payload.status,
            output=payload.output,
            evidence_paths=payload.evidence_paths,
            confidence=payload.confidence,
            error=payload.error,
            metadata=payload.metadata,
        )
        capabilities = (
            _norllama_capability_snapshot() if payload.include_capabilities else {}
        )
        event = db_console_runtime_store.record_planner_receipt(
            db,
            user_id=current_user.id,
            job_id=job_id,
            receipt=receipt.as_dict(),
            capabilities=capabilities,
            metadata={"source": "console_runtime_api"},
        )
        return event.as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc


@router.post("/jobs/{job_id}/runs")
async def run_console_runtime_job_once(
    job_id: str,
    payload: ConsoleRuntimeRunCreate,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    if not payload.dry_run and payload.live_execution_approved:
        _require_live_execution_confirmation(payload.confirm_live_execution)
    try:
        options = ConsoleRuntimeRunOptions(
            worker_id=payload.worker_id,
            dry_run=payload.dry_run,
            complete=payload.complete,
            continuous=payload.continuous,
            max_steps=payload.max_steps,
            max_runtime_seconds=payload.max_runtime_seconds,
            local_token_budget=payload.local_token_budget,
            cloud_token_budget=payload.cloud_token_budget,
            goal_phase_sequence=payload.goal_phase_sequence,
            planner_kind=payload.planner_kind,
            model=payload.model,
            max_output_tokens=payload.max_output_tokens,
            route_policy=dict(payload.route_policy),
            metadata=payload.metadata,
            include_capabilities=payload.include_capabilities,
            live_execution_approved=payload.live_execution_approved,
        )
        worker = DbConsoleRuntimeWorker(db_console_runtime_store)
        user_id = current_user.id

        def run_worker() -> dict[str, Any]:
            worker_db = _console_runtime_worker_session(db)
            try:
                if payload.continuous:
                    return worker.run_continuous(
                        worker_db,
                        user_id=user_id,
                        job_id=job_id,
                        options=options,
                    )
                return worker.run_once(
                    worker_db,
                    user_id=user_id,
                    job_id=job_id,
                    options=options,
                )
            finally:
                worker_db.close()

        return await asyncio.to_thread(run_worker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/approval")
async def decide_console_runtime_job_approval(
    job_id: str,
    payload: ConsoleRuntimeApprovalDecision,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    actor = str(getattr(current_user, "email", "") or current_user.id)
    try:
        if payload.decision == "approve":
            _require_live_execution_confirmation(payload.confirm_live_execution)
            job = db_console_runtime_store.approve_job(
                db,
                user_id=current_user.id,
                job_id=job_id,
                reason=payload.reason,
                approved_by=actor,
            )
        else:
            job = db_console_runtime_store.reject_approval(
                db,
                user_id=current_user.id,
                job_id=job_id,
                reason=payload.reason,
                rejected_by=actor,
            )
        return job.as_dict()
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/events")
async def list_console_runtime_job_events(
    job_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        db_console_runtime_store.get_job(db, user_id=current_user.id, job_id=job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc
    return _event_payload(
        db_console_runtime_store.events_after(
            db,
            user_id=current_user.id,
            job_id=job_id,
            after_sequence=after,
            limit=limit,
        ),
        after=after,
    )


@router.post("/jobs/{job_id}/events")
async def append_console_runtime_job_event(
    job_id: str,
    payload: ConsoleRuntimeEventCreate,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        event = db_console_runtime_store.append_event(
            db,
            user_id=current_user.id,
            job_id=job_id,
            event_type=payload.event_type,
            payload=payload.payload,
            summary=payload.summary,
            detail=payload.detail,
            visibility=payload.visibility,
            artifacts=payload.artifacts,
        )
        return event.as_dict()
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc


@router.get("/events")
async def list_console_runtime_events(
    job_id: str = Query("", max_length=128),
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    if job_id:
        try:
            db_console_runtime_store.get_job(db, user_id=current_user.id, job_id=job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Console runtime job not found"
            ) from exc
    return _event_payload(
        db_console_runtime_store.events_after(
            db,
            user_id=current_user.id,
            job_id=job_id or None,
            after_sequence=after,
            limit=limit,
        ),
        after=after,
    )


@router.get("/jobs/{job_id}/events/stream")
async def stream_console_runtime_job_events(
    job_id: str,
    after: int = Query(0, ge=0),
    once: bool = Query(False),
    poll_seconds: float = Query(1.0, ge=0.1, le=30.0),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    try:
        db_console_runtime_store.get_job(db, user_id=current_user.id, job_id=job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Console runtime job not found"
        ) from exc

    async def event_stream():
        cursor = int(after or 0)
        while True:
            events = db_console_runtime_store.events_after(
                db,
                user_id=current_user.id,
                job_id=job_id,
                after_sequence=cursor,
                limit=200,
            )
            for event in events:
                cursor = event.sequence
                yield event_to_sse(event)
            if once:
                return
            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(float(poll_seconds))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
