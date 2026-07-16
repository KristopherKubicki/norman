from __future__ import annotations

import pytest

from app.api.deps import get_console_runtime_user, get_current_user
from app.core.auth_cache import clear_auth_caches
from app.core.config import settings
from app.crud.user import create_user, get_user_by_email
from app.main import app
from app.schemas.user import UserCreate
from app.services.norllama.specialist_lanes import specialist_cascade_template


def _seed_runtime_job(test_app, *, job_id="job-visible"):
    response = test_app.post(
        "/api/v1/console-runtime/jobs",
        json={
            "job_id": job_id,
            "objective": "Expose runtime activity to the TUI",
            "done_when": ["events are visible"],
        },
    )
    assert response.status_code == 200
    behavior = test_app.post(
        f"/api/v1/console-runtime/jobs/{job_id}/events",
        json={
            "event_type": "behavior.observed",
            "payload": {"phase": "planning"},
            "summary": "Mapping runtime event feed.",
        },
    )
    assert behavior.status_code == 200
    started = test_app.post(
        f"/api/v1/console-runtime/jobs/{job_id}/events",
        json={
            "event_type": "tool.started",
            "payload": {
                "invocation_id": "tool-api",
                "tool_name": "pytest",
                "args_summary": "tests/test_console_runtime_kernel.py",
            },
            "summary": "Started pytest",
            "detail": "tests/test_console_runtime_kernel.py",
        },
    )
    assert started.status_code == 200
    completed = test_app.post(
        f"/api/v1/console-runtime/jobs/{job_id}/events",
        json={
            "event_type": "tool.completed",
            "payload": {
                "invocation_id": "tool-api",
                "tool_name": "pytest",
                "output_preview": "13 passed",
            },
            "summary": "Focused runtime tests passed.",
            "detail": "13 passed",
        },
    )
    assert completed.status_code == 200
    return {
        "behavior": behavior.json(),
        "started": started.json(),
        "completed": completed.json(),
    }


def test_console_runtime_api_lists_jobs_and_activity(test_app):
    seeded = _seed_runtime_job(test_app, job_id="job-visible-api-list")

    jobs_response = test_app.get("/api/v1/console-runtime/jobs")
    assert jobs_response.status_code == 200
    jobs_payload = jobs_response.json()
    assert any(
        item["job_id"] == "job-visible-api-list" for item in jobs_payload["items"]
    )

    activity_response = test_app.get(
        "/api/v1/console-runtime/jobs/job-visible-api-list"
        f"?after={seeded['behavior']['sequence'] - 1}"
    )
    assert activity_response.status_code == 200
    activity = activity_response.json()

    assert activity["job"]["status"] == "queued"
    assert activity["category_counts"] == {"job": 1, "behavior": 1, "tool": 2}
    assert [event["event_type"] for event in activity["events"]] == [
        "behavior.observed",
        "tool.started",
        "tool.completed",
    ]
    assert activity["next_after"] == seeded["completed"]["sequence"]


def test_console_runtime_api_defaults_jobs_to_local_warm_policy_routing(test_app):
    response = test_app.post(
        "/api/v1/console-runtime/jobs",
        json={
            "job_id": "job-local-warm-policy-defaults",
            "objective": "Route TUI work through local warm policy first",
        },
    )

    assert response.status_code == 200
    route_policy = response.json()["contract"]["route_policy"]
    assert route_policy["provider"] == "norllama"
    assert route_policy["preferred_provider"] == "norllama"
    assert route_policy["planner"] == "norllama"
    assert route_policy["model_proxy"] == "norllama"
    assert route_policy["local_first"] is True
    assert route_policy["allow_cloud_proxy"] is False
    assert route_policy["use_capability_catalog"] is True
    assert route_policy["model_selection"] == "warm_policy"


