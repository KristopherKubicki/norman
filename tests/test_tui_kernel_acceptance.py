from __future__ import annotations

import json

from scripts import tui_kernel_acceptance as acceptance


def route_invocations(
    model: str = "qwen3.6:27b",
    *,
    worker: str = "spark-151",
    phase: str = "literal_response",
) -> list[dict[str, str]]:
    return [
        {
            "phase": phase,
            "task_kind": "chat",
            "route_selected_model": model,
            "requested_model": model,
            "effective_runtime_model": model,
            "selected_worker": worker,
            "target_worker": worker,
            "target_worker_mode": "explicit",
            "gateway_selected_worker": worker,
            "observed_worker": worker,
            "observed_worker_source": "gateway_response",
            "execution_mode": "live",
            "output_shape": "complete",
            "request_id": f"req-{phase}",
            "client_request_id": f"req-{phase}",
            "gateway_request_id": f"gw-{phase}",
            "invocation_id": f"worker:turn-test:{phase}:1:model",
        }
    ]


def test_form_payload_uses_locked_local_llm_route():
    target = acceptance.default_targets()["norman"]
    scenario = acceptance.default_scenarios()["canary"]
    run = acceptance.materialize_scenario(scenario, target, run_id="r1")

    payload = acceptance.form_payload(run)

    assert payload["runtime"] == "localllm"
    assert payload["model"] == "qwen3.6:27b"
    assert payload["route_lock"] == "1"
    assert payload["job_budget"] == "2m"
    assert run.expected_response == "DONE local visible r1-norman-canary"


def test_norman_target_uses_ssh_when_acceptance_runs_off_host(monkeypatch):
    monkeypatch.delenv("NORMAN_TUI_ACCEPTANCE_NORMAN_SSH_TARGET", raising=False)
    monkeypatch.setattr(acceptance.socket, "gethostname", lambda: "hal")

    assert acceptance.default_targets()["norman"].ssh_target == "norman.home.arpa"


def test_norman_target_stays_local_when_acceptance_runs_on_norman(monkeypatch):
    monkeypatch.delenv("NORMAN_TUI_ACCEPTANCE_NORMAN_SSH_TARGET", raising=False)
    monkeypatch.setattr(acceptance.socket, "gethostname", lambda: "norman")

    assert acceptance.default_targets()["norman"].ssh_target == ""


def test_runtime_token_resolver_prefers_direct_env(monkeypatch):
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "direct-token")
    monkeypatch.delenv("NORMAN_API_TOKEN", raising=False)

    assert acceptance.resolve_console_runtime_token() == "direct-token"
    token, meta = acceptance.resolve_console_runtime_token_with_source()
    assert token == "direct-token"
    assert meta["runtime_token_source"] == "env"
    assert meta["runtime_token_secret_name"] == ""


def test_runtime_token_resolver_uses_norman_keys(monkeypatch):
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("NORMAN_API_TOKEN", raising=False)
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://norman.local")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "keys-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET", "runtime/token")
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"value": "brokered-runtime-token"}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(acceptance.urllib.request, "urlopen", fake_urlopen)

    token, meta = acceptance.resolve_console_runtime_token_with_source()
    assert token == "brokered-runtime-token"
    assert meta["runtime_token_source"] == "norman_keys"
    assert meta["runtime_token_secret_name"] == "runtime/token"
    assert acceptance.resolve_console_runtime_token() == "brokered-runtime-token"
    assert len(requests) == 2
    request, timeout = requests[0]
    assert request.full_url == "http://norman.local/v1/secrets/get"
    assert timeout == 2.0
    assert request.get_header("Authorization") == "Bearer keys-token"
    assert b'"name": "runtime/token"' in request.data
    assert b'"requester_id": "runtime-tui-bridge"' in request.data


