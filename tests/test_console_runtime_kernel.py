from __future__ import annotations

import pytest

from app.services.console_runtime import (
    ConsoleJobContract,
    ConsoleJobStatus,
    ConsoleRuntimeKernel,
    InvalidTransitionError,
    JobNotFoundError,
    ModelBudget,
    ModelRequest,
    ModelResult,
    ModelUsage,
)
from app.services.console_runtime.adapters.fake import FakeModelAdapter
from app.services.console_runtime.adapters.norllama import NorllamaModelAdapter
from app.services.console_runtime.adapters import norllama as norllama_adapter
from app.services.console_runtime.streaming import event_to_sse, events_to_sse
from app.services.norllama.types import NorllamaRoute


def _contract(**overrides):
    values = {
        "objective": "Build the Norman console runtime nucleus",
        "done_when": ["job state is durable", "model calls are adapter-owned"],
        "required_artifacts": [],
        "max_runtime_seconds": 7200,
        "checkpoint_interval_seconds": 900,
    }
    values.update(overrides)
    return ConsoleJobContract(**values)


def test_create_job_records_contract_and_event():
    kernel = ConsoleRuntimeKernel()

    job = kernel.create_job(_contract(), job_id="job-test")

    assert job.job_id == "job-test"
    assert job.status == ConsoleJobStatus.QUEUED
    assert job.contract.done_when == [
        "job state is durable",
        "model calls are adapter-owned",
    ]
    assert [event.event_type for event in kernel.events("job-test")] == ["job.created"]


def test_lease_start_and_checkpoint_job():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")

    leased = kernel.lease_job("job-test", worker_id="worker-a", lease_seconds=30)
    assert leased.status == ConsoleJobStatus.LEASED
    assert leased.lease is not None
    assert leased.lease.worker_id == "worker-a"

    started = kernel.start_job("job-test")
    assert started.status == ConsoleJobStatus.RUNNING

    checkpointed = kernel.checkpoint_job(
        "job-test",
        summary="Initial adapter contract added.",
        artifacts=["docs/norman_console_runtime_plan.md"],
    )

    assert checkpointed.status == ConsoleJobStatus.CHECKPOINTED
    assert checkpointed.checkpoints == ["Initial adapter contract added."]
    assert checkpointed.artifacts == ["docs/norman_console_runtime_plan.md"]
    assert [event.event_type for event in kernel.events("job-test")] == [
        "job.created",
        "job.leased",
        "job.started",
        "job.checkpointed",
    ]


def test_invoke_model_uses_adapter_and_records_events():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")
    adapter = FakeModelAdapter(responses=["runtime draft"])
    request = ModelRequest(
        model="local-test",
        route_key="planner.local",
        messages=[{"role": "user", "content": "plan"}],
    )

    result = kernel.invoke_model("job-test", adapter=adapter, request=request)

    assert result.text == "runtime draft"
    assert adapter.invocations == [request]
    assert kernel.get_job("job-test").status == ConsoleJobStatus.RUNNING
    assert [event.event_type for event in kernel.events("job-test")] == [
        "job.created",
        "model.requested",
        "model.completed",
    ]


def test_complete_job_requires_contract_artifacts():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(
        _contract(required_artifacts=["runtime-plan.md"]),
        job_id="job-test",
    )

    with pytest.raises(InvalidTransitionError):
        kernel.complete_job("job-test")

    completed = kernel.complete_job(
        "job-test",
        summary="Required artifact produced.",
        artifacts=["runtime-plan.md"],
    )

    assert completed.status == ConsoleJobStatus.DONE
    assert completed.artifacts == ["runtime-plan.md"]