def test_console_runtime_api_exposes_kernel_capabilities(test_app, monkeypatch):
    from app.api.api_v1.routers import console_runtime as console_runtime_router

    monkeypatch.setattr(
        console_runtime_router.norllama_mesh_cache,
        "get_mesh_overview",
        lambda timeout_seconds=2: {
            "schema": "norman.norllama.mesh.v1",
            "status": "ok",
            "worker_count": 3,
            "healthy_worker_count": 3,
        },
    )
    monkeypatch.setattr(
        console_runtime_router.norllama_warm_policy,
        "build_warm_policy",
        lambda mesh=None: {
            "schema": "norman.norllama.warm-policy.v1",
            "route_posture": "ready",
        },
    )
    response = test_app.get("/api/v1/console-runtime/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kernel"]["supports"]["db_event_stream"] is True
    assert payload["kernel"]["supports"]["codex_optional"] is True
    assert payload["kernel"]["supports"]["cloud_llm_offline"] is True
    assert payload["kernel"]["supports"]["local_first_default"] is True
    assert payload["kernel"]["supports"]["explicit_cloud_escalation"] is True
    assert payload["kernel"]["supports"]["norllama_frontdoor"] is True
    assert payload["kernel"]["supports"]["continuous_goal_loop"] is True
    assert payload["kernel"]["supports"]["phased_goal_loop"] is True
    assert payload["kernel"]["supports"]["bounded_goal_runs"] is True
    assert payload["kernel"]["supports"]["local_token_budget"] is True
    assert payload["kernel"]["supports"]["tui_kernel_execution_promotion"] is True
    assert payload["kernel"]["supports"]["route_summary"] is True
    assert payload["kernel"]["supports"]["usage_ledger"] is True
    assert payload["kernel"]["supports"]["usage_by_provider"] is True
    assert payload["kernel"]["supports"]["usage_by_job"] is True
    assert payload["kernel"]["supports"]["usage_by_day"] is True
    assert payload["kernel"]["supports"]["local_first_kpi"] is True
    assert payload["kernel"]["supports"]["local_first_proof"] is True
    assert payload["kernel"]["supports"]["tui_acceptance_gate"] is True
    assert payload["kernel"]["supports"]["dynamic_model_pool"] is True
    assert payload["kernel"]["supports"]["route_receipt_pool"] is True
    assert payload["kernel"]["supports"]["specialist_lane_registry"] is True
    assert payload["kernel"]["supports"]["specialist_route_receipts"] is True
    assert payload["kernel"]["supports"]["deterministic_expert_cascade"] is True
    assert "goal" in payload["kernel"]["event_categories"]
    assert "policy" in payload["kernel"]["event_categories"]
    assert "route" in payload["kernel"]["event_categories"]
    assert "shell" in payload["kernel"]["event_categories"]
    assert payload["kernel"]["mode"]["active_mode"]
    assert payload["norllama"]["provider"] == "norllama"
    assert payload["norllama"]["capability_catalog"]["schema"] == (
        "norman.norllama.capability-catalog.v1"
    )
    assert payload["norllama"]["capability_catalog"]["defaults"]["code"] == (
        "qwen3.6:27b"
    )
    assert payload["norllama"]["specialist_lanes"]["schema"] == (
        "norman.norllama.specialist-lanes.v1"
    )
    assert payload["norllama"]["specialist_lanes"]["count"] == 10
    assert (
        payload["norllama"]["specialist_lanes"]["deterministic_experts"]["count"] == 11
    )
    assert payload["norllama"]["specialist_lanes"]["proof"]["schema"] == (
        "norman.norllama.specialist-proof.v1"
    )
    assert payload["norllama"]["specialist_lanes"]["proof"]["lane_count"] == 10
    assert payload["norllama"]["mesh"]["status"] == "ok"
    assert payload["norllama"]["mesh"]["healthy_worker_count"] == 3
    assert payload["norllama"]["warm_policy"]["route_posture"] == "ready"


