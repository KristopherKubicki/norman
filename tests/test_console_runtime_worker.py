from __future__ import annotations

import uuid

import pytest

from app import crud
from app.schemas.user import UserCreate
from app.services.console_runtime import ConsoleJobContract
from app.services.console_runtime.adapters.bedrock import BedrockModelAdapter
from app.services.console_runtime.adapters.fake import FakeModelAdapter
from app.services.console_runtime.store import DbConsoleRuntimeStore
from app.services.console_runtime.types import ModelResult, ModelUsage
from app.services.console_runtime.worker import (
    ConsoleRuntimeRunOptions,
    DbConsoleRuntimeWorker,
    _structured_response_signal,
)
from app.services.console_runtime import worker as worker_module
from app.services.norllama.route_policy import route_policy_contract


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
    policy = route_policy_contract()
    route_receipt = {
        "schema": "norman.norllama.route-receipt.v1",
        "status": "completed",
        "request_id": f"req-{job_id}",
        "job_id": job_id,
        "phase": "verify",
        "task_kind": "verify",
        "selected_provider": "norllama",
        "selected_model": "qwen3:8b",
        "route_selected_model": "qwen3:8b",
        "requested_model": "qwen3:8b",
        "target_model": "qwen3:8b",
        "effective_runtime_model": "qwen3:8b",
        "model_override_used": False,
        "model_override_reason": "",
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
        "policy_id": policy["policy_id"],
        "policy_hash": policy["policy_hash"],
        "policy_integrity_valid": True,
        "policy_lifecycle_state": "valid",
        "policy_default_route_allowed": True,
        "policy_issued_at": policy["issued_at"],
        "policy_expires_at": policy["expires_at"],
        "policy_refresh_generation": policy["refresh_generation"],
        "manual_degraded_authorized": False,
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
        "reasoning.tool_gate",
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
        "reasoning": 1,
    }
    events = store.events_after(db, user_id=user.id, job_id=job_id)
    behavior = next(
        event for event in events if event.event_type == "behavior.observed"
    )
    model_requested = next(
        event for event in events if event.event_type == "model.requested"
    )
    model_completed = next(
        event for event in events if event.event_type == "model.completed"
    )
    tool_completed = next(
        event for event in events if event.event_type == "tool.completed"
    )

    plan = behavior.payload["reasoning_orchestration"]
    assert plan["schema"] == "norman.reasoning-orchestrator.plan.v1"
    assert plan["plan_id"]
    assert result["reasoning_orchestration"]["plan_id"] == plan["plan_id"]
    assert model_requested.payload["reasoning_plan_id"] == plan["plan_id"]
    assert model_completed.payload["reasoning_plan_id"] == plan["plan_id"]
    assert tool_completed.payload["reasoning_plan_id"] == plan["plan_id"]
    assert model_completed.payload["reasoning_receipt"]["schema"] == (
        "norman.reasoning-orchestrator.receipt.v1"
    )
    assert isinstance(
        model_completed.payload["reasoning_receipt"]["skipped_required_tools"],
        list,
    )
    tool_gate = next(
        event for event in events if event.event_type == "reasoning.tool_gate"
    )
    assert tool_gate.payload["schema"] == "norman.reasoning-tool-gate.v1"
    assert tool_gate.payload["enforcement_required"] is False
    assert tool_gate.payload["completion_allowed"] is True
    assert result["reasoning_tool_gate"]["plan_id"] == plan["plan_id"]


