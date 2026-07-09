from __future__ import annotations

import uuid

import pytest

from app import crud
from app.schemas.user import UserCreate
from app.services.console_runtime import ConsoleJobContract
from app.services.console_runtime.adapters.fake import FakeModelAdapter
from app.services.console_runtime.store import DbConsoleRuntimeStore
from app.services.console_runtime.types import ModelResult, ModelUsage
from app.services.console_runtime.worker import (
    ConsoleRuntimeRunOptions,
    DbConsoleRuntimeWorker,
)


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "runtime-worker@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="runtime-worker@example.com",
                username="runtime_worker",
                password="pass123",
            ),
        )
    return user


def _proof_model_result(job_id, text="verified complete"):
    route_receipt = {
        "schema": "norman.norllama.route-receipt.v1",
        "status": "completed",
        "request_id": f"req-{job_id}",
        "job_id": job_id,
        "phase": "verify",
        "task_kind": "verify",
        "selected_provider": "norllama",
        "selected_model": "qwen3:8b",
        "target_model": "qwen3:8b",
        "effective_runtime_model": "qwen3:8b",
        "selected_worker": "spark-151",
        "target_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "route_attribution_source": "gateway_response",
        "routing_scope": "frontdoor_worker",
        "frontdoor": "https://llm.home.arpa/v1",
        "peer_path": ["https://llm.home.arpa/v1", "spark-151"],
        "route_reason": "local first",
        "policy_mode": "local_first",
        "cloud_proxy": False,
        "benchmark_packet_id": "uplink-1",
        "benchmark_source": "uplink_benchmark",
        "benchmark_fresh": True,
        "benchmark_score": 0.91,
        "coverage_ratio": 1.0,
        "input_tokens": 4,
        "output_tokens": 6,
        "total_tokens": 10,
        "usage_bucket": "offline_local",
        "fallback_used": False,
        "fallback_reason": None,
        "verifier_result": "pass",
        "output_shape": "complete",
    }
    return ModelResult(
        provider="norllama",
        model="qwen3:8b",
        text=text,
        usage=ModelUsage(input_tokens=4, output_tokens=6),
        metadata={
            "norllama_route": {
                "provider": "norllama",
                "local": True,
                "cloud_proxy": False,
            },
            "norllama_receipt": {
                "status": "completed",
                "route_receipt": route_receipt,
            },
        },
    )


def test_db_console_runtime_worker_completes_one_dry_run_step(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Make the runtime own this small unit of work",
            route_policy={"provider": "norllama"},
        ),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=True,
            include_capabilities=False,
        ),
    )

    assert result["job"]["status"] == "done"
    assert result["model_result"]["provider"] == "runtime-dry-run"
    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job_id)
    ]
    assert event_types == [
        "job.created",
        "job.leased",
        "job.started",
        "behavior.observed",
        "policy.mode_selected",
        "route.decided",
        "planner.receipt",
        "tool.started",
        "model.requested",
        "model.completed",
        "model.delta",
        "tool.completed",
        "job.completed",
    ]
    assert result["snapshot"]["category_counts"] == {
        "job": 4,
        "behavior": 1,
        "policy": 1,
        "route": 1,
        "planner": 1,
        "tool": 2,
        "model": 3,
    }