def test_console_runtime_api_exposes_tui_acceptance_gate(test_app, monkeypatch):
    from app.api.api_v1.routers import console_runtime

    monkeypatch.setattr(
        console_runtime,
        "latest_acceptance_gate",
        lambda: {
            "schema": "norman.tui-kernel-acceptance-gate.v1",
            "status": "pass",
            "passed": True,
            "pass_percent": 100.0,
            "release_gate": {"zero_cloud_tokens": True},
        },
    )

    response = test_app.get("/api/v1/console-runtime/tui-acceptance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "norman.tui-kernel-acceptance-gate.v1"
    assert payload["status"] == "pass"
    assert payload["release_gate"]["zero_cloud_tokens"] is True


def test_console_runtime_api_lists_events_with_cursor(test_app):
    seeded = _seed_runtime_job(test_app, job_id="job-visible-api-events")

    response = test_app.get(
        "/api/v1/console-runtime/jobs/job-visible-api-events/events"
        f"?after={seeded['behavior']['sequence']}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["next_after"] == seeded["completed"]["sequence"]
    assert [event["event_type"] for event in payload["items"]] == [
        "tool.started",
        "tool.completed",
    ]


def test_console_runtime_api_streams_sse_once(test_app):
    seeded = _seed_runtime_job(test_app, job_id="job-visible-api-stream")

    response = test_app.get(
        "/api/v1/console-runtime/jobs/job-visible-api-stream/events/stream"
        f"?once=true&after={seeded['behavior']['sequence'] - 1}"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: behavior.observed" in response.text
    assert "event: tool.started" in response.text
    assert "event: tool.completed" in response.text
    assert '"summary":"Focused runtime tests passed."' in response.text


def test_console_runtime_api_missing_job_returns_404(test_app):
    response = test_app.get("/api/v1/console-runtime/jobs/missing/events")

    assert response.status_code == 404


def test_console_runtime_api_exposes_route_summary(test_app):
    _seed_runtime_job(test_app, job_id="job-visible-api-route-summary")
    route = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-route-summary/events",
        json={
            "event_type": "route.decided",
            "summary": "Routed bounded work to Norllama.",
            "payload": {
                "task_kind": "summarize",
                "selected_lane": "summarizer",
                "selected_provider": "norllama",
                "selected_runner": "norllama",
                "selected_model": "qwen3:8b",
                "selected_endpoint": "http://192.168.2.151:18151/v1",
                "egress_class": "lan",
                "attribution": {"worker_id": "spark-151"},
                "local": True,
                "allowed": True,
            },
        },
    )
    assert route.status_code == 200
    cloud = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-route-summary/events",
        json={
            "event_type": "route.decided",
            "summary": "Escalated mutation to cloud verifier.",
            "payload": {
                "task_kind": "write",
                "selected_lane": "verifier",
                "selected_provider": "bedrock",
                "selected_runner": "bedrock",
                "selected_model": "claude-check",
                "egress_class": "cloud_llm",
                "local": False,
                "allowed": True,
            },
        },
    )
    assert cloud.status_code == 200
    specialist_cascade = specialist_cascade_template(
        phase="summarize",
        selected_provider="norllama",
        selected_model="qwen3:8b",
        selected_worker="spark-151",
    )
    specialist_cascade["lanes"][0]["status"] = "pass"
    specialist_cascade["deterministic_experts"][0]["status"] = "pass"
    model = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-route-summary/events",
        json={
            "event_type": "model.completed",
            "summary": "Norllama model completed.",
            "payload": {
                "provider": "norllama",
                "model": "qwen3:8b",
                "execution_mode": "live",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "local": True,
                "cloud_proxy": False,
                "egress_class": "lan",
                "receipt_audit": {"status": "pass", "pass": True, "failures": []},
                "completion_gate": {"status": "pass", "gate_passed": True},
                "route_receipt": {
                    "schema": "norman.norllama.route-receipt.v1",
                    "status": "completed",
                    "request_id": "req-visible-api-route-summary",
                    "job_id": "job-visible-api-route-summary",
                    "phase": "summarize",
                    "task_kind": "summarize",
                    "selected_provider": "norllama",
                    "selected_model": "qwen3:8b",
                    "target_model": "qwen3:8b",
                    "effective_runtime_model": "qwen3:8b",
                    "selected_worker": "spark-151",
                    "observed_worker": "spark-151",
                    "observed_worker_source": "gateway_response",
                    "frontdoor": "https://llm.home.arpa/v1",
                    "peer_path": ["https://llm.home.arpa/v1", "spark-151"],
                    "route_reason": "API route summary fixture",
                    "policy_mode": "local_first",
                    "usage_bucket": "offline_local",
                    "cloud_proxy": False,
                    "benchmark_packet_id": "test-route-proof",
                    "benchmark_source": "uplink_benchmark",
                    "benchmark_fresh": True,
                    "benchmark_gate": {
                        "gate": "production",
                        "promotion_authoritative": True,
                    },
                    "promotion_authoritative": True,
                    "benchmark_score": 0.91,
                    "coverage_ratio": 0.88,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "fallback_used": False,
                    "fallback_reason": None,
                    "output_shape": "complete",
                    "verifier_result": "pass",
                    "execution_mode": "live",
                    "receipt_audit": {
                        "status": "pass",
                        "pass": True,
                        "failures": [],
                    },
                    "completion_gate": {"status": "pass", "gate_passed": True},
                    "specialist_cascade": specialist_cascade,
                },
            },
        },
    )
    assert model.status_code == 200

    activity = test_app.get(
        "/api/v1/console-runtime/jobs/job-visible-api-route-summary"
    )
    assert activity.status_code == 200
    embedded = activity.json()["route_summary"]
    assert embedded["route"]["total"] == 2
    assert embedded["route"]["offline_safe"] == 1
    assert embedded["route"]["cloud_llm"] == 1
    assert embedded["route"]["spark_hint"] == 1
    assert embedded["model"]["by_worker"] == {"spark-151": 1}
    assert embedded["workers"]["by_id"] == {"spark-151": 2}
    assert embedded["spark_evidence_count"] == 2
    assert embedded["local_first_kpi"]["status"] == "on_target"

    response = test_app.get(
        "/api/v1/console-runtime/route-summary" "?job_id=job-visible-api-route-summary"
    )
    assert response.status_code == 200
    summary = response.json()
    assert summary["job_id"] == "job-visible-api-route-summary"
    assert summary["route"]["by_provider"] == {"norllama": 1, "bedrock": 1}
    assert summary["route"]["by_worker"] == {"spark-151": 1}
    assert summary["local_evidence_count"] == 2
    assert summary["cloud_evidence_count"] == 1
    assert summary["local_first_kpi"]["cloud_evidence_count"] == 1
    proof = test_app.get("/api/v1/console-runtime/local-first-proof")
    assert proof.status_code == 200
    proof_payload = proof.json()
    assert proof_payload["schema"] == "norman.console-runtime.local-first-proof.v1"
    assert proof_payload["totals"]["local_tokens"] >= 15
    assert proof_payload["totals"]["spark_evidence_count"] >= 1
    assert proof_payload["totals"]["specialist_required_count"] >= 21
    assert proof_payload["totals"]["specialist_evidence_count"] >= 2
    assert proof_payload["release_gate"]["has_spark_evidence"] is True
    assert proof_payload["release_gate"]["specialist_cascade_visible"] is True
    assert proof_payload["release_gate"]["has_specialist_evidence"] is True


