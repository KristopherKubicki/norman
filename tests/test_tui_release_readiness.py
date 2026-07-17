from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_readiness(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_release_readiness",
        scripts_dir / "tui_release_readiness.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_release_readiness"] = module
    spec.loader.exec_module(module)
    return module


def _fake_tools(monkeypatch, module, *, http_payloads=None, returncode=0):
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    http_payloads = http_payloads or {}

    def fake_which(name):
        return f"/usr/bin/{name}"

    def fake_http(url, *, timeout_seconds):
        assert timeout_seconds == 2
        return http_payloads.get(url, (200, {}))

    def fake_run(command, *, env, timeout_seconds):
        assert timeout_seconds == 2
        commands.append((list(command), env))
        return subprocess.CompletedProcess(command, returncode, "", "")

    monkeypatch.setattr(module.shutil, "which", fake_which)
    monkeypatch.setattr(module, "_http_json", fake_http)
    monkeypatch.setattr(module, "_run_command", fake_run)
    return commands


def test_bedrock_missing_profile_is_a_blocking_contract_failure(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_readiness(monkeypatch)
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "work.config.toml").write_text(
        'model_provider = "amazon-bedrock"\n[aws]\nregion = "us-east-2"\n',
        encoding="utf-8",
    )
    commands = _fake_tools(monkeypatch, module)

    report = module.build_report(
        codex_bin="codex",
        codex_home=str(codex_home),
        service_tier="default",
        norman_health_url="",
        norllama_endpoints=[],
        cloud_token_budget="",
        timeout_seconds=2,
        env={"NORMAN_CODEX_STANDARD_PROFILE_V2": "work"},
    )

    by_id = {check["id"]: check for check in report["checks"]}
    assert report["status"] == "blocked"
    assert report["blockers"] == ["bedrock_credentials_profile_missing"]
    assert by_id["bedrock_credentials_profile_missing"]["blocking"] is True
    assert by_id["bedrock_aws_identity"]["status"] == "skip"
    assert commands == []


def test_bedrock_report_uses_only_read_only_sts_and_no_model_inference(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_readiness(monkeypatch)
    commands = _fake_tools(
        monkeypatch,
        module,
        http_payloads={
            "https://norman.example/health": (200, {"status": "ok"}),
            "https://llm.example/v1/models": (200, {"data": [{"id": "local"}]}),
        },
    )

    report = module.build_report(
        codex_bin="codex",
        codex_home=str(tmp_path / "codex"),
        service_tier="default",
        norman_health_url="https://norman.example/health",
        norllama_endpoints=["https://llm.example"],
        cloud_token_budget="1024",
        timeout_seconds=2,
        env={
            "NORMAN_CODEX_STANDARD_PROFILE_V2": "bedrock-work",
            "NORMAN_CODEX_STANDARD_AWS_PROFILE": "approved-profile",
            "NORMAN_CODEX_STANDARD_AWS_REGION": "us-east-2",
        },
    )

    by_id = {check["id"]: check for check in report["checks"]}
    assert report["status"] == "ready"
    assert by_id["norllama_models"]["status"] == "pass"
    assert by_id["cloud_budget_policy"]["metadata"]["cloud_token_budget"] == 1024
    assert len(commands) == 1
    command, command_env = commands[0]
    assert command == [
        "/usr/bin/aws",
        "--profile",
        "approved-profile",
        "--region",
        "us-east-2",
        "sts",
        "get-caller-identity",
        "--output",
        "json",
    ]
    assert command_env
    assert command_env["AWS_PROFILE"] == "approved-profile"
    assert command_env["AWS_REGION"] == "us-east-2"
    assert all("exec" not in item for item in command)


def test_direct_route_requires_codex_login_but_not_aws_identity(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_readiness(monkeypatch)
    commands = _fake_tools(monkeypatch, module)

    report = module.build_report(
        codex_bin="codex",
        codex_home=str(tmp_path / "codex"),
        service_tier="flex",
        norman_health_url="",
        norllama_endpoints=[],
        cloud_token_budget="",
        timeout_seconds=2,
        env={},
    )

    by_id = {check["id"]: check for check in report["checks"]}
    assert report["status"] == "ready"
    assert by_id["codex_direct_login"]["status"] == "pass"
    assert by_id["bedrock_aws_identity"]["status"] == "skip"
    assert commands == [(["/usr/bin/codex", "login", "status"], None)]


def test_cli_writes_machine_readable_and_markdown_reports(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_readiness(monkeypatch)
    json_output = tmp_path / "release.json"
    markdown_output = tmp_path / "release.md"
    report = {
        "schema": module.SCHEMA,
        "checked_at": 123,
        "status": "ready",
        "blocking": False,
        "blockers": [],
        "summary": {"checks": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "launch": {
            "provider_surface": "aws-bedrock",
            "service_tier": "default",
            "model": "openai.gpt-5.6-sol",
        },
        "checks": [
            {
                "id": "bedrock_aws_identity",
                "status": "pass",
                "blocking": False,
                "detail": "Configured AWS profile passed the read-only STS identity check.",
                "recovery": "",
                "metadata": {},
            }
        ],
    }
    monkeypatch.setattr(module, "build_report", lambda **_: report)

    assert (
        module.main(
            [
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
                "--quiet",
            ]
        )
        == 0
    )

    assert json.loads(json_output.read_text(encoding="utf-8")) == report
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "Status: **READY**" in markdown
    assert "`bedrock_aws_identity`" in markdown


def test_managed_launchers_run_required_preflight_before_codex() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (
        root / "scripts" / "agent_console_template" / "agent_console_launch.sh",
        root / "scripts" / "norman_codex_launch.sh",
    ):
        source = path.read_text(encoding="utf-8")
        assert 'PREFLIGHT_MODE="${NORMAN_CODEX_PREFLIGHT_MODE:-required}"' in source
        assert "run_release_preflight" in source
        assert "--fail-on-blocker" in source
        assert source.index("run_release_preflight") < source.index("run_codex()")


def test_browser_workers_gate_codex_before_launching_a_prompt() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (
        root / "scripts" / "agent_console_template" / "agent_console_web.py",
        root / "scripts" / "norman_codex_web.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "def codex_launch_preflight(service_tier: str)" in source
        assert '"provider_error_kind": "tui_preflight_blocked"' in source
        assert source.index(
            "release_preflight = codex_launch_preflight"
        ) < source.index(
            "cmd = [",
            source.index("def _execute_codex_prompt"),
        )
