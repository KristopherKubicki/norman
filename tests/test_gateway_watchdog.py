import json
from types import SimpleNamespace

import pytest

from scripts import gateway_watchdog as watchdog
from scripts import codex_gateway_status as client
from scripts import codex_rescue as rescue

SERVICE = {
    "unit": "norman-production@abcdef01.service",
    "ActiveState": "active",
    "SubState": "running",
    "UnitFileState": "enabled",
}


def test_watchdog_waits_through_startup_then_recovers_once():
    first, repair = watchdog.observe({}, SERVICE, 0, 1000, 999, False)
    assert first["phase"] == "recovering" and not repair
    later, repair = watchdog.observe(first, SERVICE, 0, 1180, 999, False)
    assert repair
    later["restart_attempts"] = [1180]
    assert not watchdog.observe(later, SERVICE, 0, 1200, 999, False)[1]


@pytest.mark.parametrize(
    "change,code,maintenance,uptime",
    [
        ({"ActiveState": "deactivating"}, 0, False, 999),
        ({"ActiveState": "activating"}, 0, False, 999),
        ({"ActiveState": "unknown"}, 0, False, 999),
        ({"UnitFileState": "disabled"}, 0, False, 999),
        ({}, 503, False, 999),
        ({}, 200, False, 999),
        ({}, 0, True, 999),
        ({}, 0, False, 30),
    ],
)
def test_watchdog_does_not_interrupt_maintenance_startup_or_http_responses(
    change, code, maintenance, uptime
):
    _, repair = watchdog.observe(
        {"down_since": 1000}, {**SERVICE, **change}, code, 1500, uptime, maintenance
    )
    assert not repair


def test_watchdog_circuit_breaker_and_recovered_health():
    state = {"down_since": 1000, "restart_attempts": [1100, 2100]}
    result, repair = watchdog.observe(state, SERVICE, 0, 3300, 999, False)
    assert not repair and len(result["restart_attempts"]) == 2
    result, repair = watchdog.observe(state, SERVICE, 200, 3300, 999, False)
    assert result["phase"] == "ready" and result["down_since"] is None
    assert result["restart_attempts"] == state["restart_attempts"]


def test_status_atomic_and_no_private_service_details(tmp_path):
    state, _ = watchdog.observe({}, SERVICE, 200, 1000, 999, False)
    path = tmp_path / "status.json"
    watchdog.write_state(path, state)
    assert watchdog.read_state(path) == state
    assert "unit" not in json.dumps(state)
    assert path.stat().st_mode & 0o777 == 0o644


def test_stale_ready_status_is_not_reported_as_ready(monkeypatch):
    from contextlib import contextmanager
    from io import BytesIO

    @contextmanager
    def open_response(*args, **kwargs):
        yield BytesIO(
            json.dumps(
                {
                    "schema": watchdog.SCHEMA,
                    "checked_at": 900,
                    "phase": "ready",
                    "message": "Ready",
                }
            ).encode()
        )

    monkeypatch.setattr(client.urllib.request, "urlopen", open_response)
    monkeypatch.setattr(client.time, "time", lambda: 1000)
    assert client.get_status("https://gateway.test/v1")["phase"] == "stale"


def test_client_wait_expires_without_starting_or_resetting_session(monkeypatch, capsys):
    monkeypatch.setattr(
        client,
        "get_status",
        lambda *a, **k: {"phase": "unreachable", "message": "offline"},
    )
    assert not client.wait_for_gateway("https://keystone.kris.openbrand.com/v1", 0)
    assert "existing history is preserved" in capsys.readouterr().err


def test_rescue_scope_stays_on_local_worker_without_tools(monkeypatch):
    calls = []

    def request(base, path, payload=None, timeout=5):
        calls.append((base, path, payload))
        if path == "/readyz":
            return {"ready": True, "policy": {"production_route_eligible": True}}
        if path == "/api/ps":
            return {"models": [{"model": "qwen3.8:27b"}]}
        if path == "/v1/models":
            return {
                "data": [
                    {
                        "id": "qwen3.8:27b",
                        "provider": "ollama",
                        "hosts": ["http://127.0.0.1:11434"],
                    }
                ]
            }
        return {"choices": [{"message": {"content": "Check backend startup logs."}}]}

    monkeypatch.setattr(rescue, "request", request)
    result = rescue.diagnose("work", "connection refused")
    assert result["diagnosis"]
    assert all(base == rescue.WORKERS["work"] for base, _, _ in calls)
    assert "tools" not in calls[-1][2]
    assert int(rescue.HEADERS["X-Norllama-Peer-Hop"]) > 1000


def test_rescue_refuses_invalid_policy_before_prompt_delivery(monkeypatch):
    calls = []
    monkeypatch.setattr(
        rescue, "request", lambda *a, **k: calls.append(a) or {"ready": False}
    )
    with pytest.raises(ValueError, match="policy"):
        rescue.diagnose("work", "connection refused")
    assert len(calls) == 1


def test_rescue_refuses_nonlocal_backend_and_oversize_prompt():
    with pytest.raises(ValueError):
        rescue.select_model(
            {
                "data": [
                    {
                        "id": "qwen",
                        "provider": "ollama",
                        "hosts": ["http://192.168.40.150:11434"],
                    }
                ]
            }
        )
    with pytest.raises(ValueError):
        rescue.diagnose("work", "x" * 32769)