def test_console_runtime_api_records_norllama_route_outcomes(test_app):
    first = test_app.post(
        "/api/v1/console-runtime/route-outcomes",
        json={
            "agent": "Housebot",
            "session": "housebot-codex",
            "host": "toy-box",
            "outcome": {
                "source": "local-execution",
                "status": "ok",
                "ok": True,
                "model": "qwen3-coder-next:q4_K_M",
                "endpoint": "https://llm.home.arpa",
                "worker_endpoint": "http://192.168.2.151:18151",
                "response_chars": 12,
                "input_tokens": 11,
                "output_tokens": 3,
                "total_tokens": 14,
                "reason": "response text returned",
            },
        },
    )
    assert first.status_code == 200
    event = first.json()["event"]
    assert event["event_type"] == "route.local-llm-outcome"
    assert event["category"] == "route"
    assert event["payload"]["selected_provider"] == "norllama"
    assert event["payload"]["selected_model"] == "qwen3-coder-next:q4_K_M"
    assert event["payload"]["attribution"]["worker_id"] == "spark-151"

    second = test_app.post(
        "/api/v1/console-runtime/route-outcomes",
        json={
            "agent": "Uplink",
            "session": "uplink-codex",
            "host": "networking-host",
            "outcome": {
                "source": "planner-preflight",
                "status": "timeout",
                "ok": False,
                "model": "gemma4:26b-a4b-it-q4_K_M",
                "endpoint": "https://llm.home.arpa",
                "upstream": "http://192.168.2.150:18151",
                "reason": "planner timed out",
            },
        },
    )
    assert second.status_code == 200

    response = test_app.get("/api/v1/console-runtime/route-outcomes")
    assert response.status_code == 200
    summary = response.json()
    assert summary["count"] >= 2
    assert summary["by_worker"]["spark-151"] >= 1
    assert summary["by_worker"]["spark-150"] >= 1
    gemma = next(
        item
        for item in summary["models"]
        if item["model"] == "gemma4:26b-a4b-it-q4_K_M"
    )
    assert gemma["cooldown"]["active"] is True
    assert gemma["cooldown"]["status"] == "timeout"

    route_summary = test_app.get("/api/v1/console-runtime/route-summary")
    assert route_summary.status_code == 200
    route_payload = route_summary.json()
    assert route_payload["route"]["by_provider"]["norllama"] >= 2
    assert route_payload["workers"]["by_id"]["spark-151"] >= 1