def test_runtime_token_resolver_can_use_secret_command(monkeypatch):
    monkeypatch.delenv("NORMAN_CONSOLE_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("NORMAN_API_TOKEN", raising=False)
    monkeypatch.delenv("NORMAN_KEYS_URL", raising=False)
    monkeypatch.setenv("NORMAN_SECRET_CMD", "secretctl read {name}")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET", "runtime/token")
    calls = []

    class Result:
        stdout = "command-runtime-token\n"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(acceptance.subprocess, "run", fake_run)

    token, meta = acceptance.resolve_console_runtime_token_with_source()
    assert token == "command-runtime-token"
    assert meta["runtime_token_source"] == "secret_command"
    assert meta["runtime_token_secret_name"] == "runtime/token"
    assert acceptance.resolve_console_runtime_token() == "command-runtime-token"
    assert len(calls) == 2
    assert calls[0][0] == ["secretctl", "read", "runtime/token"]
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True


def test_receipt_from_norman_api_poll_waits_for_terminal_proof(monkeypatch):
    calls = []
    receipts = [
        {
            "available": True,
            "job_id": "turn-running",
            "job_status": "running",
            "output_shape": "",
        },
        {
            "available": True,
            "job_id": "turn-running",
            "job_status": "running",
            "output_shape": "complete",
            "execution_mode": "live",
            "receipt_audit": {"status": "pass", "pass": True},
            "completion_gate": {"gate_passed": True},
        },
    ]

    def fake_receipt(job_id, *, api_base, token, timeout):
        calls.append((job_id, api_base, token, timeout))
        return receipts.pop(0)

    monkeypatch.setattr(acceptance, "receipt_from_norman_api", fake_receipt)
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)

    receipt = acceptance.receipt_from_norman_api_poll(
        "turn-running",
        api_base="http://norman/api/v1",
        token="token",
        timeout=3.0,
        poll_attempts=4,
        poll_interval=0.1,
    )

    assert receipt["output_shape"] == "complete"
    assert len(calls) == 2
    assert calls[0] == ("turn-running", "http://norman/api/v1", "token", 3.0)


def test_receipt_from_norman_api_poll_records_transient_404(monkeypatch):
    calls = []
    receipts = [
        {
            "available": False,
            "error": "runtime API status 404: Console runtime job not found",
        },
        {
            "available": True,
            "job_id": "turn-visible",
            "job_status": "done",
        },
    ]

    def fake_receipt(job_id, *, api_base, token, timeout):
        calls.append((job_id, api_base, token, timeout))
        return receipts.pop(0)

    monkeypatch.setattr(acceptance, "receipt_from_norman_api", fake_receipt)
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)

    receipt = acceptance.receipt_from_norman_api_poll(
        "turn-visible",
        api_base="http://norman/api/v1",
        token="token",
        timeout=3.0,
        poll_attempts=4,
        poll_interval=0.1,
    )

    assert receipt["job_status"] == "done"
    assert receipt["transient_404_count"] == 1
    assert receipt["poll_attempts_used"] == 2
    assert receipt["poll_history"][0]["available"] is False
    assert len(calls) == 2


def test_receipt_from_norman_db_poll_waits_for_terminal_receipt(monkeypatch, tmp_path):
    calls = []
    receipts = [
        {
            "available": True,
            "job_id": "turn-db",
            "job_status": "running",
            "output_shape": "",
        },
        {
            "available": True,
            "proof_source": "central_db",
            "job_id": "turn-db",
            "job_status": "done",
            "output_shape": "complete",
            "execution_mode": "live",
            "receipt_audit": {"status": "pass", "pass": True},
            "completion_gate": {"status": "pass", "gate_passed": True},
        },
    ]

    def fake_db(job_id, *, repo_root):
        calls.append((job_id, repo_root))
        return receipts.pop(0)

    monkeypatch.setattr(acceptance, "receipt_from_norman_db", fake_db)
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)

    receipt = acceptance.receipt_from_norman_db_poll(
        "turn-db",
        repo_root=tmp_path,
        poll_attempts=4,
        poll_interval=0.1,
    )

    assert receipt["job_status"] == "done"
    assert receipt["proof_source"] == "central_db"
    assert receipt["poll_attempts_used"] == 2
    assert len(calls) == 2


