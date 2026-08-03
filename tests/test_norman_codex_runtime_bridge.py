from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib import error as urllib_error

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = REPO_ROOT / "scripts" / "norman_codex_runtime_bridge.py"
BRIDGE_ENV_NAMES = (
    "NORMAN_API_BASE_URL",
    "NORMAN_API_TOKEN",
    "NORMAN_CODEX_RUNTIME_BRIDGE_ENABLED",
    "NORMAN_CODEX_RUNTIME_BRIDGE_STRICT",
    "NORMAN_CODEX_RUNTIME_BRIDGE_TIMEOUT_SECONDS",
    "NORMAN_CONSOLE_RUNTIME_API_BASE",
    "NORMAN_CONSOLE_RUNTIME_ENABLED",
    "NORMAN_CONSOLE_RUNTIME_SECRET_NAME",
    "NORMAN_CONSOLE_RUNTIME_TOKEN",
    "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET",
    "NORMAN_KEYS_API_BASE",
    "NORMAN_KEYS_API_TOKEN",
    "NORMAN_KEYS_LANE",
    "NORMAN_KEYS_SECRET_NAME",
    "NORMAN_KEYS_TOKEN",
    "NORMAN_KEYS_URL",
    "NORMAN_SECRET_CMD",
)


class _Response:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _load_bridge(monkeypatch):
    for name in BRIDGE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    module_name = f"norman_codex_runtime_bridge_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _receipt(codex_home: Path) -> dict[str, object]:
    return json.loads(
        (codex_home / "web-bridge" / "terminal_runtime_route_receipt.json").read_text(
            encoding="utf-8"
        )
    )


def test_disabled_bridge_is_fail_open_and_writes_only_to_given_codex_home(
    monkeypatch, tmp_path, capsys
) -> None:
    module = _load_bridge(monkeypatch)
    codex_home = tmp_path / ".codex-work"
    unrelated_home = tmp_path / ".codex"

    assert (
        module.main(["--codex-home", str(codex_home), "--session-id", "work-session"])
        == 0
    )

    receipt_path = codex_home / "web-bridge" / "terminal_runtime_route_receipt.json"
    receipt = _receipt(codex_home)
    assert receipt["status"] == "disabled"
    assert receipt["mode"] == "control_only"
    assert receipt["terminal_execution"] == "native_codex"
    assert receipt["connector_tool_authority"] == "native_codex"
    assert not (unrelated_home / "web-bridge").exists()
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt_path.parent.stat().st_mode) == 0o700
    assert capsys.readouterr().out == ""


def test_norman_keys_route_recording_uses_control_only_native_codex_authority(
    monkeypatch, tmp_path
) -> None:
    module = _load_bridge(monkeypatch)
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://keys.local")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "keys-token")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET", "runtime/work-token")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url == "http://keys.local/v1/secrets/get":
            return _Response({"value": "runtime-token"})
        if request.full_url == "http://norman.local/api/v1/console-runtime/jobs":
            return _Response({"job_id": "terminal-remote-job"})
        if request.full_url.endswith(
            "/console-runtime/jobs/terminal-remote-job/events"
        ):
            return _Response({"event_id": "route-event"})
        raise AssertionError(request.full_url)

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    codex_home = tmp_path / ".codex-work"
    result = module.record_terminal_runtime_route(
        codex_home=codex_home,
        session_id="work-session",
        agent_name="work-codex",
        service_tier="flex",
        model="gpt-5.5",
    )

    assert result == module.BridgeResult(
        status="connected", job_id="terminal-remote-job"
    )
    assert [request.full_url for request, _timeout in requests] == [
        "http://keys.local/v1/secrets/get",
        "http://norman.local/api/v1/console-runtime/jobs",
        "http://norman.local/api/v1/console-runtime/jobs/terminal-remote-job/events",
    ]
    assert all("/runs" not in request.full_url for request, _timeout in requests)
    assert requests[0][0].get_header("Authorization") == "Bearer keys-token"
    assert requests[1][0].get_header("Authorization") == "Bearer runtime-token"

    keys_payload = json.loads(requests[0][0].data.decode("utf-8"))
    job_payload = json.loads(requests[1][0].data.decode("utf-8"))
    event_payload = json.loads(requests[2][0].data.decode("utf-8"))
    assert keys_payload["name"] == "runtime/work-token"
    assert job_payload["route_policy"] == module.ROUTE_POLICY
    assert job_payload["route_policy"]["mode"] == "control_only"
    assert job_payload["authority_flags"] == {
        "source": "norman_codex_runtime_bridge",
        "terminal_execution": "native_codex",
        "connector_tool_authority": "native_codex",
        "advisory_only": True,
    }
    assert job_payload["metadata"]["session_id"] == "work-session"
    assert event_payload["event_type"] == "route.decided"
    assert event_payload["payload"]["route_policy"] == module.ROUTE_POLICY
    assert event_payload["payload"]["connector_tool_authority"] == "native_codex"