def test_db_console_runtime_worker_defaults_to_local_first_norllama(db, monkeypatch):
    from app.services.norllama import routing

    monkeypatch.setattr(
        routing.settings, "llm_offline_provider", "openai_compatible", raising=False
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_offline_base_url",
        "https://llm.home.arpa/v1",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_offline_model",
        "gemma4:26b-a4b-it-q4_K_M",
        raising=False,
    )
    monkeypatch.setattr(
        routing.settings,
        "llm_benchmark_packet_path",
        "/tmp/norman-test-missing-benchmark-packet.json",
        raising=False,
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-local-first-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Plan with the spark front door"),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=True,
            include_capabilities=False,
        ),
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    policy_event = next(
        event for event in events if event.event_type == "policy.mode_selected"
    )
    route_event = next(event for event in events if event.event_type == "route.decided")
    planner_event = next(
        event for event in events if event.event_type == "planner.receipt"
    )

    assert result["job"]["status"] == "done"
    assert policy_event.payload["active_mode"] == "local_first_online"
    assert route_event.payload["selected_provider"] == "norllama"
    assert route_event.payload["local"] is True
    assert route_event.payload["cloud_proxy"] is False
    assert route_event.payload["cost_basis"] == "local_token_estimate"
    assert route_event.payload["capability_snapshot"] == {}
    assert planner_event.payload["route"]["provider"] == "norllama"
    assert planner_event.payload["route"]["endpoint"] == "https://llm.home.arpa/v1"
    assert planner_event.payload["route"]["model"] == ""
    assert planner_event.payload["route_receipt"]["selected_model"] == ""
    assert planner_event.payload["route_receipt"]["fallback_reason"]
    assert "no eligible" in planner_event.payload["route_receipt"]["fallback_reason"]
    assert planner_event.payload["output_shape"] == "empty"