def test_db_console_runtime_worker_checkpoints_when_reasoning_tool_gate_required(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-reasoning-gate-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="status?",
            route_policy={
                "provider": "norllama",
                "reasoning_tool_gate_required": True,
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

    assert result["job"]["status"] == "checkpointed"
    gate = result["reasoning_tool_gate"]
    assert gate["enforcement_required"] is True
    assert gate["gate_passed"] is False
    assert gate["completion_allowed"] is False
    assert "tui_status_api" in gate["missing_required_tools"]
    assert "route_receipt_ledger" in gate["missing_required_tools"]
    events = store.events_after(db, user_id=user.id, job_id=job_id)
    assert events[-2].event_type == "reasoning.tool_gate"
    assert events[-1].event_type == "job.checkpointed"
    assert (
        events[-1].summary == "Runtime worker checkpointed after reasoning tool gate."
    )


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


def test_db_console_runtime_worker_normalizes_verifier_before_audit_and_gate(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-verify-normalized-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Verify the route-proof sequence completes cleanly",
            route_policy={
                "provider": "norllama",
                "route_proof_required": True,
                "require_verifier_for_completion": True,
                "verifier_can_stop": True,
            },
        ),
    )
    model_result = _proof_model_result(
        job_id,
        text="STATUS: COMPLETE\nNo remaining work.",
    )
    route_receipt = model_result.metadata["norllama_receipt"]["route_receipt"]
    route_receipt["verifier_result"] = "skipped"
    adapter = FakeModelAdapter(
        responses=[model_result],
        name="norllama",
        model="qwen3:8b",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-verify-normalized-test",
            dry_run=True,
            include_capabilities=False,
            metadata={"goal_phase": "verify"},
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    event_types = [event.event_type for event in events]
    audit_event = next(
        event for event in events if event.event_type == "route.receipt_audited"
    )
    gate_event = next(
        event for event in events if event.event_type == "route.completion_gate"
    )
    model_event = next(
        event for event in events if event.event_type == "model.completed"
    )

    assert result["job"]["status"] == "done"
    assert result["route_proof"]["gate_passed"] is True
    assert event_types.index("verification.completed") < event_types.index(
        "route.receipt_audited"
    )
    assert event_types.index("route.receipt_audited") < event_types.index(
        "route.completion_gate"
    )
    assert audit_event.payload["route_receipt"]["verifier_result"] == "pass"
    assert audit_event.payload["receipt_audit"]["pass"] is True
    assert model_event.payload["route_receipt"]["verifier_result"] == "pass"
    assert model_event.payload["route_receipt"]["receipt_audit"]["pass"] is True
    assert gate_event.payload["route_receipt"] == audit_event.payload["route_receipt"]
    assert gate_event.payload["receipt_audit"] == audit_event.payload["receipt_audit"]
    assert gate_event.payload["completion_gate"]["gate_passed"] is True


def test_db_console_runtime_worker_does_not_require_verifier_on_nonfinal_step(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-nonfinal-proof-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Produce a local candidate answer before final verification",
            route_policy={
                "provider": "norllama",
                "route_proof_required": True,
                "require_verifier_for_completion": True,
            },
        ),
    )
    model_result = _proof_model_result(job_id, text='{"candidate": "answer"}')
    route_receipt = model_result.metadata["norllama_receipt"]["route_receipt"]
    route_receipt["phase"] = "chat"
    route_receipt["task_kind"] = "chat"
    route_receipt["verifier_result"] = "skipped"
    adapter = FakeModelAdapter(
        responses=[model_result],
        name="norllama",
        model="qwen3:8b",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-nonfinal-proof-test",
            dry_run=True,
            complete=False,
            include_capabilities=False,
            metadata={"goal_phase": "work", "goal_task_kind": "chat"},
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    audit_event = next(
        event for event in events if event.event_type == "route.receipt_audited"
    )
    gate_event = next(
        event for event in events if event.event_type == "route.completion_gate"
    )

    assert result["job"]["status"] == "checkpointed"
    assert result["route_proof"]["gate_passed"] is True
    assert adapter.invocations[0].metadata["completion_requested"] is False
    assert adapter.invocations[0].metadata["require_verifier_for_completion"] is False
    assert audit_event.payload["receipt_audit"]["pass"] is True
    assert audit_event.payload["route_receipt"]["verifier_result"] == "skipped"
    assert gate_event.payload["completion_gate"]["gate_passed"] is True


def test_db_console_runtime_worker_uses_route_model_unless_route_locked(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-route-model-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Use the policy-selected route model.",
            route_policy={
                "provider": "norllama",
                "model": "qwen3.6:27b",
                "model_selection": "explicit",
            },
        ),
    )
    adapter = FakeModelAdapter(responses=["route model ok"], name="norllama")

    worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-route-model-test",
            dry_run=True,
            include_capabilities=False,
            model="qwen3.6:35b-a3b-q4_K_M",
            metadata={
                "requested_model": "gpt-5.4",
                "route_selected_model": "gpt-5.4",
                "target_model": "gpt-5.4",
            },
        ),
        adapter=adapter,
    )

    invocation = adapter.invocations[0]
    assert invocation.model == "qwen3.6:27b"
    assert invocation.metadata["route_selected_model"] == "qwen3.6:27b"
    assert invocation.metadata["requested_model"] == "qwen3.6:27b"
    assert invocation.metadata["model_override_used"] is False


