from __future__ import annotations

import uuid

import pytest

from app import crud
from app.core.config import settings
from app.schemas.user import UserCreate
from app.services.console_runtime import ConsoleJobContract, ConsoleSubtaskContract
from app.services.console_runtime.store import DbConsoleRuntimeStore
from app.services.console_runtime.supervisor import (
    LIVE_EXECUTION_CONFIRMATION,
    ConsoleRuntimeWorkerService,
)


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "runtime-supervisor@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="runtime-supervisor@example.com",
                username="runtime_supervisor",
                password="pass123",
            ),
        )
    return user


def _create_job(db, store: DbConsoleRuntimeStore, user_id: int, *, suffix: str = ""):
    job_id = f"job-supervisor-{suffix or uuid.uuid4().hex}"
    return store.create_job(
        db,
        user_id=user_id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective=f"Run supervisor job {job_id}",
            route_policy={"provider": "norllama"},
        ),
    )


def _create_workstream_subtasks(
    db,
    store: DbConsoleRuntimeStore,
    user_id: int,
    *,
    prefix: str,
    max_concurrency: int = 10,
    route_policies: list[dict] | None = None,
):
    coordinator = store.create_job(
        db,
        user_id=user_id,
        job_id=f"job-supervisor-coordinator-{prefix}",
        contract=ConsoleJobContract(
            objective=f"Coordinate supervisor workstream {prefix}",
        ),
    )
    workstream = store.create_workstream(
        db,
        user_id=user_id,
        coordinator_job_id=coordinator.job_id,
        title=f"Supervisor workstream {prefix}",
        max_concurrency=max_concurrency,
    )
    policies = route_policies or [{}, {}]
    subtasks = [
        ConsoleSubtaskContract(
            job_id=f"job-supervisor-{prefix}-{index}",
            objective=f"Run supervisor subtask {prefix}-{index}",
            route_policy=policy,
        )
        for index, policy in enumerate(policies, start=1)
    ]
    return workstream, store.delegate_subtasks(
        db,
        user_id=user_id,
        workstream_id=workstream.workstream_id,
        subtasks=subtasks,
    )


def _clear_runnable_jobs(db, store: DbConsoleRuntimeStore) -> None:
    for user_id, job in store.list_runnable_jobs(db, limit=100):
        store.fail_job(db, user_id=user_id, job_id=job.job_id, error="test cleanup")


