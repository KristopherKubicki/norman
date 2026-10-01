#!/usr/bin/env python3
"""Record an advisory Norman runtime route before native terminal Codex starts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA = "norman.codex-terminal-runtime-bridge.v1"
CONSOLE_RUNTIME_TOKEN_SECRET_DEFAULTS = (
    "norman/console-runtime-token",
    "norman/console-runtime-service-token",
    "runtime/console-runtime-token",
    "runtime/console-runtime-service-token",
)
ROUTE_POLICY = {
    "runtime": "terminal_native_codex",
    "provider": "norllama",
    "preferred_provider": "norllama",
    "planner": "norllama",
    "model_proxy": "norllama",
    "local_first": True,
    "allow_cloud_proxy": False,
    "allow_cloud_tool_proxy": False,
    "use_capability_catalog": True,
    "model_selection": "warm_policy",
    "cost_posture": "local_token_first",
    "mode": "control_only",
    "terminal_execution": "native_codex",
    "advisory_only": True,
}


@dataclass(frozen=True)
class BridgeResult:
    status: str
    job_id: str = ""
    failure_class: str = ""


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _timeout_seconds() -> float:
    value = _first_env(
        "NORMAN_CODEX_RUNTIME_BRIDGE_TIMEOUT_SECONDS",
        "NORMAN_CONSOLE_RUNTIME_TIMEOUT_SECONDS",
        "NORMAN_KEYS_TIMEOUT_SECONDS",
    )
    try:
        return max(0.1, float(value or "1.5"))
    except ValueError:
        return 1.5


def _runtime_api_base() -> str:
    return _first_env("NORMAN_CONSOLE_RUNTIME_API_BASE", "NORMAN_API_BASE_URL")


def _runtime_bridge_enabled(api_base: str) -> bool:
    if "NORMAN_CODEX_RUNTIME_BRIDGE_ENABLED" in os.environ:
        return _env_flag("NORMAN_CODEX_RUNTIME_BRIDGE_ENABLED", False)
    if "NORMAN_CONSOLE_RUNTIME_ENABLED" in os.environ:
        return _env_flag("NORMAN_CONSOLE_RUNTIME_ENABLED", False)
    return bool(api_base)


def _runtime_api_url(api_base: str, path: str) -> str:
    parsed = urllib.parse.urlsplit(str(api_base or "").strip())
    base = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
    )
    clean_path = "/" + str(path or "").lstrip("/")
    if base.endswith("/console-runtime"):
        if clean_path.startswith("/console-runtime/"):
            clean_path = clean_path[len("/console-runtime") :]
        elif clean_path == "/console-runtime":
            clean_path = ""
        return f"{base}{clean_path}"
    if base.endswith("/api/v1"):
        return f"{base}{clean_path}"
    if base.endswith("/api"):
        return f"{base}/v1{clean_path}"
    return f"{base}/api/v1{clean_path}"


def _norman_keys_secret_get_url() -> str:
    base = _first_env("NORMAN_KEYS_URL", "NORMAN_KEYS_API_BASE").rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1/secrets/get"):
        return base
    if base.endswith("/v1"):
        return f"{base}/secrets/get"
    return f"{base}/v1/secrets/get"


def _runtime_token_secret_names() -> list[str]:
    explicit = _first_env(
        "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET",
        "NORMAN_CONSOLE_RUNTIME_SECRET_NAME",
        "NORMAN_KEYS_SECRET_NAME",
    )
    names = [explicit] if explicit else []
    if not explicit and (
        _norman_keys_secret_get_url() or os.environ.get("NORMAN_SECRET_CMD", "").strip()
    ):
        names.extend(CONSOLE_RUNTIME_TOKEN_SECRET_DEFAULTS)
    return list(dict.fromkeys(name for name in names if name))


def _resolve_runtime_token_from_norman_keys(
    secret_name: str,
    *,
    session_id: str,
) -> str:
    url = _norman_keys_secret_get_url()
    if not url:
        return ""
    payload = {
        "name": secret_name,
        "reason": "Terminal Codex runtime bridge route recording",
        "requester_id": _first_env(
            "NORMAN_KEYS_REQUESTER_ID",
            "NORMAN_CONSOLE_RUNTIME_REQUESTER_ID",
        )
        or "runtime-terminal-codex-bridge",
        "session_id": session_id,
        "lane": _first_env("NORMAN_KEYS_LANE", "NORMAN_CONSOLE_RUNTIME_LANE"),
        "target_host": socket.gethostname(),
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    keys_token = _first_env("NORMAN_KEYS_TOKEN", "NORMAN_KEYS_API_TOKEN")
    if keys_token:
        headers["Authorization"] = f"Bearer {keys_token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
        body = response.read().decode("utf-8", "replace")
    parsed = json.loads(body) if body.strip() else {}
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("value") or parsed.get("secret") or "").strip()


def _norman_secret_command(secret_name: str) -> list[str]:
    configured = os.environ.get("NORMAN_SECRET_CMD", "").strip()
    if not configured:
        return []
    command = shlex.split(configured)
    if not command:
        return []
    if "{name}" in configured:
        return [part.replace("{name}", secret_name) for part in command]
    return [*command, "get", secret_name]


def _resolve_runtime_token_from_secret_command(secret_name: str) -> str:
    command = _norman_secret_command(secret_name)
    if not command:
        return ""
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=_timeout_seconds(),
    )
    return result.stdout.strip()


def resolve_console_runtime_token(session_id: str) -> str:
    direct = _first_env("NORMAN_CONSOLE_RUNTIME_TOKEN", "NORMAN_API_TOKEN")
    if direct:
        return direct
    for secret_name in _runtime_token_secret_names():
        try:
            token = _resolve_runtime_token_from_norman_keys(
                secret_name, session_id=session_id
            )
        except (
            json.JSONDecodeError,
            OSError,
            TimeoutError,
            urllib.error.URLError,
        ):
            token = ""
        if token:
            return token
        try:
            token = _resolve_runtime_token_from_secret_command(secret_name)
        except (OSError, subprocess.SubprocessError, TimeoutError):
            token = ""
        if token:
            return token
    return ""


def _safe_identifier(value: str, fallback: str, *, limit: int) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "")).strip("-_.:")
    return (clean or fallback)[:limit]


def terminal_job_id(codex_home: Path, session_id: str) -> str:
    hostname = _safe_identifier(socket.gethostname(), "terminal", limit=36)
    session = _safe_identifier(session_id, "default", limit=36)
    home_hash = hashlib.sha256(
        str(codex_home.expanduser().resolve()).encode("utf-8")
    ).hexdigest()[:12]
    return f"terminal-{hostname}-{session}-{home_hash}"[:128]


def _runtime_json_request(
    api_base: str,
    token: str,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    request = urllib.request.Request(
        _runtime_api_url(api_base, path),
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
        body = response.read().decode("utf-8", "replace")
    parsed = json.loads(body) if body.strip() else {}
    return parsed if isinstance(parsed, dict) else {}


def _job_payload(
    *,
    job_id: str,
    agent_name: str,
    session_id: str,
    service_tier: str,
    model: str,
) -> dict[str, Any]:
    authority = {
        "source": "norman_codex_runtime_bridge",
        "terminal_execution": "native_codex",
        "connector_tool_authority": "native_codex",
        "advisory_only": True,
    }
    return {
        "job_id": job_id,
        "objective": "Record terminal Codex local-first advisory route.",
        "done_when": [
            "Native Codex retains terminal execution and connector authority.",
        ],
        "success_metrics": [
            "The advisory local-first route is visible in console runtime.",
        ],
        "required_artifacts": [],
        "max_runtime_seconds": 7200,
        "checkpoint_interval_seconds": 900,
        "question_budget": 0,
        "authority_flags": authority,
        "route_policy": dict(ROUTE_POLICY),
        "metadata": {
            "source": "norman_codex_runtime_bridge",
            "agent_name": agent_name,
            "session_id": session_id,
            "host_name": socket.gethostname(),
            "service_tier": service_tier,
            "model": model,
            "terminal_execution": "native_codex",
            "connector_tool_authority": "native_codex",
            "advisory_only": True,
        },
    }


def _route_event_payload() -> dict[str, Any]:
    return {
        "event_type": "route.decided",
        "summary": "Advisory local-first route recorded; native Codex retained.",
        "detail": (
            "Norllama is the preflight planner; connector and tool authority "
            "remain native Codex."
        ),
        "visibility": "timeline",
        "payload": {
            "source": "norman_codex_runtime_bridge",
            "terminal_execution": "native_codex",
            "local_preflight_provider": "norllama",
            "connector_tool_authority": "native_codex",
            "route_policy": dict(ROUTE_POLICY),
        },
        "artifacts": [],
    }


def _failure_class(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return "http_409" if exc.code == 409 else f"http_{int(exc.code)}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "network_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_response"
    if isinstance(exc, OSError):
        return "io_error"
    return "bridge_error"


def record_terminal_runtime_route(
    *,
    codex_home: Path,
    session_id: str,
    agent_name: str,
    service_tier: str,
    model: str,
) -> BridgeResult:
    api_base = _runtime_api_base()
    if not _runtime_bridge_enabled(api_base):
        return BridgeResult(status="disabled")
    if not api_base:
        return BridgeResult(status="failed", failure_class="api_not_configured")

    token = resolve_console_runtime_token(session_id)
    if not token:
        return BridgeResult(status="failed", failure_class="token_unavailable")

    job_id = terminal_job_id(codex_home, session_id)
    try:
        response = _runtime_json_request(
            api_base,
            token,
            "/console-runtime/jobs",
            _job_payload(
                job_id=job_id,
                agent_name=agent_name,
                session_id=session_id,
                service_tier=service_tier,
                model=model,
            ),
        )
        remote_job_id = str(response.get("job_id") or "").strip()
        if remote_job_id:
            job_id = remote_job_id
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            return BridgeResult(status="failed", failure_class=_failure_class(exc))
    except (json.JSONDecodeError, OSError, TimeoutError, urllib.error.URLError) as exc:
        return BridgeResult(status="failed", failure_class=_failure_class(exc))

    try:
        _runtime_json_request(
            api_base,
            token,
            f"/console-runtime/jobs/{urllib.parse.quote(job_id, safe='')}/events",
            _route_event_payload(),
        )
    except (json.JSONDecodeError, OSError, TimeoutError, urllib.error.URLError) as exc:
        return BridgeResult(
            status="failed", job_id=job_id, failure_class=_failure_class(exc)
        )
    return BridgeResult(status="connected", job_id=job_id)


def _receipt_path(codex_home: Path) -> Path:
    return (
        codex_home.expanduser().resolve()
        / "web-bridge"
        / "terminal_runtime_route_receipt.json"
    )


def write_receipt(codex_home: Path, result: BridgeResult) -> None:
    state_dir = _receipt_path(codex_home).parent
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": result.status,
        "mode": "control_only",
        "terminal_execution": "native_codex",
        "local_preflight_provider": "norllama",
        "connector_tool_authority": "native_codex",
        "job_id": result.job_id,
        "receipt_at": datetime.now(timezone.utc).isoformat(),
        "failure_class": result.failure_class,
    }
    target = state_dir / "terminal_runtime_route_receipt.json"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=state_dir,
        prefix=".terminal_runtime_route_receipt.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record an advisory local-first route for native terminal Codex."
    )
    parser.add_argument("--codex-home", required=True)
    parser.add_argument(
        "--session-id",
        default=_first_env("NORMAN_CODEX_SESSION", "HOUSEBOT_CODEX_SESSION")
        or "terminal",
    )
    parser.add_argument(
        "--agent-name",
        default=_first_env(
            "NORMAN_CODEX_AGENT_NAME",
            "NORMAN_CONSOLE_RUNTIME_AGENT_NAME",
            "HOUSEBOT_CODEX_AGENT_NAME",
        )
        or "terminal-codex",
    )
    parser.add_argument(
        "--service-tier",
        default=_first_env("NORMAN_CODEX_SERVICE_TIER") or "default",
    )
    parser.add_argument("--model", default=_first_env("NORMAN_CODEX_MODEL"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args(argv)


def _summary(result: BridgeResult) -> str:
    if result.status == "connected":
        return (
            "Terminal runtime bridge connected (control-only; native Codex retained)."
        )
    if result.status == "disabled":
        return "Terminal runtime bridge disabled."
    return f"Terminal runtime bridge unavailable ({result.failure_class or 'failed'}); native Codex retained."


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    codex_home = Path(args.codex_home)
    result = record_terminal_runtime_route(
        codex_home=codex_home,
        session_id=_safe_identifier(args.session_id, "terminal", limit=80),
        agent_name=_safe_identifier(args.agent_name, "terminal-codex", limit=80),
        service_tier=_safe_identifier(args.service_tier, "default", limit=40),
        model=_safe_identifier(args.model, "", limit=120),
    )
    try:
        write_receipt(codex_home, result)
    except OSError:
        result = BridgeResult(
            status="failed",
            job_id=result.job_id,
            failure_class="receipt_write_failed",
        )
    if args.summary:
        print(_summary(result))
    strict = args.strict or _env_flag("NORMAN_CODEX_RUNTIME_BRIDGE_STRICT", False)
    return 1 if strict and result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