def test_db_console_runtime_worker_checkpoints_when_route_proof_fails(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-route-proof-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Execute a route-proofed local step",
            route_policy={"provider": "norllama", "route_proof_required": True},
        ),
    )
    route_receipt = {
        "schema": "norman.norllama.route-receipt.v1",
        "status": "completed",
        "request_id": "req-route-proof",
        "job_id": job_id,
        "phase": "plan",
        "task_kind": "plan",
        "selected_provider": "norllama",
        "selected_model": "qwen3:8b",
        "target_model": "qwen3:8b",
        "effective_runtime_model": "qwen3:8b",
        "selected_worker": "spark-151",
        "target_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "frontdoor": "https://llm.home.arpa/v1",
        "peer_path": ["https://llm.home.arpa/v1", "spark-151"],
        "route_reason": "local first",
        "policy_mode": "local_first",
        "cloud_proxy": False,
        "benchmark_packet_id": "uplink-1",
        "benchmark_source": "uplink_benchmark",
        "benchmark_fresh": True,
        "benchmark_score": 0.91,
        "coverage_ratio": 1.0,
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
        "usage_bucket": "offline_local",
        "fallback_used": False,
        "fallback_reason": None,
        "verifier_result": "skipped",
        "output_shape": "progress_only",
    }
    adapter = FakeModelAdapter(
        responses=[
            ModelResult(
                provider="norllama",
                model="qwen3:8b",
                text="I started a plan.",
                usage=ModelUsage(input_tokens=1, output_tokens=2),
                metadata={
                    "norllama_route": {
                        "provider": "norllama",
                        "local": True,
                        "cloud_proxy": False,
                    },
                    "norllama_receipt": {
                        "status": "completed",
                        "route_receipt": route_receipt,
                    },
                },
            )
        ],
        name="norllama",
        model="qwen3:8b",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-route-proof-test",
            dry_run=True,
            include_capabilities=False,
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    audit_event = next(
        event for event in events if event.event_type == "route.receipt_audited"
    )

    assert result["job"]["status"] == "checkpointed"
    assert result["route_proof"]["gate_passed"] is False
    assert audit_event.payload["receipt_audit"]["pass"] is False
    assert (
        "bad_output_shape:progress_only"
        in (audit_event.payload["receipt_audit"]["failures"])
    )


def test_db_console_runtime_worker_runs_bounded_goal_loop(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-goal-loop-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Keep working until the goal loop ends"),
    )

    adapter = FakeModelAdapter(
        responses=["plan", "work", "verify"],
        name="runtime-dry-run",
        model="runtime-dry-run",
    )
    result = worker.run_continuous(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-goal-test",
            dry_run=True,
            continuous=True,
            max_steps=3,
            include_capabilities=False,
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    event_types = [event.event_type for event in events]
    route_events = [event for event in events if event.event_type == "route.decided"]
    planner_events = [
        event for event in events if event.event_type == "planner.receipt"
    ]
    goal_steps = [
        event for event in events if event.event_type == "goal.step_completed"
    ]

    assert result["continuous"] is True
    assert result["steps_completed"] == 3
    assert result["stop_reason"] == "done"
    assert result["job"]["status"] == "done"
    assert event_types[1] == "goal.started"
    assert event_types[-1] == "goal.stopped"
    assert len(goal_steps) == 3
    assert len(route_events) == 3
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
    assert [event.payload["task_kind"] for event in planner_events] == [
        "plan",
        "chat",
        "verify",
    ]
    assert all(event.payload["local"] is True for event in route_events)
    assert [call.metadata["goal_phase"] for call in adapter.invocations] == [
        "plan",
        "work",
        "verify",
    ]
    assert "runtime planner" in adapter.invocations[0].messages[0]["content"]
    assert "runtime worker" in adapter.invocations[1].messages[0]["content"]
    assert "verifier" in adapter.invocations[2].messages[0]["content"]
    assert result["snapshot"]["category_counts"]["goal"] == 5
    assert result["snapshot"]["route_summary"]["cloud_evidence_count"] == 0


def test_db_console_runtime_worker_runs_literal_response_phase_as_chat(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-literal-response-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Canary only. Reply exactly: DONE local visible.",
            route_policy={
                "provider": "norllama",
                "task_kind": "literal_response",
                "output_shape_expected": "literal_response",
            },
        ),
    )

    adapter = FakeModelAdapter(
        responses=["DONE local visible"],
        name="runtime-dry-run",
        model="gemma3:1b",
    )
    result = worker.run_continuous(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-literal-test",
            dry_run=True,
            continuous=True,
            max_steps=1,
            goal_phase_sequence=["literal_response"],
            planner_kind="literal_response",
            model="gemma3:1b",
            include_capabilities=False,
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    goal_steps = [
        event for event in events if event.event_type == "goal.step_completed"
    ]
    planner_events = [
        event for event in events if event.event_type == "planner.receipt"
    ]

    assert result["job"]["status"] == "done"
    assert result["steps_completed"] == 1
    assert result["stop_reason"] == "done"
    assert result["last_result"]["model_result"]["text"] == "DONE local visible"
    assert [event.payload["phase"] for event in goal_steps] == ["literal_response"]
    assert [event.payload["task_kind"] for event in goal_steps] == ["chat"]
    assert [event.payload["task_kind"] for event in planner_events] == ["chat"]
    assert len(adapter.invocations) == 1
    invocation = adapter.invocations[0]
    assert invocation.metadata["goal_phase"] == "literal_response"
    assert invocation.metadata["goal_task_kind"] == "chat"
    assert "literal-response worker" in invocation.messages[0]["content"]
    assert "Done when:" not in invocation.messages[1]["content"]
    assert "Success metrics:" not in invocation.messages[1]["content"]
    assert (
        "Canary only. Reply exactly: DONE local visible."
        in invocation.messages[1]["content"]
    )


def test_db_console_runtime_worker_verifier_can_stop_goal_loop_early(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-verifier-stop-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Keep working until the verifier says complete",
            route_policy={"provider": "norllama", "verifier_can_stop": True},
        ),
    )
    adapter = FakeModelAdapter(
        responses=["plan", "work", "STATUS: COMPLETE\nNo remaining work."],
        name="runtime-dry-run",
        model="runtime-dry-run",
    )

    result = worker.run_continuous(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-verify-stop-test",
            dry_run=True,
            continuous=True,
            max_steps=5,
            include_capabilities=False,
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    verification_events = [
        event for event in events if event.event_type == "verification.completed"
    ]
    goal_steps = [
        event for event in events if event.event_type == "goal.step_completed"
    ]

    assert result["job"]["status"] == "done"
    assert result["stop_reason"] == "done"
    assert result["steps_completed"] == 3
    assert [event.payload["phase"] for event in goal_steps] == [
        "plan",
        "work",
        "verify",
    ]
    assert len(adapter.invocations) == 3
    assert verification_events
    assert verification_events[0].payload["signal"] == "complete"


def test_db_console_runtime_worker_verifier_can_continue_goal_loop(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-verifier-continue-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Keep working through verifier feedback",
            route_policy={"provider": "norllama", "verifier_can_stop": True},
        ),
    )
    adapter = FakeModelAdapter(
        responses=[
            "plan",
            "work",
            "STATUS: NEEDS_MORE_WORK\nAnother local step is needed.",
            "more work",
            "STATUS: COMPLETE\nNo remaining work.",
        ],
        name="runtime-dry-run",
        model="runtime-dry-run",
    )

    result = worker.run_continuous(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-verify-continue-test",
            dry_run=True,
            continuous=True,
            max_steps=5,
            include_capabilities=False,
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    goal_steps = [
        event for event in events if event.event_type == "goal.step_completed"
    ]
    needs_work_events = [
        event for event in events if event.event_type == "verification.needs_more_work"
    ]
    completed_events = [
        event for event in events if event.event_type == "verification.completed"
    ]

    assert result["job"]["status"] == "done"
    assert result["stop_reason"] == "done"
    assert result["steps_completed"] == 5
    assert [event.payload["phase"] for event in goal_steps] == [
        "plan",
        "work",
        "verify",
        "work",
        "verify",
    ]
    assert len(adapter.invocations) == 5
    assert needs_work_events[0].payload["signal"] == "needs_more_work"
    assert completed_events[-1].payload["signal"] == "complete"


def test_db_console_runtime_worker_checkpoints_when_artifacts_are_missing(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-checkpoint-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Produce a required runtime artifact",
            required_artifacts=["final-report.md"],
        ),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(worker_id="worker-test", dry_run=True),
    )

    assert result["job"]["status"] == "checkpointed"
    assert result["snapshot"]["latest_event"]["event_type"] == "job.checkpointed"
    assert result["snapshot"]["job"]["checkpoints"] == [
        "Runtime worker checkpointed after one model step."
    ]


def test_db_console_runtime_worker_marks_job_failed_when_adapter_fails(db):
    class BrokenAdapter:
        name = "broken"

        @property
        def capabilities(self):
            return FakeModelAdapter().capabilities

        def invoke(self, request):
            raise RuntimeError("adapter exploded")

    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-failed-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Exercise failure path"),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=False,
            live_execution_approved=True,
        ),
        adapter=BrokenAdapter(),
    )

    job = store.get_job(db, user_id=user.id, job_id=job_id)
    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job_id)
    ]
    assert result["job"]["status"] == "failed"
    assert result["model_failed"] is True
    assert result["failure_class"] == "model_adapter_failed"
    assert result["error"] == "adapter exploded"
    assert job.status == "failed"
    assert job.last_error == "adapter exploded"
    assert event_types[-3:] == ["model.failed", "tool.failed", "job.failed"]


