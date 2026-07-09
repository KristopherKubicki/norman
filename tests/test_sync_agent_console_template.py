from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path


def _load_sync_script(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_PATH" not in os.environ:
        monkeypatch.setenv(
            "NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_PATH",
            str(Path(__file__).with_name("__missing_bedrock_region_smoke__.json")),
        )
    if (
        "NORMAN_SYNC_NON_WORK_BEDROCK_PROFILE_SOURCE" not in os.environ
        and "NORMAN_SYNC_TEST_ALLOW_DEFAULT_NON_WORK_BEDROCK_SOURCE" not in os.environ
    ):
        monkeypatch.setenv(
            "NORMAN_SYNC_NON_WORK_BEDROCK_PROFILE_SOURCE",
            str(Path(__file__).with_name("__missing_non_work_bedrock__.toml")),
        )
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "sync_agent_console_template",
        scripts_dir / "sync_agent_console_template.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sync_agent_console_template"] = module
    spec.loader.exec_module(module)
    return module


def _instance(module, name: str, host_name: str = "work-special"):
    return module.ConsoleInstance(
        name=name,
        host_name=host_name,
        ssh_target="root@example.invalid",
        use_sudo=False,
        env_file=f"/etc/{name}/codex-web.env",
        web_path=f"/opt/{name}/{name}_codex_web.py",
        launch_path=f"/opt/{name}/{name}_codex_launch.sh",
        supervisor_path=f"/opt/{name}/{name}_codex_supervisor.sh",
        restart_units=(f"{name}-codex.service", f"{name}-codex-web.service"),
        agent_label=name,
        web_port="8765",
        web_token="token",
        prompt_file=f"/opt/{name}/prompt.txt",
        codex_home=f"/var/lib/{name}/codex",
    )


def _host(module):
    return module.DiscoveryHost(
        name="work-special",
        ssh_target="root@example.invalid",
        use_sudo=False,
        env_globs=(),
        public_host="work-special.example.invalid",
        lan_host="192.0.2.10",
    )


def _named_host(module, name: str, group_host: str = "192.0.2.10"):
    return module.DiscoveryHost(
        name=name,
        ssh_target="root@example.invalid",
        use_sudo=False,
        env_globs=(),
        public_host=f"{name}.example.invalid",
        lan_host=group_host,
    )


def test_discovery_infers_codex_home_from_launcher_fallback(
    monkeypatch, tmp_path
) -> None:
    module = _load_sync_script(monkeypatch)
    env_dir = tmp_path / "etc" / "housebot"
    env_dir.mkdir(parents=True)
    launch_path = tmp_path / "opt" / "housebot_codex_launch.sh"
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(
        'CODEX_HOME="${CODEX_HOME:-/root/.codex-housebot}"\n',
        encoding="utf-8",
    )
    (env_dir / "codex-web.env").write_text(
        f"NORMAN_CODEX_LAUNCHER={launch_path}\n" "NORMAN_CODEX_AGENT_NAME=Housebot\n",
        encoding="utf-8",
    )
    host = module.DiscoveryHost(
        name="toy-box",
        ssh_target="root@example.invalid",
        use_sudo=False,
        env_globs=(str(tmp_path / "etc" / "*" / "codex-web.env"),),
        public_host="toy-box.example.invalid",
        lan_host="192.0.2.10",
    )
    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["bash", "-lc", script],
    )

    instances = module.discover_host_instances(host)

    assert len(instances) == 1
    assert instances[0].name == "housebot"
    assert instances[0].codex_home == "/root/.codex-housebot"


def test_list_versions_surfaces_restart_staged_state(monkeypatch, capsys) -> None:
    module = _load_sync_script(monkeypatch)
    monkeypatch.setattr(
        module,
        "ui_versions",
        lambda host, instances: {
            "panelbot": module.UiVersionStatus(
                version="2026.05.31.1",
                web_restart_required=True,
                web_restart_reason="console web script changed after this process started",
            )
        },
    )

    module.list_versions({"work-special": [_instance(module, "panelbot")]})

    assert capsys.readouterr().out == (
        "work-special\n"
        "  - panelbot: UI v2026.05.31.1 "
        "(restart staged: console web script changed after this process started)\n"
    )


def test_list_versions_surfaces_idle_auto_update_safe_state(
    monkeypatch, capsys
) -> None:
    module = _load_sync_script(monkeypatch)
    monkeypatch.setattr(
        module,
        "ui_versions",
        lambda host, instances: {
            "panelbot": module.UiVersionStatus(
                version="2026.05.31.1",
                web_restart_required=True,
                web_restart_reason="console web script changed after this process started",
                prompt_idle=True,
                auto_update_safe=True,
                busy=False,
            )
        },
    )

    module.list_versions({"work-special": [_instance(module, "panelbot")]})

    assert capsys.readouterr().out == (
        "work-special\n"
        "  - panelbot: UI v2026.05.31.1 "
        "(restart staged; idle auto-update safe: "
        "console web script changed after this process started)\n"
    )


