from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib import error as urllib_error
from urllib import request as urllib_request


def _load_agent_console_web(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOUSEBOT_CODEX_WEB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(tmp_path))
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_web.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_console_web_runtime_bridge_test", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_llm_url_does_not_duplicate_version_or_api_base(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.local_llm_url("https://llm.home.arpa/v1", "/v1/overview") == (
        "https://llm.home.arpa/v1/overview"
    )
    assert module.local_llm_url("https://llm.home.arpa/v1", "/api/overview") == (
        "https://llm.home.arpa/api/overview"
    )
    assert module.local_llm_url("http://local-llm:18151/api", "/api/tags") == (
        "http://local-llm:18151/api/tags"
    )


def test_status_snapshot_prefers_response_bound_runtime_job(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.write_text(module.LAST_PROMPT_PATH, "fresh prompt")
    module.write_last_response(
        "fresh local answer",
        console_runtime_job_id="turn-fresh-local",
        prompt="fresh prompt",
        source="test",
        updated_at=123,
    )
    module.write_text(module.LAST_ERROR_PATH, "")
    module.write_text(module.THREAD_ID_PATH, "")
    module.update_status_meta(
        pending=False,
        state="ok",
        status_message="Ready.",
        last_console_runtime_job_id="turn-stale-local",
    )

    monkeypatch.setattr(module, "recover_stale_prompt_state", lambda: None)
    monkeypatch.setattr(module, "capture_pane", lambda: "")
    monkeypatch.setattr(module, "service_status", lambda names: [])
    monkeypatch.setattr(module, "usage_snapshot", lambda thread_id="": {"totals": {}})
    monkeypatch.setattr(module, "load_draft_attachments", lambda: [])
    monkeypatch.setattr(module, "prompt_thread_alive", lambda: False)
    monkeypatch.setattr(module, "active_codex_process_alive", lambda: False)
    monkeypatch.setattr(module, "console_runtime_activity_snapshot", lambda: {})
    monkeypatch.setattr(module, "console_runtime_capabilities_snapshot", lambda: {})
    monkeypatch.setattr(
        module, "console_runtime_local_first_proof_snapshot", lambda: {}
    )
    monkeypatch.setattr(module, "local_llm_health_snapshot", lambda _model: {})
    monkeypatch.setattr(module, "local_llm_route_outcome_summary", lambda: {})
    monkeypatch.setattr(module, "bedrock_health_snapshot", lambda snapshot_at=0: {})
    monkeypatch.setattr(
        module, "host_pressure_guard_snapshot", lambda snapshot_at=0: {}
    )
    monkeypatch.setattr(module, "usage_accounting_tags", lambda: {})

    snapshot = module.current_snapshot()

    assert snapshot["last_response"] == "fresh local answer"
    assert snapshot["last_console_runtime_job_id"] == "turn-fresh-local"
    assert snapshot["last_response_console_runtime_job_id"] == "turn-fresh-local"
    assert snapshot["last_response_meta"]["source"] == "test"


def test_response_owner_meta_ignores_stale_response_hash(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.write_last_response(
        "first answer",
        console_runtime_job_id="turn-first",
        prompt="first prompt",
        source="test",
    )

    assert module.last_response_meta_for("first answer")["console_runtime_job_id"] == (
        "turn-first"
    )
    assert module.last_response_meta_for("second answer") == {}


def test_console_runtime_bridge_posts_audit_events(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_JOB_ID", "job-tui")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"event_id": "evt-test", "sequence": 7}).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    entry = module.normalize_audit_event(
        {
            "event_type": "tmux.send",
            "summary": "Sent raw text",
            "detail": "ls -la",
            "payload": {"message_preview": "ls -la"},
        }
    )

    module.mirror_audit_event_to_console_runtime(entry, background=False)

    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == (
        "http://norman.local/api/v1/console-runtime/jobs/job-tui/events"
    )
    assert timeout == module.CONSOLE_RUNTIME_TIMEOUT_SECONDS
    assert request.get_header("Authorization") == "Bearer runtime-token"
    payload = json.loads(request.data.decode())
    assert payload["event_type"] == "tool.tmux.send"
    assert payload["summary"] == "Sent raw text"
    assert payload["payload"]["original_event_type"] == "tmux.send"
    assert payload["payload"]["audit_event"]["payload"]["message_preview"] == "ls -la"


def test_console_runtime_token_can_resolve_from_norman_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("NORMAN_API_TOKEN", raising=False)
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://norman.local")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "keys-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET", "norman/runtime-token")
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"value": "brokered-runtime-token"}).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.CONSOLE_RUNTIME_TOKEN == "brokered-runtime-token"
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == "http://norman.local/v1/secrets/get"
    assert timeout == module.CONSOLE_RUNTIME_TIMEOUT_SECONDS
    assert request.get_header("Authorization") == "Bearer keys-token"
    payload = json.loads(request.data.decode())
    assert payload["name"] == "norman/runtime-token"
    assert payload["requester_id"] == "runtime-tui-bridge"
    assert payload["session_id"] == module.SESSION


def test_console_runtime_token_uses_default_norman_keys_secret_name(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("NORMAN_API_TOKEN", raising=False)
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_SECRET_NAME", raising=False)
    monkeypatch.delenv("NORMAN_KEYS_SECRET_NAME", raising=False)
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://norman.local")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "keys-token")
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"value": "default-brokered-token"}).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.CONSOLE_RUNTIME_TOKEN == "default-brokered-token"
    assert len(requests) == 1
    payload = json.loads(requests[0][0].data.decode())
    assert payload["name"] == "norman/console-runtime-token"


def test_console_runtime_token_retries_after_startup_resolution_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("NORMAN_API_TOKEN", raising=False)
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://norman.local")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "keys-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET", "norman/runtime-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN_RETRY_SECONDS", "0")
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url == "http://norman.local/v1/secrets/get":
            if (
                len(
                    [
                        item
                        for item, _timeout in requests
                        if item.full_url == request.full_url
                    ]
                )
                == 1
            ):
                raise TimeoutError("keys unavailable")
            return Response({"value": "brokered-runtime-token"})
        if request.full_url.endswith("/console-runtime/capabilities"):
            assert request.get_header("Authorization") == (
                "Bearer brokered-runtime-token"
            )
            return Response({"provider": "runtime"})
        return Response({})

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.CONSOLE_RUNTIME_TOKEN == ""

    capabilities = module.console_runtime_capabilities_snapshot(force=True)

    assert capabilities["provider"] == "runtime"
    assert module.CONSOLE_RUNTIME_TOKEN == "brokered-runtime-token"


def test_console_runtime_job_advertises_kernel_shadow_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel-shadow")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"job_id": "job-shadow"}).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    job_id = module.ensure_console_runtime_job(create=True)

    assert job_id == "job-shadow"
    assert module.tui_backend_snapshot() == {
        "backend": "kernel_shadow",
        "kernel_shadow": True,
        "turn_shadow": True,
        "kernel_execution": False,
        "kernel_primary": False,
        "kernel_owned_turn": False,
        "control_only": False,
        "execution_backend": "codex_direct",
    }
    assert len(requests) == 1
    request, _timeout = requests[0]
    payload = json.loads(request.data.decode())
    assert payload["route_policy"]["runtime"] == "shell"
    assert payload["route_policy"]["planner"] == "norllama"
    assert payload["route_policy"]["model_proxy"] == "norllama"
    assert payload["route_policy"]["tui_backend"] == "kernel_shadow"
    assert payload["route_policy"]["kernel_shadow"] is True
    assert payload["metadata"]["tui_backend"] == "kernel_shadow"
    assert payload["metadata"]["kernel_execution_enabled"] is False
    assert payload["authority_flags"]["kernel_shadow"] is True


def test_console_runtime_snapshot_disabled_without_api_base(monkeypatch, tmp_path):
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_API_BASE", raising=False)
    monkeypatch.delenv("NORMAN_API_BASE_URL", raising=False)
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.console_runtime_bridge_enabled() is False
    assert module.console_runtime_activity_snapshot() == {
        "backend": "codex_direct",
        "kernel_shadow": False,
        "turn_shadow": True,
        "kernel_execution": False,
        "kernel_primary": False,
        "kernel_owned_turn": False,
        "control_only": False,
        "execution_backend": "codex_direct",
        "enabled": False,
        "connected": False,
        "job_id": "",
        "events": [],
        "next_after": 0,
        "latest_event": None,
        "route_summary": {},
        "turn_shadow_job_id": "",
        "error": "",
    }