def test_db_console_runtime_worker_requires_approval_before_live_execution(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-approval-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Try live execution without approval"),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(worker_id="worker-test", dry_run=False),
        adapter=FakeModelAdapter(responses=["should not be invoked"], name="fake-live"),
    )

    assert result["approval_required"] is True
    assert result["model_result"] is None
    assert result["job"]["status"] == "waiting_approval"
    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job_id)
    ]
    assert event_types[-1] == "job.approval_required"
    assert "model.requested" not in event_types


def test_db_console_runtime_worker_allows_explicitly_approved_live_execution(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-approved-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Run approved live execution"),
    )
    adapter = FakeModelAdapter(
        responses=[_proof_model_result(job_id, "approved live output")],
        name="fake-live",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=False,
            live_execution_approved=True,
        ),
        adapter=adapter,
    )

    assert result["job"]["status"] == "done"
    assert result["model_result"]["provider"] == "norllama"
    assert adapter.invocations


def test_db_console_runtime_worker_blocks_cloud_route_when_cloud_llms_disabled(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-cloud-block-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Plan with a cloud route",
            route_policy={
                "provider": "bedrock",
                "cloud_llm_disabled": True,
                "allow_cloud_proxy": True,
            },
        ),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=True,
            include_capabilities=False,
        ),
    )

    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job_id)
    ]
    assert result["route_blocked"] is True
    assert result["job"]["status"] == "blocked"
    assert "cloud LLM provider blocked by policy" in result["blocked_reason"]
    assert "policy.mode_selected" in event_types
    assert "route.decided" in event_types
    assert "policy.egress_blocked" in event_types
    assert "model.requested" not in event_types