def test_receipt_from_norman_db_poll_can_require_terminal_state(monkeypatch, tmp_path):
    calls = []
    receipts = [
        {
            "available": True,
            "proof_source": "central_db",
            "job_id": "turn-db-terminal",
            "job_status": "running",
            "output_shape": "complete",
            "execution_mode": "live",
            "receipt_audit": {"status": "pass", "pass": True},
            "completion_gate": {"status": "pass", "gate_passed": True},
        },
        {
            "available": True,
            "proof_source": "central_db",
            "job_id": "turn-db-terminal",
            "job_status": "done",
            "output_shape": "complete",
            "execution_mode": "live",
            "receipt_audit": {"status": "pass", "pass": True},
            "completion_gate": {"status": "pass", "gate_passed": True},
        },
    ]

    def fake_db(job_id, *, repo_root):
        calls.append((job_id, repo_root))
        return receipts.pop(0)

    monkeypatch.setattr(acceptance, "receipt_from_norman_db", fake_db)
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)

    receipt = acceptance.receipt_from_norman_db_poll(
        "turn-db-terminal",
        repo_root=tmp_path,
        poll_attempts=4,
        poll_interval=0.1,
        accept_provable_running=False,
    )

    assert receipt["job_status"] == "done"
    assert receipt["poll_attempts_used"] == 2
    assert len(calls) == 2


def test_auto_route_local_scenario_is_unlocked():
    target = acceptance.default_targets()["norman"]
    scenario = acceptance.default_scenarios()["auto_route_local"]
    run = acceptance.materialize_scenario(scenario, target, run_id="r-auto")

    payload = acceptance.form_payload(run)

    assert payload["runtime"] == "auto"
    assert payload["model"] == ""
    assert payload["route_lock"] == "0"
    assert scenario.expected_task_kind == "chat"
    assert "billing=unhealthy timeout" in run.message
    assert run.expected_response == "r-auto-norman-auto_route_local"


def test_select_scenarios_all_includes_deeper_smokes():
    scenarios = acceptance.select_scenarios("all")

    names = {scenario.name for scenario in scenarios}
    assert {
        "canary",
        "route_receipt",
        "auto_route_local",
        "workspace_preflight",
        "specialist_visibility",
    }.issubset(names)


def test_select_targets_rejects_unknown_names():
    try:
        acceptance.select_targets("norman,missing")
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("unknown target should fail")


def test_runtime_api_url_normalizes_api_bases():
    assert (
        acceptance._runtime_api_url(
            "https://norman.home.arpa/api/v1", "/console-runtime/jobs/j1"
        )
        == "https://norman.home.arpa/api/v1/console-runtime/jobs/j1"
    )
    assert (
        acceptance._runtime_api_url(
            "https://norman.home.arpa/api", "/console-runtime/jobs/j1"
        )
        == "https://norman.home.arpa/api/v1/console-runtime/jobs/j1"
    )
    assert (
        acceptance._runtime_api_url(
            "https://norman.home.arpa", "/console-runtime/jobs/j1"
        )
        == "https://norman.home.arpa/api/v1/console-runtime/jobs/j1"
    )