def test_external_observer_waits_and_bounds_advisory_calls(monkeypatch):
    import sys
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import gateway_observer

    failed = {"phase": "unreachable"}
    first, analyze = gateway_observer.update({}, failed, 1000)
    assert not analyze
    later, analyze = gateway_observer.update(first, failed, 1180)
    assert analyze
    later["last_diagnosis_attempt"] = 1180
    assert not gateway_observer.update(later, failed, 1300)[1]
    ready, analyze = gateway_observer.update(later, {"phase": "ready"}, 1400)
    assert not analyze and ready["down_since"] is None


def test_http_health_with_invalid_body_is_not_a_restart_trigger(monkeypatch):
    from io import BytesIO

    monkeypatch.setattr(
        watchdog.urllib.request, "urlopen", lambda *a, **k: BytesIO(b"not json")
    )
    code = watchdog.health_probe()
    assert code == 503
    assert not watchdog.observe({"down_since": 1000}, SERVICE, code, 1500, 999, False)[
        1
    ]


def test_clock_rollback_does_not_reset_restart_budget():
    state = {"down_since": 1000, "restart_attempts": [1800, 2000]}
    result, repair = watchdog.observe(state, SERVICE, 0, 1700, 999, False)
    assert not repair
    assert result["restart_attempts"] == [1800, 2000]


def test_restart_budget_is_written_before_failed_systemctl_request(
    tmp_path, monkeypatch
):
    path = tmp_path / "status.json"
    watchdog.write_state(path, {"down_since": 1000})
    monkeypatch.setattr(watchdog.time, "time", lambda: 1500)
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 1500)
    monkeypatch.setattr(
        watchdog,
        "service_state",
        lambda: {**SERVICE, "ActiveEnterTimestampMonotonic": "1000000"},
    )
    monkeypatch.setattr(watchdog, "health_probe", lambda: 0)
    monkeypatch.setattr(
        "sys.argv",
        [
            "watchdog",
            "--state",
            str(path),
            "--maintenance",
            str(tmp_path / "maintenance"),
            "--repair",
        ],
    )

    def restart(command, **kwargs):
        assert command == ["systemctl", "--no-block", "try-restart", SERVICE["unit"]]
        assert watchdog.read_state(path)["restart_attempts"] == [1500]
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(watchdog.subprocess, "run", restart)
    assert watchdog.main() == 0
    assert watchdog.read_state(path)["restart_request_succeeded"] is False


def test_http_status_access_denial_is_actionable_and_not_retried(monkeypatch):
    import urllib.error

    def denied(*a, **k):
        raise urllib.error.HTTPError("https://example.test", 403, "Forbidden", {}, None)

    monkeypatch.setattr(client.urllib.request, "urlopen", denied)
    assert client.get_status("https://example.test/v1")["phase"] == "access_denied"
    assert not client.wait_for_gateway("https://example.test/v1", 120)


def test_work_status_uses_the_work_frontdoor_path(monkeypatch):
    seen = []

    def offline(url, **kwargs):
        seen.append(url)
        raise OSError("offline")

    monkeypatch.setattr(client.urllib.request, "urlopen", offline)
    client.get_status("https://norman.home.arpa/work/v1/")
    assert seen == ["https://norman.home.arpa/work/_gateway/status"]


@pytest.mark.parametrize("scope", ["work", "personal"])
def test_rescue_accepts_only_owning_worker_lan_address(scope):
    from urllib.parse import urlsplit

    own = rescue.WORKERS[scope]
    other = rescue.WORKERS["personal" if scope == "work" else "work"]
    row = {
        "id": "qwen3.8:27b",
        "provider": "ollama",
        "hosts": ["http://" + urlsplit(own).hostname + ":11435"],
    }
    assert rescue.select_model({"data": [row]}, worker=own) == row["id"]
    row["hosts"].append("http://" + urlsplit(other).hostname + ":11435")
    with pytest.raises(ValueError, match="No worker-local"):
        rescue.select_model({"data": [row]}, worker=own)


def test_rescue_check_never_reads_stdin_or_sends_a_prompt(monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["codex-rescue", "--scope", "personal", "--check"])
    monkeypatch.setattr(
        sys.stdin, "read", lambda *a: pytest.fail("must not read stdin")
    )
    calls = []
    docs = {
        "/readyz": {"ready": True, "policy": {"production_route_eligible": True}},
        "/v1/models": {
            "data": [
                {
                    "id": "qwen3.8:27b",
                    "provider": "ollama",
                    "hosts": ["http://192.168.40.150:11435"],
                }
            ]
        },
        "/api/ps": {"models": [{"name": "qwen3.8:27b"}]},
    }

    def request(base, path, payload=None, timeout=5):
        assert base == rescue.WORKERS["personal"]
        assert payload is None
        calls.append(path)
        return docs[path]

    monkeypatch.setattr(rescue, "request", request)
    assert rescue.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["generation_performed"] is False
    assert result["session_history_accessed"] is False
    assert result["resident"] is True
    docs["/api/ps"]["models"] = []
    with pytest.raises(ValueError, match="not resident"):
        rescue.diagnose("personal", "check this outage")
    assert all(path != "/v1/chat/completions" for path in calls)
