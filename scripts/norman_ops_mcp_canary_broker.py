#!/usr/bin/env python3
"""Broker a single read-only Ops MCP canary credential from encrypted cred."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_CRED_BIN = Path("/usr/local/bin/cred")
OPS_MCP_CANARY_SECRET = "control-plane/ops-mcp-canary-key"
MAX_TOKEN_BYTES = 16 * 1024


class BrokerError(RuntimeError):
    """Expected failure that must not disclose the credential."""


def _clean(value: object) -> str:
    return str(value or "").strip()


def _credential_passphrase_file() -> Path:
    credentials_dir = _clean(os.getenv("CREDENTIALS_DIRECTORY"))
    if not credentials_dir:
        raise BrokerError("systemd credentials directory is unavailable")
    path = Path(credentials_dir) / "norman-cred-passphrase"
    if not path.is_file():
        raise BrokerError("credential passphrase is unavailable")
    return path


def _cred_bin() -> Path:
    configured = _clean(os.getenv("NORMAN_CRED_BIN"))
    candidate = Path(configured).expanduser() if configured else DEFAULT_CRED_BIN
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise BrokerError("encrypted cred executable is unavailable")
    return candidate


def _cred_command(*arguments: str) -> list[str]:
    return [
        str(_cred_bin()),
        "--passphrase-file",
        str(_credential_passphrase_file()),
        *arguments,
    ]


def _audit(action: str) -> None:
    requester = _clean(os.getenv("SSH_CONNECTION")).split(" ", 1)[0] or "local"
    try:
        subprocess.run(
            [
                "logger",
                "-p",
                "authpriv.notice",
                "-t",
                "norman-ops-mcp-canary-broker",
                f"{action} requester={requester} alias={OPS_MCP_CANARY_SECRET}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        pass


def _read_secret() -> str:
    try:
        result = subprocess.run(
            _cred_command("get", OPS_MCP_CANARY_SECRET),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        raise BrokerError("encrypted cred lookup failed") from exc
    value = _clean(result.stdout)
    if not value:
        raise BrokerError("encrypted cred returned an empty credential")
    return value


def _provision_secret() -> None:
    raw = sys.stdin.buffer.read(MAX_TOKEN_BYTES + 1)
    if len(raw) > MAX_TOKEN_BYTES:
        raise BrokerError("credential input is too large")
    value = raw.decode("utf-8", errors="strict").strip()
    if not value:
        raise BrokerError("credential input is empty")
    try:
        subprocess.run(
            _cred_command(
                "put",
                OPS_MCP_CANARY_SECRET,
                "--stdin",
                "--source",
                "norman-ops-mcp-canary-broker",
                "--note",
                "read-only Ops MCP continuation canary",
            ),
            input=value,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        raise BrokerError("encrypted cred update failed") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("get", "provision"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "get":
            print(_read_secret())
        else:
            _provision_secret()
            print(f"provisioned={OPS_MCP_CANARY_SECRET}")
        _audit(args.command)
        return 0
    except (BrokerError, UnicodeDecodeError) as exc:
        _audit("denied")
        print(f"Ops MCP canary broker failed: {exc}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