def test_contract_and_model_types_normalize_boundaries():
    contract = ConsoleJobContract(
        objective="  normalize runtime work  ",
        done_when=[" durable ", "", None],
        success_metrics=["tests pass"],
        required_artifacts=[" artifact.json ", ""],
        max_runtime_seconds=0,
        checkpoint_interval_seconds=-10,
        question_budget=-1,
        authority_flags={"write": False},
        route_policy={"preferred": "norllama"},
    )
    budget = ModelBudget(
        max_model_calls=0,
        max_runtime_seconds=0,
        max_output_tokens=0,
    )
    usage = ModelUsage(input_tokens=-5, output_tokens=7, total_tokens=1)
    request = ModelRequest(
        messages=[{"role": "user", "content": "  hello  "}],
        model="  qwen3-coder  ",
        route_key=" planner.local ",
        budget=budget,
    )

    assert contract.objective == "normalize runtime work"
    assert contract.done_when == ["durable"]
    assert contract.required_artifacts == ["artifact.json"]
    assert contract.max_runtime_seconds == 1
    assert contract.checkpoint_interval_seconds == 1
    assert contract.question_budget == 0
    assert budget.as_dict() == {
        "max_model_calls": 1,
        "max_runtime_seconds": 1,
        "max_output_tokens": 1,
    }
    assert usage.as_dict() == {
        "input_tokens": 0,
        "output_tokens": 7,
        "total_tokens": 7,
    }
    assert request.model == "qwen3-coder"
    assert request.route_key == "planner.local"


def test_duplicate_and_missing_jobs_fail_closed():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")

    with pytest.raises(InvalidTransitionError):
        kernel.create_job(_contract(), job_id="job-test")

    with pytest.raises(JobNotFoundError):
        kernel.get_job("job-missing")

    with pytest.raises(JobNotFoundError):
        kernel.lease_job("job-missing", worker_id="worker-a")


def test_invalid_transitions_are_rejected():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")

    with pytest.raises(InvalidTransitionError):
        kernel.start_job("job-test")

    with pytest.raises(InvalidTransitionError):
        kernel.checkpoint_job("job-test", summary="too early")

    kernel.lease_job("job-test", worker_id="worker-a")

    with pytest.raises(InvalidTransitionError):
        kernel.lease_job("job-test", worker_id="worker-b")


def test_checkpoint_can_be_released_to_another_worker():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")
    kernel.lease_job("job-test", worker_id="worker-a")
    kernel.checkpoint_job("job-test", summary="worker-a paused")

    leased = kernel.lease_job("job-test", worker_id="worker-b", lease_seconds=1)

    assert leased.status == ConsoleJobStatus.LEASED
    assert leased.lease is not None
    assert leased.lease.worker_id == "worker-b"
    assert [event.event_type for event in kernel.events("job-test")] == [
        "job.created",
        "job.leased",
        "job.checkpointed",
        "job.leased",
    ]


def test_approval_hold_can_checkpoint_without_progressing_work():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")

    held = kernel.require_approval(
        "job-test",
        reason="write action requires operator approval",
        requested_by="worker-a",
    )
    assert held.status == ConsoleJobStatus.WAITING_APPROVAL

    checkpointed = kernel.checkpoint_job(
        "job-test",
        summary="Waiting on explicit approval before mutation.",
    )

    assert checkpointed.status == ConsoleJobStatus.CHECKPOINTED
    assert [event.event_type for event in kernel.events("job-test")] == [
        "job.created",
        "job.approval_required",
        "job.checkpointed",
    ]


def test_terminal_jobs_reject_more_work_but_blocked_can_be_canceled():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-blocked")
    kernel.block_job("job-blocked", reason="human input required")

    with pytest.raises(InvalidTransitionError):
        kernel.invoke_model(
            "job-blocked",
            adapter=FakeModelAdapter(responses=["should not run"]),
            request=ModelRequest(messages=[{"role": "user", "content": "continue"}]),
        )

    canceled = kernel.cancel_job("job-blocked", reason="operator superseded")
    assert canceled.status == ConsoleJobStatus.CANCELED

    kernel.create_job(_contract(), job_id="job-done")
    kernel.complete_job("job-done")

    with pytest.raises(InvalidTransitionError):
        kernel.cancel_job("job-done")


def test_model_failure_marks_job_failed_and_records_event():
    class BrokenAdapter:
        name = "broken"

        @property
        def capabilities(self):
            return FakeModelAdapter().capabilities

        def invoke(self, request):
            raise RuntimeError("provider unavailable")

    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")

    with pytest.raises(RuntimeError):
        kernel.invoke_model(
            "job-test",
            adapter=BrokenAdapter(),
            request=ModelRequest(messages=[{"role": "user", "content": "plan"}]),
        )

    job = kernel.get_job("job-test")
    assert job.status == ConsoleJobStatus.FAILED
    assert job.last_error == "provider unavailable"
    assert [event.event_type for event in kernel.events("job-test")] == [
        "job.created",
        "model.requested",
        "model.failed",
    ]


