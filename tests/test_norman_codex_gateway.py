from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_SCRIPT = REPO_ROOT / "scripts" / "norman_codex_launch.sh"
TOKEN_HELPER = REPO_ROOT / "scripts" / "norman_codex_gateway_token.py"
TEMPLATE_LAUNCH_SCRIPT = (
    REPO_ROOT / "scripts" / "agent_console_template" / "agent_console_launch.sh"
)
SUPERVISOR_SCRIPT = REPO_ROOT / "scripts" / "norman_codex_supervisor.sh"
TEMPLATE_SUPERVISOR_SCRIPT = (
    REPO_ROOT / "scripts" / "agent_console_template" / "agent_console_supervisor.sh"
)


def _load_token_helper():
    module_name = f"norman_codex_gateway_token_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, TOKEN_HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _clear_gateway_broker_environment(monkeypatch) -> None:
    for name in (
        "NORMAN_CODEX_GATEWAY_TOKEN_SECRET",
        "NORMAN_CODEX_GATEWAY_TOKEN_TIMEOUT_SECONDS",
        "NORMAN_CODEX_GATEWAY_REQUESTER_ID",
        "NORMAN_CODEX_LANE",
        "NORMAN_CODEX_SESSION",
        "NORMAN_CRED_BIN",
        "NORMAN_KEYS_API_BASE",
        "NORMAN_KEYS_API_TOKEN",
        "NORMAN_KEYS_LANE",
        "NORMAN_KEYS_REQUESTER_ID",
        "NORMAN_KEYS_TARGET_HOST",
        "NORMAN_KEYS_TIMEOUT_SECONDS",
        "NORMAN_KEYS_TOKEN",
        "NORMAN_KEYS_URL",
        "NORMAN_SECRET_CMD",
    ):
        monkeypatch.delenv(name, raising=False)


def test_gateway_token_helper_uses_norman_secret_command_placeholder(
    monkeypatch, capsys
) -> None:
    module = _load_token_helper()
    _clear_gateway_broker_environment(monkeypatch)
    monkeypatch.setenv(
        "NORMAN_SECRET_CMD",
        "/usr/local/bin/norman-keys --lease {name} --format value",
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="brokered-token\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main(["--secret", "norman/gateway token"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "brokered-token\n"
    assert captured.err == ""
    assert calls == [
        (
            [
                "/usr/local/bin/norman-keys",
                "--lease",
                "norman/gateway token",
                "--format",
                "value",
            ],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 5.0,
            },
        )
    ]