def test_list_versions_surfaces_finished_prompt_idle_auto_update_safe_state(
    monkeypatch, capsys
) -> None:
    module = _load_sync_script(monkeypatch)
    monkeypatch.setattr(
        module,
        "ui_versions",
        lambda host, instances: {
            "panelbot": module.UiVersionStatus(
                version="2026.05.31.1",
                web_restart_required=True,
                web_restart_reason="console web script changed after this process started",
                prompt_idle=True,
                prompt_done=True,
                auto_update_safe=True,
                busy=False,
            )
        },
    )

    module.list_versions({"work-special": [_instance(module, "panelbot")]})

    assert capsys.readouterr().out == (
        "work-special\n"
        "  - panelbot: UI v2026.05.31.1 "
        "(restart staged; prompt done; idle auto-update safe: "
        "console web script changed after this process started)\n"
    )


def test_list_versions_surfaces_status_endpoint_errors(monkeypatch, capsys) -> None:
    module = _load_sync_script(monkeypatch)
    monkeypatch.setattr(
        module,
        "ui_versions",
        lambda host, instances: {
            "control-plane": module.UiVersionStatus(
                version="2026.05.31.1",
                status_error="TimeoutError: timed out",
            )
        },
    )

    module.list_versions({"work-special": [_instance(module, "control-plane")]})

    assert capsys.readouterr().out == (
        "work-special\n"
        "  - control-plane: UI v2026.05.31.1 "
        "(status unavailable: TimeoutError: timed out)\n"
    )


def test_list_versions_surfaces_version_fetch_errors(monkeypatch, capsys) -> None:
    module = _load_sync_script(monkeypatch)
    monkeypatch.setattr(
        module,
        "ui_versions",
        lambda host, instances: {
            "control-plane": module.UiVersionStatus(
                version="unknown",
                version_error="URLError: connection refused",
            )
        },
    )

    module.list_versions({"work-special": [_instance(module, "control-plane")]})

    assert capsys.readouterr().out == (
        "work-special\n"
        "  - control-plane: UI vunknown "
        "(version unavailable: URLError: connection refused)\n"
    )


def test_list_versions_surfaces_readiness_fallback_hint(monkeypatch, capsys) -> None:
    module = _load_sync_script(monkeypatch)
    monkeypatch.setattr(
        module,
        "ui_versions",
        lambda host, instances: {
            "control-plane": module.UiVersionStatus(
                version="2026.05.31.1",
                readiness_error="HTTPError: 404 Not Found",
            )
        },
    )

    module.list_versions({"work-special": [_instance(module, "control-plane")]})

    assert capsys.readouterr().out == (
        "work-special\n"
        "  - control-plane: UI v2026.05.31.1 "
        "(readiness fallback: HTTPError: 404 Not Found)\n"
    )


def test_parse_args_supports_guarded_web_only_restart(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)

    args = module.parse_args(["--restart-web-only", "--targets", "panelbot"])

    assert args.restart_web_only is True
    assert args.restart is False
    assert args.force_restart is False
    assert args.targets == ["panelbot"]


def test_parse_args_supports_route_receipt_shadow_enablement(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)

    args = module.parse_args(
        [
            "--targets",
            "market-sizing",
            "toy-box",
            "--enable-route-receipts",
            "--route-receipt-dir",
            "/tmp/receipts",
            "--route-receipt-items",
            "50",
        ]
    )

    assert args.enable_route_receipts is True
    assert args.route_receipt_dir == "/tmp/receipts"
    assert args.route_receipt_items == "50"
    assert args.targets == ["market-sizing", "toy-box"]