def test_console_runtime_api_appends_planner_receipt_event(test_app):
    seeded = _seed_runtime_job(test_app, job_id="job-visible-api-planner")

    response = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-planner/events",
        json={
            "event_type": "planner.receipt",
            "summary": "Norllama planner receipt accepted.",
            "payload": {
                "receipt_kind": "norllama_prefilter",
                "route": {"provider": "norllama", "capability": "planner"},
            },
            "visibility": "timeline",
            "artifacts": ["planner-receipt.json"],
        },
    )

    assert response.status_code == 200
    event = response.json()
    assert event["category"] == "planner"
    assert event["sequence"] > seeded["completed"]["sequence"]
    activity = test_app.get("/api/v1/console-runtime/jobs/job-visible-api-planner")
    assert activity.status_code == 200
    payload = activity.json()
    assert payload["job"]["artifacts"] == ["planner-receipt.json"]
    assert payload["latest_event"]["event_type"] == "planner.receipt"


def test_console_runtime_api_creates_norllama_planner_receipt(test_app, monkeypatch):
    from app.api.api_v1.routers import console_runtime

    class FakeCapabilities:
        def as_dict(self):
            return {
                "provider": "norllama",
                "models": ["planner-local"],
                "supports_tools": True,
                "metadata": {"tool_lanes": ["rerank", "ocr"]},
            }

    class FakeNorllamaAdapter:
        @property
        def capabilities(self):
            return FakeCapabilities()

    monkeypatch.setattr(console_runtime, "NorllamaModelAdapter", FakeNorllamaAdapter)
    _seed_runtime_job(test_app, job_id="job-visible-api-planner-create")

    response = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-planner-create/planner/receipts",
        json={
            "kind": "scout",
            "input_text": "Find the next runtime ownership slice.",
            "route_policy": {"provider": "norllama", "model": "planner-local"},
            "status": "accepted",
            "evidence_paths": ["scout-receipt.json"],
        },
    )

    assert response.status_code == 200
    event = response.json()
    assert event["event_type"] == "planner.receipt"
    assert event["category"] == "planner"
    assert event["payload"]["task_kind"] == "scout"
    assert event["payload"]["status"] == "accepted"
    assert event["payload"]["provider"] == "norllama"
    assert event["payload"]["capability"] == "scout"
    assert event["payload"]["route"]["model"] == "planner-local"
    assert event["payload"]["capabilities"]["models"] == ["planner-local"]

    activity = test_app.get(
        "/api/v1/console-runtime/jobs/job-visible-api-planner-create"
    )
    assert activity.status_code == 200
    payload = activity.json()
    assert payload["job"]["artifacts"] == ["scout-receipt.json"]
    assert payload["category_counts"]["planner"] == 1