def test_secret_command_is_shlex_parsed_and_substitutes_secret_name(
    monkeypatch, tmp_path
) -> None:
    module = _load_bridge(monkeypatch)
    monkeypatch.setenv(
        "NORMAN_SECRET_CMD",
        "/usr/local/bin/norman-secret --name '{name}' --format value",
    )
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET", "runtime/work token")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="token-from-broker\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.resolve_console_runtime_token("work-session") == "token-from-broker"
    assert calls == [
        (
            [
                "/usr/local/bin/norman-secret",
                "--name",
                "runtime/work token",
                "--format",
                "value",
            ],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 1.5,
            },
        )
    ]


def test_terminal_job_ids_are_deterministic_and_isolated_by_codex_home(
    monkeypatch, tmp_path
) -> None:
    module = _load_bridge(monkeypatch)
    work_home = tmp_path / ".codex-work"
    personal_home = tmp_path / ".codex"

    work_id = module.terminal_job_id(work_home, "same-session")

    assert work_id == module.terminal_job_id(work_home, "same-session")
    assert work_id != module.terminal_job_id(personal_home, "same-session")
    assert work_id != module.terminal_job_id(work_home, "other-session")


@pytest.mark.parametrize(
    ("failure", "expected_failure_class"),
    [
        (
            lambda: urllib_error.HTTPError(
                "http://token@norman.local/api/v1/console-runtime/jobs",
                503,
                "unavailable",
                {},
                None,
            ),
            "http_503",
        ),
        (lambda: TimeoutError("runtime endpoint timed out"), "timeout"),
    ],
)
def test_transport_failures_are_fail_open_and_receipts_remain_sanitized(
    monkeypatch, tmp_path, capsys, failure, expected_failure_class
) -> None:
    module = _load_bridge(monkeypatch)
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "runtime-token")
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure()),
    )
    codex_home = tmp_path / ".codex-work"

    assert module.main(["--codex-home", str(codex_home), "--summary"]) == 0

    output = capsys.readouterr().out
    receipt = _receipt(codex_home)
    assert expected_failure_class in output
    assert "runtime-token" not in output
    assert "token@norman.local" not in output
    assert receipt["status"] == "failed"
    assert receipt["failure_class"] == expected_failure_class
    assert "runtime-token" not in json.dumps(receipt)
    assert "norman.local" not in json.dumps(receipt)


def test_missing_token_is_fail_open_and_strict_mode_returns_nonzero(
    monkeypatch, tmp_path, capsys
) -> None:
    module = _load_bridge(monkeypatch)
    monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_API_BASE", "http://norman.local/api/v1")
    codex_home = tmp_path / ".codex-work"

    assert module.main(["--codex-home", str(codex_home), "--summary"]) == 0
    assert _receipt(codex_home)["failure_class"] == "token_unavailable"
    assert "token_unavailable" in capsys.readouterr().out

    monkeypatch.setenv("NORMAN_CODEX_RUNTIME_BRIDGE_STRICT", "1")
    assert module.main(["--codex-home", str(codex_home), "--summary"]) == 1
