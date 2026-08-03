#!/usr/bin/env python3
"""Broker approved Codex gateway tokens from Norman's encrypted cred vault."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


DEFAULT_CRED_BIN = Path("/usr/local/bin/cred")
DEFAULT_SOURCE_SECRET = "norman/prompt-proxy-token"
ROUTE_SECRETS = frozenset(
    {
        "autocamera/prompt-proxy-token",
        "cloudagent/prompt-proxy-token",
        "compere/prompt-proxy-token",
        "control-plane/prompt-proxy-token",
        "earlybird/prompt-proxy-token",
        "glimpser/prompt-proxy-token",
        "gold-book/prompt-proxy-token",
        "housebot/prompt-proxy-token",
        "infra/prompt-proxy-token",
        "market-sizing/prompt-proxy-token",
        "networking/prompt-proxy-token",
        "norman/prompt-proxy-token",
        "parkergale/prompt-proxy-token",
        "theseus/prompt-proxy-token",
        "tmi-dashboards/prompt-proxy-token",
    }
)


class BrokerError(RuntimeError):
    """Expected broker failure that must not disclose a token value."""


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


def _read_secret(secret_name: str) -> str:
    if secret_name not in ROUTE_SECRETS:
        raise BrokerError("requested alias is not approved for Codex gateway use")
    try:
        result = subprocess.run(
            _cred_command("get", secret_name),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        raise BrokerError("encrypted cred lookup failed") from exc
    value = _clean(result.stdout)
    if not value:
        raise BrokerError("encrypted cred returned an empty token")
    return value


def _write_secret(secret_name: str, value: str) -> None:
    try:
        subprocess.run(
            _cred_command(
                "put",
                secret_name,
                "--stdin",
                "--source",
                "norman-codex-gateway-broker",
                "--note",
                "Codex checkout gateway alias",
            ),
            input=value,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        raise BrokerError("encrypted cred alias update failed") from exc


def _audit(action: str, secret_name: str = "") -> None:
    requester = _clean(os.getenv("SSH_CONNECTION")).split(" ", 1)[0] or "local"
    message = f"{action} requester={requester}"
    if secret_name:
        message = f"{message} alias={secret_name}"
    try:
        subprocess.run(
            [
                "logger",
                "-p",
                "authpriv.notice",
                "-t",
                "norman-codex-gateway-broker",
                message,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        pass


def provision_route_aliases() -> int:
    source = _read_secret(DEFAULT_SOURCE_SECRET)
    copied = 0
    for secret_name in sorted(ROUTE_SECRETS):
        if secret_name == DEFAULT_SOURCE_SECRET:
            continue
        _write_secret(secret_name, source)
        copied += 1
    _audit("provisioned", "all-routes")
    print(f"provisioned={copied} aliases")
    return 0


def get_route_token(secret_name: str) -> int:
    token = _read_secret(secret_name)
    _audit("issued", secret_name)
    print(token)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Broker approved Codex gateway tokens from Norman cred."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("get", help="print one approved gateway token")
    get.add_argument("secret")
    commands.add_parser(
        "provision",
        help="copy the existing Norman gateway token into checkout aliases",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "get":
            return get_route_token(str(args.secret))
        return provision_route_aliases()
    except BrokerError as exc:
        _audit("denied", _clean(getattr(args, "secret", "")))
        print(f"Norman Codex gateway broker failed: {exc}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