def test_db_console_runtime_worker_runs_read_only_shell_step(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-shell-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Run a read-only shell command",
            route_policy={"runtime": "shell", "command": "pwd"},
        ),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=False,
            live_execution_approved=True,
        ),
    )

    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job_id)
    ]
    assert result["job"]["status"] == "done"
    assert result["shell_result"]["returncode"] == 0
    assert "route.decided" in event_types
    assert "shell.started" in event_types
    assert "shell.completed" in event_types
    assert "model.requested" not in event_types


def test_db_console_runtime_worker_blocks_shell_step_in_control_only_mode(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-shell-control-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Do not run shell in control-only mode",
            route_policy={
                "runtime": "shell",
                "command": "pwd",
                "mode": "control_only",
            },
        ),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=False,
            live_execution_approved=True,
        ),
    )

    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job_id)
    ]
    assert result["route_blocked"] is True
    assert result["job"]["status"] == "blocked"
    assert "shell execution blocked by policy" in result["blocked_reason"]
    assert "route.decided" in event_types
    assert "policy.egress_blocked" in event_types
    assert "shell.started" not in event_types


def test_db_console_runtime_worker_holds_mutating_shell_step_for_approval(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-shell-hold-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Try a mutating shell command",
            route_policy={"runtime": "shell", "command": "python3 --version"},
        ),
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-test",
            dry_run=False,
            live_execution_approved=True,
        ),
    )

    event_types = [
        event.event_type
        for event in store.events_after(db, user_id=user.id, job_id=job_id)
    ]
    assert result["approval_required"] is True
    assert result["job"]["status"] == "waiting_approval"
    assert "mutating command" in result["approval_reason"]
    assert "shell.started" not in event_types


def test_db_console_runtime_worker_runs_workspace_preflight_shell_phase(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-preflight-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Inspect workspace before answering",
            route_policy={
                "provider": "norllama",
                "kernel_workspace_preflight": True,
                "kernel_preflight_commands": ["pwd", "git status --short"],
            },
        ),
    )
    adapter = FakeModelAdapter(
        responses=[_proof_model_result(job_id, "verified")],
        name="runtime-dry-run",
        model="runtime-dry-run",
    )

    result = worker.run_continuous(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-preflight-test",
            dry_run=False,
            continuous=True,
            live_execution_approved=True,
            max_steps=2,
            goal_phase_sequence=["preflight", "verify"],
            include_capabilities=False,
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    shell_started = [event for event in events if event.event_type == "shell.started"]
    shell_completed = [
        event for event in events if event.event_type == "shell.completed"
    ]
    goal_steps = [
        event for event in events if event.event_type == "goal.step_completed"
    ]

    assert result["job"]["status"] == "done"
    assert result["steps_completed"] == 2
    assert result["stop_reason"] == "done"
    assert [event.payload["phase"] for event in goal_steps] == [
        "preflight",
        "verify",
    ]
    assert [event.payload["task_kind"] for event in goal_steps] == ["shell", "verify"]
    assert [event.payload["command"] for event in shell_started] == [
        "pwd",
        "git status --short",
    ]
    assert [event.payload["returncode"] for event in shell_completed] == [0, 0]
    assert len(adapter.invocations) == 1
    assert adapter.invocations[0].metadata["goal_phase"] == "verify"
    assert result["snapshot"]["route_summary"]["execution_events"]["shell"] >= 4


def test_db_console_runtime_worker_holds_preflight_mutating_command_for_approval(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-preflight-hold-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Inspect workspace before answering",
            route_policy={
                "provider": "norllama",
                "kernel_workspace_preflight": True,
                "kernel_preflight_commands": ["python3 --version"],
            },
        ),
    )

    result = worker.run_continuous(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-preflight-hold-test",
            dry_run=False,
            continuous=True,
            live_execution_approved=True,
            max_steps=1,
            goal_phase_sequence=["preflight"],
            include_capabilities=False,
        ),
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    event_types = [event.event_type for event in events]

    assert result["job"]["status"] == "waiting_approval"
    assert result["stop_reason"] == "approval_required"
    assert result["last_result"]["approval_required"] is True
    assert "mutating command" in result["last_result"]["approval_reason"]
    assert "shell.started" not in event_types
