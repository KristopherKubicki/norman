from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib import error, request

import pytest


def _load_bbs_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "norman_sms_bbs.py"
    spec = importlib.util.spec_from_file_location(
        "norman_sms_bbs_for_tests", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _settings(module, tmp_path: Path, *, bbs_token: str = ""):
    return module.SmsBbsSettings(
        bind="127.0.0.1",
        port=0,
        state_dir=tmp_path / "state",
        workdir=tmp_path,
        codex_bin="codex",
        model="gpt-5.4",
        service_tier="default",
        timeout_seconds=60,
        bbs_token=bbs_token,
        max_response_chars=1600,
        callback_retry_seconds=1,
    )


def _turn(turn_id: str, sequence: int, message: str) -> dict[str, Any]:
    return {
        "conversation_id": "conversation-1",
        "turn_id": turn_id,
        "sequence": sequence,
        "message": message,
        "callback_url": "http://127.0.0.1:8797/callbacks/sms",
        "source": {"message_sid": f"SM-{turn_id}"},
    }


def test_sidecar_accepts_authenticated_turns_and_resumes_thread(tmp_path) -> None:
    module = _load_bbs_module()
    executions: list[tuple[str, str]] = []
    callbacks: list[tuple[str, str, dict[str, Any]]] = []

    def executor(turn: dict[str, Any], thread_id: str) -> dict[str, Any]:
        executions.append((str(turn["turn_id"]), thread_id))
        return {
            "body": f"Reply to {turn['turn_id']}",
            "bbs_thread_id": thread_id or "codex-thread-1",
        }

    settings = _settings(module, tmp_path, bbs_token="bbs-token")
    processor = module.SmsTurnProcessor(
        state_dir=settings.state_dir / "turns",
        executor=executor,
        callback_token="callback-host-token",
        callback_sender=lambda url, token, completion: callbacks.append(
            (url, token, completion)
        ),
    )
    server = module.create_server(settings, processor)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    def post(payload: Any, token: str = "") -> tuple[int, dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = (
            payload.encode("utf-8")
            if isinstance(payload, str)
            else json.dumps(payload).encode("utf-8")
        )
        req = request.Request(
            f"{base_url}/api/sms/turns",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=2) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        with request.urlopen(f"{base_url}/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["ok"] is True
        assert post(_turn("turn-1", 1, "first"))[0] == 403
        assert post("{", "bbs-token")[0] == 400
        assert post(_turn("turn-1", 1, "first"), "bbs-token") == (
            202,
            {
                "accepted": True,
                "conversation_id": "conversation-1",
                "turn_id": "turn-1",
            },
        )
        processor.process_pending()
        assert post(_turn("turn-2", 2, "second"), "bbs-token")[0] == 202
        processor.process_pending()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)

    persisted = (
        settings.state_dir / "turns" / "conversations" / "conversation-1.json"
    ).read_text(encoding="utf-8")
    assert executions == [("turn-1", ""), ("turn-2", "codex-thread-1")]
    assert [completion["turn_id"] for _, _, completion in callbacks] == [
        "turn-1",
        "turn-2",
    ]
    assert all(token == "callback-host-token" for _, token, _ in callbacks)
    assert "callback-host-token" not in persisted


def test_sidecar_executes_codex_command_and_extracts_new_thread(tmp_path) -> None:
    module = _load_bbs_module()
    settings = _settings(module, tmp_path)
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = Path(command[command.index("-o") + 1])
        output.write_text("SMS reply\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            '{"type":"thread.started","thread_id":"codex-thread-1"}\n',
            "",
        )

    executor = module.CodexSmsExecutor(settings, runner=runner)
    result = executor(_turn("turn-1", 1, "first"), "")

    assert result == {
        "success": True,
        "body": "SMS reply",
        "bbs_thread_id": "codex-thread-1",
    }
    assert calls[0][:8] == [
        "codex",
        "exec",
        "--json",
        "--dangerously-bypass-approvals-and-sandbox",
        "-m",
        "gpt-5.4",
        "-c",
        'service_tier="default"',
    ]
    assert (
        settings.state_dir / "outputs" / "turn-1.txt"
    ).stat().st_mode & 0o777 == 0o600


def test_sidecar_uses_configured_default_model_when_sms_model_is_blank(
    tmp_path,
) -> None:
    module = _load_bbs_module()
    settings = module.SmsBbsSettings(
        **{**_settings(module, tmp_path).__dict__, "model": ""}
    )
    executor = module.CodexSmsExecutor(settings)

    command = executor._command(
        turn=_turn("turn-1", 1, "first"),
        bbs_thread_id="",
        output_path=tmp_path / "reply.txt",
    )

    assert "-m" not in command
    assert "gpt-5.4" not in command


def test_sidecar_classifies_codex_model_errors_without_retaining_output(
    tmp_path, capsys
) -> None:
    module = _load_bbs_module()
    settings = _settings(module, tmp_path)

    def runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "The requested model is unavailable",
        )

    result = module.CodexSmsExecutor(settings, runner=runner)(
        _turn("turn-1", 1, "first"),
        "",
    )

    assert result["success"] is False
    assert json.loads(capsys.readouterr().out) == {
        "event": "sms_codex_failure",
        "failure_class": "model_unavailable",
        "return_code": 1,
    }


def test_new_command_starts_a_clear_new_sms_session() -> None:
    module = _load_bbs_module()

    prompt = module._sms_prompt({"message": " /NEW "})

    assert "new, independent SMS conversation" in prompt
    assert "ready for their next message" in prompt
    assert "Operator message:" not in prompt


def test_regular_sms_prompt_requires_an_immediate_final_response() -> None:
    module = _load_bbs_module()

    prompt = module._sms_prompt({"message": "Check the deployment status."})

    assert "Act on the operator's request now" in prompt
    assert "Do not give a plan, promise a later follow-up" in prompt
    assert (
        "completed results, a concrete blocker, or one necessary clarifying question"
        in prompt
    )


def test_normal_bbs_files_do_not_expose_the_isolated_sms_route() -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"

    for name in ("norman_codex_web.py", "agent_console_template/agent_console_web.py"):
        source = (scripts_dir / name).read_text(encoding="utf-8")
        assert "/api/sms/turns" not in source
        assert "SmsTurnProcessor" not in source


def test_sms_bbs_systemd_unit_uses_the_nvm_aware_codex_launcher() -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    unit = (scripts_dir / "systemd" / "norman-sms-bbs.service").read_text(
        encoding="utf-8"
    )
    launcher = (scripts_dir / "systemd" / "norman-sms-codex").read_text(
        encoding="utf-8"
    )

    assert (
        "NORMAN_CODEX_BIN=/home/kristopher/code/norman/scripts/systemd/norman-sms-codex"
        in unit
    )
    assert "nvm.sh" in launcher
    assert "nvm use --silent default" in launcher


def test_sidecar_stops_after_sigterm_without_deadlocking(tmp_path) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    environment = {
        **os.environ,
        "NORMAN_SMS_BBS_BIND": "127.0.0.1",
        "NORMAN_SMS_BBS_PORT": str(port),
        "NORMAN_SMS_BBS_STATE_DIR": str(tmp_path / "state"),
        "NORMAN_SMS_BBS_WORKDIR": str(tmp_path),
    }
    process = subprocess.Popen(
        [sys.executable, str(scripts_dir / "norman_sms_bbs.py")],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("SMS BBS did not start")
        process.terminate()
        process.wait(timeout=3)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)

    assert process.returncode == 0


def test_sidecar_rejects_non_loopback_binding(tmp_path) -> None:
    module = _load_bbs_module()
    settings = _settings(module, tmp_path)
    public_settings = module.SmsBbsSettings(**{**settings.__dict__, "bind": "0.0.0.0"})
    processor = module.SmsTurnProcessor(
        state_dir=tmp_path / "turns",
        executor=lambda *_args: {},
        callback_token="callback-host-token",
    )

    with pytest.raises(module.SmsBbsError, match="loopback"):
        module.create_server(public_settings, processor)