def test_db_console_runtime_worker_allows_route_locked_model_override(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-route-lock-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Honor explicit operator route lock.",
            route_policy={
                "provider": "norllama",
                "model": "qwen3.6:27b",
                "model_selection": "explicit",
            },
        ),
    )
    adapter = FakeModelAdapter(responses=["route locked ok"], name="norllama")

    worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-route-lock-test",
            dry_run=True,
            include_capabilities=False,
            model="qwen3.6:35b-a3b-q4_K_M",
            metadata={"route_lock": True},
        ),
        adapter=adapter,
    )

    invocation = adapter.invocations[0]
    assert invocation.model == "qwen3.6:35b-a3b-q4_K_M"
    assert invocation.metadata["route_selected_model"] == "qwen3.6:27b"
    assert invocation.metadata["requested_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert invocation.metadata["model_override_used"] is True
    assert invocation.metadata["model_override_reason"] == "operator_route_lock"


def test_db_console_runtime_worker_uses_goal_phase_as_task_kind_fallback(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-phase-task-kind-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Use the phase when no explicit task kind is provided.",
            route_policy={"provider": "norllama", "model_selection": "explicit"},
        ),
    )
    adapter = FakeModelAdapter(responses=["phase fallback ok"], name="norllama")

    worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-phase-task-kind-test",
            dry_run=True,
            include_capabilities=False,
            metadata={"goal_phase": "work"},
        ),
        adapter=adapter,
    )

    invocation = adapter.invocations[0]
    assert invocation.metadata["norllama_task_kind"] == "chat"
    assert invocation.metadata["route_selected_model"] != ""


def test_structured_response_signal_requires_visible_json_document():
    objective = (
        "Return one compact JSON object with keys unhealthy_service, evidence "
        "and nonce value liveproof."
    )

    assert (
        _structured_response_signal(
            objective,
            'STATUS: COMPLETE\n{"unhealthy_service":"billing","evidence":"down","nonce":"liveproof"}',
        )
        == "needs_more_work"
    )
    assert (
        _structured_response_signal(
            objective,
            '{"unhealthy_service":"billing","evidence":"down","nonce":"liveproof"}',
        )
        == "complete"
    )


