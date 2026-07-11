#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib


DEFAULT_OLLAMA_LABEL = "org.lollie.llm-node.ollama"
DEFAULT_CADDY_LABEL = "org.lollie.llm-node.caddy"
DEFAULT_NORLLAMA_LABEL = "org.lollie.norllama"
DEFAULT_OLLAMA_BIN = "/opt/homebrew/bin/ollama"
DEFAULT_CADDY_BIN = "/opt/homebrew/bin/caddy"
DEFAULT_NORLLAMA_PYTHON = "/usr/bin/python3"
DEFAULT_NORLLAMA_GATEWAY = "/Users/k/norllama/norllama_gateway.py"
DEFAULT_NORLLAMA_WORKING_DIR = "/Users/k/norllama"
DEFAULT_OLLAMA_HOST = "127.0.0.1:11434"
DEFAULT_OLLAMA_KEEP_ALIVE = "5m"
DEFAULT_OLLAMA_MAX_LOADED_MODELS = 1
DEFAULT_OLLAMA_NUM_PARALLEL = 1
DEFAULT_NORLLAMA_BIND = "0.0.0.0"
DEFAULT_NORLLAMA_PORT = 18151
DEFAULT_NORLLAMA_TIMEOUT_S = 120
DEFAULT_NORLLAMA_PUBLIC_PROVIDER_NAME = "norllama"
DEFAULT_NORLLAMA_OLLAMA_BASES = "http://127.0.0.1:11434"
DEFAULT_NORLLAMA_PEER_BASES = ""
DEFAULT_NORLLAMA_SELF_BASE = ""
DEFAULT_NORLLAMA_MAX_PEER_HOPS = 1
DEFAULT_NORLLAMA_PEER_TIMEOUT_S = 1.5
DEFAULT_CADDYFILE = "/opt/homebrew/etc/caddy/llm.Caddyfile"
DEFAULT_LOG_DIR = "/tmp"


def _plist_xml(payload: dict[str, object]) -> str:
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML).decode("utf-8")


def _add_launchd_identity(
    payload: dict[str, object], *, user_name: str = "", group_name: str = ""
) -> None:
    if user_name.strip():
        payload["UserName"] = user_name.strip()
    if group_name.strip():
        payload["GroupName"] = group_name.strip()


def render_ollama_plist(
    *,
    label: str = DEFAULT_OLLAMA_LABEL,
    ollama_bin: str = DEFAULT_OLLAMA_BIN,
    host: str = DEFAULT_OLLAMA_HOST,
    keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE,
    max_loaded_models: int = DEFAULT_OLLAMA_MAX_LOADED_MODELS,
    num_parallel: int = DEFAULT_OLLAMA_NUM_PARALLEL,
    models_dir: str = "",
    log_dir: str = DEFAULT_LOG_DIR,
    user_name: str = "",
    group_name: str = "",
    home_dir: str = "",
) -> str:
    env = {
        "OLLAMA_HOST": host,
        "OLLAMA_KEEP_ALIVE": str(keep_alive),
        "OLLAMA_MAX_LOADED_MODELS": str(max_loaded_models),
        "OLLAMA_NUM_PARALLEL": str(num_parallel),
    }
    if home_dir.strip():
        env["HOME"] = home_dir.strip()
    if models_dir.strip():
        env["OLLAMA_MODELS"] = models_dir.strip()

    payload = {
        "Label": label,
        "ProgramArguments": [ollama_bin, "serve"],
        "EnvironmentVariables": env,
        "KeepAlive": True,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": f"{log_dir.rstrip('/')}/{label}.out.log",
        "StandardErrorPath": f"{log_dir.rstrip('/')}/{label}.err.log",
    }
    if home_dir.strip():
        payload["WorkingDirectory"] = home_dir.strip()
    _add_launchd_identity(payload, user_name=user_name, group_name=group_name)
    return _plist_xml(payload)


def render_caddy_plist(
    *,
    label: str = DEFAULT_CADDY_LABEL,
    caddy_bin: str = DEFAULT_CADDY_BIN,
    caddyfile: str = DEFAULT_CADDYFILE,
    log_dir: str = DEFAULT_LOG_DIR,
    user_name: str = "",
    group_name: str = "",
) -> str:
    payload = {
        "Label": label,
        "ProgramArguments": [
            caddy_bin,
            "run",
            "--config",
            caddyfile,
            "--adapter",
            "caddyfile",
        ],
        "KeepAlive": True,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "WorkingDirectory": "/opt/homebrew/etc/caddy",
        "StandardOutPath": f"{log_dir.rstrip('/')}/{label}.out.log",
        "StandardErrorPath": f"{log_dir.rstrip('/')}/{label}.err.log",
    }
    _add_launchd_identity(payload, user_name=user_name, group_name=group_name)
    return _plist_xml(payload)