def test_norllama_adapter_returns_route_receipt(monkeypatch):
    monkeypatch.setattr(
        norllama_adapter.settings,
        "llm_offline_provider",
        "norllama",
        raising=False,
    )
    monkeypatch.setattr(
        norllama_adapter.settings,
        "llm_offline_base_url",
        "http://127.0.0.1:11434",
        raising=False,
    )
    monkeypatch.setattr(
        norllama_adapter.settings,
        "llm_offline_model",
        "qwen3:8b",
        raising=False,
    )
    calls = []

    def fake_invoke_text_chat(**kwargs):
        calls.append(kwargs)
        return {
            "model": kwargs["model"],
            "choices": [{"message": {"content": "adapter ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 5},
            "headers": {
                "X-Norllama-Worker-Id": "spark-151",
                "X-Norllama-Peer-Path": "llm.home.arpa,spark-151",
                "X-Norllama-Request-Id": "gw-job-adapter-test",
            },
        }

    monkeypatch.setattr(
        norllama_adapter.norllama_gateway,
        "invoke_text_chat",
        fake_invoke_text_chat,
    )
    adapter = NorllamaModelAdapter()

    result = adapter.invoke(
        ModelRequest(
            messages=[{"role": "user", "content": "plan"}],
            metadata={
                "route_policy": {
                    "provider": "norllama",
                    "model_timeout_seconds": 75,
                },
                "job_id": "job-adapter-test",
                "session_name": "norman-codex",
                "goal_phase": "work",
                "goal_task_kind": "chat",
                "invocation_id": "worker:job-adapter-test:work:1:model",
            },
        )
    )

    assert result.text == "adapter ok"
    assert calls[0]["timeout_seconds"] == 75
    assert calls[0]["correlation_headers"]["X-Request-Id"] == (
        "worker:job-adapter-test:work:1:model"
    )
    assert calls[0]["correlation_headers"]["X-Norman-Job-Id"] == "job-adapter-test"
    assert calls[0]["correlation_headers"]["X-Norman-Session"] == "norman-codex"
    assert calls[0]["correlation_headers"]["X-Norman-Phase"] == "work"
    assert calls[0]["correlation_headers"]["X-Norman-Lane"] == "chat"
    assert result.provider == "norllama"
    assert result.usage.total_tokens == 7
    assert result.metadata["norllama_route"]["provider"] == "norllama"
    assert result.metadata["norllama_receipt"]["status"] == "completed"
    route_receipt = result.metadata["norllama_receipt"]["route_receipt"]
    assert route_receipt["total_tokens"] == 7
    assert route_receipt["client_request_id"] == (
        "worker:job-adapter-test:work:1:model"
    )
    assert route_receipt["gateway_request_id"] == "gw-job-adapter-test"
    assert route_receipt["invocation_id"] == "worker:job-adapter-test:work:1:model"
    lanes = {
        lane["lane"]: lane for lane in route_receipt["specialist_cascade"]["lanes"]
    }
    assert lanes["receipt_auditor"]["status"] == "pass"
    assert lanes["non_answer_detector"]["status"] == "pass"
    assert lanes["difficulty_estimator"]["status"] == "pass"
    assert lanes["receipt_auditor"]["live_smoke_test"]["status"] == "passed"
    assert lanes["receipt_auditor"]["proof_state"] == "production"


def test_norllama_adapter_derives_job_header_from_invocation_id():
    headers = norllama_adapter._correlation_headers(
        ModelRequest(
            messages=[{"role": "user", "content": "work"}],
            metadata={
                "session_name": "norman-codex",
                "goal_phase": "work",
                "goal_task_kind": "chat",
                "execution_mode": "live",
                "invocation_id": "worker:job-derived-header:work:1:model",
            },
        ),
        task_id="worker:job-derived-header:work:1:model",
    )

    assert headers["X-Request-Id"] == "worker:job-derived-header:work:1:model"
    assert headers["X-Norman-Job-Id"] == "job-derived-header"
    assert headers["X-Norman-Session"] == "norman-codex"
    assert headers["X-Norman-Execution-Mode"] == "live"


def test_norllama_adapter_executes_worker_route_without_rerouting(monkeypatch):
    route = NorllamaRoute(
        lane="norllama_code",
        provider="norllama",
        provider_kind="norllama",
        capability="code",
        model="qwen3.6:27b",
        endpoint="https://llm.home.arpa/v1",
        local=True,
        cloud_proxy=False,
        requires_receipt=True,
        reason="worker selected code route",
        attribution={
            "model_selection": {"model": "qwen3.6:27b", "source": "worker_route"},
            "selection_source": "frontdoor_delegated",
            "routing_scope": "frontdoor",
        },
    )
    calls = []

    def fail_reroute(_task):
        raise AssertionError("adapter must not reroute worker-selected requests")

    def fake_invoke_text_chat(**kwargs):
        calls.append(kwargs)
        return {
            "model": kwargs["model"],
            "choices": [{"message": {"content": "adapter ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            "headers": {
                "X-Norllama-Worker-Id": "spark-151",
                "X-Norllama-Peer-Path": "llm.home.arpa,spark-151",
                "X-Norllama-Request-Id": "gw-worker-route",
            },
        }

    monkeypatch.setattr(norllama_adapter, "route_task", fail_reroute)
    monkeypatch.setattr(
        norllama_adapter.norllama_gateway,
        "invoke_text_chat",
        fake_invoke_text_chat,
    )

    result = NorllamaModelAdapter().invoke(
        ModelRequest(
            messages=[{"role": "user", "content": "patch"}],
            model="qwen3.6:27b",
            metadata={
                "route_policy": {"provider": "norllama"},
                "norllama_route": route.as_dict(),
                "norllama_task_kind": "code",
                "route_selected_model": "qwen3.6:27b",
                "requested_model": "qwen3.6:27b",
                "job_id": "job-worker-route",
                "goal_phase": "work",
                "goal_task_kind": "code",
                "invocation_id": "worker:job-worker-route:work:1:model",
            },
        )
    )

    receipt = result.metadata["norllama_receipt"]["route_receipt"]
    assert calls[0]["model"] == "qwen3.6:27b"
    assert receipt["task_kind"] == "code"
    assert receipt["phase"] == "work"
    assert receipt["selected_model"] == "qwen3.6:27b"
    assert receipt["route_selected_model"] == "qwen3.6:27b"
    assert receipt["requested_model"] == "qwen3.6:27b"
    assert receipt["effective_runtime_model"] == "qwen3.6:27b"
    assert receipt["gateway_request_id"] == "gw-worker-route"


def test_norllama_adapter_reports_live_capabilities(monkeypatch):
    monkeypatch.setattr(
        norllama_adapter.settings,
        "llm_offline_model",
        "qwen3:8b",
        raising=False,
    )
    monkeypatch.setattr(
        norllama_adapter.norllama_gateway,
        "fetch_capabilities",
        lambda **kwargs: {
            "models": ["planner-local", "reranker-local"],
            "tool_lanes": ["ocr", "rerank"],
            "task_kinds": ["chat", "plan", "rerank"],
            "modalities": ["text", "image"],
            "supports": {"tools": True, "streaming": True, "files": True},
        },
    )

    capabilities = NorllamaModelAdapter().capabilities

    assert capabilities.models == ["qwen3:8b", "planner-local", "reranker-local"]
    assert capabilities.supports_tools is True
    assert capabilities.supports_streaming is True
    assert capabilities.supports_files is True
    assert capabilities.metadata["capabilities_endpoint"] is True
    assert capabilities.metadata["tool_lanes"] == ["ocr", "rerank"]


def test_fake_adapter_can_return_structured_model_result():
    structured = ModelResult(
        provider="ollama",
        model="qwen3-coder",
        text="draft",
        stop_reason="tool_budget",
        usage=ModelUsage(input_tokens=10, output_tokens=4),
        metadata={"route": "local"},
    )
    adapter = FakeModelAdapter(responses=[structured], name="fake-local")
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")

    result = kernel.invoke_model(
        "job-test",
        adapter=adapter,
        request=ModelRequest(messages=[{"role": "user", "content": "draft"}]),
    )
    completion_event = kernel.events("job-test")[-1]

    assert result is structured
    assert completion_event.payload["provider"] == "ollama"
    assert completion_event.payload["model"] == "qwen3-coder"
    assert completion_event.payload["usage"] == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }


def test_job_and_event_dicts_are_json_ready():
    kernel = ConsoleRuntimeKernel()
    job = kernel.create_job(_contract(), job_id="job-test")

    job_payload = job.as_dict()
    event_payload = kernel.events("job-test")[0].as_dict()

    assert job_payload["status"] == "queued"
    assert job_payload["contract"]["objective"] == job.contract.objective
    assert event_payload["event_type"] == "job.created"
    assert event_payload["job_id"] == "job-test"


def test_runtime_events_are_ordered_and_cursorable():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")
    kernel.record_behavior(
        "job-test",
        phase="planning",
        summary="Inspecting existing TUI stream behavior.",
        detail="Looking for EventSource and audit hooks.",
    )
    tool_id = kernel.start_tool(
        "job-test",
        tool_name="rg",
        args_summary="rg EventSource app scripts tests",
    )
    kernel.complete_tool(
        "job-test",
        invocation_id=tool_id,
        tool_name="rg",
        summary="Found current stream hooks.",
        output_preview="scripts/agent_console_template/agent_console_web.py",
        artifacts=["runtime-events.jsonl"],
    )
    kernel.record_model_delta(
        "job-test",
        provider="ollama",
        model="qwen3-coder",
        text="Drafting event feed.",
    )

    events = kernel.events("job-test")
    sequences = [event.sequence for event in events]
    assert sequences == sorted(sequences)
    assert sequences == [1, 2, 3, 4, 5]
    assert [event.category for event in events] == [
        "job",
        "behavior",
        "tool",
        "tool",
        "model",
    ]
    assert [event.event_type for event in kernel.events_after(after_sequence=2)] == [
        "tool.started",
        "tool.completed",
        "model.delta",
    ]
    assert kernel.get_job("job-test").artifacts == ["runtime-events.jsonl"]


def test_planner_receipt_is_first_class_runtime_event():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")

    event = kernel.record_planner_receipt(
        "job-test",
        receipt={
            "task_kind": "plan",
            "status": "accepted",
            "route": {
                "provider": "norllama",
                "capability": "planner",
                "model": "qwen3:8b",
            },
            "evidence_paths": ["planner-receipt.json"],
        },
        capabilities={
            "provider": "norllama",
            "models": ["qwen3:8b"],
            "metadata": {"tool_lanes": ["rerank"]},
        },
    )

    assert event.event_type == "planner.receipt"
    assert event.category == "planner"
    assert event.payload["provider"] == "norllama"
    assert event.payload["capability"] == "planner"
    assert event.payload["task_kind"] == "plan"
    assert event.payload["capabilities"]["models"] == ["qwen3:8b"]
    assert kernel.get_job("job-test").artifacts == ["planner-receipt.json"]


def test_activity_snapshot_summarizes_visible_runtime_activity():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")
    kernel.record_behavior(
        "job-test",
        phase="execution",
        summary="Running shell command.",
    )
    kernel.start_tool("job-test", tool_name="pytest")

    snapshot = kernel.activity_snapshot("job-test", after_sequence=1, limit=10)

    assert snapshot["job"]["job_id"] == "job-test"
    assert snapshot["event_count"] == 3
    assert snapshot["category_counts"] == {"job": 1, "behavior": 1, "tool": 1}
    assert snapshot["latest_event"]["event_type"] == "tool.started"
    assert [event["event_type"] for event in snapshot["events"]] == [
        "behavior.observed",
        "tool.started",
    ]
    assert snapshot["next_after"] == 3


def test_sse_renderer_uses_sequence_event_and_json_payload():
    kernel = ConsoleRuntimeKernel()
    kernel.create_job(_contract(), job_id="job-test")
    kernel.record_behavior(
        "job-test",
        phase="planning",
        summary="Planning visible activity rail.",
    )

    rendered = events_to_sse(kernel.events("job-test"))
    single = event_to_sse(kernel.events("job-test")[1])

    assert "id: 1\n" in rendered
    assert "event: job.created\n" in rendered
    assert "event: behavior.observed\n" in single
    assert '"category":"behavior"' in single
    assert '"summary":"Planning visible activity rail."' in single