def test_db_console_runtime_worker_deterministically_verifies_literal_response(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-literal-verified-{uuid.uuid4().hex}"
    expected = "DONE local visible unit-test"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective=f"Canary only. Reply exactly: {expected}",
            route_policy={
                "provider": "norllama",
                "route_proof_required": True,
                "require_verifier_for_completion": True,
            },
        ),
    )
    model_result = _proof_model_result(job_id, text=expected)
    route_receipt = model_result.metadata["norllama_receipt"]["route_receipt"]
    route_receipt["phase"] = "chat"
    route_receipt["task_kind"] = "chat"
    route_receipt["verifier_result"] = "skipped"
    adapter = FakeModelAdapter(
        responses=[model_result],
        name="norllama",
        model="qwen3:8b",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-literal-verified-test",
            dry_run=True,
            include_capabilities=False,
            planner_kind="literal_response",
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    audit_event = next(
        event for event in events if event.event_type == "route.receipt_audited"
    )
    gate_event = next(
        event for event in events if event.event_type == "route.completion_gate"
    )

    assert result["job"]["status"] == "done"
    assert result["route_proof"]["gate_passed"] is True
    assert any(event.event_type == "verification.completed" for event in events)
    assert audit_event.payload["route_receipt"]["verifier_result"] == "pass"
    assert audit_event.payload["receipt_audit"]["pass"] is True
    assert gate_event.payload["completion_gate"]["gate_passed"] is True


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
        responses=["DONE local visible."],
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
    assert result["last_result"]["model_result"]["text"] == "DONE local visible."
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
    assert (
        "Prior local candidate outputs" in adapter.invocations[2].messages[1]["content"]
    )
    assert "work" in adapter.invocations[2].messages[1]["content"]
    assert verification_events
    assert verification_events[0].payload["signal"] == "complete"


def test_db_console_runtime_worker_structured_requirements_override_complete_signal(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-structured-verify-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective=(
                "Return one compact JSON object with keys unhealthy_service, "
                "evidence, and nonce. Use nonce value n-123."
            ),
            route_policy={"provider": "norllama", "verifier_can_stop": True},
        ),
    )
    adapter = FakeModelAdapter(
        responses=[
            (
                "STATUS: COMPLETE\n\n"
                '{"unhealthy_service":"billing","evidence":"timeout"}'
            )
        ],
        name="runtime-dry-run",
        model="runtime-dry-run",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-structured-verify-test",
            dry_run=True,
            complete=True,
            include_capabilities=False,
            metadata={"goal_phase": "verify"},
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    needs_work_events = [
        event for event in events if event.event_type == "verification.needs_more_work"
    ]
    completed_events = [
        event for event in events if event.event_type == "verification.completed"
    ]

    assert result["job"]["status"] == "checkpointed"
    assert needs_work_events
    assert needs_work_events[0].payload["signal"] == "needs_more_work"
    assert completed_events == []


def test_db_console_runtime_worker_structured_nonce_allows_json_complete_signal(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-structured-complete-{uuid.uuid4().hex}"
    nonce = "67d552698d-norman-auto_route_local"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective=(
                "Return one compact JSON object with keys unhealthy_service, "
                f"evidence, and nonce. Use nonce value {nonce}."
            ),
            route_policy={"provider": "norllama", "verifier_can_stop": True},
        ),
    )
    adapter = FakeModelAdapter(
        responses=[
            (
                '{"unhealthy_service":"billing","evidence":"timeout",'
                f'"nonce":"{nonce}"}}'
            )
        ],
        name="runtime-dry-run",
        model="runtime-dry-run",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-structured-complete-test",
            dry_run=True,
            complete=True,
            include_capabilities=False,
            metadata={"goal_phase": "verify"},
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    completed_events = [
        event for event in events if event.event_type == "verification.completed"
    ]

    assert result["job"]["status"] == "done"
    assert completed_events
    assert completed_events[0].payload["signal"] == "complete"


def test_db_console_runtime_worker_structured_verify_reuses_valid_prior_candidate(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-structured-prior-{uuid.uuid4().hex}"
    nonce = "prior-json-nonce"
    candidate = (
        '{"unhealthy_service":"billing","evidence":"timeout",' f'"nonce":"{nonce}"}}'
    )
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective=(
                "Return one compact JSON object with keys unhealthy_service, "
                f"evidence, and nonce. Use nonce value {nonce}."
            ),
            route_policy={"provider": "norllama", "verifier_can_stop": True},
        ),
    )
    store.append_event(
        db,
        user_id=user.id,
        job_id=job_id,
        event_type="model.completed",
        payload={
            "provider": "norllama",
            "model": "qwen3.6:27b",
            "output_preview": candidate,
            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
        },
    )
    adapter = FakeModelAdapter(
        responses=["STATUS: NEEDS_MORE_WORK"],
        name="runtime-dry-run",
        model="runtime-dry-run",
    )

    result = worker.run_once(
        db,
        user_id=user.id,
        job_id=job_id,
        options=ConsoleRuntimeRunOptions(
            worker_id="worker-structured-prior-test",
            dry_run=True,
            complete=True,
            include_capabilities=False,
            metadata={"goal_phase": "verify"},
        ),
        adapter=adapter,
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    completed_events = [
        event for event in events if event.event_type == "verification.completed"
    ]

    assert result["job"]["status"] == "done"
    assert result["model_result"]["text"] == candidate
    assert completed_events
    assert completed_events[-1].payload["signal"] == "complete"


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


def test_db_console_runtime_worker_uses_native_bedrock_for_explicit_cloud_route(
    db, monkeypatch
):
    class FakeBedrockClient:
        def __init__(self):
            self.calls = []

        def converse(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "stopReason": "end_turn",
                "usage": {
                    "inputTokens": 7,
                    "outputTokens": 5,
                    "totalTokens": 12,
                },
                "output": {
                    "message": {
                        "content": [{"text": "Native Bedrock route completed."}]
                    }
                },
            }

    client = FakeBedrockClient()
    adapter = BedrockModelAdapter(client_factory=lambda **kwargs: client)
    monkeypatch.setattr(worker_module, "BedrockModelAdapter", lambda: adapter)

    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-bedrock-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Produce a release plan through the explicit cloud route.",
            route_policy={
                "provider": "bedrock",
                "model": "anthropic.claude-test",
                "allow_cloud_proxy": True,
                "aws_region": "us-east-2",
                "aws_profile": "norman-bedrock",
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
            complete=False,
            live_execution_approved=True,
        ),
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    model_event = next(
        event for event in events if event.event_type == "model.completed"
    )
    route_event = next(event for event in events if event.event_type == "route.decided")

    assert client.calls
    assert result["model_result"]["provider"] == "bedrock"
    assert result["model_result"]["usage"]["total_tokens"] == 12
    assert route_event.payload["selected_provider"] == "bedrock"
    assert route_event.payload["selected_runner"] == "bedrock"
    assert model_event.payload["provider"] == "bedrock"
    assert model_event.payload["route"]["provider"] == "bedrock"
    assert model_event.payload["route_receipt"]["usage_bucket"] == "bedrock_amazon"
    assert model_event.payload["route_receipt"]["total_tokens"] == 12


def test_db_console_runtime_worker_fails_native_bedrock_without_fallback(
    db, monkeypatch
):
    class FailingBedrockAdapter:
        name = "bedrock"

        def __init__(self):
            self.invocations = 0

        def invoke(self, request):
            self.invocations += 1
            raise RuntimeError("Bedrock Converse AccessDeniedException")

    adapter = FailingBedrockAdapter()
    monkeypatch.setattr(worker_module, "BedrockModelAdapter", lambda: adapter)

    def unexpected_norllama_fallback():
        raise AssertionError("native Bedrock failure must not select Norllama")

    monkeypatch.setattr(
        worker_module,
        "NorllamaModelAdapter",
        unexpected_norllama_fallback,
    )
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    worker = DbConsoleRuntimeWorker(store)
    job_id = f"job-worker-bedrock-failure-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Exercise native Bedrock terminal failure handling.",
            route_policy={
                "provider": "bedrock",
                "model": "anthropic.claude-test",
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
            dry_run=False,
            complete=False,
            include_capabilities=False,
            live_execution_approved=True,
        ),
    )

    events = store.events_after(db, user_id=user.id, job_id=job_id)
    event_types = [event.event_type for event in events]
    failed_event = next(event for event in events if event.event_type == "model.failed")
    requested_events = [
        event for event in events if event.event_type == "model.requested"
    ]

    assert adapter.invocations == 1
    assert result["job"]["status"] == "failed"
    assert result["model_failed"] is True
    assert result["failure_class"] == "model_adapter_failed"
    assert "AccessDeniedException" in result["error"]
    assert event_types[-3:] == ["model.failed", "tool.failed", "job.failed"]
    assert len(requested_events) == 1
    assert requested_events[0].payload["provider"] == "bedrock"
    assert failed_event.payload["provider"] == "bedrock"
    assert failed_event.payload["route"]["provider"] == "bedrock"
    assert failed_event.payload["route_receipt"]["status"] == "failed"
    assert failed_event.payload["route_receipt"]["selected_provider"] == "bedrock"
    assert failed_event.payload["route_receipt"]["cloud_proxy"] is True
    assert "model.completed" not in event_types
    assert result["route_receipt"]["status"] == "failed"


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