def test_console_runtime_api_runs_one_dry_run_worker_step(test_app):
    created = test_app.post(
        "/api/v1/console-runtime/jobs",
        json={
            "job_id": "job-visible-api-run",
            "objective": "Let the runtime own a single execution step",
            "route_policy": {"provider": "norllama"},
        },
    )
    assert created.status_code == 200

    response = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-run/runs",
        json={
            "worker_id": "api-worker-test",
            "dry_run": True,
            "include_capabilities": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["status"] == "done"
    assert payload["model_result"]["provider"] == "runtime-dry-run"
    assert payload["snapshot"]["latest_event"]["event_type"] == "job.completed"
    assert payload["snapshot"]["category_counts"]["policy"] == 1
    assert payload["snapshot"]["category_counts"]["route"] == 1
    assert payload["snapshot"]["category_counts"]["planner"] == 1
    assert payload["snapshot"]["category_counts"]["model"] == 3
    assert payload["snapshot"]["category_counts"]["tool"] == 2


@pytest.mark.asyncio
async def test_console_runtime_api_run_endpoint_offloads_worker_to_thread(monkeypatch):
    from app.api.api_v1.routers import console_runtime

    calls = {"to_thread": 0, "run_once": 0}
    sessions = []

    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    class FakeUser:
        id = 123

    class FakeWorker:
        def __init__(self, store):
            self.store = store

        def run_once(self, worker_db, *, user_id, job_id, options):
            calls["run_once"] += 1
            assert worker_db is sessions[0]
            assert user_id == 123
            assert job_id == "job-threaded-run"
            assert options.worker_id == "api-threaded-worker"
            return {"job": {"job_id": job_id}, "threaded": True}

    async def fake_to_thread(fn):
        calls["to_thread"] += 1
        return fn()

    def fake_session_local():
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(console_runtime, "DbConsoleRuntimeWorker", FakeWorker)
    monkeypatch.setattr(console_runtime.db_session, "SessionLocal", fake_session_local)
    monkeypatch.setattr(console_runtime.asyncio, "to_thread", fake_to_thread)

    result = await console_runtime.run_console_runtime_job_once(
        "job-threaded-run",
        console_runtime.ConsoleRuntimeRunCreate(worker_id="api-threaded-worker"),
        current_user=FakeUser(),
        db=object(),
    )

    assert result == {"job": {"job_id": "job-threaded-run"}, "threaded": True}
    assert calls == {"to_thread": 1, "run_once": 1}
    assert len(sessions) == 1
    assert sessions[0].closed is True


def test_console_runtime_api_runs_continuous_goal_loop(test_app):
    created = test_app.post(
        "/api/v1/console-runtime/jobs",
        json={
            "job_id": "job-visible-api-goal-run",
            "objective": "Let the runtime keep working locally",
        },
    )
    assert created.status_code == 200

    response = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-goal-run/runs",
        json={
            "worker_id": "api-goal-test",
            "dry_run": True,
            "continuous": True,
            "max_steps": 2,
            "goal_phase_sequence": ["plan", "work", "verify"],
            "cloud_token_budget": 0,
            "include_capabilities": False,
            "metadata": {"source": "api-test"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["continuous"] is True
    assert payload["steps_completed"] == 2
    assert payload["stop_reason"] == "done"
    assert [step["phase"] for step in payload["steps"]] == ["plan", "work"]
    assert [step["task_kind"] for step in payload["steps"]] == ["plan", "chat"]
    assert payload["job"]["status"] == "done"
    assert payload["usage"]["cloud_tokens"] == 0
    assert payload["snapshot"]["category_counts"]["goal"] == 4
    assert payload["snapshot"]["category_counts"]["route"] == 2
    assert payload["snapshot"]["route_summary"]["cloud_evidence_count"] == 0


def test_console_runtime_api_exposes_worker_status(test_app, monkeypatch):
    from app.api.api_v1.routers import console_runtime
    from app.services.console_runtime.supervisor import LIVE_EXECUTION_CONFIRMATION

    monkeypatch.setattr(
        console_runtime.console_runtime_worker_service,
        "config_payload",
        lambda: {
            "enabled": False,
            "dry_run": True,
            "live_execution_enabled": False,
            "tick_seconds": 5.0,
            "batch_size": 1,
            "worker_id": "runtime-background-worker",
        },
    )
    monkeypatch.setattr(
        console_runtime.norllama_mesh_cache,
        "get_mesh_overview",
        lambda timeout_seconds=2: {
            "schema": "norman.norllama.mesh.v1",
            "status": "ok",
            "worker_count": 3,
            "healthy_worker_count": 3,
        },
    )
    monkeypatch.setattr(
        console_runtime.norllama_warm_policy,
        "build_warm_policy",
        lambda mesh=None: {
            "schema": "norman.norllama.warm-policy.v1",
            "route_posture": "ready",
            "residency_posture": "warm",
            "residency": {"warm": 2, "warming": 0, "degraded": 0, "unavailable": 0},
            "counts": {"prefetch": 0},
            "route_guardrails": {
                "schema": "norman.norllama.route-guardrail-matrix.v1",
                "lanes": {
                    "planner": {
                        "status": "ready",
                        "eligible_count": 2,
                        "canary_count": 0,
                        "blocked_count": 1,
                    },
                    "canary": {
                        "status": "canary",
                        "eligible_count": 0,
                        "canary_count": 1,
                        "blocked_count": 0,
                    },
                },
            },
            "workers": [
                {
                    "id": "spark-150",
                    "role": "production",
                    "reachable": True,
                    "pressure": {"state": "normal"},
                    "desired_models": ["qwen3-coder:30b-a3b-q4_K_M"],
                    "prefetch_models": [],
                }
            ],
        },
    )
    monkeypatch.setattr(
        console_runtime,
        "latest_acceptance_gate",
        lambda: {
            "schema": "norman.tui-kernel-acceptance-gate.v1",
            "status": "pass",
            "passed": True,
            "pass_percent": 100.0,
        },
    )

    response = test_app.get("/api/v1/console-runtime/worker/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["enabled"] is False
    assert payload["config"]["dry_run"] is True
    assert payload["live_execution_confirmation"] == LIVE_EXECUTION_CONFIRMATION
    assert "runnable_count" in payload
    assert (
        payload["route_summary"]["schema"] == "norman.console-runtime.route-summary.v1"
    )
    assert payload["usage_ledger"]["schema"] == "norman.console-runtime.usage-ledger.v1"
    assert payload["local_first_kpi"]["schema"] == (
        "norman.console-runtime.local-first-kpi.v1"
    )
    assert payload["local_first_proof"]["schema"] == (
        "norman.console-runtime.local-first-proof.v1"
    )
    assert payload["tui_acceptance"]["schema"] == (
        "norman.tui-kernel-acceptance-gate.v1"
    )
    assert payload["tui_acceptance"]["status"] == "pass"
    assert payload["route_outcome_summary"]["schema"] == (
        "norman.norllama.route-outcomes-summary.v1"
    )
    assert payload["norllama"]["residency_posture"] == "warm"
    assert payload["norllama"]["healthy_worker_count"] == 3
    assert payload["norllama"]["lane_status"]["planner"]["eligible_count"] == 2
    assert payload["norllama"]["lane_status"]["canary"]["status"] == "canary"
    assert payload["norllama"]["workers"][0]["id"] == "spark-150"


def test_console_runtime_api_worker_control_requires_live_confirmation(test_app):
    response = test_app.post(
        "/api/v1/console-runtime/worker/control",
        json={"dry_run": False},
    )

    assert response.status_code == 400
    assert "Live runtime execution requires" in response.json()["detail"]


def test_console_runtime_api_run_live_without_approval_holds_job(test_app):
    created = test_app.post(
        "/api/v1/console-runtime/jobs",
        json={
            "job_id": "job-visible-api-live-hold",
            "objective": "Try one live runtime step without approval",
        },
    )
    assert created.status_code == 200

    response = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-live-hold/runs",
        json={"worker_id": "api-live-test", "dry_run": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["approval_required"] is True
    assert payload["model_result"] is None
    assert payload["job"]["status"] == "waiting_approval"
    assert payload["snapshot"]["latest_event"]["event_type"] == "job.approval_required"


def test_console_runtime_api_live_run_approval_requires_confirmation(test_app):
    created = test_app.post(
        "/api/v1/console-runtime/jobs",
        json={
            "job_id": "job-visible-api-live-confirm",
            "objective": "Try one approved live runtime step without the phrase",
        },
    )
    assert created.status_code == 200

    response = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-live-confirm/runs",
        json={
            "worker_id": "api-live-test",
            "dry_run": False,
            "live_execution_approved": True,
        },
    )

    assert response.status_code == 400
    assert "Live runtime execution requires" in response.json()["detail"]


def test_console_runtime_api_approval_resumes_waiting_job(test_app):
    from app.services.console_runtime.supervisor import LIVE_EXECUTION_CONFIRMATION

    created = test_app.post(
        "/api/v1/console-runtime/jobs",
        json={
            "job_id": "job-visible-api-approval-resume",
            "objective": "Resume a held runtime step",
        },
    )
    assert created.status_code == 200
    held = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-approval-resume/runs",
        json={"worker_id": "api-live-test", "dry_run": False},
    )
    assert held.status_code == 200
    assert held.json()["job"]["status"] == "waiting_approval"

    rejected_without_phrase = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-approval-resume/approval",
        json={"decision": "approve"},
    )
    assert rejected_without_phrase.status_code == 400

    approved = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-approval-resume/approval",
        json={
            "decision": "approve",
            "reason": "operator approved one step",
            "confirm_live_execution": LIVE_EXECUTION_CONFIRMATION,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "checkpointed"

    resumed = test_app.post(
        "/api/v1/console-runtime/jobs/job-visible-api-approval-resume/runs",
        json={
            "worker_id": "api-dry-resume-test",
            "dry_run": True,
            "include_capabilities": False,
        },
    )
    assert resumed.status_code == 200
    payload = resumed.json()
    assert payload["job"]["status"] == "done"
    assert payload["snapshot"]["category_counts"]["approval"] == 1


def test_console_runtime_api_accepts_configured_service_token(test_app, db):
    clear_auth_caches()
    previous_token = settings.console_runtime_service_token
    previous_email = settings.console_runtime_service_user_email
    saved_current_override = app.dependency_overrides.pop(get_current_user, None)
    saved_runtime_override = app.dependency_overrides.pop(
        get_console_runtime_user, None
    )
    settings.console_runtime_service_token = "runtime-service-token"
    settings.console_runtime_service_user_email = "runtime@example.com"
    try:
        if not get_user_by_email(db, email="runtime@example.com"):
            create_user(
                db,
                UserCreate(
                    email="runtime@example.com",
                    username="runtime_user",
                    password="pass123",
                ),
            )

        bad = test_app.get(
            "/api/v1/console-runtime/jobs",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert bad.status_code == 401

        headers = {"Authorization": "Bearer runtime-service-token"}
        created = test_app.post(
            "/api/v1/console-runtime/jobs",
            headers=headers,
            json={
                "job_id": "job-service-token",
                "objective": "Mirror TUI runtime activity",
            },
        )
        assert created.status_code == 200

        listed = test_app.get("/api/v1/console-runtime/jobs", headers=headers)
        assert listed.status_code == 200
        assert any(
            item["job_id"] == "job-service-token" for item in listed.json()["items"]
        )
    finally:
        clear_auth_caches()
        settings.console_runtime_service_token = previous_token
        settings.console_runtime_service_user_email = previous_email
        if saved_current_override is not None:
            app.dependency_overrides[get_current_user] = saved_current_override
        if saved_runtime_override is not None:
            app.dependency_overrides[get_console_runtime_user] = saved_runtime_override