def test_console_runtime_supervisor_global_capacity_blocks_selection(db, monkeypatch):
    monkeypatch.setattr(
        settings, "console_runtime_worker_global_concurrency", 1, raising=False
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _workstream, subtasks = _create_workstream_subtasks(
        db,
        store,
        user.id,
        prefix=f"global-capacity-{uuid.uuid4().hex}",
    )
    service = ConsoleRuntimeWorkerService(store=store)

    selected = service._select_runnable_jobs(
        db,
        candidates=[(user.id, job) for job in subtasks],
        active_counts={"total": 1, "norllama_pool_total": 0, "by_workstream": {}},
        batch_size=10,
    )

    assert selected == []


def test_console_runtime_supervisor_enforces_workstream_capacity(db, monkeypatch):
    monkeypatch.setattr(
        settings, "console_runtime_worker_global_concurrency", 10, raising=False
    )
    monkeypatch.setattr(
        settings, "console_runtime_workstream_max_concurrency", 10, raising=False
    )
    monkeypatch.setattr(
        settings, "console_runtime_norllama_pool_concurrency", 10, raising=False
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _workstream, subtasks = _create_workstream_subtasks(
        db,
        store,
        user.id,
        prefix=f"workstream-capacity-{uuid.uuid4().hex}",
        max_concurrency=1,
    )
    service = ConsoleRuntimeWorkerService(store=store)

    selected = service._select_runnable_jobs(
        db,
        candidates=[(user.id, job) for job in subtasks],
        active_counts={
            "total": 0,
            "norllama_pool_total": 0,
            "by_workstream": {},
        },
        batch_size=10,
    )

    assert [job.job_id for _, job in selected] == [subtasks[0].job_id]


def test_console_runtime_supervisor_limits_norllama_pool_without_blocking_other_providers(
    db, monkeypatch
):
    monkeypatch.setattr(
        settings, "console_runtime_worker_global_concurrency", 10, raising=False
    )
    monkeypatch.setattr(
        settings, "console_runtime_workstream_max_concurrency", 10, raising=False
    )
    monkeypatch.setattr(
        settings, "console_runtime_norllama_pool_concurrency", 1, raising=False
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _workstream, subtasks = _create_workstream_subtasks(
        db,
        store,
        user.id,
        prefix=f"norllama-pool-capacity-{uuid.uuid4().hex}",
        route_policies=[
            {},
            {},
            {"provider": "shell"},
        ],
    )
    service = ConsoleRuntimeWorkerService(store=store)

    selected = service._select_runnable_jobs(
        db,
        candidates=[(user.id, job) for job in subtasks],
        active_counts={
            "total": 0,
            "norllama_pool_total": 0,
            "by_workstream": {},
        },
        batch_size=3,
    )

    assert [job.job_id for _, job in selected] == [
        subtasks[0].job_id,
        subtasks[2].job_id,
    ]


def test_console_runtime_supervisor_round_robins_between_workstreams(db, monkeypatch):
    monkeypatch.setattr(
        settings, "console_runtime_worker_global_concurrency", 10, raising=False
    )
    monkeypatch.setattr(
        settings, "console_runtime_workstream_max_concurrency", 10, raising=False
    )
    monkeypatch.setattr(
        settings, "console_runtime_norllama_pool_concurrency", 10, raising=False
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    suffix = uuid.uuid4().hex
    _workstream_a, subtasks_a = _create_workstream_subtasks(
        db,
        store,
        user.id,
        prefix=f"fair-a-{suffix}",
    )
    _workstream_b, subtasks_b = _create_workstream_subtasks(
        db,
        store,
        user.id,
        prefix=f"fair-b-{suffix}",
    )
    service = ConsoleRuntimeWorkerService(store=store)

    selected = service._select_runnable_jobs(
        db,
        candidates=[
            (user.id, subtasks_a[0]),
            (user.id, subtasks_a[1]),
            (user.id, subtasks_b[0]),
            (user.id, subtasks_b[1]),
        ],
        active_counts={
            "total": 0,
            "norllama_pool_total": 0,
            "by_workstream": {},
        },
        batch_size=4,
    )

    assert [job.job_id for _, job in selected] == [
        subtasks_a[0].job_id,
        subtasks_b[0].job_id,
        subtasks_a[1].job_id,
        subtasks_b[1].job_id,
    ]


@pytest.mark.asyncio
async def test_console_runtime_supervisor_tick_is_disabled_by_default(db, monkeypatch):
    monkeypatch.setattr(
        settings, "console_runtime_worker_enabled", False, raising=False
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _clear_runnable_jobs(db, store)
    job = _create_job(db, store, user.id, suffix="disabled")
    service = ConsoleRuntimeWorkerService(store=store)

    processed = await service._tick()

    assert processed == 0
    loaded = store.get_job(db, user_id=user.id, job_id=job.job_id)
    snapshot = await service.snapshot()
    assert loaded.status == "queued"
    assert snapshot.enabled is False
    assert snapshot.running is False
    store.fail_job(db, user_id=user.id, job_id=job.job_id, error="test cleanup")


@pytest.mark.asyncio
async def test_console_runtime_supervisor_tick_runs_one_dry_run_job(db, monkeypatch):
    monkeypatch.setattr(settings, "console_runtime_worker_enabled", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_dry_run", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_batch_size", 1, raising=False)
    monkeypatch.setattr(
        settings, "console_runtime_worker_id", "supervisor-test", raising=False
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _clear_runnable_jobs(db, store)
    job = _create_job(db, store, user.id, suffix="enabled")
    service = ConsoleRuntimeWorkerService(store=store)

    processed = await service._tick()

    assert processed == 1
    db.expire_all()
    loaded = store.get_job(db, user_id=user.id, job_id=job.job_id)
    snapshot = await service.snapshot()
    assert loaded.status == "done"
    assert snapshot.enabled is True
    assert snapshot.running is True
    assert snapshot.jobs_started == 1
    assert snapshot.jobs_completed == 1
    assert snapshot.last_job_id == job.job_id
    assert snapshot.last_error == ""
    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job.job_id)
    ]
    assert "planner.receipt" in event_types
    assert event_types[-1] == "job.completed"


@pytest.mark.asyncio
async def test_console_runtime_supervisor_respects_batch_size(db, monkeypatch):
    monkeypatch.setattr(settings, "console_runtime_worker_enabled", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_dry_run", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_batch_size", 1, raising=False)
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _clear_runnable_jobs(db, store)
    first = _create_job(db, store, user.id, suffix="batch-a")
    second = _create_job(db, store, user.id, suffix="batch-b")
    service = ConsoleRuntimeWorkerService(store=store)

    processed = await service._tick()

    assert processed == 1
    db.expire_all()
    assert store.get_job(db, user_id=user.id, job_id=first.job_id).status == "done"
    assert store.get_job(db, user_id=user.id, job_id=second.job_id).status == "queued"


@pytest.mark.asyncio
async def test_console_runtime_supervisor_can_run_continuous_goal_loop(db, monkeypatch):
    monkeypatch.setattr(settings, "console_runtime_worker_enabled", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_dry_run", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_batch_size", 1, raising=False)
    monkeypatch.setattr(
        settings, "console_runtime_worker_continuous_enabled", True, raising=False
    )
    monkeypatch.setattr(settings, "console_runtime_worker_max_steps", 2, raising=False)
    monkeypatch.setattr(
        settings,
        "console_runtime_worker_goal_phase_sequence",
        ["plan", "work", "verify"],
        raising=False,
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _clear_runnable_jobs(db, store)
    job = _create_job(db, store, user.id, suffix="continuous")
    service = ConsoleRuntimeWorkerService(store=store)

    processed = await service._tick()

    assert processed == 1
    db.expire_all()
    loaded = store.get_job(db, user_id=user.id, job_id=job.job_id)
    assert loaded.status == "done"
    events = store.events_after(db, user_id=user.id, job_id=job.job_id)
    goal_steps = [
        event for event in events if event.event_type == "goal.step_completed"
    ]
    assert len(goal_steps) == 2
    assert [event.payload["phase"] for event in goal_steps] == ["plan", "work"]
    assert [event.event_type for event in events].count("route.decided") == 2
    assert events[-1].event_type == "goal.stopped"


@pytest.mark.asyncio
async def test_console_runtime_supervisor_promotes_tui_turn_candidate(db, monkeypatch):
    monkeypatch.setattr(settings, "console_runtime_worker_enabled", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_dry_run", True, raising=False)
    monkeypatch.setattr(settings, "console_runtime_worker_batch_size", 1, raising=False)
    monkeypatch.setattr(
        settings, "console_runtime_worker_continuous_enabled", False, raising=False
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    _clear_runnable_jobs(db, store)
    job_id = f"job-supervisor-tui-{uuid.uuid4().hex}"
    job = store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Use a local-first TUI kernel goal loop",
            durable_workstream=True,
            route_policy={
                "provider": "norllama",
                "planner": "norllama",
                "model_proxy": "norllama",
                "durable_workstream": True,
                "continuous_goal_candidate": True,
                "kernel_execution_enabled": True,
                "kernel_execution_candidate": True,
                "max_steps": 3,
                "cloud_token_budget": 0,
                "goal_phase_sequence": ["plan", "work", "verify"],
            },
            metadata={
                "source": "agent_console_web",
                "kind": "tui_turn_shadow",
                "kernel_execution_enabled": True,
                "kernel_execution_candidate": True,
                "durable_workstream": True,
                "continuous_goal_candidate": True,
            },
        ),
        metadata={
            "source": "agent_console_web",
            "kind": "tui_turn_shadow",
            "kernel_execution_enabled": True,
            "kernel_execution_candidate": True,
            "durable_workstream": True,
            "continuous_goal_candidate": True,
        },
    )
    service = ConsoleRuntimeWorkerService(store=store)

    processed = await service._tick()

    assert processed == 1
    db.expire_all()
    loaded = store.get_job(db, user_id=user.id, job_id=job.job_id)
    assert loaded.status == "checkpointed"
    events = store.events_after(db, user_id=user.id, job_id=job.job_id)
    goal_steps = [
        event for event in events if event.event_type == "goal.step_completed"
    ]
    assert [event.payload["phase"] for event in goal_steps] == [
        "plan",
        "work",
        "verify",
    ]
    assert [event.payload["task_kind"] for event in goal_steps] == [
        "plan",
        "chat",
        "verify",
    ]
    assert loaded.checkpoint_capsules[-1]["facts"][-1] == "Verifier state: pending"


@pytest.mark.asyncio
async def test_console_runtime_supervisor_control_requires_live_confirmation(
    monkeypatch,
):
    monkeypatch.setattr(
        settings, "console_runtime_worker_enabled", False, raising=False
    )
    monkeypatch.setattr(settings, "console_runtime_worker_dry_run", True, raising=False)
    monkeypatch.setattr(
        settings, "console_runtime_worker_live_execution_enabled", False, raising=False
    )
    service = ConsoleRuntimeWorkerService()

    with pytest.raises(ValueError, match="Live runtime execution requires"):
        await service.configure(dry_run=False)

    await service.configure(
        dry_run=False,
        live_execution_enabled=True,
        confirm_live_execution=LIVE_EXECUTION_CONFIRMATION,
    )

    assert settings.console_runtime_worker_dry_run is False
    assert settings.console_runtime_worker_live_execution_enabled is True


@pytest.mark.asyncio
async def test_console_runtime_supervisor_status_payload_reports_controls(monkeypatch):
    monkeypatch.setattr(
        settings, "console_runtime_worker_enabled", False, raising=False
    )
    monkeypatch.setattr(settings, "console_runtime_worker_dry_run", True, raising=False)
    monkeypatch.setattr(
        settings, "console_runtime_worker_live_execution_enabled", False, raising=False
    )
    monkeypatch.setattr(settings, "console_runtime_worker_batch_size", 3, raising=False)
    monkeypatch.setattr(
        settings, "console_runtime_worker_id", "status-worker", raising=False
    )
    service = ConsoleRuntimeWorkerService()

    payload = await service.status_payload(runnable_count=2)

    assert payload["runnable_count"] == 2
    assert payload["config"]["enabled"] is False
    assert payload["config"]["dry_run"] is True
    assert payload["config"]["live_execution_enabled"] is False
    assert payload["config"]["continuous_enabled"] is False
    assert payload["config"]["max_steps"] >= 1
    assert payload["config"]["max_runtime_seconds"] >= 30
    assert payload["config"]["goal_phase_sequence"]
    assert payload["config"]["batch_size"] == 3
    assert payload["config"]["worker_id"] == "status-worker"
    assert payload["live_execution_confirmation"] == LIVE_EXECUTION_CONFIRMATION