def test_route_receipt_sync_exports_shadow_capture_env(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    market = _instance(module, "market-sizing")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert (
        module.sync_instance_route_receipts(
            _host(module),
            market,
            receipt_dir="/var/lib/norman/route_receipts",
            max_items="250",
        )
        is True
    )

    script = captured["script"]
    assert '"NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED":"1"' in script
    assert '"NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI":"market-sizing"' in script
    assert (
        '"NORMAN_CODEX_ROUTE_RECEIPT_DIR":' '"/var/lib/norman/route_receipts"'
    ) in script
    assert "route_receipt_path.mkdir(parents=True, exist_ok=True)" in script
    assert "receipt_owner_source = Path('/var/lib/market-sizing/codex')" in script
    assert "os.chown(route_receipt_path, target_uid, target_gid)" in script
    assert "os.chmod(route_receipt_path, 0o750)" in script
    assert (
        '"NORMAN_CODEX_ROUTE_RECEIPT_PATH":'
        '"/var/lib/norman/route_receipts/market-sizing.jsonl"'
    ) in script
    assert "route_receipt_file.touch()" in script
    assert "os.chown(route_receipt_file, target_uid, target_gid)" in script
    assert "os.chmod(route_receipt_file, 0o640)" in script
    assert '"NORMAN_CODEX_ROUTE_RECEIPT_ITEMS":"250"' in script


def test_web_restart_units_use_the_web_service_slot(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")

    assert module.web_restart_units([panelbot]) == ["panelbot-codex-web.service"]


def test_restart_scope_uses_web_only_for_ui_script_changes(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")

    assert (
        module.restart_scope_for_instance(
            panelbot,
            changed_paths={panelbot.web_path},
            changed_instances={},
        )
        == "web"
    )


def test_restart_scope_uses_full_for_context_affecting_changes(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")

    assert (
        module.restart_scope_for_instance(
            panelbot,
            changed_paths={panelbot.launch_path},
            changed_instances={},
        )
        == "full"
    )
    assert (
        module.restart_scope_for_instance(
            panelbot,
            changed_paths=set(),
            changed_instances={"panelbot": panelbot},
        )
        == "full"
    )


def test_restart_selected_web_services_keeps_runtime_guard(monkeypatch, capsys) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    restarted = []

    monkeypatch.setattr(
        module,
        "restart_block_reasons",
        lambda host, instances: {"panelbot": "active child pid 123"},
    )
    monkeypatch.setattr(
        module,
        "restart_and_health_check_instances",
        lambda host, instances, *, check_health, web_only=False: restarted.append(
            (tuple(instance.name for instance in instances), check_health, web_only)
        ),
    )

    module.restart_selected_web_services(
        {"work-special": [panelbot]},
        force_restart=False,
        check_health=True,
    )

    assert restarted == []
    assert capsys.readouterr().out == (
        "==> restarting web services on work-special\n"
        "  - skip web restart panelbot: active child pid 123\n"
    )


def test_restart_selected_web_services_can_force_guarded_web_restart(
    monkeypatch, capsys
) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    restarted = []

    monkeypatch.setattr(
        module,
        "restart_block_reasons",
        lambda host, instances: {"panelbot": "active child pid 123"},
    )
    monkeypatch.setattr(
        module,
        "restart_and_health_check_instances",
        lambda host, instances, *, check_health, web_only=False: restarted.append(
            (tuple(instance.name for instance in instances), check_health, web_only)
        ),
    )

    module.restart_selected_web_services(
        {"work-special": [panelbot]},
        force_restart=True,
        check_health=False,
    )

    assert restarted == [(("panelbot",), False, True)]
    assert capsys.readouterr().out == (
        "==> restarting web services on work-special\n"
        "  - serial web restart queue: panelbot\n"
    )


def test_restart_block_reason_ignores_dead_stale_child_pid(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)

    reason = module._status_restart_block_reason(
        {
            "active_child_pid": 123,
            "model_process_alive": False,
            "pending": False,
            "queue_depth": 0,
            "state": "ok",
        }
    )

    assert reason == ""


def test_restart_block_reason_trusts_auto_update_safe_idle_state(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)

    reason = module._status_restart_block_reason(
        {
            "active_child_pid": 123,
            "model_process_alive": False,
            "pending": False,
            "queue_depth": 0,
            "state": "ok",
            "busy": False,
            "prompt_idle": True,
            "auto_update_safe": True,
        }
    )

    assert reason == ""


def test_restart_block_reason_keeps_live_or_unknown_child_pid_conservative(
    monkeypatch,
) -> None:
    module = _load_sync_script(monkeypatch)

    live_reason = module._status_restart_block_reason(
        {"active_child_pid": 123, "model_process_alive": True}
    )
    unknown_reason = module._status_restart_block_reason({"active_child_pid": 456})

    assert live_reason == "active child pid 123"
    assert unknown_reason == "active child pid 456"


def test_restart_handoff_summary_reports_resumable_context(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)

    summary = module._status_restart_handoff_summary(
        {
            "context_handoff": {
                "can_resume_thread": True,
                "thread_id": "thread-abcdef123",
                "history_count": 12,
                "queue_depth": 2,
                "context_preserved": True,
            }
        }
    )

    assert summary == "handoff resume thread-a, 12 history, 2 queued"


def test_restart_guard_prefers_lightweight_readiness_probe(monkeypatch) -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "sync_agent_console_template.py"
    ).read_text(encoding="utf-8")

    assert '"/api/restart-readiness"' in source
    assert '"/api/status"' in source
    assert "readiness_timeout = RESTART_READINESS_TIMEOUT_SECONDS" in source
    assert "status_timeout = STATUS_PROBE_TIMEOUT_SECONDS" in source
    assert "fetch_json(readiness_url, readiness_timeout)" in source
    assert "fetch_json(status_url, status_timeout)" in source


def test_ui_versions_prefers_lightweight_readiness_probe(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    captured: dict[str, str] = {}

    def fake_ssh_command(host, script):
        captured["script"] = script
        return ["ssh", script]

    monkeypatch.setattr(module, "ssh_command", fake_ssh_command)
    monkeypatch.setattr(module, "capture", lambda _cmd: "[]")

    module.ui_versions(_host(module), [_instance(module, "panelbot")])

    script = captured["script"]
    assert "/api/restart-readiness" in script
    assert "/api/status" in script
    assert "def fetch_json(url, timeout):" in script
    assert "readiness_timeout = 3" in script
    assert "status_timeout = 12" in script
    assert "status = fetch_json(readiness_url, readiness_timeout)" in script
    assert "status = fetch_json(status_url, status_timeout)" in script
    assert 'result["readiness_error"]' in script
    assert 'result["prompt_done"]' in script


def test_origin_sync_exports_bbs_env_file_without_raw_token(monkeypatch) -> None:
    monkeypatch.setenv("NORMAN_SYNC_BBS_URL", "http://switchboard.local:8765")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert "NORMAN_CODEX_BBS_URL" in script
    assert "NORMAN_CODEX_BBS_ACTOR" in script
    assert "NORMAN_CODEX_BBS_ENV_FILE" in script
    assert "NORMAN_CODEX_SERVICE_TIER" in script
    assert '"NORMAN_CODEX_SERVICE_TIER":"default"' in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "NORMAN_CODEX_STANDARD_MODEL" in script
    assert "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2" in script
    assert "NORMAN_CODEX_BEDROCK_FAILOVER_MODEL" in script
    assert "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION" in script
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2":""' in script
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER_MODEL":""' in script
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION":""' in script
    assert "traqline-bedrock-us-east-1" not in script
    assert "us-east-1" not in script
    assert '"NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES":"1"' in script
    assert "traqline-bedrock" in script
    assert "openai.gpt-5.5" in script
    assert "NORMAN_CODEX_FLEX_MODEL" in script
    assert "NORMAN_CODEX_PRIORITY_MODEL" in script
    assert "NORMAN_CODEX_SWITCHABLE_MODELS" in script
    assert "openai.gpt-5.4" in script
    assert "gpt-5.4" in script
    assert module.WORK_SWITCHABLE_MODELS == (
        "openai.gpt-5.4,openai.gpt-5.5,gpt-5.4,gpt-5.5"
    )
    assert '"NORMAN_CODEX_DIRECT_TIERS_ENABLED":"1"' in script
    assert "ob-traqline-admin" in script
    assert "SWITCHBOARD_URL" in script
    assert "SWITCHBOARD_ACTOR" in script
    assert "SWITCHBOARD_ENV_FILE" in script
    assert "/etc/panelbot/switchboard-bbs.env" in script
    assert "SWITCHBOARD_TOKEN" not in script


def test_origin_sync_exports_discovered_local_llm_inventory(
    monkeypatch, tmp_path: Path
) -> None:
    sense_path = tmp_path / "ollama_sense.json"
    vllm_sense_path = tmp_path / "vllm_sense.json"
    sense_path.write_text(
        json.dumps(
            {
                "schema": "norman.tui.ollama-sense.v1",
                "endpoints": [
                    {
                        "endpoint": "http://192.168.2.151:11434",
                        "ok": True,
                        "models": [
                            "qwen3-coder-next:q4_K_M",
                            "gpt-oss:120b",
                            "qwen3.5:122b-a10b-q4_K_M",
                            "llama3.2:1b",
                            "qwen3-vl:30b-a3b-instruct-q4_K_M",
                        ],
                    },
                    {
                        "endpoint": "http://192.168.2.152:11434",
                        "ok": True,
                        "models": [
                            "qwen3-coder-next:q4_K_M",
                            "gpt-oss:120b",
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    vllm_sense_path.write_text(
        json.dumps(
            {
                "schema": "norman.tui.vllm-sense.v1",
                "endpoints": [
                    {
                        "endpoint": "http://spark-1.home.arpa:8000",
                        "ok": True,
                        "models": [
                            "Qwen/Qwen3-Coder-30B-A3B",
                            "meta-llama/Llama-3.1-70B-Instruct",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NORMAN_SYNC_LOCAL_LLM_SENSE_JSON", str(sense_path))
    monkeypatch.setenv("NORMAN_SYNC_LOCAL_LLM_SENSE_JSONS", str(vllm_sense_path))
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.LOCAL_LLM_DEFAULT_MODEL == "gpt-oss:120b"
    assert module.LOCAL_LLM_MODELS == (
        "gpt-oss:120b",
        "qwen3.5:122b-a10b-q4_K_M",
        "meta-llama/Llama-3.1-70B-Instruct",
    )
    assert module.LOCAL_LLM_ENDPOINTS == (
        "http://192.168.2.151:11434",
        "http://192.168.2.152:11434",
        "http://spark-1.home.arpa:8000",
    )
    assert module.LOCAL_LLM_MODEL_ENDPOINTS["gpt-oss:120b"] == [
        "http://192.168.2.151:11434",
        "http://192.168.2.152:11434",
    ]
    assert "qwen3-coder-next:q4_K_M" not in module.LOCAL_LLM_MODEL_ENDPOINTS
    assert "Qwen/Qwen3-Coder-30B-A3B" not in module.LOCAL_LLM_MODEL_ENDPOINTS
    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert '"NORMAN_LOCAL_LLM_MODEL":"gpt-oss:120b"' in script
    assert '"NORMAN_LOCAL_LLM_MODELS":"' in script
    assert (
        '"NORMAN_LOCAL_LLM_ENDPOINTS":"http://192.168.2.151:11434,http://192.168.2.152:11434,http://spark-1.home.arpa:8000"'
        in script
    )
    assert '"NORMAN_LOCAL_LLM_MODEL_ENDPOINTS":"' in script
    assert "http://spark-1.home.arpa:8000" in script
    assert "qwen3.5:122b-a10b-q4_K_M" in script
    assert "Qwen/Qwen3-Coder-30B-A3B" not in script
    assert "qwen3-coder-next:q4_K_M" not in script
    assert "qwen3-vl:30b-a3b-instruct-q4_K_M" not in script


def test_work_runtime_default_model_reset_migrates_old_default(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_WORK_RUNTIME_DEFAULT_MODEL_RESET", "1")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_runtime_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert "runtime_settings.json" in script
    assert "openai.gpt-5.5" in script
    assert "openai.gpt-5.4" in script
    assert 'payload["service_tier"] = "default"' in script


def test_work_bedrock_secondary_failover_requires_explicit_enablement(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_ENABLED", "1")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert (
        '"NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2":"traqline-bedrock-us-east-1"'
        in script
    )
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION":"us-east-1"' in script
    assert '"NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES":"2"' in script


def test_work_bedrock_secondary_failover_auto_requires_fresh_smoke(
    monkeypatch, tmp_path: Path
) -> None:
    smoke_path = tmp_path / "bedrock_region_smoke.json"
    smoke_path.write_text(
        json.dumps(
            {
                "checked_at": time.time(),
                "profiles": {
                    "traqline-bedrock-us-east-1": {
                        "ok": True,
                        "profile_v2": "traqline-bedrock-us-east-1",
                        "model": "openai.gpt-5.4",
                        "aws_region": "us-east-1",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_PATH", str(smoke_path))
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert (
        '"NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2":"traqline-bedrock-us-east-1"'
        in script
    )
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION":"us-east-1"' in script
    assert '"NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES":"2"' in script


def test_work_bedrock_tertiary_failover_auto_requires_fresh_smoke(
    monkeypatch, tmp_path: Path
) -> None:
    smoke_path = tmp_path / "bedrock_region_smoke.json"
    smoke_path.write_text(
        json.dumps(
            {
                "checked_at": time.time(),
                "profiles": {
                    "traqline-bedrock-us-east-1": {
                        "ok": True,
                        "profile_v2": "traqline-bedrock-us-east-1",
                        "model": "openai.gpt-5.4",
                        "aws_region": "us-east-1",
                    },
                    "traqline-bedrock-us-west-2": {
                        "ok": True,
                        "profile_v2": "traqline-bedrock-us-west-2",
                        "model": "openai.gpt-5.4",
                        "aws_region": "us-west-2",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_PATH", str(smoke_path))
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert (
        '"NORMAN_CODEX_BEDROCK_FAILOVER2_PROFILE_V2":"traqline-bedrock-us-west-2"'
        in script
    )
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_REGION":"us-west-2"' in script
    assert '"NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES":"3"' in script


def test_work_bedrock_secondary_failover_auto_ignores_failed_smoke(
    monkeypatch, tmp_path: Path
) -> None:
    smoke_path = tmp_path / "bedrock_region_smoke.json"
    smoke_path.write_text(
        json.dumps(
            {
                "checked_at": time.time(),
                "profiles": {
                    "traqline-bedrock-us-east-1": {
                        "ok": False,
                        "profile_v2": "traqline-bedrock-us-east-1",
                        "model": "openai.gpt-5.5",
                        "aws_region": "us-east-1",
                        "error_kind": "bedrock_engine_not_found",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_SMOKE_PATH", str(smoke_path))
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2":""' in script
    assert '"NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION":""' in script
    assert '"NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES":"1"' in script


def test_work_bedrock_defaults_can_explicitly_keep_direct_tiers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_WORK_DIRECT_TIERS_ENABLED", "1")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_SERVICE_TIER":"default"' in script
    assert '"NORMAN_CODEX_DIRECT_TIERS_ENABLED":"1"' in script


def test_work_bedrock_defaults_can_explicitly_disable_direct_tiers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_WORK_DIRECT_TIERS_ENABLED", "0")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_SERVICE_TIER":"default"' in script
    assert '"NORMAN_CODEX_DIRECT_TIERS_ENABLED":"0"' in script


def test_work_bedrock_defaults_can_be_disabled_and_cleaned(monkeypatch) -> None:
    monkeypatch.setenv("NORMAN_SYNC_WORK_BEDROCK_DEFAULT_ENABLED", "0")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_SERVICE_TIER":"auto"' in script
    assert "remove_keys" in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "NORMAN_CODEX_STANDARD_MODEL" in script
    assert "NORMAN_CODEX_STANDARD_MODEL" in script
    assert "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2" in script
    assert "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION" in script
    assert "NORMAN_CODEX_DIRECT_TIERS_ENABLED" in script
    assert "traqline-bedrock" not in script
    assert '"NORMAN_CODEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_MODEL_FLOOR":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_DIRECT_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_FLEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_PRIORITY_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_SWITCHABLE_MODELS":"gpt-5.4,gpt-5.5"' in script
    assert '"NORMAN_CODEX_AVAILABLE_MODELS":"gpt-5.4,gpt-5.5"' in script
    assert "openai.gpt-5.5" not in script
    assert "ob-traqline-admin" not in script


def test_work_bedrock_profile_sync_copies_host_local_profile(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_bedrock_profile(_host(module), panelbot) is True

    script = captured["script"]
    assert "/home/kristopher/.codex-infra/traqline-bedrock.config.toml" in script
    assert "/var/lib/panelbot/codex" in script
    assert "traqline-bedrock.config.toml" in script
    assert '(profile_name + ".config.toml")' in script
    assert "profile_specs = json.loads" in script
    assert '"profile_v2":"traqline-bedrock-us-east-1"' not in script
    assert '"aws_region":"us-east-1"' not in script
    assert '"reasoning_effort":"xhigh"' in script
    assert 'ensure_table_setting(rendered, "", "profile", profile_name)' not in script
    assert 'ensure_table_setting(rendered, aws_table, "region", aws_region)' in script
    assert 'ensure_table_setting(rendered, aws_table, "wire_api"' not in script
    assert "model_reasoning_effort" in script
    assert 'target.write_text(rendered, encoding="utf-8")' in script


def test_work_bedrock_profile_sync_copies_secondary_profile_when_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_WORK_BEDROCK_FAILOVER_ENABLED", "1")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_bedrock_profile(_host(module), panelbot) is True

    script = captured["script"]
    assert '"profile_v2":"traqline-bedrock-us-east-1"' in script
    assert '"aws_region":"us-east-1"' in script


def test_work_special_host_receives_work_bedrock_defaults_by_host(
    monkeypatch,
) -> None:
    module = _load_sync_script(monkeypatch)
    ad_hoc = _instance(module, "ad-hoc-work-lane")
    work_special = _host(module)
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.instance_uses_work_config(work_special, ad_hoc) is True
    assert module.sync_instance_origin_settings(work_special, ad_hoc) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_BILLING_SCOPE":"work-special"' in script
    assert '"NORMAN_CODEX_BILLING_OWNER":"openbrand"' in script
    assert '"NORMAN_CODEX_SERVICE_TIER":"default"' in script
    assert '"NORMAN_CODEX_STANDARD_PROFILE_V2":"traqline-bedrock"' in script
    assert '"NORMAN_CODEX_STANDARD_AWS_PROFILE":"ob-traqline-admin"' in script


def test_work_named_tui_on_norman_stays_personal_without_test_override(
    monkeypatch,
) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot", host_name="norman")
    norman = _named_host(module, "norman")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.instance_uses_work_config(norman, panelbot) is False
    assert module.instance_uses_non_work_bedrock(norman, panelbot) is False
    assert module.sync_instance_bedrock_profile(norman, panelbot) is False
    assert module.sync_instance_origin_settings(norman, panelbot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_BILLING_SCOPE":"norman"' in script
    assert '"NORMAN_CODEX_BILLING_OWNER":"kristopher"' in script
    assert '"NORMAN_CODEX_SERVICE_TIER":"flex"' in script
    assert '"NORMAN_CODEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_DIRECT_MODEL":"gpt-5.4"' in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "traqline-bedrock" not in script
    assert "ob-traqline-admin" not in script


def test_norman_can_opt_into_work_config_for_local_testing(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_WORK_CONFIG_EXTRA_HOSTS", "norman")
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot", host_name="norman")
    norman = _named_host(module, "norman")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.instance_uses_work_config(norman, panelbot) is True
    assert module.sync_instance_origin_settings(norman, panelbot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_BILLING_SCOPE":"work-special"' in script
    assert '"NORMAN_CODEX_BILLING_OWNER":"openbrand"' in script
    assert '"NORMAN_CODEX_SERVICE_TIER":"default"' in script
    assert '"NORMAN_CODEX_STANDARD_PROFILE_V2":"traqline-bedrock"' in script
    assert '"NORMAN_CODEX_STANDARD_AWS_PROFILE":"ob-traqline-admin"' in script


def test_personal_tui_does_not_receive_work_bedrock_defaults(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    housebot = _instance(module, "housebot", host_name="toy-box")
    toy_box = _named_host(module, "toy-box")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "unchanged\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_bedrock_profile(toy_box, housebot) is False
    assert module.sync_instance_origin_settings(toy_box, housebot) is False

    script = captured["script"]
    assert '"NORMAN_CODEX_SERVICE_TIER":"flex"' in script
    assert "remove_keys" in script
    assert '"NORMAN_CODEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_DIRECT_MODEL":"gpt-5.4"' in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "traqline-bedrock" not in script
    assert "NORMAN_CODEX_DIRECT_TIERS_ENABLED" in script
    assert "ob-traqline-admin" not in script


def test_non_work_bedrock_defaults_can_be_disabled_and_cleaned(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_NON_WORK_BEDROCK_DEFAULT_ENABLED", "0")
    module = _load_sync_script(monkeypatch)
    housebot = _instance(module, "housebot")
    toy_box = _named_host(module, "toy-box")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(toy_box, housebot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_SERVICE_TIER":"flex"' in script
    assert "remove_keys" in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "traqline-bedrock" not in script
    assert '"NORMAN_CODEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_MODEL_FLOOR":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_DIRECT_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_FLEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_PRIORITY_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_SWITCHABLE_MODELS":"gpt-5.4,gpt-5.5"' in script
    assert '"NORMAN_CODEX_AVAILABLE_MODELS":"gpt-5.4,gpt-5.5"' in script
    assert "openai.gpt-5.5" not in script


def test_non_work_bedrock_profile_sync_requires_explicit_source(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "bedrock.config.toml"
    source.write_text('model = "openai.gpt-5.4"\n', encoding="utf-8")
    monkeypatch.setenv(
        "NORMAN_SYNC_NON_WORK_BEDROCK_PROFILE_SOURCE",
        str(source),
    )
    monkeypatch.setenv("NORMAN_SYNC_NON_WORK_BEDROCK_AWS_PROFILE", "personal-bedrock")
    monkeypatch.setenv("NORMAN_SYNC_NON_WORK_BEDROCK_AWS_REGION", "us-west-2")
    module = _load_sync_script(monkeypatch)
    housebot = _instance(module, "housebot", host_name="toy-box")
    toy_box = _named_host(module, "toy-box")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.instance_uses_non_work_bedrock(toy_box, housebot) is True
    assert module.sync_instance_bedrock_profile(toy_box, housebot) is True

    script = captured["script"]
    assert str(source) in script
    assert '"source_text":' in script
    assert '"source_text_present":true' in script
    assert "openai.gpt-5.4" in script
    assert '"profile_v2":"personal-bedrock"' in script
    assert '"aws_profile":"personal-bedrock"' in script
    assert '"aws_region":"us-west-2"' in script
    assert "ob-traqline-admin" not in script


def test_personal_tui_uses_non_work_bedrock_only_with_explicit_source(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "bedrock.config.toml"
    source.write_text('model = "openai.gpt-5.4"\n', encoding="utf-8")
    monkeypatch.setenv("NORMAN_SYNC_NON_WORK_BEDROCK_PROFILE_SOURCE", str(source))
    monkeypatch.setenv("NORMAN_SYNC_NON_WORK_BEDROCK_AWS_PROFILE", "personal-bedrock")
    monkeypatch.setenv("NORMAN_SYNC_NON_WORK_BEDROCK_AWS_REGION", "us-west-2")
    module = _load_sync_script(monkeypatch)
    housebot = _instance(module, "housebot", host_name="toy-box")
    toy_box = _named_host(module, "toy-box")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.instance_uses_non_work_bedrock(toy_box, housebot) is True
    assert module.sync_instance_origin_settings(toy_box, housebot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_SERVICE_TIER":"default"' in script
    assert '"NORMAN_CODEX_STANDARD_PROFILE_V2":"personal-bedrock"' in script
    assert '"NORMAN_CODEX_STANDARD_AWS_PROFILE":"personal-bedrock"' in script
    assert '"NORMAN_CODEX_STANDARD_AWS_REGION":"us-west-2"' in script
    assert "ob-traqline-admin" not in script


def test_personal_tui_uses_default_personal_bedrock_source_when_present(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_TEST_ALLOW_DEFAULT_NON_WORK_BEDROCK_SOURCE", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / ".codex-nonwork" / "personal-bedrock.config.toml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# personal bedrock overlay\n", encoding="utf-8")
    module = _load_sync_script(monkeypatch)
    housebot = _instance(module, "housebot", host_name="toy-box")
    toy_box = _named_host(module, "toy-box")
    captured: list[str] = []

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured.append(cmd[1])
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.NON_WORK_BEDROCK_PROFILE_SOURCE == str(source)
    assert module.NON_WORK_BEDROCK_AWS_PROFILE == "kk-personal"
    assert module.NON_WORK_BEDROCK_AWS_REGION == "us-east-2"
    assert module.instance_uses_non_work_bedrock(toy_box, housebot) is True
    assert module.sync_instance_origin_settings(toy_box, housebot) is True
    assert module.sync_instance_bedrock_profile(toy_box, housebot) is True

    origin_script, profile_script = captured
    assert '"NORMAN_CODEX_STANDARD_PROFILE_V2":"personal-bedrock"' in origin_script
    assert '"NORMAN_CODEX_STANDARD_AWS_PROFILE":"kk-personal"' in origin_script
    assert '"NORMAN_CODEX_STANDARD_AWS_REGION":"us-east-2"' in origin_script
    assert "ob-traqline-admin" not in origin_script
    assert str(source) in profile_script
    assert '"source_text_present":true' in profile_script
    assert "# personal bedrock overlay" in profile_script
    assert '"profile_v2":"personal-bedrock"' in profile_script
    assert '"aws_profile":"kk-personal"' in profile_script
    assert '"aws_region":"us-east-2"' in profile_script
    assert "ob-traqline-admin" not in profile_script


def test_personal_bedrock_source_falls_back_when_sync_runs_as_root(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("NORMAN_SYNC_TEST_ALLOW_DEFAULT_NON_WORK_BEDROCK_SOURCE", "1")
    root_home = tmp_path / "root"
    fallback_home = tmp_path / "kristopher"
    source = fallback_home / ".codex-nonwork" / "traqline-bedrock.config.toml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# personal fallback profile\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(root_home))
    monkeypatch.setenv("NORMAN_SYNC_NON_WORK_BEDROCK_FALLBACK_HOME", str(fallback_home))

    module = _load_sync_script(monkeypatch)

    assert module.NON_WORK_BEDROCK_PROFILE_SOURCE == str(source)
    assert module.NON_WORK_BEDROCK_PROFILE_V2 == "personal-bedrock"
    assert module.non_work_bedrock_profile_source_ready() is True


def test_netops_defaults_to_direct_5_4_and_removes_bedrock(
    monkeypatch,
) -> None:
    module = _load_sync_script(monkeypatch)
    networking = _instance(module, "networking")
    netops_host = _named_host(module, "networking-host")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert "networking" not in module.WORK_BEDROCK_DEFAULT_INSTANCES
    assert module.instance_uses_non_work_bedrock(netops_host, networking) is False
    assert module.sync_instance_bedrock_profile(netops_host, networking) is False
    assert module.sync_instance_origin_settings(netops_host, networking) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_SERVICE_TIER":"flex"' in script
    assert '"NORMAN_CODEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_MODEL_FLOOR":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_DIRECT_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_FLEX_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_PRIORITY_MODEL":"gpt-5.4"' in script
    assert '"NORMAN_CODEX_SWITCHABLE_MODELS":"gpt-5.4,gpt-5.5"' in script
    assert '"NORMAN_CODEX_AVAILABLE_MODELS":"gpt-5.4,gpt-5.5"' in script
    assert "NORMAN_CODEX_STANDARD_PROFILE_V2" in script
    assert "traqline-bedrock" not in script
    assert "openai.gpt-5.5" not in script


def test_console_files_include_soul_support_scripts(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")

    files = dict(panelbot.files)

    assert files["vector-preflight"] == "/opt/panelbot/tui_vector_preflight.py"
    assert files["soul-loader"] == "/opt/panelbot/compose_soul_context.py"
    assert files["soul-validator"] == "/opt/panelbot/validate_soul_md.py"
    assert module.SOURCE_FILES["vector-preflight"].name == "tui_vector_preflight.py"
    assert module.SOURCE_FILES["soul-loader"].name == "compose_soul_context.py"
    assert module.SOURCE_FILES["soul-validator"].name == "validate_soul_md.py"


def test_origin_sync_enables_soul_context(monkeypatch) -> None:
    module = _load_sync_script(monkeypatch)
    panelbot = _instance(module, "panelbot")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda host, script: ["ssh", script],
    )

    def fake_capture(cmd):
        captured["script"] = cmd[1]
        return "changed\n"

    monkeypatch.setattr(module, "capture", fake_capture)

    assert module.sync_instance_origin_settings(_host(module), panelbot) is True

    script = captured["script"]
    assert '"NORMAN_CODEX_SOUL_ENABLED":"1"' in script
    assert '"NORMAN_CODEX_SOUL_ACTOR":"panelbot"' in script
    assert '"NORMAN_CODEX_SOUL_IDENTITY_ROOT":"/etc/norman/identity"' in script
    assert (
        '"NORMAN_CODEX_SOUL_LOADER":"/opt/panelbot/compose_soul_context.py"' in script
    )
    assert (
        '"NORMAN_CODEX_CONTEXT_PREFLIGHT_OFFLINE_COMMAND":'
        '"python3 /opt/panelbot/tui_vector_preflight.py"' in script
    )
    assert '"NORMAN_CODEX_VECTOR_PREFLIGHT_LIMIT":"5"' in script


def test_soul_identity_tree_syncs_base_and_actor_files(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_sync_script(monkeypatch)
    identity_root = tmp_path / "identity"
    actor_dir = identity_root / "actors" / "panelbot"
    actor_dir.mkdir(parents=True)
    (identity_root / "BASE_SOUL.md").write_text("base", encoding="utf-8")
    (actor_dir / "SOUL.md").write_text("actor", encoding="utf-8")
    installed: list[tuple[str, Path]] = []

    monkeypatch.setattr(module, "LOCAL_SOUL_IDENTITY_ROOT", identity_root)
    monkeypatch.setattr(module, "REMOTE_SOUL_IDENTITY_ROOT", "/etc/norman/identity")
    monkeypatch.setattr(module, "local_sha256", lambda path: f"sha:{path.name}")

    def fake_install_source_path(host, *, remote_path, source, source_sha256):
        installed.append((remote_path, source))
        return True

    monkeypatch.setattr(module, "install_source_path", fake_install_source_path)

    changed = module.sync_soul_identity_tree(_host(module))

    assert changed == [
        "/etc/norman/identity/BASE_SOUL.md",
        "/etc/norman/identity/actors/panelbot/SOUL.md",
    ]
    assert installed == [
        ("/etc/norman/identity/BASE_SOUL.md", identity_root / "BASE_SOUL.md"),
        (
            "/etc/norman/identity/actors/panelbot/SOUL.md",
            identity_root / "actors" / "panelbot" / "SOUL.md",
        ),
    ]