def test_console_runtime_startup_defer_skips_runtime_polling(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.CONSOLE_RUNTIME_STARTUP_DEFER_UNTIL = module.time.time() + 60
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        raise AssertionError("startup defer should not open runtime connection")

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    activity = module.console_runtime_activity_snapshot()
    capabilities = module.console_runtime_capabilities_snapshot()
    proof = module.console_runtime_local_first_proof_snapshot()
    outcomes = module.console_runtime_route_outcomes_summary()

    assert activity["connected"] is False
    assert activity["error"] == "runtime bridge startup jitter"
    assert capabilities["deferred"] is True
    assert proof["deferred"] is True
    assert outcomes["deferred"] is True
    assert requests == []


def test_console_runtime_proof_snapshots_fetch_runtime_contracts(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/console-runtime/capabilities"):
            return Response(
                {
                    "norllama": {
                        "specialist_lanes": {
                            "proof": {
                                "schema": "norman.norllama.specialist-proof.v1",
                                "lane_count": 10,
                                "production_ready_count": 9,
                            }
                        }
                    }
                }
            )
        if request.full_url.endswith(
            "/console-runtime/local-first-proof?limit=250&session_limit=20"
        ):
            return Response(
                {
                    "schema": "norman.console-runtime.local-first-proof.v1",
                    "totals": {
                        "specialist_evidence_count": 2,
                        "specialist_benchmark_fresh_count": 2,
                    },
                    "release_gate": {"specialist_proof_ready": True},
                }
            )
        return Response({})

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    capabilities = module.console_runtime_capabilities_snapshot(force=True)
    proof = module.console_runtime_local_first_proof_snapshot(force=True)

    assert capabilities["source"] == "/console-runtime/capabilities"
    assert capabilities["norllama"]["specialist_lanes"]["proof"]["schema"] == (
        "norman.norllama.specialist-proof.v1"
    )
    assert proof["source"] == "/console-runtime/local-first-proof"
    assert proof["totals"]["specialist_evidence_count"] == 2
    assert len(requests) == 2
    assert requests[0][0].get_header("Authorization") == "Bearer runtime-token"


def test_console_runtime_proof_snapshots_use_stale_backoff_after_timeout(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.CONSOLE_RUNTIME_PROOF_TTL_SECONDS = 0
    module.CONSOLE_RUNTIME_PROOF_BACKOFF_SECONDS = 60
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "norllama": {
                        "specialist_lanes": {
                            "proof": {
                                "schema": "norman.norllama.specialist-proof.v1",
                                "lane_count": 10,
                            }
                        }
                    }
                }
            ).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if len(requests) == 1:
            return Response()
        raise TimeoutError("runtime proof timeout")

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    first = module.console_runtime_capabilities_snapshot(force=True)
    second = module.console_runtime_capabilities_snapshot(force=True)
    third = module.console_runtime_capabilities_snapshot()

    assert first["norllama"]["specialist_lanes"]["proof"]["lane_count"] == 10
    assert second["stale"] is True
    assert second["error"] == "runtime proof timeout"
    assert third["stale"] is True
    assert third["error"] == "runtime proof timeout"
    assert len(requests) == 2


def test_console_runtime_turn_shadow_creates_per_turn_job(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_JOB_ID", "job-session")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/console-runtime/jobs"):
            payload = json.loads(request.data.decode())
            return Response({"job_id": payload["job_id"]})
        if request.full_url.endswith("/planner/receipts"):
            return Response({"event_type": "planner.receipt", "sequence": 2})
        if request.full_url.endswith("/events"):
            return Response({"event_type": "turn.started", "sequence": 3})
        return Response({})

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    prompt = (
        "Unlocked local routing check. Do not use tools. Given these service "
        "statuses: api=healthy, billing=unhealthy timeout, cache=healthy. "
        "Return one compact JSON object with keys unhealthy_service, evidence, "
        "and nonce. Use nonce value r-auto-norman-auto_route_local."
    )
    turn_plan = module.build_turn_plan_estimate(
        prompt=prompt,
        attachments=[],
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="auto",
        speed="balanced",
        detail=2,
        timeout_seconds=300,
        created_at=123,
    )
    shadow = module.ensure_console_runtime_turn_shadow_job(
        prompt=prompt,
        started_at=123,
        attachments=[],
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="auto",
        timeout_seconds=300,
        turn_plan=turn_plan,
        turn_envelope={"kind": "turn"},
        cost_route={"selected_runtime": "localllm", "route_source": "local_first"},
    )

    assert shadow["enabled"] is True
    assert shadow["job_id"].startswith("turn-")
    urls = [request.full_url for request, _timeout in requests]
    assert urls == [
        "http://norman.local/api/v1/console-runtime/jobs",
        f"http://norman.local/api/v1/console-runtime/jobs/{shadow['job_id']}/planner/receipts",
        f"http://norman.local/api/v1/console-runtime/jobs/{shadow['job_id']}/events",
    ]
    create_payload = json.loads(requests[0][0].data.decode())
    assert create_payload["objective"] == prompt
    assert "nonce value r-auto-norman-auto_route_local" in create_payload["objective"]
    assert "…" not in create_payload["objective"]
    assert create_payload["metadata"]["kind"] == "tui_turn_shadow"
    assert create_payload["metadata"]["source"] == "agent_console_web"
    assert create_payload["metadata"]["session_job_id"] == "job-session"
    assert create_payload["route_policy"]["runtime"] == "kernel_shadow"
    assert create_payload["route_policy"]["provider"] == "norllama"
    assert create_payload["route_policy"]["preferred_provider"] == "norllama"
    assert create_payload["route_policy"]["planner"] == "norllama"
    assert create_payload["route_policy"]["model_proxy"] == "norllama"
    assert create_payload["route_policy"]["turn_shadow"] is True
    assert create_payload["route_policy"]["kernel_execution_enabled"] is False
    assert create_payload["route_policy"]["kernel_execution_candidate"] is False
    assert create_payload["route_policy"]["continuous_goal_candidate"] is True
    assert create_payload["route_policy"]["goal_phase_sequence"] == [
        "plan",
        "work",
        "verify",
    ]
    assert create_payload["route_policy"]["cloud_token_budget"] == 0
    assert create_payload["route_policy"]["selected_runtime"] == "localllm"
    assert create_payload["metadata"]["kernel_execution_enabled"] is False
    assert create_payload["metadata"]["kernel_execution_candidate"] is False
    assert create_payload["metadata"]["continuous_goal_candidate"] is True
    assert create_payload["metadata"]["goal_phase_sequence"] == [
        "plan",
        "work",
        "verify",
    ]
    receipt_payload = json.loads(requests[1][0].data.decode())
    assert receipt_payload["include_capabilities"] is False
    assert receipt_payload["output"]["planner_role"] == "shadow_frontdoor"
    started_event = json.loads(requests[2][0].data.decode())
    assert started_event["event_type"] == "turn.started"
    assert started_event["payload"]["session_job_id"] == "job-session"
    assert started_event["payload"]["objective"] == prompt
    assert started_event["payload"]["objective_summary"] != prompt


def test_console_runtime_turn_shadow_can_mark_kernel_execution_candidate(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_JOB_ID", "job-session")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/console-runtime/jobs"):
            payload = json.loads(request.data.decode())
            return Response({"job_id": payload["job_id"]})
        if request.full_url.endswith("/planner/receipts"):
            return Response({"event_type": "planner.receipt", "sequence": 2})
        if request.full_url.endswith("/events"):
            return Response({"event_type": "turn.started", "sequence": 3})
        return Response({})

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    shadow = module.ensure_console_runtime_turn_shadow_job(
        prompt="Use the local runtime to plan and verify this TUI task.",
        started_at=456,
        attachments=[],
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="auto",
        timeout_seconds=300,
        turn_plan={"goal": "local first"},
        turn_envelope={"kind": "turn"},
        cost_route={"selected_runtime": "localllm", "route_source": "local_first"},
    )

    assert module.tui_backend_snapshot()["kernel_execution"] is True
    assert module.tui_backend_snapshot()["kernel_primary"] is True
    assert shadow["enabled"] is True
    create_payload = json.loads(requests[0][0].data.decode())
    assert create_payload["authority_flags"]["kind"] == "tui_turn_shadow"
    assert create_payload["authority_flags"]["kernel_execution_enabled"] is True
    assert create_payload["authority_flags"]["kernel_execution_candidate"] is True
    assert create_payload["route_policy"]["provider"] == "norllama"
    assert create_payload["route_policy"]["preferred_provider"] == "norllama"
    assert create_payload["route_policy"]["kernel_execution_enabled"] is True
    assert create_payload["route_policy"]["kernel_execution_candidate"] is True
    assert create_payload["route_policy"]["continuous_goal_candidate"] is True
    assert create_payload["route_policy"]["cloud_token_budget"] == 0
    assert create_payload["metadata"]["kernel_execution_enabled"] is True
    assert create_payload["metadata"]["kernel_execution_candidate"] is True


def test_kernel_primary_runtime_can_return_visible_response(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.5:32b-q4_K_M")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(
        running_console_runtime_job_id="turn-kernel-primary",
        running_cost_route={
            "selected_runtime": "localllm",
            "selected_model": "qwen3.5:32b-q4_K_M",
        },
    )
    requests = []

    def fake_json_request(method, path, payload=None, timeout_seconds=None):
        requests.append((method, path, payload or {}, timeout_seconds))
        assert path.endswith("/console-runtime/jobs/turn-kernel-primary/runs")
        return {
            "continuous": True,
            "stop_reason": "done",
            "steps_completed": 3,
            "usage": {"local_tokens": 42, "cloud_tokens": 0},
            "last_result": {
                "model_result": {
                    "provider": "norllama",
                    "model": "qwen3.5:32b-q4_K_M",
                    "text": "Verified local answer.",
                    "usage": {"input_tokens": 30, "output_tokens": 12},
                }
            },
            "snapshot": {
                "events": [
                    {
                        "event_type": "model.delta",
                        "payload": {"text": "Plan locally."},
                    },
                    {
                        "event_type": "goal.step_completed",
                        "payload": {"phase": "plan"},
                    },
                    {
                        "event_type": "model.delta",
                        "payload": {"text": "Do the local work."},
                    },
                    {
                        "event_type": "goal.step_completed",
                        "payload": {"phase": "work"},
                    },
                    {
                        "event_type": "model.delta",
                        "payload": {"text": "Verified local answer."},
                    },
                    {
                        "event_type": "goal.step_completed",
                        "payload": {"phase": "verify"},
                    },
                ]
            },
        }

    monkeypatch.setattr(module, "_console_runtime_json_request", fake_json_request)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    response, error, _thread_id, usage = module._execute_prompt_runtime(
        "Summarize these notes locally.",
        "balanced",
        2,
        [],
        "localllm",
        "qwen3.5:32b-q4_K_M",
        300,
        service_tier="default",
        job_budget="5m",
    )

    assert error == ""
    assert response == "Verified local answer."
    assert usage["runtime"] == "localllm"
    assert usage["route_execution"] == "console_runtime_kernel"
    assert usage["provider_surface"] == "norllama"
    assert usage["kernel_cloud_tokens"] == 0
    assert requests[0][0] == "POST"
    assert requests[0][2]["dry_run"] is False
    assert requests[0][2]["continuous"] is True
    assert requests[0][2]["max_steps"] == 5
    assert requests[0][2]["cloud_token_budget"] == 0
    assert requests[0][2]["model"] == "qwen3.5:32b-q4_K_M"
    assert requests[0][2]["route_policy"]["verifier_can_stop"] is True
    assert requests[0][2]["route_policy"]["model_timeout_seconds"] == 175.0
    assert requests[0][2]["metadata"]["provider_timeout_seconds"] == 175.0
    assert requests[0][2]["confirm_live_execution"] == "ENABLE LIVE RUNTIME"


def test_kernel_primary_model_uses_local_candidates_after_health_gate(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(
        running_cost_route={
            "selected_runtime": "codex",
            "selected_model": "gpt-5.4",
            "route_source": "local_first_health_gate",
            "local_guardrail_candidates": ["qwen3.6:35b-a3b-q4_K_M"],
            "local_candidates": ["qwen3.6:35b-a3b-q4_K_M"],
            "local_model": "llama3.2:3b",
        },
    )

    assert (
        module.console_runtime_kernel_primary_model("codex", "gpt-5.4")
        == "qwen3.6:35b-a3b-q4_K_M"
    )
    assert module.local_llm_execution_candidate_models("llama3.2:3b")[0] == (
        "llama3.2:3b"
    )
    assert "qwen3.6:35b-a3b-q4_K_M" in module.local_llm_execution_candidate_models(
        "llama3.2:3b"
    )


def test_kernel_primary_runtime_surfaces_model_adapter_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_OWNED_TURN", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(running_console_runtime_job_id="turn-kernel-primary")

    def fake_json_request(method, path, payload=None, timeout_seconds=None):
        assert method == "POST"
        assert path.endswith("/console-runtime/jobs/turn-kernel-primary/runs")
        assert payload["route_policy"]["allow_cloud_proxy"] is False
        return {
            "job": {
                "job_id": "turn-kernel-primary",
                "status": "failed",
                "last_error": "HTTPSConnectionPool read timed out",
            },
            "model_result": None,
            "model_failed": True,
            "failure_class": "model_adapter_failed",
            "error": "llm.home.arpa read timed out",
            "snapshot": {"events": []},
        }

    monkeypatch.setattr(module, "_console_runtime_json_request", fake_json_request)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    response, error, _thread_id, usage = module._execute_console_runtime_kernel_prompt(
        "Canary only. Reply exactly: DONE.",
        "fast",
        1,
        [],
        "localllm",
        "qwen3.5:32b-q4_K_M",
        300,
        service_tier="default",
        job_budget="5m",
    )

    assert response == ""
    assert error == "llm.home.arpa read timed out"
    assert usage["success"] is False
    assert usage["output_shape"] == "error"
    assert usage["kernel_model_failed"] is True
    assert usage["kernel_failure_class"] == "model_adapter_failed"
    assert "llm.home.arpa read timed out" in usage["kernel_failure_reason"]


def test_kernel_primary_literal_response_uses_single_step_final_delta(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_OWNED_TURN", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(running_console_runtime_job_id="turn-kernel-primary")
    requests = []

    def fake_json_request(method, path, payload=None, timeout_seconds=None):
        requests.append((method, path, payload or {}, timeout_seconds))
        assert path.endswith("/console-runtime/jobs/turn-kernel-primary/runs")
        return {
            "continuous": True,
            "stop_reason": "done",
            "steps_completed": 5,
            "usage": {"local_tokens": 965, "cloud_tokens": 0},
            "last_result": {
                "model_result": {
                    "provider": "norllama",
                    "model": "gemma3:1b",
                    "text": "DONE local visible",
                    "usage": {"input_tokens": 149, "output_tokens": 4},
                }
            },
            "snapshot": {
                "events": [
                    {
                        "event_type": "model.delta",
                        "payload": {
                            "text": (
                                "Okay, here is a concise plan.\n\n"
                                "**Done local visible**\n\n"
                                "* **Plan:** Capture route receipt evidence.\n"
                                "* **Needed Evidence:** TUI route."
                            )
                        },
                    },
                    {
                        "event_type": "goal.step_completed",
                        "payload": {"phase": "plan"},
                    },
                    {
                        "event_type": "model.delta",
                        "payload": {
                            "text": (
                                "Done when:\n"
                                "- The visible TUI turn has recorded route evidence."
                            )
                        },
                    },
                    {
                        "event_type": "goal.step_completed",
                        "payload": {"phase": "work"},
                    },
                    {
                        "event_type": "model.delta",
                        "payload": {"text": "DONE local visible"},
                    },
                    {
                        "event_type": "goal.step_completed",
                        "payload": {"phase": "verify"},
                    },
                ]
            },
        }

    monkeypatch.setattr(module, "_console_runtime_json_request", fake_json_request)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    response, error, _thread_id, usage = module._execute_console_runtime_kernel_prompt(
        "Canary only. Reply exactly: DONE local visible.",
        "fast",
        1,
        [],
        "localllm",
        "gemma3:1b",
        120,
        service_tier="default",
        job_budget="2m",
    )

    payload = requests[0][2]
    assert response == "DONE local visible"
    assert error == ""
    assert payload["max_steps"] == 1
    assert payload["goal_phase_sequence"] == ["literal_response"]
    assert payload["planner_kind"] == "literal_response"
    assert payload["max_output_tokens"] == 96
    assert payload["route_policy"]["task_kind"] == "literal_response"
    assert payload["route_policy"]["output_shape_expected"] == "literal_response"
    assert payload["metadata"]["task_kind"] == "literal_response"
    assert usage["success"] is True
    assert usage["output_shape"] == "complete"
    assert usage["kernel_local_tokens"] == 965
    assert usage["kernel_cloud_tokens"] == 0


def test_kernel_primary_runtime_falls_back_to_codex(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(running_console_runtime_job_id="turn-kernel-primary")

    def fake_json_request(*_args, **_kwargs):
        raise module.urllib_error.URLError("runtime offline")

    def fake_codex(*_args, **_kwargs):
        return (
            "Cloud fallback answer.",
            "",
            "thread-fallback",
            {"runtime": "codex", "model": "gpt-test", "total_tokens": 9},
        )

    monkeypatch.setattr(module, "_console_runtime_json_request", fake_json_request)
    monkeypatch.setattr(module, "_execute_codex_prompt", fake_codex)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    response, error, thread_id, usage = module._execute_prompt_runtime(
        "Summarize these notes locally.",
        "balanced",
        2,
        [],
        "codex",
        "gpt-test",
        300,
        service_tier="default",
        job_budget="5m",
    )

    assert response == "Cloud fallback answer."
    assert error == ""
    assert thread_id == "thread-fallback"
    assert usage["runtime"] == "codex"


def test_kernel_owned_turn_blocks_codex_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_OWNED_TURN", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(running_console_runtime_job_id="turn-kernel-primary")

    def fake_json_request(*_args, **_kwargs):
        raise module.urllib_error.URLError("runtime offline")

    def fake_codex(*_args, **_kwargs):
        raise AssertionError("kernel-owned turn must not call Codex fallback")

    monkeypatch.setattr(module, "_console_runtime_json_request", fake_json_request)
    monkeypatch.setattr(module, "_execute_codex_prompt", fake_codex)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    response, error, _thread_id, usage = module._execute_prompt_runtime(
        "Summarize these notes locally.",
        "balanced",
        2,
        [],
        "codex",
        "gpt-test",
        300,
        service_tier="default",
        job_budget="5m",
    )

    assert response == ""
    assert "No Codex/cloud fallback was used" in error
    assert "runtime offline" in error
    assert usage["runtime"] == "localllm"
    assert usage["route_execution"] == "console_runtime_kernel"
    assert usage["kernel_owned_turn"] is True
    assert usage["kernel_failure_class"] == "URLError"
    assert usage["success"] is False


def test_kernel_primary_reports_turn_job_create_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    monkeypatch.setattr(
        module,
        "ensure_console_runtime_turn_shadow_job",
        lambda **_kwargs: {
            "enabled": True,
            "job_id": "",
            "status": "error",
            "error": "bridge create timeout",
        },
    )

    response, error, _thread_id, usage = module._execute_console_runtime_kernel_prompt(
        "Summarize these notes locally.",
        "balanced",
        2,
        [],
        "codex",
        "gpt-test",
        300,
        service_tier="default",
        job_budget="5m",
    )

    assert response == ""
    assert "did not create a turn job" in error
    assert "Turn shadow status: error" in error
    assert "bridge create timeout" in error
    assert usage["route_execution"] == "console_runtime_kernel"
    assert usage["kernel_failure_class"] == "job_create_failed"
    assert usage["output_shape"] == "job_create_failed"
    assert usage["success"] is False


def test_kernel_workspace_preflight_runs_before_codex_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(
        running_console_runtime_job_id="turn-kernel-preflight",
        running_cost_route={"selected_runtime": "localllm"},
    )
    requests = []
    codex_prompts = []

    def fake_json_request(method, path, payload=None, timeout_seconds=None):
        requests.append((method, path, payload or {}, timeout_seconds))
        assert path.endswith("/console-runtime/jobs/turn-kernel-preflight/runs")
        return {
            "continuous": True,
            "stop_reason": "max_steps",
            "steps_completed": 1,
            "snapshot": {
                "events": [
                    {
                        "event_type": "shell.output",
                        "payload": {
                            "invocation_id": "worker:job:shell:1",
                            "stream": "stdout",
                            "text": "/home/kristopher/code/norman\n",
                        },
                    },
                    {
                        "event_type": "shell.completed",
                        "payload": {
                            "invocation_id": "worker:job:shell:1",
                            "command": "pwd",
                            "returncode": 0,
                            "output_preview": "/home/kristopher/code/norman",
                        },
                    },
                ]
            },
        }

    def fake_codex(prompt, *_args, **_kwargs):
        codex_prompts.append(prompt)
        return (
            "Cloud fallback used preflight.",
            "",
            "thread-fallback",
            {"runtime": "codex", "model": "gpt-test", "total_tokens": 9},
        )

    monkeypatch.setattr(module, "_console_runtime_json_request", fake_json_request)
    monkeypatch.setattr(module, "_execute_codex_prompt", fake_codex)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    response, error, thread_id, usage = module._execute_prompt_runtime(
        "Fix this repo test failure.",
        "balanced",
        2,
        [],
        "codex",
        "gpt-test",
        300,
        service_tier="default",
        job_budget="5m",
    )

    assert response == "Cloud fallback used preflight."
    assert error == ""
    assert thread_id == "thread-fallback"
    assert usage["runtime"] == "codex"
    assert len(requests) == 1
    payload = requests[0][2]
    assert payload["dry_run"] is False
    assert payload["complete"] is False
    assert payload["continuous"] is True
    assert payload["cloud_token_budget"] == 0
    assert payload["goal_phase_sequence"] == ["preflight"]
    assert payload["planner_kind"] == "shell"
    assert payload["route_policy"]["kernel_workspace_preflight"] is True
    assert "pwd" in payload["route_policy"]["kernel_preflight_commands"]
    assert any(
        command.startswith("rg --files")
        for command in payload["route_policy"]["kernel_preflight_commands"]
    )
    assert codex_prompts
    assert "Norman kernel read-only workspace preflight evidence" in codex_prompts[0]
    assert "/home/kristopher/code/norman" in codex_prompts[0]
    assert "Do not assume mutation approval" in codex_prompts[0]


def test_console_runtime_audit_mirrors_to_active_turn_shadow(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_JOB_ID", "job-session")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"event_id": "evt"}).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    module.update_status_meta(running_console_runtime_job_id="turn-shadow-1")

    entry = module.normalize_audit_event(
        {
            "event_type": "planner.local-preflight",
            "summary": "Norllama planner preflight completed.",
            "detail": "cloud_needed=no",
        }
    )
    module.mirror_audit_event_to_console_runtime(entry, background=False)

    assert [request.full_url for request, _timeout in requests] == [
        "http://norman.local/api/v1/console-runtime/jobs/job-session/events",
        "http://norman.local/api/v1/console-runtime/jobs/turn-shadow-1/events",
    ]
    payload = json.loads(requests[1][0].data.decode())
    assert payload["payload"]["original_event_type"] == "planner.local-preflight"
    assert payload["summary"] == "Norllama planner preflight completed."


def test_local_llm_route_outcome_mirrors_to_console_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_CODEX_AGENT_NAME", "Housebot")
    monkeypatch.setenv("NORMAN_CODEX_SESSION", "housebot-codex")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"event": {"event_type": "route.local-llm-outcome"}}
            ).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    module.mirror_local_llm_route_outcome_to_console_runtime(
        {
            "source": "local-execution",
            "status": "ok",
            "ok": True,
            "model": "qwen3-coder-next:q4_K_M",
            "endpoint": "https://llm.home.arpa",
            "worker_endpoint": "http://192.168.2.151:18151",
            "reason": "response text returned",
        },
        background=False,
    )

    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == (
        "http://norman.local/api/v1/console-runtime/route-outcomes"
    )
    assert timeout == module.CONSOLE_RUNTIME_TIMEOUT_SECONDS
    assert request.get_header("Authorization") == "Bearer runtime-token"
    payload = json.loads(request.data.decode())
    assert payload["source"] == "agent_console_web"
    assert payload["agent"] == "Housebot"
    assert payload["session"] == "housebot-codex"
    assert payload["outcome"]["model"] == "qwen3-coder-next:q4_K_M"
    assert payload["outcome"]["worker_endpoint"] == "http://192.168.2.151:18151"


def test_agent_console_web_accepts_norman_codex_env_prefix(monkeypatch, tmp_path):
    for key in (
        "HOUSEBOT_CODEX_SESSION",
        "HOUSEBOT_CODEX_WEB_PORT",
        "HOUSEBOT_CODEX_WEB_TOKEN",
        "HOUSEBOT_CODEX_AGENT_NAME",
        "HOUSEBOT_CODEX_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NORMAN_CODEX_SESSION", "norman-session")
    monkeypatch.setenv("NORMAN_CODEX_WEB_PORT", "9797")
    monkeypatch.setenv("NORMAN_CODEX_WEB_TOKEN", "norman-token")
    monkeypatch.setenv("NORMAN_CODEX_AGENT_NAME", "Norman")
    monkeypatch.setenv("NORMAN_CODEX_MODEL", "gpt-norman")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.SESSION == "norman-session"
    assert module.PORT == 9797
    assert module.TOKEN == "norman-token"
    assert module.AGENT_NAME == "Norman"
    assert module.MODEL == "gpt-norman"


def test_console_template_prefers_structured_runtime_activity():
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_web.py"
    ).read_text(encoding="utf-8")

    assert "configured_console_runtime = console_runtime_activity_snapshot()" in source
    assert '"runtime": configured_console_runtime' in source
    assert '"runtime_capabilities": configured_runtime_capabilities' in source
    assert '"local_first_proof": configured_local_first_proof' in source
    assert "function buildRuntimeActivityInsight(snapshot)" in source
    assert "function latestRuntimeEvent(snapshot)" in source
    assert "function runtimeRouteSummaryLine(runtime, snapshot = null)" in source
    assert "runtimeRouteSummaryLine(runtime, snapshot)" in source
    assert (
        "function effectiveRouteForSnapshot(snapshot = state.snapshot, live = null)"
        in source
    )
    assert (
        "function effectiveRouteSummaryLine(snapshot = state.snapshot, live = null)"
        in source
    )
    assert '"effective"' in source
    assert '"fallback"' in source
    assert "runtime.route_summary" in source
    assert "workers.by_id" in source
    assert "NORMAN_TUI_BACKEND" in source
    assert "kernel_shadow" in source
    assert (
        "Structured planner, policy, route, behavior, model, shell, and tool events"
        in source
    )


def test_profile_v2_args_use_profile_file_without_legacy_config(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CODEX_STANDARD_PROFILE_V2", "personal-bedrock")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.codex_profile_v2_config_args("default") == [
        module.CODEX_PROFILE_CONFIG_FLAG,
        "personal-bedrock",
    ]
    assert "-c" not in module.codex_profile_v2_config_args("default")


def test_bedrock_profile_routes_omit_openai_service_tier_config(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CODEX_STANDARD_PROFILE_V2", "personal-bedrock")
    monkeypatch.setenv("NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2", "bedrock-backup")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.service_tier_config_args("auto") == []
    assert module.service_tier_config_args("default") == []
    assert module.service_tier_config_args("bedrock-failover") == []


def test_profile_flag_uses_profile_v2_for_pre_0134_codex_with_both_flags(
    monkeypatch, tmp_path
):
    module = _load_agent_console_web(monkeypatch, tmp_path)

    def fake_run(args, **_kwargs):
        if args == [module.CODEX_BIN, "exec", "--help"]:
            return SimpleNamespace(stdout="--profile --profile-v2", stderr="")
        if args == [module.CODEX_BIN, "--version"]:
            return SimpleNamespace(stdout="codex-cli 0.133.0", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.resolve_codex_profile_config_flag() == "--profile-v2"


def test_profile_flag_uses_profile_for_0134_plus_codex_with_both_flags(
    monkeypatch, tmp_path
):
    module = _load_agent_console_web(monkeypatch, tmp_path)

    def fake_run(args, **_kwargs):
        if args == [module.CODEX_BIN, "exec", "--help"]:
            return SimpleNamespace(stdout="--profile --profile-v2", stderr="")
        if args == [module.CODEX_BIN, "--version"]:
            return SimpleNamespace(stdout="codex-cli 0.142.3", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.resolve_codex_profile_config_flag() == "--profile"


def test_launch_template_uses_profile_file_without_legacy_profile_config():
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_launch.sh"
    ).read_text(encoding="utf-8")

    assert 'CODEX_PROFILE_ARGS=("$CODEX_PROFILE_FLAG" "$STANDARD_PROFILE_V2")' in source
    assert 'profile=\\"$STANDARD_PROFILE_V2\\"' not in source
    assert (
        "else\n"
        "        CODEX_SERVICE_TIER_ARGS=(-c 'service_tier=\"default\"')\n"
        "    fi" in source
    )


def test_sync_template_checks_live_disk_version_parity():
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "sync_agent_console_template.py"
    ).read_text(encoding="utf-8")

    assert "def verify_ui_version_parity" in source
    assert "/api/version?token=" in source
    assert "version_url" in source
    assert "page_url" in source
    assert "verify_ui_version_parity(host, restart_scope_list)" in source
    assert "def sync_instance_codex_profile_files" in source
    assert "sync_instance_codex_profile_files(host, instance)" in source
    assert 'base_config = target_home / "config.toml"' in source


def test_localllm_runtime_accepts_small_text_models(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_MODEL", "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M"
    )
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_MODELS",
        "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M",
    )
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MIN_TEXT_B", "3")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_EXECUTION_ENABLED", "1")

    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.LOCAL_LLM_DEFAULT_MODEL == (
        "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M"
    )
    assert module.runtime_can_execute("localllm") is True
    assert module.RUNTIME_REGISTRY["localllm"]["execution"] == "active"


def test_localllm_runtime_rejects_legacy_qwen3_text_model(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_EXECUTION_ENABLED", "1")

    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module._qwen_below_floor("qwen3:8b") is True
    assert module._local_llm_model_allowed("qwen3:8b") is False
    assert module.LOCAL_LLM_DEFAULT_MODEL == "local-llm"
    assert module.runtime_can_execute("localllm") is True


def test_localllm_runtime_accepts_qwen35_plus_model(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.5:27b-q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.5:27b-q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_EXECUTION_ENABLED", "1")

    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module._qwen_below_floor("qwen3.5:27b-q4_K_M") is False
    assert module._local_llm_model_allowed("qwen3.5:27b-q4_K_M") is True
    assert module.LOCAL_LLM_DEFAULT_MODEL == "qwen3.5:27b-q4_K_M"
    assert module.runtime_can_execute("localllm") is True


def test_localllm_runtime_accepts_qwen3_coder_benchmark_lane(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3-coder:30b-a3b-q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3-coder:30b-a3b-q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_EXECUTION_ENABLED", "1")

    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module._qwen_below_floor("qwen3-coder:30b-a3b-q4_K_M") is False
    assert module._local_llm_model_allowed("qwen3-coder:30b-a3b-q4_K_M") is True
    assert "qwen3-coder:30b-a3b-q4_K_M" in module.local_llm_preferred_models()
    assert module.runtime_can_execute("localllm") is True


def test_localllm_lane_models_keep_benchmark_guardrails(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_MODELS",
        "qwen3.6:27b,gemma4:26b-a4b-it-q4_K_M,qwen3-coder:30b-a3b-q4_K_M",
    )
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert (
        module.local_llm_prompt_lane("Summarize these meeting notes into bullets.")
        == "summarizer"
    )
    assert module.local_llm_prompt_lane("Patch this repo test failure.") == "coder"
    assert module.local_llm_lane_models("summarizer")[:2] == [
        "qwen3.6:35b-a3b-q4_K_M",
        "qwen3.6:27b",
    ]
    assert module.local_llm_lane_models("coder")[:2] == [
        "qwen3.6:27b",
        "qwen3.6:35b-a3b-q4_K_M",
    ]
    assert module.local_llm_lane_models("canary")[:2] == [
        "gemma3:4b",
        "llama3.2:3b",
    ]


def test_localllm_health_defaults_to_benchmark_route_model(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_EXECUTION_ENABLED", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    calls = []

    def fake_probe(endpoint, model):
        calls.append((endpoint, model))
        return {
            "ok": True,
            "endpoint": endpoint,
            "model": model,
            "reason": "model advertised",
        }

    monkeypatch.setattr(module, "local_llm_probe_endpoint", fake_probe)

    snapshot = module.local_llm_health_snapshot(force=True)

    assert module.LOCAL_LLM_DEFAULT_MODEL == "qwen3.6:27b"
    assert module.LOCAL_LLM_ROUTE_DEFAULT_MODEL == "qwen3.6:27b"
    assert snapshot["model"] == "qwen3.6:27b"
    assert calls == [
        ("http://local-llm:18151", "qwen3.6:27b"),
    ]


def test_localllm_autosenses_norman_norllama_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("NORMAN_LOCAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_MODELS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_ENDPOINTS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_FRONTDOORS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_MODEL_ENDPOINTS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED", raising=False)

    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.LOCAL_LLM_DEFAULT_MODEL == "qwen3.6:27b"
    assert module.LOCAL_LLM_AUTOSENSE_ENABLED is True
    assert module.runtime_can_execute("localllm") is True
    assert module.local_llm_candidate_endpoints("qwen3.6:27b") == [
        "https://llm.home.arpa",
        "https://llm.knox.lollie.org",
    ]


def test_localllm_foreground_collapses_frontdoor_aliases(monkeypatch, tmp_path):
    monkeypatch.delenv("NORMAN_LOCAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_MODELS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_ENDPOINTS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_FRONTDOORS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_MODEL_ENDPOINTS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED", raising=False)
    monkeypatch.setenv("NORMAN_LOCAL_LLM_CALL_TIMEOUT_SECONDS", "360")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_SHORT_TIMEOUT_SECONDS", "120")

    module = _load_agent_console_web(monkeypatch, tmp_path)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        raise TimeoutError("front door timed out")

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    response, error, _thread_id, usage = module._execute_local_llm_prompt(
        "Canary check only: reply with two bullets.",
        "quick",
        1,
        [],
        timeout_seconds=4800,
        model="qwen3-coder-next:q4_K_M",
        service_tier="default",
        job_budget="quick",
    )

    assert response == ""
    assert "llm.home.arpa" in error
    assert "llm.knox.lollie.org" not in error
    assert calls == [("https://llm.home.arpa/api/chat", 120)]
    assert usage["provider_timeout_seconds"] == 120


def test_localllm_autosense_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("NORMAN_LOCAL_LLM_ENDPOINTS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_FRONTDOORS", raising=False)
    monkeypatch.delenv("NORMAN_LOCAL_LLM_MODEL_ENDPOINTS", raising=False)
    monkeypatch.setenv("NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED", "0")

    module = _load_agent_console_web(monkeypatch, tmp_path)

    assert module.LOCAL_LLM_AUTOSENSE_ENABLED is False
    assert module.local_llm_candidate_endpoints("llama3.2:3b") == []
    assert module.runtime_can_execute("localllm") is False


def test_literal_response_canary_stays_fast_read_only(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)
    prompt = "Canary only. Reply exactly: DONE local visible."

    recommendation = module.turn_control_recommendation(
        prompt,
        [],
        speed="quick",
        detail=1,
        job_budget="2m",
        optimization_mode="auto",
    )
    envelope = module.build_turn_control_envelope(
        prompt=prompt,
        attachments=[],
        turn_control=recommendation,
        runtime="localllm",
        model="gemma4:26b-a4b-it-q4_K_M",
        service_tier="auto",
        job_budget=recommendation["effective_job_budget"],
        speed=recommendation["effective_speed"],
        detail=recommendation["effective_detail"],
    )

    assert module.prompt_is_literal_response_request(prompt) is True
    assert module.route_receipt_requires_operator_approval(prompt) is False
    assert module.turn_control_mutation_risk(prompt) == "none"
    assert recommendation["workload"] == "literal_response"
    assert recommendation["effective_speed"] == "fast"
    assert recommendation["effective_detail"] == 1
    assert recommendation["effective_job_budget"] == "2m"
    assert envelope["operator_intent_class"] == "literal_response"
    assert envelope["authority_class"] == "read_only"
    assert envelope["mutation_risk"] == "none"
    assert envelope["budget"]["max_wall_seconds"] == 120
    assert "answer_from_current_state" in envelope["allowed_actions"]
    assert envelope["blocked_actions"] == []
    assert module.prompt_is_local_first_candidate(prompt) is True
    assert module.prompt_requires_cloud_or_tools(prompt) is False
    assert module.local_llm_prompt_lane(prompt) == "canary"


def test_literal_canary_allows_tiny_canary_model_without_lowering_general_floor(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3-coder-next:q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3-coder-next:q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_CANARY_MODELS", "gemma3:4b,gemma3:1b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    def fake_health(model):
        return {
            "ok": model == "gemma3:1b",
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised" if model == "gemma3:1b" else "not resident",
        }

    monkeypatch.setattr(module, "local_llm_health_snapshot", fake_health)

    decision = module.cost_route_decision_for_prompt(
        prompt="Canary only. Reply exactly: DONE local visible.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="2m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert module._local_llm_model_allowed("gemma3:1b") is False
    assert module._local_llm_model_allowed_for_lane("canary", "gemma3:1b") is True
    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "gemma3:1b"
    assert decision["local_lane"] == "canary"
    assert "gemma3:1b" in decision["local_candidates"]


def test_cost_route_prefers_local_for_safe_self_contained_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:11434",
            "reason": "model advertised",
            "mesh": {
                "schema": "norman.norllama.mesh.v1",
                "status": "ok",
                "healthy_worker_count": 1,
            },
        },
    )

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert decision["local_lane"] == "summarizer"
    assert decision["local_candidate_policy"] == "benchmark_lane_guardrail"
    assert decision["route_source"] == "local_first_policy"
    assert decision["charge_basis"] == "local_token_estimate"
    assert decision["local_mesh"]["healthy_worker_count"] == 1


def test_cost_route_keeps_service_status_matrix_local(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:11434",
            "reason": "model advertised",
        },
    )
    prompt = (
        "Unlocked local routing check. Do not use tools. Given these service "
        "statuses: api=healthy, billing=unhealthy timeout, cache=healthy. "
        "Return one compact JSON object with keys unhealthy_service, evidence, "
        "and nonce."
    )

    assert module.turn_control_mutation_risk(prompt) == "none"
    assert module.prompt_requires_cloud_or_tools(prompt) is False
    assert module.prompt_is_local_first_candidate(prompt) is True

    decision = module.cost_route_decision_for_prompt(
        prompt=prompt,
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert decision["route_source"] == "local_first_policy"
    assert decision["mutation_risk"] == "none"


def test_cost_route_keeps_route_diagnostic_local(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setenv("NORMAN_TUI_BACKEND", "kernel")
    monkeypatch.setenv("NORMAN_TUI_KERNEL_EXECUTION", "1")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_PLANNER_MODELS",
        "qwen3.6:35b-a3b-q4_K_M,qwen3.6:27b",
    )
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:11434",
            "reason": "model advertised",
        },
    )
    prompt = "why did that go to cloud? why not to our bedrock at least?"

    assert module.prompt_is_route_status_diagnostic(prompt) is True
    assert module.route_receipt_requested_action(prompt) == "status"
    assert module.turn_control_mutation_risk(prompt) == "none"
    assert module.prompt_requires_cloud_or_tools(prompt) is False
    assert module.prompt_is_local_first_candidate(prompt) is True
    assert module.console_runtime_kernel_primary_skip_reason(prompt, [], "codex") == ""

    decision = module.cost_route_decision_for_prompt(
        prompt=prompt,
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert decision["local_lane"] == "planner"
    assert decision["route_source"] == "local_first_policy"
    assert decision["requested_action"] == "status"
    assert decision["mutation_risk"] == "none"


def test_route_diagnostic_does_not_mask_mutating_order(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)
    prompt = "please fix the TUI route config and restart uplink"

    assert module.prompt_is_route_status_diagnostic(prompt) is False
    assert module.prompt_requires_cloud_or_tools(prompt) is True
    assert module.turn_control_mutation_risk(prompt) == "deploy_restart"


def test_cost_route_does_not_treat_negated_tools_as_tool_requirement(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3-coder-next:q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3-coder-next:q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )

    assert (
        module.prompt_requires_cloud_or_tools(
            "Summarize alpha beta gamma in two bullets. No tools or external actions."
        )
        is False
    )
    assert module.prompt_requires_cloud_or_tools("Run tests and summarize failures.")

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize alpha beta gamma in two bullets. No tools or external actions.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="quick",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["route_source"] == "local_first_policy"


def test_drift_flags_bulk_perplexity_work_as_scout_handoff(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assessment = module.assess_tui_drift(
        "Use Perplexity to scan 500 products at high velocity and gather evidence URLs."
    )

    assert assessment["summary"] == "Wrong interface"
    assert assessment["recommended_action"] == "handoff"
    assert assessment["handoff_target"] == "scout-agent-mcp"
    assert assessment["mission_drift"] == "wrong_interface"
    assert module.scout_handoff_guard_blocks(assessment) is True

    context = module.drift_assessment_prompt_context(assessment)
    assert "scout-agent-mcp" in context
    assert "wrong interface" in context.lower()


def test_drift_skips_scout_reroute_implementation_prompts(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)

    assessment = module.assess_tui_drift(
        "Add a wrong-interface reroute so this TUI intercepts Perplexity scan asks from other bots."
    )

    assert assessment["handoff_target"] == ""
    assert module.scout_handoff_guard_blocks(assessment) is False


def test_start_web_prompt_blocks_scout_handoff_without_mcp_token(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_SCOUT_AGENT_MCP_HTTP_URL", "http://scout.local:8797")
    monkeypatch.delenv("NORMAN_SCOUT_AGENT_MCP_HTTP_TOKEN", raising=False)
    monkeypatch.delenv("SCOUT_AGENT_MCP_HTTP_TOKEN", raising=False)
    module = _load_agent_console_web(monkeypatch, tmp_path)
    events = []

    monkeypatch.setattr(
        module, "append_audit_event", lambda **kwargs: events.append(kwargs) or {}
    )
    monkeypatch.setattr(
        module,
        "launch_prompt_worker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Scout handoff must not launch the Codex worker")
        ),
    )

    accepted, snapshot = module.start_web_prompt(
        "Use Perplexity to scan 500 products at high velocity and gather evidence URLs.",
        speed="balanced",
        detail=2,
        job_budget="5m",
    )

    assert accepted is False
    assert snapshot["pending"] is False
    assert snapshot["state"] == "handoff"
    assert "Wrong interface" in snapshot["status_message"]
    assert snapshot["drift_assessment"]["handoff_target"] == "scout-agent-mcp"
    handoff_event = next(
        event for event in events if event["event_type"] == "chat.scout-handoff"
    )
    assert handoff_event["severity"] == "warn"


def test_cost_route_uses_norllama_contract_guardrail_candidates(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    warm_policy = module.local_llm_warm_policy_from_payload(
        {
            "service": "norllama",
            "contracts": [
                {
                    "contract_id": "chat",
                    "aliases": ["general_chat"],
                    "default_model": "qwen3.6:35b-a3b-q4_K_M",
                    "dispatch": "unified_chat",
                    "status": "benchmark_backed",
                    "selection_method": "weighted_local_suite_score",
                    "best_weighted_score": 10.1,
                    "guardrail": "Keep exact facts behind a verifier.",
                },
                {
                    "contract_id": "code_risk",
                    "aliases": ["patch_risk"],
                    "default_model": "qwen3.6:27b",
                    "dispatch": "unified_chat",
                    "status": "benchmark_backed",
                    "selection_method": "weighted_local_suite_score",
                    "best_weighted_score": 1.2,
                },
            ],
        }
    )

    def fake_health(model):
        if model == "local-llm":
            return {
                "ok": True,
                "model": model,
                "endpoint": "http://local-llm:18151",
                "warm_policy": warm_policy,
            }
        return {
            "ok": model in {"qwen3.6:35b-a3b-q4_K_M", "qwen3.6:27b"},
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        }

    monkeypatch.setattr(module, "local_llm_health_snapshot", fake_health)

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert decision["local_candidate_policy"] == (
        "norllama_warm_policy_degraded_fallback"
    )
    assert decision["local_candidates"][:1] == ["qwen3.6:35b-a3b-q4_K_M"]
    assert decision["local_guardrail_candidates"] == ["qwen3.6:35b-a3b-q4_K_M"]
    assert decision["local_guardrail_lane"]["status"] == "prefetch_or_wait"


def test_cost_route_labels_first_class_norllama_warm_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    warm_policy = {
        "schema": "norllama.warm-policy.v1",
        "source": "/v1/warm-policy",
        "route_posture": "prefetch_or_wait",
        "route_guardrails": {
            "schema": "norman.norllama.route-guardrail-matrix.v1",
            "lanes": {
                "summarizer": {
                    "lane": "summarizer",
                    "status": "prefetch_or_wait",
                    "eligible_models": [
                        {
                            "model": "qwen3.6:35b-a3b-q4_K_M",
                            "authority": "preflight_or_draft",
                            "chat_candidate": True,
                        }
                    ],
                }
            },
        },
    }

    def fake_health(model):
        if model == "local-llm":
            return {
                "ok": True,
                "model": model,
                "endpoint": "http://local-llm:18151",
                "warm_policy": warm_policy,
            }
        return {
            "ok": model in {"qwen3.6:35b-a3b-q4_K_M", "qwen3.6:27b"},
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        }

    monkeypatch.setattr(module, "local_llm_health_snapshot", fake_health)

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert decision["local_candidate_policy"] == (
        "norllama_warm_policy_degraded_fallback"
    )
    assert decision["local_guardrail_lane"]["status"] == "prefetch_or_wait"


def test_cost_route_tries_next_local_model_when_default_unhealthy(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_MODELS",
        "qwen3.6:27b,qwen3.5:27b-q4_K_M,gemma4:26b-a4b-it-q4_K_M",
    )
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    def fake_health(model):
        if model == "qwen3.5:27b-q4_K_M":
            return {
                "ok": True,
                "model": model,
                "endpoint": "http://local-llm:18151",
                "reason": "model advertised",
            }
        return {
            "ok": False,
            "model": model,
            "endpoint": "",
            "reason": "model unavailable",
        }

    monkeypatch.setattr(module, "local_llm_health_snapshot", fake_health)

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.5:27b-q4_K_M"
    assert decision["local_lane"] == "summarizer"
    assert decision["local_candidates"][:3] == [
        "qwen3.6:35b-a3b-q4_K_M",
        "qwen3.6:27b",
        "qwen3.5:27b-q4_K_M",
    ]
    failed_models = {item["model"] for item in decision["local_candidate_failures"]}
    assert {"qwen3.6:35b-a3b-q4_K_M", "qwen3.6:27b"} <= failed_models


def test_cost_route_skips_recently_failed_local_model_cooldown(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ROUTE_COOLDOWN_SECONDS", "900")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.append_local_llm_route_outcome(
        source="test",
        status="empty-response",
        ok=False,
        model="qwen3.6:35b-a3b-q4_K_M",
        endpoint="",
        reason="empty smoke output",
    )

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:27b"
    assert decision["local_lane"] == "summarizer"
    assert decision["local_cooldowns"][0]["model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert decision["local_cooldowns"][0]["cooldown"]["status"] == "empty-response"
    assert decision["local_cooldowns"][0]["cooldown"]["scope"] == "local_tui"


def test_cost_route_ignores_old_adapter_empty_response_cooldown(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ROUTE_COOLDOWN_SECONDS", "900")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.append_local_llm_route_outcome(
        source="test",
        status="empty-response",
        ok=False,
        model="qwen3.6:35b-a3b-q4_K_M",
        endpoint="",
        adapter="openai-chat",
        reason="old response adapter returned only reasoning",
    )

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert "local_cooldowns" not in decision


def test_cost_route_uses_fleet_route_outcome_cooldown(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    recorded_at = module.now_ts()
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "schema": "norman.norllama.route-outcomes-summary.v1",
                    "count": 2,
                    "ok": 0,
                    "fail": 2,
                    "cooldown_seconds": 900,
                    "by_tui": {"Uplink": 2},
                    "by_worker": {"spark-150": 2},
                    "models": [
                        {
                            "model": "qwen3.6:35b-a3b-q4_K_M",
                            "ok": 0,
                            "fail": 2,
                            "last_status": "timeout",
                            "last_reason": "worker timed out",
                            "last_recorded_at": recorded_at,
                            "last_tui": "Uplink",
                            "last_worker_id": "spark-150",
                            "cooldown": {
                                "active": True,
                                "model": "qwen3.6:35b-a3b-q4_K_M",
                                "endpoint": "",
                                "status": "timeout",
                                "reason": "worker timed out",
                                "recorded_at": recorded_at,
                                "age_seconds": 10,
                                "remaining_seconds": 890,
                                "worker_id": "spark-150",
                            },
                        }
                    ],
                }
            ).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        assert request.full_url.startswith(
            "http://norman.local/api/v1/console-runtime/route-outcomes?"
        )
        assert request.get_header("Authorization") == "Bearer runtime-token"
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert len(requests) == 1
    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:27b"
    assert decision["local_lane"] == "summarizer"
    assert decision["fleet_route_outcomes"]["by_worker"] == {"spark-150": 2}
    cooldown = decision["local_cooldowns"][0]["cooldown"]
    assert cooldown["source"] == "console_runtime"
    assert cooldown["scope"] == "fleet"
    assert cooldown["last_tui"] == "Uplink"
    assert cooldown["last_worker_id"] == "spark-150"


def test_cost_route_ignores_unavailable_fleet_route_outcomes(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    def fake_urlopen(request, timeout):
        raise urllib_error.URLError("offline")

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )

    decision = module.cost_route_decision_for_prompt(
        prompt="Summarize the following notes into three bullets: alpha beta gamma.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert decision["local_lane"] == "summarizer"
    assert "local_cooldowns" not in decision
    assert "fleet_route_outcomes" not in decision


def test_cost_route_keeps_cloud_for_mutating_work(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:11434",
        },
    )

    decision = module.cost_route_decision_for_prompt(
        prompt="Fix the deployment, patch the code, and run tests.",
        attachments=[],
        relay_callback=None,
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        job_budget="5m",
        optimization_mode="",
        route_lock=False,
        requested_runtime="codex",
        requested_model=module.MODEL,
        requested_service_tier="default",
    )

    assert decision["selected_runtime"] == "codex"
    assert "mutation risk" in decision["reason"]


def _specialist_warm_policy(status: str = "ready"):
    def lane(name, model):
        return {
            "lane": name,
            "status": status,
            "eligible_models": [
                {
                    "model": model,
                    "authority": "preflight_or_draft",
                    "chat_candidate": True,
                }
            ],
        }

    return {
        "schema": "norllama.warm-policy.v1",
        "source": "/v1/warm-policy",
        "route_posture": "ready" if status == "ready" else "prefetch_or_wait",
        "residency_posture": "warm" if status == "ready" else "cold",
        "route_guardrails": {
            "schema": "norman.norllama.route-guardrail-matrix.v1",
            "source": "/v1/warm-policy",
            "lanes": {
                "planner": lane("planner", "planner-local"),
                "filter": lane("filter", "filter-local"),
                "summarizer": lane("summarizer", "summary-local"),
                "verifier": lane("verifier", "verify-local"),
            },
        },
    }


def test_context_preflight_uses_norllama_planner_for_cloud_turn(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    events = []
    calls = []

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )
    monkeypatch.setattr(
        module, "append_audit_event", lambda **kwargs: events.append(kwargs) or {}
    )

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(
            {
                "endpoint": endpoint,
                "model": model,
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
                "max_output_tokens": max_output_tokens,
                "num_ctx": num_ctx,
            }
        )
        return (
            {
                "response": json.dumps(
                    {
                        "route": "local_plan",
                        "cloud_needed": False,
                        "safe_local_answer_possible": True,
                        "next_local_steps": ["summarize the prompt locally"],
                        "risk": "low",
                    }
                ),
                "prompt_eval_count": 12,
                "eval_count": 8,
            },
            "http://local-llm:18151/api/generate",
            "ollama-generate",
        )

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    context = module.context_preflight_prompt_context(
        "Summarize these notes before deciding whether cloud execution is needed.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert "Norllama planner preflight" in context
    assert "cloud_needed=no" in context
    assert "safe_local_answer_possible=yes" in context
    assert "qwen3.6:35b-a3b-q4_K_M" in context
    assert calls[0]["model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert (
        calls[0]["max_output_tokens"]
        == module.LOCAL_PLANNER_PREFLIGHT_MAX_OUTPUT_TOKENS
    )
    accounting = module.take_latest_context_preflight_accounting("codex", module.MODEL)
    assert accounting["local_preflight_used"] is True
    assert accounting["local_preflight_status"] == "ok"
    assert accounting["local_preflight_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert accounting["local_preflight_tokens"] == 20
    assert accounting["local_preflight_candidate_lane"] == "planner"
    assert accounting["local_preflight_candidate_policy"] == "benchmark_lane_guardrail"
    assert accounting["local_preflight_failure_class"] == "ok"
    assert accounting["local_preflight_receipt"]["schema"] == (
        "norman.tui.local-preflight-receipt.v1"
    )
    assert accounting["local_preflight_receipt"]["local_tokens"] == 20
    assert accounting["cloud_tokens_avoided_floor"] == 0
    planner_event = next(
        event for event in events if event["event_type"] == "planner.local-preflight"
    )
    assert planner_event["payload"]["planner"]["used"] is True
    assert planner_event["payload"]["planner"]["receipt"]["failure_class"] == "ok"


def test_context_preflight_runs_ready_norllama_specialists(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_SPECIALIST_PIPELINE_MAX_EXECUTIONS", "2")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    warm_policy = _specialist_warm_policy("ready")
    events = []
    calls = []

    def fake_health(model):
        payload = {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        }
        if model == "local-llm":
            payload["warm_policy"] = warm_policy
        return payload

    monkeypatch.setattr(module, "local_llm_health_snapshot", fake_health)
    monkeypatch.setattr(
        module, "append_audit_event", lambda **kwargs: events.append(kwargs) or {}
    )

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(
            {
                "model": model,
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
                "max_output_tokens": max_output_tokens,
            }
        )
        if model == "planner-local":
            response = {
                "route": "local_plan",
                "cloud_needed": False,
                "safe_local_answer_possible": True,
                "next_local_steps": ["summarize locally first"],
                "risk": "low",
            }
            prompt_tokens, output_tokens = 12, 8
        elif model == "filter-local":
            response = {
                "route": "local_filter",
                "cloud_needed": False,
                "safe_local_answer_possible": True,
                "next_local_steps": ["safe summarization lane"],
                "risk": "low",
            }
            prompt_tokens, output_tokens = 5, 5
        else:
            response = {
                "route": "local_summary",
                "cloud_needed": False,
                "safe_local_answer_possible": True,
                "next_local_steps": ["draft concise bullets locally"],
                "risk": "low",
            }
            prompt_tokens, output_tokens = 7, 8
        return (
            {
                "response": json.dumps(response),
                "prompt_eval_count": prompt_tokens,
                "eval_count": output_tokens,
            },
            "http://local-llm:18151/api/generate",
            "ollama-generate",
        )

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    context = module.context_preflight_prompt_context(
        "Summarize these notes before deciding whether cloud execution is needed.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert [call["model"] for call in calls] == [
        "planner-local",
        "filter-local",
        "summary-local",
    ]
    assert "Norllama planner preflight" in context
    assert "Norllama specialist pipeline: 2/4 local specialist stages ran" in context
    accounting = module.take_latest_context_preflight_accounting("codex", module.MODEL)
    assert accounting["local_preflight_used"] is True
    assert accounting["local_preflight_tokens"] == 20
    assert accounting["local_preflight_candidate_policy"] == "norllama_warm_policy"
    assert accounting["local_preflight_warm_policy_source"] == "/v1/warm-policy"
    assert accounting["local_specialist_used"] is True
    assert accounting["local_specialist_status"] == "ok"
    assert accounting["local_specialist_stage_count"] == 4
    assert accounting["local_specialist_executed_count"] == 2
    assert accounting["local_specialist_ready_count"] == 3
    assert accounting["local_specialist_tokens"] == 25
    assert accounting["local_specialist_warm_policy_source"] == "/v1/warm-policy"
    assert accounting["local_specialist_route_posture"] == "ready"
    assert accounting["cloud_preflight_net_token_delta_estimate"] == -45
    receipt = accounting["local_specialist_receipt"]
    assert receipt["schema"] == "norman.tui.local-specialist-pipeline.v1"
    assert receipt["execution_policy"] == "ready_only"
    assert [stage["stage_id"] for stage in receipt["stages"]] == [
        "intent-classifier",
        "summarizer-specialist",
        "planner",
        "local-verifier",
    ]
    specialist_event = next(
        event for event in events if event["event_type"] == "planner.local-specialists"
    )
    assert specialist_event["payload"]["specialist_pipeline"]["used"] is True


def test_context_preflight_specialists_try_fallback_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_PLANNER_PREFLIGHT_MODELS", "llama3.2:3b")
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_FILTER_MODELS", "qwen3-coder-next:q4_K_M,llama3.2:3b"
    )
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_PLANNER_MODELS", "qwen3-coder-next:q4_K_M,llama3.2:3b"
    )
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ROUTE_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("NORMAN_LOCAL_SPECIALIST_PIPELINE_MAX_EXECUTIONS", "2")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    warm_policy = _specialist_warm_policy("ready")
    calls = []

    def fake_health(model):
        payload = {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        }
        if model == "local-llm":
            payload["warm_policy"] = warm_policy
        return payload

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(model)
        if model == "qwen3-coder-next:q4_K_M":
            raise TimeoutError("spark route timed out")
        response = {
            "route": "local_plan",
            "cloud_needed": False,
            "safe_local_answer_possible": True,
            "next_local_steps": ["use fallback local preflight"],
            "risk": "low",
        }
        return (
            {
                "message": {"role": "assistant", "content": json.dumps(response)},
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
            "http://local-llm:18151/api/chat",
            "ollama-chat",
        )

    monkeypatch.setattr(module, "local_llm_health_snapshot", fake_health)
    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    module.context_preflight_prompt_context(
        "Plan the safe local checks before cloud escalation.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    accounting = module.take_latest_context_preflight_accounting("codex", module.MODEL)
    receipt = accounting["local_specialist_receipt"]
    assert calls == [
        "qwen3-coder-next:q4_K_M",
        "llama3.2:3b",
        "qwen3-coder-next:q4_K_M",
        "llama3.2:3b",
        "qwen3-coder-next:q4_K_M",
        "llama3.2:3b",
    ]
    assert accounting["local_specialist_status"] == "ok"
    assert accounting["local_specialist_executed_count"] == 2
    assert [stage["model"] for stage in receipt["stages"] if stage.get("executed")] == [
        "llama3.2:3b",
        "llama3.2:3b",
    ]
    outcomes = module.load_local_llm_route_outcomes(limit=10)
    assert [
        item["status"]
        for item in outcomes
        if item["model"] == "qwen3-coder-next:q4_K_M"
    ] == ["timeout", "timeout", "timeout"]


def test_context_preflight_uses_degraded_fallback_for_cold_norllama_lane(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    warm_policy = _specialist_warm_policy("prefetch_or_wait")
    events = []
    calls = []

    def fake_health(model):
        payload = {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        }
        if model == "local-llm":
            payload["warm_policy"] = warm_policy
        return payload

    monkeypatch.setattr(module, "local_llm_health_snapshot", fake_health)
    monkeypatch.setattr(
        module, "append_audit_event", lambda **kwargs: events.append(kwargs) or {}
    )

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(model)
        return (
            {
                "response": json.dumps(
                    {
                        "route": "local_plan",
                        "cloud_needed": False,
                        "safe_local_answer_possible": True,
                    }
                ),
                "prompt_eval_count": 12,
                "eval_count": 8,
            },
            "http://local-llm:18151/api/generate",
            "ollama-generate",
        )

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    context = module.context_preflight_prompt_context(
        "Summarize these notes before deciding whether cloud execution is needed.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert calls == [
        "qwen3.6:35b-a3b-q4_K_M",
        "qwen3.6:35b-a3b-q4_K_M",
        "qwen3.6:35b-a3b-q4_K_M",
    ]
    assert "planned local stages but did not run a ready specialist" not in context
    accounting = module.take_latest_context_preflight_accounting("codex", module.MODEL)
    assert accounting["local_preflight_used"] is True
    assert accounting["local_preflight_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert accounting["local_preflight_candidate_policy"] == (
        "norllama_warm_policy_degraded_fallback"
    )
    assert accounting["local_specialist_used"] is True
    assert accounting["local_specialist_status"] == "ok"
    assert accounting["local_specialist_stage_count"] == 4
    assert accounting["local_specialist_executed_count"] == 2
    assert accounting["local_specialist_tokens"] == 40
    assert accounting["local_specialist_failure_class"] == ""
    receipt = accounting["local_specialist_receipt"]
    assert receipt["route_posture"] == "prefetch_or_wait"
    assert [stage["model"] for stage in receipt["stages"] if stage.get("executed")] == [
        "qwen3.6:35b-a3b-q4_K_M",
        "qwen3.6:35b-a3b-q4_K_M",
    ]
    assert receipt["stages"][0]["candidate_policy"] == (
        "norllama_warm_policy_degraded_fallback"
    )
    specialist_event = next(
        event for event in events if event["event_type"] == "planner.local-specialists"
    )
    assert specialist_event["payload"]["specialist_pipeline"]["used"] is True


def test_context_preflight_skips_norllama_planner_for_localllm_runtime(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    events = []

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("local planner should not run recursively")

    monkeypatch.setattr(module, "local_llm_generate_once", fail_generate)
    monkeypatch.setattr(
        module, "append_audit_event", lambda **kwargs: events.append(kwargs) or {}
    )

    context = module.context_preflight_prompt_context(
        "Answer locally from the provided prompt.",
        attachments=[],
        runtime="localllm",
        model="qwen3.6:27b",
    )

    assert context == ""
    assert events == []


def test_context_preflight_can_use_dedicated_norllama_planner_model(
    monkeypatch, tmp_path
):
    planner_model = "hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M"
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_PLANNER_PREFLIGHT_MODELS", planner_model)
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(model)
        return (
            {
                "response": json.dumps(
                    {
                        "route": "local_plan",
                        "cloud_needed": False,
                        "safe_local_answer_possible": True,
                    }
                )
            },
            "http://local-llm:18151/api/generate",
            "ollama-generate",
        )

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    context = module.context_preflight_prompt_context(
        "Plan locally before escalating.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert calls == [planner_model]
    assert planner_model in context
    assert module.LOCAL_LLM_DEFAULT_MODEL == "qwen3.6:27b"
    assert module.LOCAL_LLM_ROUTE_DEFAULT_MODEL == "qwen3.6:27b"


def test_context_preflight_handles_unhealthy_norllama_planner(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    events = []

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": False,
            "model": model,
            "endpoint": "",
            "reason": "frontdoor timeout",
        },
    )
    monkeypatch.setattr(
        module, "append_audit_event", lambda **kwargs: events.append(kwargs) or {}
    )

    context = module.context_preflight_prompt_context(
        "Plan the deployment safely before making changes.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert "Norllama planner preflight did not add context" in context
    assert "frontdoor timeout" in context
    planner_event = next(
        event for event in events if event["event_type"] == "planner.local-preflight"
    )
    assert planner_event["severity"] == "warning"
    assert planner_event["payload"]["planner"]["used"] is False


def test_context_preflight_cloud_gate_warns_without_local_reduction(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_CODEX_CLOUD_CONTEXT_GATE_TOKENS", "10")
    monkeypatch.setenv("NORMAN_LOCAL_PLANNER_PREFLIGHT_ENABLED", "0")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    events = []

    monkeypatch.setattr(
        module, "append_audit_event", lambda **kwargs: events.append(kwargs) or {}
    )

    context = module.context_preflight_prompt_context(
        "This is a large enough prompt to cross the local reduction gate.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert "Cloud context gate" in context
    assert "not reduced locally" in context
    accounting = module.take_latest_context_preflight_accounting("codex", module.MODEL)
    assert accounting["cloud_context_gate_active"] is True
    assert accounting["cloud_context_gate_status"] == "needs-local-reduction"
    gate_event = next(
        event for event in events if event["event_type"] == "planner.cloud-context-gate"
    )
    assert gate_event["severity"] == "warning"
    assert gate_event["payload"]["accounting"]["local_preflight_used"] is False


def test_context_preflight_limits_norllama_planner_candidate_timeouts(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_MODELS",
        "qwen3.6:27b,qwen3.5:27b-q4_K_M,gemma4:26b-a4b-it-q4_K_M",
    )
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_PLANNER_PREFLIGHT_MAX_CANDIDATES", "1")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(model)
        raise TimeoutError("cold model")

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    context = module.context_preflight_prompt_context(
        "Plan the deployment safely before making changes.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert calls == ["qwen3.6:35b-a3b-q4_K_M"]
    assert "Norllama planner preflight did not add context" in context
    assert "qwen3.6:35b-a3b-q4_K_M" in context
    assert "qwen3.5:27b-q4_K_M" not in context
    accounting = module.take_latest_context_preflight_accounting("codex", module.MODEL)
    assert accounting["local_preflight_status"] == "unavailable"
    assert accounting["local_preflight_failure_class"] == "cold_load_timeout"
    assert accounting["local_preflight_receipt"]["last_failure_model"] == (
        "qwen3.6:35b-a3b-q4_K_M"
    )


def test_context_preflight_tries_second_benchmark_planner_candidate(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(model)
        if len(calls) == 1:
            raise TimeoutError("cold model")
        return (
            {
                "response": json.dumps(
                    {
                        "route": "local_plan",
                        "cloud_needed": False,
                        "safe_local_answer_possible": True,
                        "next_local_steps": ["use the second benchmark lane"],
                    }
                ),
                "prompt_eval_count": 12,
                "eval_count": 8,
            },
            "http://local-llm:18151/api/generate",
            "ollama-generate",
        )

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    context = module.context_preflight_prompt_context(
        "Plan the deployment safely before making changes.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert calls == ["qwen3.6:35b-a3b-q4_K_M", "qwen3.6:27b"]
    assert "Norllama planner preflight" in context
    assert "qwen3.6:27b" in context
    accounting = module.take_latest_context_preflight_accounting("codex", module.MODEL)
    assert accounting["local_preflight_used"] is True
    assert accounting["local_preflight_model"] == "qwen3.6:27b"
    assert accounting["local_preflight_failure_class"] == "ok"
    assert accounting["local_preflight_receipt"]["failure_count"] == 1
    assert accounting["local_preflight_receipt"]["last_failure_status"] == "timeout"


def test_context_preflight_skips_cooled_down_planner_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3.6:27b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_PLANNER_PREFLIGHT_MAX_CANDIDATES", "2")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    calls = []
    module.append_local_llm_route_outcome(
        source="test",
        status="timeout",
        ok=False,
        model="qwen3.6:35b-a3b-q4_K_M",
        endpoint="",
        reason="planner timed out",
    )

    monkeypatch.setattr(
        module,
        "local_llm_health_snapshot",
        lambda model: {
            "ok": True,
            "model": model,
            "endpoint": "http://local-llm:18151",
            "reason": "model advertised",
        },
    )
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: {})

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(model)
        return (
            {
                "response": json.dumps(
                    {
                        "route": "local_plan",
                        "cloud_needed": False,
                        "safe_local_answer_possible": True,
                    }
                )
            },
            "http://local-llm:18151/api/generate",
            "ollama-generate",
        )

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    context = module.context_preflight_prompt_context(
        "Summarize these notes before deciding whether cloud execution is needed.",
        attachments=[],
        runtime="codex",
        model=module.MODEL,
    )

    assert calls == ["qwen3.6:27b"]
    assert "qwen3.6:27b" in context
    assert "qwen3.6:35b-a3b-q4_K_M" not in calls


def test_localllm_execution_adapter_records_local_usage(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "message": {"role": "assistant", "content": "Local summary."},
                    "prompt_eval_count": 11,
                    "eval_count": 3,
                }
            ).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    response, error, _thread_id, usage = module._execute_prompt_runtime(
        "Summarize these notes: alpha beta gamma.",
        "balanced",
        2,
        [],
        "localllm",
        "llama3.2:3b",
        30,
        service_tier="default",
        job_budget="5m",
    )

    assert response == "Local summary."
    assert error == ""
    assert requests[0][0].full_url == "http://local-llm:11434/api/chat"
    payload = json.loads(requests[0][0].data.decode())
    assert payload["model"] == "llama3.2:3b"
    assert payload["keep_alive"] == module.LOCAL_LLM_KEEP_ALIVE
    assert payload["think"] is False
    assert payload["options"]["num_ctx"] == 8192
    assert payload["options"]["num_predict"] == module.LOCAL_LLM_SHORT_MAX_OUTPUT_TOKENS
    assert usage["provider_surface"] == "norllama"
    assert usage["route_class"] == "local"
    assert usage["route_execution"] == "local_worker"
    assert usage["provider_num_ctx"] == 8192
    assert usage["total_tokens"] == 14


def test_localllm_foreground_timeout_is_budget_capped(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_CALL_TIMEOUT_SECONDS", "360")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_FOREGROUND_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_SHORT_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_QUICK_MAX_OUTPUT_TOKENS", "384")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_SHORT_MAX_OUTPUT_TOKENS", "800")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_NUM_CTX", "8192")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_SHORT_NUM_CTX", "4096")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "message": {"role": "assistant", "content": "Local canary."},
                    "prompt_eval_count": 5,
                    "eval_count": 2,
                }
            ).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    assert module.normalize_response_speed("quick") == "fast"
    assert module.normalize_job_budget("short") == "5m"
    assert module.normalize_job_budget("quick") == "2m"
    assert module.local_llm_foreground_timeout_seconds(4800, "quick") == 120
    assert module.local_llm_foreground_timeout_seconds(4800, "short") == 180
    assert module.local_llm_foreground_timeout_seconds(4800, "normal") == 240
    assert module.local_llm_num_ctx_for_budget("quick") == 4096
    assert module.local_llm_num_ctx_for_budget("short") == 8192
    assert module.local_llm_max_output_tokens_for_budget("quick") == 384
    assert module.local_llm_max_output_tokens_for_budget("short") == 800
    assert module.console_runtime_kernel_primary_timeout(4800, "quick") == 120

    response, error, _thread_id, usage = module._execute_local_llm_prompt(
        "Canary check only: reply with two bullets.",
        "quick",
        1,
        [],
        timeout_seconds=4800,
        model="llama3.2:3b",
        service_tier="default",
        job_budget="short",
    )

    assert response == "Local canary."
    assert error == ""
    payload = json.loads(requests[0][0].data.decode())
    assert payload["options"]["num_ctx"] == 8192
    assert payload["options"]["num_predict"] == 800
    assert requests[0][1] == 180
    assert usage["provider_timeout_seconds"] == 180
    assert usage["provider_num_ctx"] == 8192
    assert usage["provider_max_output_tokens"] == 800


def test_localllm_execution_preserves_cancel_request(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        raise AssertionError("cancelled local turn should not issue a request")

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    module.update_status_meta(cancel_requested_at=module.now_ts())

    response, error, _thread_id, usage = module._execute_local_llm_prompt(
        "Canary check only: reply with two bullets.",
        "quick",
        1,
        [],
        timeout_seconds=4800,
        model="llama3.2:3b",
        service_tier="default",
        job_budget="short",
    )

    assert response == ""
    assert error == module.CANCELLED_WEB_REPLY_MESSAGE
    assert requests == []
    assert usage["success"] is False
    assert usage["provider_timeout_seconds"] == 180


def test_localllm_execution_records_empty_response_outcome(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    class Response:
        headers = {"X-Norllama-Worker-Endpoint": "http://spark:18151"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "response": "",
                    "done": True,
                    "done_reason": "length",
                    "prompt_eval_count": 11,
                    "eval_count": 3,
                }
            ).encode()

    monkeypatch.setattr(
        module.urllib_request, "urlopen", lambda *_args, **_kwargs: Response()
    )

    response, error, _thread_id, usage = module._execute_prompt_runtime(
        "Summarize these notes: alpha beta gamma.",
        "balanced",
        2,
        [],
        "localllm",
        "llama3.2:3b",
        30,
        service_tier="default",
        job_budget="5m",
    )
    outcomes = module.load_local_llm_route_outcomes(limit=5)
    cooldown = module.local_llm_route_cooldown("llama3.2:3b")

    assert response == ""
    assert "did not return a response" in error
    assert usage["success"] is False
    assert outcomes[-1]["status"] == "empty-response"
    assert outcomes[-1]["worker_endpoint"] == "http://spark:18151"
    assert cooldown["status"] == "empty-response"


def test_localllm_execution_tries_next_route_candidate_after_timeout(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "gemma4:26b-a4b-it-q4_K_M")
    monkeypatch.setenv(
        "NORMAN_LOCAL_LLM_MODELS",
        "gemma4:26b-a4b-it-q4_K_M,qwen3-coder-next:q4_K_M",
    )
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED", "0")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    module.update_status_meta(
        running_cost_route={
            "selected_runtime": "localllm",
            "selected_model": "gemma4:26b-a4b-it-q4_K_M",
            "local_candidates": [
                "gemma4:26b-a4b-it-q4_K_M",
                "qwen3-coder-next:q4_K_M",
            ],
        }
    )
    calls = []

    def fake_generate(
        endpoint,
        model,
        prompt,
        *,
        timeout_seconds,
        max_output_tokens=None,
        num_ctx=None,
    ):
        calls.append(model)
        if model == "gemma4:26b-a4b-it-q4_K_M":
            raise TimeoutError("spark cold load timed out")
        return (
            {
                "message": {"role": "assistant", "content": "- alpha\n- beta gamma"},
                "prompt_eval_count": 13,
                "eval_count": 5,
            },
            "http://local-llm:18151/api/chat",
            "norllama-chat",
        )

    monkeypatch.setattr(module, "local_llm_generate_once", fake_generate)

    response, error, _thread_id, usage = module._execute_local_llm_prompt(
        "Summarize alpha beta gamma into exactly two short bullets.",
        "quick",
        1,
        [],
        timeout_seconds=180,
        model="gemma4:26b-a4b-it-q4_K_M",
        service_tier="default",
        job_budget="quick",
    )
    outcomes = module.load_local_llm_route_outcomes(limit=5)

    assert response == "- alpha\n- beta gamma"
    assert error == ""
    assert calls == ["gemma4:26b-a4b-it-q4_K_M", "qwen3-coder-next:q4_K_M"]
    assert usage["model"] == "qwen3-coder-next:q4_K_M"
    assert usage["local_worker_candidate_count"] == 2
    assert [item["status"] for item in outcomes[-2:]] == ["timeout", "ok"]
    assert [item["model"] for item in outcomes[-2:]] == [
        "gemma4:26b-a4b-it-q4_K_M",
        "qwen3-coder-next:q4_K_M",
    ]


def test_localllm_execution_rejects_plan_only_visible_output(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:11434")
    module = _load_agent_console_web(monkeypatch, tmp_path)

    class Response:
        headers = {"X-Norllama-Worker-Endpoint": "http://spark:18151"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "### Plan\n"
                            "Objective: summarize the notes.\n"
                            "Done When: two bullets are visible.\n"
                            "Success Metrics: route receipt captured."
                        ),
                    },
                    "prompt_eval_count": 11,
                    "eval_count": 18,
                }
            ).encode()

    monkeypatch.setattr(
        module.urllib_request, "urlopen", lambda *_args, **_kwargs: Response()
    )

    assert (
        module.visible_response_output_shape(
            "Summarize these notes: alpha beta gamma.",
            "### Plan\nObjective: summarize.\nDone When: complete.",
        )
        == "progress_only"
    )
    assert (
        module.visible_response_output_shape(
            "Summarize these notes: alpha beta gamma.",
            "- alpha\n- beta gamma",
        )
        == "complete"
    )

    response, error, _thread_id, usage = module._execute_prompt_runtime(
        "Summarize these notes: alpha beta gamma.",
        "balanced",
        2,
        [],
        "localllm",
        "llama3.2:3b",
        30,
        service_tier="default",
        job_budget="5m",
    )
    outcomes = module.load_local_llm_route_outcomes(limit=5)
    cooldown = module.local_llm_route_cooldown("llama3.2:3b")

    assert response == ""
    assert "did not return a response" in error
    assert usage["success"] is False
    assert usage["output_shape"] == "progress_only"
    assert outcomes[-1]["status"] == "bad-output"
    assert "output_shape=progress_only" in outcomes[-1]["reason"]
    assert cooldown["status"] == "bad-output"


def test_localllm_health_probe_stops_after_transport_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "llama3.2:3b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://dead-llm:18151")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_HEALTH_TIMEOUT_SECONDS", "0.2")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        raise urllib_error.URLError("timed out")

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    probe = module.local_llm_probe_endpoint("http://dead-llm:18151", "llama3.2:3b")

    assert probe["ok"] is False
    assert "timed out" in probe["reason"]
    assert requests == [("http://dead-llm:18151/v1/capabilities", 0.2)]


def test_localllm_health_probe_accepts_norllama_v1_capabilities(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        if request.full_url.endswith("/v1/capabilities"):
            return Response(
                {
                    "service": "norllama",
                    "status": "ready",
                    "models": [{"name": "qwen3:8b"}],
                }
            )
        if request.full_url.endswith("/v1/overview"):
            return Response(
                {
                    "service": "norllama",
                    "status": "ok",
                    "gateway": {"name": "norllama"},
                    "catalog_summary": {"visible_model_count": 1},
                }
            )
        if request.full_url.endswith("/v1/warm-policy"):
            return Response(
                {
                    "schema": "norllama.warm-policy.v1",
                    "status": "ok",
                    "route_posture": "ready",
                    "route_guardrails": {
                        "schema": "norman.norllama.route-guardrail-matrix.v1",
                        "lanes": {},
                    },
                }
            )
        return Response({"count": 0, "items": []})

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    probe = module.local_llm_probe_endpoint("http://local-llm:18151", "qwen3:8b")

    assert probe["ok"] is True
    assert probe["capability_source"] == "/v1/capabilities"
    assert probe["models_seen"] == ["qwen3:8b"]
    assert probe["warm_policy"]["schema"] == "norllama.warm-policy.v1"
    assert probe["warm_policy"]["source"] == "/v1/warm-policy"
    assert probe["tool_activity"]["schema"] == "norman.norllama.tool-activity.v1"
    assert probe["tool_activity"]["status"] == "quiet"
    assert requests == [
        ("http://local-llm:18151/v1/capabilities", 1.5),
        ("http://local-llm:18151/v1/overview", 1.5),
        ("http://local-llm:18151/v1/warm-policy", 3.0),
        ("http://local-llm:18151/v1/activity?limit=200", 1.5),
    ]


def test_localllm_warm_policy_synthesizes_norllama_contract_guardrails(
    monkeypatch, tmp_path
):
    module = _load_agent_console_web(monkeypatch, tmp_path)
    payload = {
        "service": "norllama",
        "contracts": [
            {
                "contract_id": "chat",
                "aliases": ["general_chat"],
                "default_model": "qwen3.6:35b-a3b-q4_K_M",
                "alternates": [
                    {"model": "qwen3.6:27b", "best_weighted_score": 9.4},
                    {"model": "gpt-oss:120b", "best_weighted_score": 2.8},
                ],
                "dispatch": "unified_chat",
                "status": "benchmark_backed",
                "best_weighted_score": 10.1,
                "selection_method": "weighted_local_suite_score",
                "guardrail": "Keep exact facts behind a verifier.",
            },
            {
                "contract_id": "rerank",
                "aliases": ["rank"],
                "default_model": "bge-m3:latest",
                "dispatch": "rerank_proxy",
                "status": "benchmark_backed",
                "selection_method": "live_tool_lane_probe",
                "best_weighted_score": 1.0,
                "guardrail": "Use as retrieval ordering signal.",
            },
            {
                "contract_id": "code_risk",
                "aliases": ["patch_risk"],
                "default_model": "qwen3.6:27b",
                "dispatch": "unified_chat",
                "status": "benchmark_backed",
                "best_weighted_score": 1.2,
            },
            {
                "contract_id": "audio_diarize",
                "aliases": ["diarize"],
                "default_model": "",
                "dispatch": "transcribe_proxy",
                "status": "pending_benchmark",
            },
        ],
    }

    names = module.local_llm_extract_model_names(payload)
    policy = module.local_llm_warm_policy_from_payload(payload)
    lanes = policy["route_guardrails"]["lanes"]

    assert "qwen3.6:35b-a3b-q4_K_M" in names
    assert "bge-m3:latest" in names
    assert policy["route_guardrails"]["schema"] == (
        "norman.norllama.route-guardrail-matrix.v1"
    )
    assert lanes["summarizer"]["status"] == "prefetch_or_wait"
    assert policy["route_posture"] == "prefetch_or_wait"
    assert lanes["coder"]["eligible_models"][0]["model"] == "qwen3.6:27b"
    assert lanes["filter"]["eligible_count"] >= 1
    assert lanes["filter"]["eligible_models"][0]["authority"] == "tool_lane_only"
    assert lanes["summarizer"]["canary_models"][0]["model"] == "gpt-oss:120b"
    assert module.local_llm_lane_models_from_warm_policy(policy, "filter") == []
    assert module.local_llm_lane_models_from_warm_policy(policy, "summarizer") == [
        "qwen3.6:35b-a3b-q4_K_M",
        "qwen3.6:27b",
    ]


def test_localllm_warm_policy_prefers_active_resident_models(monkeypatch, tmp_path):
    module = _load_agent_console_web(monkeypatch, tmp_path)
    policy = {
        "schema": "norllama.warm-policy.v1",
        "source": "/v1/warm-policy",
        "route_guardrails": {
            "schema": "norman.norllama.route-guardrail-matrix.v1",
            "lanes": {
                "filter": {
                    "lane": "filter",
                    "status": "ready",
                    "eligible_models": [
                        {
                            "model": "qwen3.6:27b",
                            "authority": "preflight_or_draft",
                            "chat_candidate": True,
                            "active": False,
                            "benchmark_quality": {"score": 5.8548},
                        },
                        {
                            "model": "qwen3.6:35b-a3b-q4_K_M",
                            "authority": "preflight_or_draft",
                            "chat_candidate": True,
                            "active": True,
                            "active_hosts": [
                                "http://192.168.2.150:18151",
                                "http://192.168.2.151:18151",
                            ],
                            "benchmark_quality": {"score": 5.4616},
                        },
                    ],
                }
            },
        },
    }

    assert module.local_llm_lane_models_from_warm_policy(policy, "filter") == [
        "qwen3.6:35b-a3b-q4_K_M",
        "qwen3.6:27b",
    ]


def test_localllm_health_probe_accepts_contracts_as_model_source(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "gemma4:26b-a4b-it-q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "gemma4:26b-a4b-it-q4_K_M")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        if request.full_url.endswith("/v1/capabilities"):
            return Response(
                {
                    "service": "norllama",
                    "gateway": {"name": "norllama"},
                    "catalog_summary": {"visible_model_count": 30},
                    "contracts": [
                        {
                            "contract_id": "chat",
                            "aliases": ["general_chat"],
                            "default_model": "gemma4:26b-a4b-it-q4_K_M",
                            "dispatch": "unified_chat",
                            "status": "benchmark_backed",
                            "best_weighted_score": 10.1,
                            "selection_method": "weighted_local_suite_score",
                        }
                    ],
                }
            )
        if request.full_url.endswith("/v1/warm-policy"):
            return Response(
                {
                    "schema": "norllama.warm-policy.v1",
                    "status": "ok",
                    "route_posture": "prefetch_or_wait",
                    "residency_posture": "cold",
                    "route_guardrails": {
                        "schema": "norman.norllama.route-guardrail-matrix.v1",
                        "source": "/v1/warm-policy",
                        "lanes": {
                            "planner": {
                                "lane": "planner",
                                "status": "prefetch_or_wait",
                                "eligible_models": [
                                    {
                                        "model": "gemma4:26b-a4b-it-q4_K_M",
                                        "chat_candidate": True,
                                        "authority": "preflight_or_draft",
                                    }
                                ],
                            }
                        },
                    },
                }
            )
        return Response({"count": 0, "items": []})

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    probe = module.local_llm_probe_endpoint(
        "http://local-llm:18151", "gemma4:26b-a4b-it-q4_K_M"
    )

    assert probe["ok"] is True
    assert probe["capability_source"] == "/v1/capabilities"
    assert probe["models_seen"] == ["gemma4:26b-a4b-it-q4_K_M"]
    assert probe["warm_policy"]["route_guardrails"]["lanes"]["planner"]["status"] == (
        "prefetch_or_wait"
    )
    assert probe["warm_policy"]["source"] == "/v1/warm-policy"
    assert requests == [
        ("http://local-llm:18151/v1/capabilities", 1.5),
        ("http://local-llm:18151/v1/warm-policy", 3.0),
        ("http://local-llm:18151/v1/activity?limit=200", 1.5),
    ]


def test_localllm_health_probe_includes_norllama_mesh_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        if request.full_url.endswith("/v1/capabilities"):
            return Response(
                {
                    "service": "norllama",
                    "status": "ready",
                    "models": [{"name": "qwen3:8b"}],
                }
            )
        if request.full_url.endswith("/v1/activity?limit=200"):
            return Response(
                {
                    "count": 3,
                    "items": [
                        {
                            "method": "GET",
                            "path": "/v1/overview",
                            "status": 200,
                        },
                        {
                            "method": "POST",
                            "path": "/v1/embeddings",
                            "status": 200,
                            "duration_ms": 36,
                            "model": "bge-m3:latest",
                        },
                    ],
                }
            )
        if request.full_url.endswith("/v1/warm-policy"):
            return Response(
                {
                    "schema": "norllama.warm-policy.v1",
                    "status": "ok",
                    "route_posture": "ready",
                    "route_guardrails": {
                        "schema": "norman.norllama.route-guardrail-matrix.v1",
                        "lanes": {},
                    },
                }
            )
        return Response(
            {
                "service": "norllama",
                "status": "ok",
                "gateway": {"name": "norllama", "version": "test"},
                "catalog_summary": {"visible_model_count": 3},
                "recent_activity": {"count": 7},
            }
        )

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    probe = module.local_llm_probe_endpoint("http://local-llm:18151", "qwen3:8b")

    assert probe["ok"] is True
    assert probe["mesh"]["schema"] == "norman.norllama.mesh.v1"
    assert probe["mesh"]["source"] == "/v1/overview"
    assert probe["mesh"]["frontdoor"]["status"] == "ok"
    assert probe["mesh"]["frontdoor"]["reachable"] is True
    assert probe["mesh"]["frontdoor"]["model_count"] == 3
    assert probe["mesh"]["frontdoor"]["gateway"]["name"] == "norllama"
    assert probe["mesh"]["model_count"] == 3
    assert probe["mesh"]["recent_activity_count"] == 7
    assert probe["warm_policy"]["source"] == "/v1/warm-policy"
    assert probe["tool_activity"]["schema"] == "norman.norllama.tool-activity.v1"
    assert probe["tool_activity"]["tool_call_count"] == 1
    assert probe["tool_activity"]["latest_tool_call"]["capability"] == "embed"
    assert probe["tool_activity"]["latest_tool_call"]["model"] == "bge-m3:latest"
    assert requests == [
        ("http://local-llm:18151/v1/capabilities", 1.5),
        ("http://local-llm:18151/v1/overview", 1.5),
        ("http://local-llm:18151/v1/warm-policy", 3.0),
        ("http://local-llm:18151/v1/activity?limit=200", 1.5),
    ]


def test_localllm_health_probe_rejects_concrete_model_when_capabilities_empty(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_MODELS", "qwen3:8b")
    monkeypatch.setenv("NORMAN_LOCAL_LLM_ENDPOINTS", "http://local-llm:18151")
    module = _load_agent_console_web(monkeypatch, tmp_path)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"service": "norllama", "status": "ready", "models": []}
            ).encode()

    def fake_urlopen(request, timeout):
        requests.append(request.full_url)
        return Response()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    probe = module.local_llm_probe_endpoint("http://local-llm:18151", "qwen3:8b")

    assert probe["ok"] is False
    assert probe["reason"] == "/v1/models returned no advertised models"
    assert requests == [
        "http://local-llm:18151/v1/capabilities",
        "http://local-llm:18151/api/capabilities",
        "http://local-llm:18151/capabilities",
        "http://local-llm:18151/api/tags",
        "http://local-llm:18151/v1/models",
    ]