def test_gateway_token_helper_requests_norman_keys(monkeypatch, capsys) -> None:
    module = _load_token_helper()
    _clear_gateway_broker_environment(monkeypatch)
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://keys.norman.test")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "keys-token")
    monkeypatch.setenv("NORMAN_KEYS_REQUESTER_ID", "gateway-test")
    monkeypatch.setenv("NORMAN_CODEX_SESSION", "session-test")
    monkeypatch.setenv("NORMAN_KEYS_LANE", "test-lane")
    monkeypatch.setattr(module.socket, "gethostname", lambda: "cli-host")
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"secret": "keys-token-value"}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    assert module.main(["--secret", "norman/prompt-proxy-token"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "keys-token-value\n"
    assert captured.err == ""
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == "http://keys.norman.test/v1/secrets/get"
    assert request.get_header("Authorization") == "Bearer keys-token"
    assert timeout == 5.0
    assert json.loads(request.data.decode("utf-8")) == {
        "lane": "test-lane",
        "name": "norman/prompt-proxy-token",
        "reason": "Codex CLI Norman gateway bearer token",
        "requester_id": "gateway-test",
        "session_id": "session-test",
        "target_host": "cli-host",
    }


def test_gateway_token_helper_fails_closed_without_approved_broker(
    monkeypatch, capsys
) -> None:
    module = _load_token_helper()
    _clear_gateway_broker_environment(monkeypatch)
    monkeypatch.setattr(module, "DEFAULT_BROKER_COMMAND", Path("/missing/broker"))
    monkeypatch.setenv("NORMAN_PROMPT_PROXY_TOKEN", "must-not-be-read")

    assert module.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no approved broker is configured" in captured.err


def test_gateway_token_helper_uses_installed_broker_by_default(
    monkeypatch, capsys, tmp_path
) -> None:
    module = _load_token_helper()
    _clear_gateway_broker_environment(monkeypatch)
    broker = tmp_path / "gateway-broker"
    broker.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    broker.chmod(0o700)
    monkeypatch.setattr(module, "DEFAULT_BROKER_COMMAND", broker)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="brokered-token\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main(["--secret", "infra/prompt-proxy-token"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "brokered-token\n"
    assert captured.err == ""
    assert calls == [
        (
            [str(broker), "get", "infra/prompt-proxy-token"],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 5.0,
            },
        )
    ]


def test_gateway_token_helper_falls_back_when_scoped_broker_rejects_token_alias(
    monkeypatch, capsys, tmp_path
) -> None:
    module = _load_token_helper()
    _clear_gateway_broker_environment(monkeypatch)
    scoped_broker = tmp_path / "networking-broker"
    installed_broker = tmp_path / "gateway-broker"
    for broker in (scoped_broker, installed_broker):
        broker.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        broker.chmod(0o700)
    monkeypatch.setenv("NORMAN_SECRET_CMD", str(scoped_broker))
    monkeypatch.setattr(module, "DEFAULT_BROKER_COMMAND", installed_broker)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == str(scoped_broker):
            raise subprocess.CalledProcessError(1, command, stderr="alias denied")
        return SimpleNamespace(stdout="brokered-token\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main(["--secret", "networking/prompt-proxy-token"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "brokered-token\n"
    assert captured.err == ""
    assert [command for command, _kwargs in calls] == [
        [str(scoped_broker), "get", "networking/prompt-proxy-token"],
        [str(installed_broker), "get", "networking/prompt-proxy-token"],
    ]


def test_gateway_token_helper_does_not_use_cred_as_a_fallback(
    monkeypatch, capsys, tmp_path
) -> None:
    module = _load_token_helper()
    _clear_gateway_broker_environment(monkeypatch)
    cred = tmp_path / "cred"
    cred.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    cred.chmod(0o700)
    monkeypatch.setattr(module, "DEFAULT_BROKER_COMMAND", Path("/missing/broker"))
    monkeypatch.setenv("NORMAN_CRED_BIN", str(cred))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="vault-token\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main(["--secret", "norman/prompt-proxy-token"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no approved broker is configured" in captured.err
    assert calls == []


def _write_codex_stub(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["CODEX_ARGS_PATH"], "w", encoding="utf-8") as handle:
    json.dump(sys.argv[1:], handle)
if os.environ.get("CODEX_ENV_PATH"):
    with open(os.environ["CODEX_ENV_PATH"], "w", encoding="utf-8") as handle:
        json.dump(
            {
                "PYTEST_XDIST_AUTO_NUM_WORKERS": os.environ.get(
                    "PYTEST_XDIST_AUTO_NUM_WORKERS"
                ),
                "NORMAN_TUI_NO_DIRECT_VAULT": os.environ.get(
                    "NORMAN_TUI_NO_DIRECT_VAULT"
                ),
            },
            handle,
        )
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _install_test_managed_secret_policy(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    requirements_path = tmp_path / "requirements.toml"
    managed_guard_path = tmp_path / "managed" / "norman_codex_secret_guard.py"
    managed_guard_path.parent.mkdir()
    shutil.copy2(
        REPO_ROOT / "scripts" / "norman_codex_secret_guard.py",
        managed_guard_path,
    )
    managed_guard_path.chmod(0o755)
    result = subprocess.run(
        [
            sys.executable,
            str(managed_guard_path),
            "--install-managed-policy",
            "--requirements-path",
            str(requirements_path),
            "--managed-guard-path",
            str(managed_guard_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    environment["NORMAN_CODEX_REQUIREMENTS_PATH"] = str(requirements_path)
    environment["NORMAN_CODEX_MANAGED_SECRET_GUARD"] = str(managed_guard_path)


def _launcher_environment(tmp_path: Path, codex_binary: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(("NORMAN_CODEX_", "HOUSEBOT_CODEX_")):
            environment.pop(key)
    environment.pop("CODEX_HOME", None)
    environment.update(
        {
            "CODEX_ARGS_PATH": str(tmp_path / "codex-args.json"),
            "CODEX_HOME": str(tmp_path / "codex-home"),
            "NORMAN_CODEX_BIN": str(codex_binary),
            "NORMAN_CODEX_PREFLIGHT_MODE": "off",
            "NORMAN_CODEX_PROFILE_CONFIG_FLAG": "--profile",
            "NORMAN_CODEX_PROMPT_FILE": str(tmp_path / "missing-prompt.txt"),
            "NORMAN_CODEX_RUNTIME_BRIDGE_SCRIPT": str(
                tmp_path / "missing-runtime-bridge.py"
            ),
            "NORMAN_CODEX_WORKDIR": str(tmp_path),
        }
    )
    _install_test_managed_secret_policy(tmp_path, environment)
    return environment


def _run_launcher(
    tmp_path: Path,
    environment: dict[str, str],
    launch_script: Path = LAUNCH_SCRIPT,
) -> list[str]:
    result = subprocess.run(
        [str(launch_script)],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((tmp_path / "codex-args.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("launch_source", (LAUNCH_SCRIPT, TEMPLATE_LAUNCH_SCRIPT))
def test_launchers_prefer_managed_norman_codex_home(
    tmp_path: Path, launch_source: Path
) -> None:
    codex_binary = tmp_path / "codex"
    _write_codex_stub(codex_binary)
    environment = _launcher_environment(tmp_path, codex_binary)
    managed_home = tmp_path / "managed-codex-home"
    environment["NORMAN_CODEX_HOME"] = str(managed_home)
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    launch_script = launch_dir / launch_source.name
    shutil.copy2(launch_source, launch_script)
    shutil.copy2(
        REPO_ROOT / "scripts" / "norman_codex_secret_guard.py",
        launch_dir / "norman_codex_secret_guard.py",
    )
    launch_script.chmod(0o700)

    _run_launcher(tmp_path, environment, launch_script)

    assert (managed_home / ".prompt_sha256").exists()


@pytest.mark.parametrize(
    "supervisor_source",
    (SUPERVISOR_SCRIPT, TEMPLATE_SUPERVISOR_SCRIPT),
)
def test_supervisors_prefer_managed_norman_codex_home(
    supervisor_source: Path,
) -> None:
    source = supervisor_source.read_text(encoding="utf-8")

    assert 'CODEX_HOME="${NORMAN_CODEX_HOME:-${CODEX_HOME:-}}"' in source
    assert "Norman Codex home is not writable" in source
    assert "launcher exited before the tmux session became healthy" in source


@pytest.mark.parametrize("launch_source", (LAUNCH_SCRIPT, TEMPLATE_LAUNCH_SCRIPT))
def test_launchers_require_the_managed_secret_guard(
    tmp_path: Path, launch_source: Path
) -> None:
    codex_binary = tmp_path / "codex"
    _write_codex_stub(codex_binary)
    environment = _launcher_environment(tmp_path, codex_binary)
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    launch_script = launch_dir / launch_source.name
    shutil.copy2(launch_source, launch_script)
    shutil.copy2(
        REPO_ROOT / "scripts" / "norman_codex_secret_guard.py",
        launch_dir / "norman_codex_secret_guard.py",
    )
    launch_script.chmod(0o700)
    arguments = _run_launcher(tmp_path, environment, launch_script)

    assert "--dangerously-bypass-hook-trust" not in arguments
    assert "features.hooks=true" not in arguments
    assert not (tmp_path / "codex-home" / "hooks.json").exists()


@pytest.mark.parametrize("launch_source", (LAUNCH_SCRIPT, TEMPLATE_LAUNCH_SCRIPT))
def test_launchers_export_bounded_pytest_xdist_auto_workers(
    tmp_path: Path, launch_source: Path
) -> None:
    codex_binary = tmp_path / "codex"
    _write_codex_stub(codex_binary)
    environment = _launcher_environment(tmp_path, codex_binary)
    environment["CODEX_ENV_PATH"] = str(tmp_path / "codex-env.json")
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    launch_script = launch_dir / launch_source.name
    shutil.copy2(launch_source, launch_script)
    shutil.copy2(
        REPO_ROOT / "scripts" / "norman_codex_secret_guard.py",
        launch_dir / "norman_codex_secret_guard.py",
    )
    launch_script.chmod(0o700)

    _run_launcher(tmp_path, environment, launch_script)

    exported_environment = json.loads(
        (tmp_path / "codex-env.json").read_text(encoding="utf-8")
    )
    assert exported_environment == {
        "PYTEST_XDIST_AUTO_NUM_WORKERS": "4",
        "NORMAN_TUI_NO_DIRECT_VAULT": "1",
    }


@pytest.mark.parametrize("launch_source", (LAUNCH_SCRIPT, TEMPLATE_LAUNCH_SCRIPT))
def test_launchers_reject_invalid_pytest_xdist_auto_worker_count(
    tmp_path: Path, launch_source: Path
) -> None:
    codex_binary = tmp_path / "codex"
    _write_codex_stub(codex_binary)
    environment = _launcher_environment(tmp_path, codex_binary)
    environment["NORMAN_CODEX_PYTEST_XDIST_AUTO_WORKERS"] = "0"

    result = subprocess.run(
        [str(launch_source)],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 2
    assert (
        "NORMAN_CODEX_PYTEST_XDIST_AUTO_WORKERS must be a positive integer."
        in result.stderr
    )


def test_launcher_keeps_direct_bedrock_as_the_default(tmp_path) -> None:
    codex_binary = tmp_path / "codex"
    _write_codex_stub(codex_binary)
    environment = _launcher_environment(tmp_path, codex_binary)

    arguments = _run_launcher(tmp_path, environment)

    assert "--profile" not in arguments
    assert "norman-gateway" not in arguments
    assert arguments[arguments.index("-m") + 1] == "openai.gpt-5.6-terra"
    assert (tmp_path / "codex-home" / "norman-gateway.config.toml").exists() is False


def test_launcher_configures_opt_in_norman_gateway(tmp_path) -> None:
    codex_binary = tmp_path / "codex"
    _write_codex_stub(codex_binary)
    environment = _launcher_environment(tmp_path, codex_binary)
    environment.update(
        {
            "NORMAN_CODEX_PROVIDER": "norman",
            "NORMAN_CODEX_GATEWAY_BASE_URL": "https://gateway.norman.test/v1",
            "NORMAN_CODEX_GATEWAY_TOKEN_SECRET": "norman/gateway-token",
        }
    )

    arguments = _run_launcher(tmp_path, environment)

    profile_flag_index = arguments.index("--profile")
    assert arguments[profile_flag_index + 1] == "norman-gateway"
    assert arguments[arguments.index("-m") + 1] == "norman-code"
    assert not any("service_tier" in argument for argument in arguments)
    assert not any("model_reasoning_effort" in argument for argument in arguments)

    profile_path = tmp_path / "codex-home" / "norman-gateway.config.toml"
    profile = profile_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(profile_path.stat().st_mode) == 0o600
    assert 'model_provider = "norman"' in profile
    assert 'name = "Norman model gateway"' in profile
    assert 'base_url = "https://gateway.norman.test/v1"' in profile
    assert 'wire_api = "responses"' in profile
    assert "stream_idle_timeout_ms = 1200000" in profile
    assert f'command = "{TOKEN_HELPER}"' in profile
    assert 'args = ["--secret", "norman/gateway-token"]' in profile
    assert "timeout_ms = 5000" in profile
    assert "refresh_interval_ms = 300000" in profile
    assert "env_key" not in profile
    assert "experimental_bearer_token" not in profile
    assert "requires_openai_auth" not in profile