def render_norllama_plist(
    *,
    label: str = DEFAULT_NORLLAMA_LABEL,
    python_bin: str = DEFAULT_NORLLAMA_PYTHON,
    gateway_path: str = DEFAULT_NORLLAMA_GATEWAY,
    working_dir: str = DEFAULT_NORLLAMA_WORKING_DIR,
    bind: str = DEFAULT_NORLLAMA_BIND,
    port: int = DEFAULT_NORLLAMA_PORT,
    timeout_s: int = DEFAULT_NORLLAMA_TIMEOUT_S,
    public_provider_name: str = DEFAULT_NORLLAMA_PUBLIC_PROVIDER_NAME,
    ollama_bases: str = DEFAULT_NORLLAMA_OLLAMA_BASES,
    peer_bases: str = DEFAULT_NORLLAMA_PEER_BASES,
    self_base: str = DEFAULT_NORLLAMA_SELF_BASE,
    max_peer_hops: int = DEFAULT_NORLLAMA_MAX_PEER_HOPS,
    peer_timeout_s: float = DEFAULT_NORLLAMA_PEER_TIMEOUT_S,
    log_dir: str = DEFAULT_LOG_DIR,
    user_name: str = "",
    group_name: str = "",
) -> str:
    env = {
        "NORLLAMA_BIND": bind,
        "NORLLAMA_PORT": str(port),
        "NORLLAMA_TIMEOUT_S": str(timeout_s),
        "NORLLAMA_PUBLIC_PROVIDER_NAME": public_provider_name,
        "NORLLAMA_OLLAMA_BASES": ollama_bases,
        "NORLLAMA_PEER_BASES": peer_bases,
        "NORLLAMA_MAX_PEER_HOPS": str(max_peer_hops),
        "NORLLAMA_PEER_TIMEOUT_S": str(peer_timeout_s),
    }
    if self_base.strip():
        env["NORLLAMA_SELF_BASE"] = self_base.strip()
    payload = {
        "Label": label,
        "ProgramArguments": [python_bin, gateway_path],
        "EnvironmentVariables": env,
        "KeepAlive": True,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "WorkingDirectory": working_dir,
        "StandardOutPath": f"{log_dir.rstrip('/')}/{label}.out.log",
        "StandardErrorPath": f"{log_dir.rstrip('/')}/{label}.err.log",
    }
    _add_launchd_identity(payload, user_name=user_name, group_name=group_name)
    return _plist_xml(payload)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render launchd plists for the Mac mini local LLM node."
    )
    parser.add_argument(
        "--service",
        choices=("ollama", "caddy", "norllama"),
        default="ollama",
        help="Which launchd service plist to render.",
    )
    parser.add_argument("--label", default="", help="Override the launchd label.")
    parser.add_argument(
        "--ollama-bin",
        default=DEFAULT_OLLAMA_BIN,
        help="Path to the Ollama binary for the ollama service.",
    )
    parser.add_argument(
        "--caddy-bin",
        default=DEFAULT_CADDY_BIN,
        help="Path to the Caddy binary for the caddy service.",
    )
    parser.add_argument(
        "--norllama-python",
        default=DEFAULT_NORLLAMA_PYTHON,
        help="Python executable for the norllama service.",
    )
    parser.add_argument(
        "--norllama-gateway",
        default=DEFAULT_NORLLAMA_GATEWAY,
        help="Path to norllama_gateway.py for the norllama service.",
    )
    parser.add_argument(
        "--norllama-working-dir",
        default=DEFAULT_NORLLAMA_WORKING_DIR,
        help="Working directory for the norllama service.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_OLLAMA_HOST,
        help="OLLAMA_HOST binding for the ollama service. Keep this loopback-only.",
    )
    parser.add_argument(
        "--keep-alive",
        default=DEFAULT_OLLAMA_KEEP_ALIVE,
        help="OLLAMA_KEEP_ALIVE value for the ollama service.",
    )
    parser.add_argument(
        "--max-loaded-models",
        type=int,
        default=DEFAULT_OLLAMA_MAX_LOADED_MODELS,
        help="OLLAMA_MAX_LOADED_MODELS for the ollama service.",
    )
    parser.add_argument(
        "--num-parallel",
        type=int,
        default=DEFAULT_OLLAMA_NUM_PARALLEL,
        help="OLLAMA_NUM_PARALLEL for the ollama service.",
    )
    parser.add_argument(
        "--models-dir",
        default="",
        help="Optional OLLAMA_MODELS directory override.",
    )
    parser.add_argument(
        "--caddyfile",
        default=DEFAULT_CADDYFILE,
        help="Path to the Caddyfile for the caddy service.",
    )
    parser.add_argument(
        "--norllama-bind",
        default=DEFAULT_NORLLAMA_BIND,
        help="Bind address for the norllama gateway.",
    )
    parser.add_argument(
        "--norllama-port",
        type=int,
        default=DEFAULT_NORLLAMA_PORT,
        help="Port for the norllama gateway.",
    )
    parser.add_argument(
        "--norllama-timeout-s",
        type=int,
        default=DEFAULT_NORLLAMA_TIMEOUT_S,
        help="Upstream request timeout for the norllama gateway.",
    )
    parser.add_argument(
        "--norllama-public-provider-name",
        default=DEFAULT_NORLLAMA_PUBLIC_PROVIDER_NAME,
        help="Provider name exposed by the norllama gateway.",
    )
    parser.add_argument(
        "--norllama-ollama-bases",
        default=DEFAULT_NORLLAMA_OLLAMA_BASES,
        help="Comma-separated private Ollama upstreams for norllama.",
    )
    parser.add_argument(
        "--norllama-peer-bases",
        default=DEFAULT_NORLLAMA_PEER_BASES,
        help="Comma-separated Norllama peer gateways.",
    )
    parser.add_argument(
        "--norllama-self-base",
        default=DEFAULT_NORLLAMA_SELF_BASE,
        help="Public base URL for this Norllama gateway, used for loop guards.",
    )
    parser.add_argument(
        "--norllama-max-peer-hops",
        type=int,
        default=DEFAULT_NORLLAMA_MAX_PEER_HOPS,
        help="Maximum Norllama peer forwards per request.",
    )
    parser.add_argument(
        "--norllama-peer-timeout-s",
        type=float,
        default=DEFAULT_NORLLAMA_PEER_TIMEOUT_S,
        help="Peer health probe timeout in seconds.",
    )
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help="Directory for launchd stdout/stderr logs.",
    )
    parser.add_argument(
        "--user-name",
        default="",
        help="Optional UserName for a LaunchDaemon plist.",
    )
    parser.add_argument(
        "--group-name",
        default="",
        help="Optional GroupName for a LaunchDaemon plist.",
    )
    parser.add_argument(
        "--home-dir",
        default="",
        help="Optional HOME and WorkingDirectory for the ollama LaunchDaemon.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.service == "caddy":
        print(
            render_caddy_plist(
                label=args.label or DEFAULT_CADDY_LABEL,
                caddy_bin=args.caddy_bin,
                caddyfile=args.caddyfile,
                log_dir=args.log_dir,
                user_name=args.user_name,
                group_name=args.group_name,
            )
        )
    elif args.service == "norllama":
        print(
            render_norllama_plist(
                label=args.label or DEFAULT_NORLLAMA_LABEL,
                python_bin=args.norllama_python,
                gateway_path=args.norllama_gateway,
                working_dir=args.norllama_working_dir,
                bind=args.norllama_bind,
                port=args.norllama_port,
                timeout_s=args.norllama_timeout_s,
                public_provider_name=args.norllama_public_provider_name,
                ollama_bases=args.norllama_ollama_bases,
                peer_bases=args.norllama_peer_bases,
                self_base=args.norllama_self_base,
                max_peer_hops=args.norllama_max_peer_hops,
                peer_timeout_s=args.norllama_peer_timeout_s,
                log_dir=args.log_dir,
                user_name=args.user_name,
                group_name=args.group_name,
            )
        )
    else:
        print(
            render_ollama_plist(
                label=args.label or DEFAULT_OLLAMA_LABEL,
                ollama_bin=args.ollama_bin,
                host=args.host,
                keep_alive=args.keep_alive,
                max_loaded_models=args.max_loaded_models,
                num_parallel=args.num_parallel,
                models_dir=args.models_dir,
                log_dir=args.log_dir,
                user_name=args.user_name,
                group_name=args.group_name,
                home_dir=args.home_dir,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