def test_live_multi_host_acceptance_requires_runtime_api_token(monkeypatch, tmp_path):
    output = tmp_path / "acceptance.json"
    monkeypatch.setattr(
        acceptance,
        "resolve_console_runtime_token_with_source",
        lambda: (
            "",
            {"runtime_token_source": "none", "runtime_token_secret_name": ""},
        ),
    )

    def fail_probe(*_args, **_kwargs):
        raise AssertionError("acceptance should not send prompts without proof token")

    monkeypatch.setattr(acceptance, "run_tui_probe", fail_probe)

    result = acceptance.main(
        [
            "--live",
            "--targets",
            "housebot",
            "--scenarios",
            "canary",
            "--run-id",
            "preflight",
            "--output-json",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 2
    assert report["preflight_failed"] is True
    assert report["runtime_api"]["base"] == acceptance.DEFAULT_RUNTIME_API_BASE
    assert report["runtime_api"]["token_available"] is False
    assert "refusing to send prompts" in report["preflight_failures"][0]
    assert report["results"] == []


def test_live_multi_host_acceptance_can_use_authoritative_norman_db_fallback(
    monkeypatch, tmp_path
):
    repo_root = tmp_path / "repo"
    (repo_root / "app" / "db").mkdir(parents=True)
    (repo_root / "app" / "models").mkdir(parents=True)
    (repo_root / "app" / "db" / "session.py").write_text("", encoding="utf-8")
    (repo_root / "app" / "models" / "console_runtime.py").write_text(
        "", encoding="utf-8"
    )
    output = tmp_path / "acceptance.json"
    monkeypatch.setattr(acceptance.socket, "gethostname", lambda: "norman")
    monkeypatch.setattr(
        acceptance,
        "resolve_console_runtime_token_with_source",
        lambda: (
            "",
            {"runtime_token_source": "none", "runtime_token_secret_name": ""},
        ),
    )

    def fake_probe(_target, run, **_kwargs):
        job_id = "turn-housebot-central-db"
        return {
            "ok": True,
            "ask_job_id": job_id,
            "ask": {"console_runtime_job_id": job_id},
            "status": {
                "pending": False,
                "last_prompt": run.message,
                "last_response": run.expected_response,
                "last_error": "",
                "last_console_runtime_job_id": job_id,
                "last_response_console_runtime_job_id": job_id,
            },
        }

    def fake_db(job_id, *, repo_root):
        assert job_id == "turn-housebot-central-db"
        return {
            "available": True,
            "proof_source": "central_db",
            "job_id": job_id,
            "job_status": "done",
            "last_error": "",
            "kernel_owned_turn": True,
            "task_kind": "literal_response",
            "selected_model": "qwen3.6:27b",
            "selected_worker": "spark-151",
            "observed_worker": "spark-151",
            "observed_worker_source": "gateway_response",
            "invocations": route_invocations(),
            "execution_mode": "live",
            "output_shape": "complete",
            "local_tokens": 77,
            "cloud_proxy": False,
            "receipt_audit": {"status": "pass", "pass": True},
            "completion_gate": {"status": "pass", "gate_passed": True},
            "goal_local_tokens": 77,
            "goal_cloud_tokens": 0,
            "ledger_cloud_tokens": 0,
            "ledger_by_provider": {"norllama": 77},
            "local_first_status": "on_target",
            "model_completed_count": 1,
            "spark_evidence_count": 1,
        }

    monkeypatch.setattr(acceptance, "run_tui_probe", fake_probe)
    monkeypatch.setattr(acceptance, "receipt_from_norman_db", fake_db)
    monkeypatch.setattr(
        acceptance,
        "poll_visible_delivery",
        lambda _target, run, *, job_id, **_kwargs: {
            "ok": True,
            "status_http_status": 200,
            "poll_attempts_used": 1,
            "status": {
                "pending": False,
                "last_prompt": run.message,
                "last_response": run.expected_response,
                "last_error": "",
                "last_console_runtime_job_id": job_id,
                "last_response_console_runtime_job_id": job_id,
            },
        },
    )

    result = acceptance.main(
        [
            "--live",
            "--targets",
            "housebot",
            "--scenarios",
            "canary",
            "--run-id",
            "central-db",
            "--repo-root",
            str(repo_root),
            "--allow-local-db-fallback",
            "--output-json",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert report["passed"] is True
    assert report["local_db_fallback"]["authorized"] is True
    assert report["runtime_api"]["token_available"] is False
    assert report["results"][0]["receipt"]["proof_source"] == "central_db"


def test_live_multi_host_acceptance_rejects_local_db_fallback_off_norman(
    monkeypatch, tmp_path
):
    repo_root = tmp_path / "repo"
    (repo_root / "app" / "db").mkdir(parents=True)
    (repo_root / "app" / "models").mkdir(parents=True)
    (repo_root / "app" / "db" / "session.py").write_text("", encoding="utf-8")
    (repo_root / "app" / "models" / "console_runtime.py").write_text(
        "", encoding="utf-8"
    )
    output = tmp_path / "acceptance.json"
    monkeypatch.setattr(acceptance.socket, "gethostname", lambda: "hal")
    monkeypatch.setattr(
        acceptance,
        "resolve_console_runtime_token_with_source",
        lambda: (
            "",
            {"runtime_token_source": "none", "runtime_token_secret_name": ""},
        ),
    )

    def fail_probe(*_args, **_kwargs):
        raise AssertionError("acceptance should not send prompts from non-Norman DB")

    monkeypatch.setattr(acceptance, "run_tui_probe", fail_probe)

    result = acceptance.main(
        [
            "--live",
            "--targets",
            "housebot",
            "--scenarios",
            "canary",
            "--run-id",
            "central-db-denied",
            "--repo-root",
            str(repo_root),
            "--allow-local-db-fallback",
            "--output-json",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 2
    assert report["preflight_failed"] is True
    assert report["local_db_fallback"]["requested"] is True
    assert report["local_db_fallback"]["authorized"] is False


def test_run_tui_probe_local_waits_for_idle_before_submit(monkeypatch):
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="idle-wait",
    )
    calls = []
    status_payloads = [
        {
            "pending": True,
            "last_console_runtime_job_id": "turn-previous",
            "last_prompt": "old prompt",
        },
        {
            "pending": True,
            "last_console_runtime_job_id": "turn-previous",
            "last_prompt": "old prompt",
        },
        {
            "pending": False,
            "last_console_runtime_job_id": "turn-previous",
            "last_prompt": "old prompt",
        },
        {
            "pending": False,
            "last_console_runtime_job_id": "turn-current",
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
        },
    ]

    def fake_fetch(url, *, data=None, timeout=10.0, headers=None):
        calls.append((url, data))
        if url.endswith("/api/status"):
            return 200, status_payloads.pop(0)
        if url.endswith("/api/ask"):
            return 202, {
                "console_runtime_job_id": "turn-current",
                "receipt_visibility": "visible",
            }
        raise AssertionError(url)

    monkeypatch.setattr(acceptance, "_fetch_json", fake_fetch)
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)

    probe = acceptance.run_tui_probe_local(
        target,
        run,
        poll_attempts=5,
        poll_interval=0.1,
        ask_timeout=1,
        status_timeout=1,
    )

    assert probe["before_idle"] is True
    assert probe["before_idle_wait_attempts"] == 2
    assert probe["before_job_id"] == "turn-previous"
    assert probe["ask_job_id"] == "turn-current"
    assert calls[0][0].endswith("/api/status")
    assert calls[3][0].endswith("/api/ask")


def test_live_multi_host_acceptance_does_not_fall_back_to_local_db_after_api_failure(
    monkeypatch,
):
    target = acceptance.default_targets()["housebot"]
    scenario = acceptance.default_scenarios()["canary"]
    run = acceptance.materialize_scenario(scenario, target, run_id="api-fail")
    job_id = "turn-housebot-api-fail"

    monkeypatch.setattr(
        acceptance,
        "run_tui_probe",
        lambda *_args, **_kwargs: {
            "ok": True,
            "ask_job_id": job_id,
            "ask": {"console_runtime_job_id": job_id},
            "status": {
                "pending": False,
                "last_prompt": run.message,
                "last_response": run.expected_response,
                "last_error": "",
                "last_console_runtime_job_id": job_id,
            },
        },
    )
    monkeypatch.setattr(
        acceptance,
        "receipt_from_norman_api_poll",
        lambda *_args, **_kwargs: {
            "available": False,
            "error": "runtime API failed",
        },
    )

    def fail_db(*_args, **_kwargs):
        raise AssertionError("multi-host proof must not use local DB fallback")

    monkeypatch.setattr(acceptance, "receipt_from_norman_db", fail_db)

    result = acceptance.main(
        [
            "--live",
            "--targets",
            "housebot",
            "--scenarios",
            "canary",
            "--run-id",
            "api-fail",
            "--runtime-token",
            "token",
        ]
    )

    assert result == 1


def test_receipt_from_activity_snapshot_maps_route_summary():
    snapshot = {
        "job": {
            "job_id": "turn-test",
            "status": "done",
            "last_error": "",
            "metadata": {"kernel_owned_turn": True, "task_kind": "literal_response"},
            "contract": {
                "route_policy": {},
                "authority_flags": {},
                "metadata": {},
            },
        },
        "route_summary": {
            "usage_ledger": {
                "offline_tokens": 12,
                "cloud_llm_tokens": 0,
                "cloud_proxy_tokens": 0,
                "other_cloud_tokens": 0,
                "by_provider": {"norllama": 12},
            },
            "local_first_kpi": {
                "offline_tokens": 12,
                "cloud_llm_tokens": 0,
                "status": "on_target",
                "readiness_percent": 100,
            },
            "model": {"completed": 1, "latest": {"model": "gemma3:1b"}},
            "planner": {"latest": {}},
            "route": {"latest": {}},
            "workers": {"by_id": {"spark-150": 1}},
            "spark_evidence_count": 1,
        },
        "events": [
            {
                "event_type": "model.completed",
                "category": "model",
                "payload": {
                    "route_receipt": {
                        "phase": "literal_response",
                        "task_kind": "chat",
                        "selected_model": "qwen3.6:27b",
                        "selected_worker": "spark-150",
                        "observed_worker": "spark-150",
                        "observed_worker_source": "gateway_response",
                        "execution_mode": "live",
                        "output_shape": "complete",
                        "cloud_proxy": False,
                        "request_id": "req-turn-test",
                        "client_request_id": "req-turn-test",
                        "gateway_request_id": "gw-turn-test",
                        "invocation_id": "worker:turn-test:work:1:model",
                        "receipt_audit": {"status": "pass", "pass": True},
                    }
                },
                "completion_gate": {"status": "pass", "gate_passed": True},
            }
        ],
    }

    receipt = acceptance._receipt_from_activity_snapshot("turn-test", snapshot)

    assert receipt["available"] is True
    assert receipt["job_status"] == "done"
    assert receipt["kernel_owned_turn"] is True
    assert receipt["task_kind"] == "chat"
    assert receipt["receipt_task_kind"] == "chat"
    assert receipt["receipt_phase"] == "literal_response"
    assert receipt["envelope_task_kind"] == "literal_response"
    assert receipt["selected_worker"] == "spark-150"
    assert receipt["observed_worker"] == "spark-150"
    assert receipt["observed_worker_source"] == "gateway_response"
    assert receipt["execution_mode"] == "live"
    assert receipt["output_shape"] == "complete"
    assert receipt["request_id"] == "req-turn-test"
    assert receipt["client_request_id"] == "req-turn-test"
    assert receipt["gateway_request_id"] == "gw-turn-test"
    assert receipt["invocation_id"] == "worker:turn-test:work:1:model"
    assert receipt["local_tokens"] == 12
    assert receipt["goal_local_tokens"] == 12
    assert receipt["ledger_cloud_tokens"] == 0
    assert receipt["local_first_status"] == "on_target"


def test_event_worker_id_prefers_norllama_model_attribution():
    payload = {
        "worker_id": "kernel-worker",
        "attribution": {
            "worker_id": "mac-mini-133",
            "worker_endpoint": "http://192.168.2.133:18151",
        },
        "metadata": {
            "norllama_receipt": {
                "metadata": {
                    "route_receipt": {
                        "selected_worker": "spark-150",
                    }
                }
            }
        },
    }

    assert acceptance._event_worker_id(payload) == "spark-150"


def test_validate_acceptance_passes_complete_local_receipt():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r2",
    )
    job_id = "turn-norman-test"
    probe = {
        "ok": True,
        "ask_job_id": job_id,
        "ask": {"console_runtime_job_id": job_id},
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
            "last_response_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "target_worker": "spark-151",
        "target_worker_mode": "explicit",
        "gateway_selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "request_id": "req-acceptance",
        "client_request_id": "req-acceptance",
        "gateway_request_id": "gw-acceptance",
        "invocation_id": "worker:turn-norman-test:work:1:model",
        "invocations": route_invocations(),
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is True
    assert failures == []
    assert proof["receipt"]["selected_worker"] == "spark-151"
    assert proof["receipt"]["observed_worker"] == "spark-151"
    assert proof["receipt"]["gateway_request_id"] == "gw-acceptance"


def test_validate_acceptance_accepts_literal_phase_with_chat_task_kind():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r2-phase",
    )
    job_id = "turn-norman-test-phase"
    probe = {
        "ok": True,
        "ask_job_id": job_id,
        "ask": {"console_runtime_job_id": job_id},
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
            "last_response_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "chat",
        "receipt_task_kind": "chat",
        "receipt_phase": "literal_response",
        "task_kinds": ["chat"],
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "request_id": "req-phase",
        "client_request_id": "req-phase",
        "gateway_request_id": "gw-phase",
        "invocation_id": "worker:turn-norman-test-phase:literal_response:1:model",
        "invocations": route_invocations(phase="literal_response"),
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is True
    assert failures == []
    assert proof["receipt"]["task_kind"] == "chat"
    assert proof["receipt"]["receipt_phase"] == "literal_response"


def test_validate_acceptance_rejects_locked_route_model_mismatch():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r2-mismatch",
    )
    job_id = "turn-norman-test-mismatch"
    probe = {
        "ok": True,
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "invocations": route_invocations("qwen3.6:35b-a3b-q4_K_M"),
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is False
    assert proof["route_proof_passed"] is False
    assert any(
        "locked route literal_response effective_runtime_model is "
        "qwen3.6:35b-a3b-q4_K_M, expected qwen3.6:27b" == failure
        for failure in failures
    )


def test_validate_acceptance_rejects_cloud_tokens_and_missing_worker():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r3",
    )
    job_id = "turn-norman-test"
    probe = {
        "ok": True,
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "",
        "observed_worker": "",
        "observed_worker_source": "",
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 2,
        "ledger_cloud_tokens": 2,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "watch",
        "model_completed_count": 1,
    }

    passed, failures, _proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is False
    assert "receipt recorded cloud LLM tokens" in failures
    assert "usage ledger recorded cloud/proxy tokens" in failures
    assert "receipt did not record worker attribution" in failures
    assert "receipt did not record observed worker attribution" in failures
    assert "local-first KPI is watch" in failures


def test_validate_acceptance_rejects_stale_status_job_id():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r-stale-job",
    )
    job_id = "turn-norman-stale"
    probe = {
        "ok": True,
        "before_job_id": job_id,
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "invocations": route_invocations(),
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is False
    assert "TUI did not expose a fresh console-runtime job id" in failures
    assert proof["before_job_id"] == job_id


def test_validate_acceptance_prefers_ask_owned_job_over_stale_status():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r-ask-job",
    )
    stale_job_id = "turn-norman-stale"
    fresh_job_id = "turn-norman-fresh"
    probe = {
        "ok": True,
        "before_job_id": stale_job_id,
        "ask_job_id": fresh_job_id,
        "ask": {"console_runtime_job_id": fresh_job_id},
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": stale_job_id,
            "last_response_console_runtime_job_id": fresh_job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": fresh_job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "invocations": route_invocations(),
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is True
    assert failures == []
    assert proof["job_id"] == fresh_job_id
    assert proof["status_job_id"] == stale_job_id


def test_job_id_from_probe_uses_fresh_status_when_ask_job_is_previous_turn():
    probe = {
        "before_job_id": "turn-previous",
        "ask_job_id": "turn-previous",
        "ask": {"console_runtime_job_id": "turn-previous"},
        "status": {
            "last_console_runtime_job_id": "turn-current",
            "last_prompt": "current nonce prompt",
            "last_response": "current nonce response",
        },
    }

    assert acceptance.job_id_from_probe(probe) == "turn-current"


def test_validate_acceptance_rejects_stale_visible_state_despite_route_proof():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r-route-proof-visible-lag",
    )
    job_id = "turn-norman-visible-lag"
    probe = {
        "ok": True,
        "ask_job_id": job_id,
        "ask": {"console_runtime_job_id": job_id},
        "status": {
            "pending": False,
            "last_prompt": "older prompt",
            "last_response": "older response",
            "last_error": "",
            "last_console_runtime_job_id": "turn-norman-older",
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "invocations": route_invocations(),
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is False
    assert proof["route_proof_passed"] is True
    assert proof["visible_delivery_passed"] is False
    assert "latest prompt does not contain the run nonce" in failures
    assert "visible response did not contain the expected literal" in failures


def test_validate_acceptance_can_require_spark_evidence():
    target = acceptance.default_targets()["norman"]
    scenario = acceptance.AcceptanceScenario(
        name="spark_required",
        message_template="Reply exactly: {expected_response}",
        expected_template="DONE spark {nonce}",
        min_spark_evidence_count=1,
    )
    run = acceptance.materialize_scenario(scenario, target, run_id="r4")
    job_id = "turn-norman-spark-test"
    probe = {
        "ok": True,
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 77,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 0,
    }

    passed, failures, _proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is False
    assert any("spark evidence count" in failure for failure in failures)


def test_validate_acceptance_uses_model_receipt_task_kind_for_unlocked_route():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["auto_route_local"],
        target,
        run_id="r-auto",
    )
    job_id = "turn-norman-auto"
    probe = {
        "ok": True,
        "ask_job_id": job_id,
        "ask": {"console_runtime_job_id": job_id},
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": (
                '{"unhealthy_service":"billing","evidence":"timeout",'
                f'"nonce":"{run.nonce}"}}'
            ),
            "last_error": "",
            "last_console_runtime_job_id": job_id,
            "last_response_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "chat",
        "receipt_task_kind": "chat",
        "envelope_task_kind": "visible_response",
        "selected_model": "qwen3.6:27b",
        "selected_worker": "spark-151",
        "target_worker": "spark-151",
        "target_worker_mode": "explicit",
        "gateway_selected_worker": "spark-151",
        "observed_worker": "spark-151",
        "observed_worker_source": "gateway_response",
        "request_id": "req-auto",
        "client_request_id": "req-auto",
        "gateway_request_id": "gw-auto",
        "invocation_id": "worker:turn-norman-auto:verify:3:model",
        "execution_mode": "live",
        "output_shape": "complete",
        "local_tokens": 109,
        "cloud_proxy": False,
        "receipt_audit": {"status": "pass", "pass": True},
        "completion_gate": {"status": "pass", "gate_passed": True},
        "goal_local_tokens": 109,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 109},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is True
    assert failures == []
    assert proof["receipt"]["task_kind"] == "chat"
    assert proof["receipt"]["envelope_task_kind"] == "visible_response"


def test_activity_snapshot_reports_phase_level_invocations():
    job_id = "turn-phase-proof"

    def model_event(phase: str, model: str, invocation: str) -> dict[str, object]:
        return {
            "category": "model",
            "event_type": "model.completed",
            "payload": {
                "route_receipt": {
                    "phase": phase,
                    "task_kind": phase if phase != "work" else "chat",
                    "selected_model": model,
                    "route_selected_model": model,
                    "requested_model": model,
                    "effective_runtime_model": model,
                    "selected_worker": "spark-151",
                    "observed_worker": "spark-151",
                    "observed_worker_source": "gateway_response",
                    "execution_mode": "live",
                    "output_shape": "complete",
                    "request_id": f"req-{phase}",
                    "gateway_request_id": f"gw-{phase}",
                    "invocation_id": invocation,
                    "receipt_audit": {"status": "pass", "pass": True},
                    "completion_gate": {"status": "pass", "gate_passed": True},
                }
            },
        }

    receipt = acceptance._receipt_from_activity_snapshot(
        job_id,
        {
            "job": {
                "job_id": job_id,
                "status": "done",
                "last_error": "",
                "contract": {"authority_flags": {"kernel_owned_turn": True}},
                "metadata": {},
            },
            "route_summary": {
                "usage_ledger": {
                    "offline_tokens": 30,
                    "cloud_llm_tokens": 0,
                    "cloud_proxy_tokens": 0,
                    "other_cloud_tokens": 0,
                    "by_provider": {"norllama": 30},
                },
                "local_first_kpi": {
                    "offline_tokens": 30,
                    "cloud_llm_tokens": 0,
                    "status": "on_target",
                },
                "model": {"completed": 3},
                "spark_evidence_count": 3,
            },
            "events": [
                model_event("plan", "qwen3.6:35b-a3b-q4_K_M", "inv-plan"),
                model_event("work", "qwen3.6:27b", "inv-work"),
                model_event("verify", "qwen3.6:27b", "inv-verify"),
            ],
        },
    )

    assert receipt["models_by_phase"] == {
        "plan": "qwen3.6:35b-a3b-q4_K_M",
        "work": "qwen3.6:27b",
        "verify": "qwen3.6:27b",
    }
    assert [item["phase"] for item in receipt["invocations"]] == [
        "plan",
        "work",
        "verify",
    ]
    assert receipt["final_invocation_phase"] == "verify"
    assert receipt["final_effective_model"] == "qwen3.6:27b"
