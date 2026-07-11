from __future__ import annotations

import importlib.util
import plistlib
import sys
from pathlib import Path


def _load_mac_mini_llm_launchd_renderer():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "render_mac_mini_llm_launchd.py"
    )
    spec = importlib.util.spec_from_file_location(
        "render_mac_mini_llm_launchd",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_render_ollama_plist_uses_loopback_host_and_model_limits() -> None:
    module = _load_mac_mini_llm_launchd_renderer()

    rendered = module.render_ollama_plist(models_dir="/Users/kristopher/.ollama/models")
    payload = plistlib.loads(rendered.encode("utf-8"))

    assert payload["Label"] == "org.lollie.llm-node.ollama"
    assert payload["ProgramArguments"] == ["/opt/homebrew/bin/ollama", "serve"]
    assert payload["EnvironmentVariables"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert payload["EnvironmentVariables"]["OLLAMA_KEEP_ALIVE"] == "5m"
    assert payload["EnvironmentVariables"]["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert payload["EnvironmentVariables"]["OLLAMA_NUM_PARALLEL"] == "1"
    assert (
        payload["EnvironmentVariables"]["OLLAMA_MODELS"]
        == "/Users/kristopher/.ollama/models"
    )
    assert payload["KeepAlive"] is True
    assert payload["RunAtLoad"] is True


def test_render_ollama_plist_can_render_launchdaemon_identity() -> None:
    module = _load_mac_mini_llm_launchd_renderer()

    rendered = module.render_ollama_plist(
        user_name="k",
        group_name="staff",
        home_dir="/Users/k",
        models_dir="/Users/k/.ollama/models",
    )
    payload = plistlib.loads(rendered.encode("utf-8"))

    assert payload["UserName"] == "k"
    assert payload["GroupName"] == "staff"
    assert payload["WorkingDirectory"] == "/Users/k"
    assert payload["EnvironmentVariables"]["HOME"] == "/Users/k"
    assert payload["EnvironmentVariables"]["OLLAMA_HOST"] == "127.0.0.1:11434"


def test_render_caddy_plist_uses_llm_caddyfile() -> None:
    module = _load_mac_mini_llm_launchd_renderer()

    rendered = module.render_caddy_plist()
    payload = plistlib.loads(rendered.encode("utf-8"))

    assert payload["Label"] == "org.lollie.llm-node.caddy"
    assert payload["ProgramArguments"] == [
        "/opt/homebrew/bin/caddy",
        "run",
        "--config",
        "/opt/homebrew/etc/caddy/llm.Caddyfile",
        "--adapter",
        "caddyfile",
    ]
    assert payload["WorkingDirectory"] == "/opt/homebrew/etc/caddy"
    assert payload["KeepAlive"] is True
    assert payload["RunAtLoad"] is True


def test_render_norllama_plist_uses_private_ollama_upstream() -> None:
    module = _load_mac_mini_llm_launchd_renderer()

    rendered = module.render_norllama_plist(
        log_dir="/Users/k/Library/Logs",
        user_name="k",
        group_name="staff",
    )
    payload = plistlib.loads(rendered.encode("utf-8"))

    assert payload["Label"] == "org.lollie.norllama"
    assert payload["ProgramArguments"] == [
        "/usr/bin/python3",
        "/Users/k/norllama/norllama_gateway.py",
    ]
    assert payload["WorkingDirectory"] == "/Users/k/norllama"
    assert payload["UserName"] == "k"
    assert payload["GroupName"] == "staff"
    assert payload["EnvironmentVariables"]["NORLLAMA_BIND"] == "0.0.0.0"
    assert payload["EnvironmentVariables"]["NORLLAMA_PORT"] == "18151"
    assert (
        payload["EnvironmentVariables"]["NORLLAMA_OLLAMA_BASES"]
        == "http://127.0.0.1:11434"
    )
    assert payload["EnvironmentVariables"]["NORLLAMA_PEER_BASES"] == ""
    assert payload["EnvironmentVariables"]["NORLLAMA_MAX_PEER_HOPS"] == "1"
    assert payload["EnvironmentVariables"]["NORLLAMA_PEER_TIMEOUT_S"] == "1.5"
    assert (
        payload["EnvironmentVariables"]["NORLLAMA_PUBLIC_PROVIDER_NAME"] == "norllama"
    )
    assert payload["KeepAlive"] is True
    assert payload["RunAtLoad"] is True


def test_render_norllama_plist_can_target_worker_frontdoors() -> None:
    module = _load_mac_mini_llm_launchd_renderer()

    rendered = module.render_norllama_plist(
        ollama_bases=(
            "http://127.0.0.1:11434,"
            "http://192.168.2.150:18151,"
            "http://192.168.2.151:18151"
        ),
        peer_bases="http://192.168.2.150:18151,http://192.168.2.151:18151",
        self_base="http://192.168.2.133:18151",
        max_peer_hops=1,
        peer_timeout_s=1.5,
    )
    payload = plistlib.loads(rendered.encode("utf-8"))

    assert (
        payload["EnvironmentVariables"]["NORLLAMA_OLLAMA_BASES"]
        == "http://127.0.0.1:11434,http://192.168.2.150:18151,http://192.168.2.151:18151"
    )
    assert (
        payload["EnvironmentVariables"]["NORLLAMA_PEER_BASES"]
        == "http://192.168.2.150:18151,http://192.168.2.151:18151"
    )
    assert (
        payload["EnvironmentVariables"]["NORLLAMA_SELF_BASE"]
        == "http://192.168.2.133:18151"
    )
    assert payload["EnvironmentVariables"]["NORLLAMA_MAX_PEER_HOPS"] == "1"
    assert payload["EnvironmentVariables"]["NORLLAMA_PEER_TIMEOUT_S"] == "1.5"
