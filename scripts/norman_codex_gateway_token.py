#!/usr/bin/env python3
"""Print a brokered Norman prompt-proxy token for Codex command authentication."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_SECRET = "norman/prompt-proxy-token"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_CRED_BIN = Path.home() / ".local" / "bin" / "cred"
DEFAULT_BROKER_COMMAND = (
    Path(__file__).resolve().with_name("norman_codex_gateway_broker.sh")
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _first_env(*names: str) -> str:
    for name in names:
        value = _clean(os.getenv(name))
        if value:
            return value
    return ""


def _keys_secret_get_url() -> str:
    base_url = _first_env("NORMAN_KEYS_URL", "NORMAN_KEYS_API_BASE").rstrip("/")
    if not base_url:
        return ""
    if base_url.endswith("/v1/secrets/get"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/secrets/get"
    return f"{base_url}/v1/secrets/get"


def _timeout_seconds() -> float:
    configured = _first_env(
        "NORMAN_CODEX_GATEWAY_TOKEN_TIMEOUT_SECONDS",
        "NORMAN_KEYS_TIMEOUT_SECONDS",
    )
    try:
        return max(0.1, float(configured or DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _secret_command(secret_name: str) -> list[str]:
    configured = _first_env("NORMAN_SECRET_CMD")
    if not configured:
        return []
    command = shlex.split(configured)
    if not command:
        return []
    if "{name}" in configured:
        return [part.replace("{name}", secret_name) for part in command]
    return [*command, "get", secret_name]


def _encrypted_cred_command(secret_name: str) -> list[str]:
    configured = _first_env("NORMAN_CRED_BIN")
    candidate = Path(configured).expanduser() if configured else DEFAULT_CRED_BIN
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return []
    return [str(candidate), "get", secret_name]


def _installed_broker_command(secret_name: str) -> list[str]:
    candidate = DEFAULT_BROKER_COMMAND
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return []
    return [str(candidate), "get", secret_name]


def _resolve_from_norman_keys(secret_name: str) -> str:
    url = _keys_secret_get_url()
    if not url:
        return ""
    payload = {
        "name": secret_name,
        "reason": "Codex CLI Norman gateway bearer token",
        "requester_id": _first_env(
            "NORMAN_KEYS_REQUESTER_ID",
            "NORMAN_CODEX_GATEWAY_REQUESTER_ID",
        )
        or "codex-cli-gateway",
        "session_id": _first_env("NORMAN_CODEX_SESSION", "HOUSEBOT_CODEX_SESSION")
        or "codex-cli",
        "lane": _first_env("NORMAN_KEYS_LANE", "NORMAN_CODEX_LANE") or "terminal-codex",
        "target_host": _first_env("NORMAN_KEYS_TARGET_HOST") or socket.gethostname(),
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    broker_token = _first_env("NORMAN_KEYS_TOKEN", "NORMAN_KEYS_API_TOKEN")
    if broker_token:
        headers["Authorization"] = f"Bearer {broker_token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body) if body.strip() else {}
    if not isinstance(parsed, dict):
        raise ValueError("Norman Keys returned an invalid secret response")
    token = _clean(parsed.get("value") or parsed.get("secret"))
    if not token:
        raise ValueError("Norman Keys returned an empty secret response")
    return token


def _resolve_from_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=_timeout_seconds(),
    )
    token = _clean(result.stdout)
    if not token:
        raise ValueError("Norman secret broker command returned an empty secret")
    return token


def resolve_token(secret_name: str) -> tuple[str, list[str]]:
    errors: list[str] = []
    if _keys_secret_get_url():
        try:
            token = _resolve_from_norman_keys(secret_name)
        except (
            json.JSONDecodeError,
            OSError,
            TimeoutError,
            urllib.error.URLError,
            ValueError,
        ):
            errors.append("Norman Keys HTTP broker request failed")
        else:
            if token:
                return token, errors

    command = _secret_command(secret_name)
    command_label = "Norman secret broker command"
    if not command:
        command = _installed_broker_command(secret_name)
        command_label = "installed Norman Codex gateway broker"
    if not command:
        command = _encrypted_cred_command(secret_name)
        command_label = "encrypted cred vault"
    if command:
        try:
            token = _resolve_from_command(command)
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError):
            errors.append(f"{command_label} lookup failed")
        else:
            if token:
                return token, errors

    return "", errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve a Norman gateway bearer token through an approved broker."
    )
    parser.add_argument(
        "--secret",
        default=_first_env("NORMAN_CODEX_GATEWAY_TOKEN_SECRET") or DEFAULT_SECRET,
        help="Logical Norman Keys secret name",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    secret_name = _clean(args.secret)
    if not secret_name:
        print(
            "A logical Norman gateway token secret name is required.", file=sys.stderr
        )
        return 2

    token, errors = resolve_token(secret_name)
    if token:
        print(token)
        return 0

    detail = "; ".join(errors) if errors else "no approved broker is configured"
    print(f"Unable to resolve Norman gateway token: {detail}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
