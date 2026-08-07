#!/usr/bin/env python3
"""Broker the networking TUI's approved device aliases from encrypted cred."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence


DEFAULT_CRED_BIN = Path("/usr/local/bin/cred")
DEFAULT_KEYS_URL = "http://127.0.0.1:8000/v1/secrets/get"
DEFAULT_TIMEOUT_SECONDS = 5.0
KEYS_SERVICE_TOKEN_SECRET = "norman/keys-service-token"
NETWORKING_SECRETS = frozenset(
    {
        "networking/firewall",
        "networking/netgear",
        "networking/dot10",
    }
)


class BrokerError(RuntimeError):
    """Expected broker failure that must not disclose secret values."""


class NormanKeysUnavailableError(BrokerError):
    """Norman Keys could not complete a request, so fallback may be allowed."""


class NormanKeysAliasMissingError(BrokerError):
    """The requested alias has not yet been provisioned in Norman Keys."""


def _clean(value: object) -> str:
    return str(value or "").strip()


def _first_env(*names: str) -> str:
    for name in names:
        value = _clean(os.getenv(name))
        if value:
            return value
    return ""


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


def _keys_secret_get_url() -> str:
    base_url = _first_env(
        "NORMAN_NETWORKING_KEYS_URL",
        "NORMAN_KEYS_URL",
        "NORMAN_KEYS_API_BASE",
    ).rstrip("/")
    if not base_url:
        return DEFAULT_KEYS_URL
    if base_url.endswith("/v1/secrets/get"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/secrets/get"
    return f"{base_url}/v1/secrets/get"


def _timeout_seconds() -> float:
    configured = _first_env(
        "NORMAN_NETWORKING_SECRET_TIMEOUT_SECONDS",
        "NORMAN_KEYS_TIMEOUT_SECONDS",
    )
    try:
        return min(max(0.1, float(configured or DEFAULT_TIMEOUT_SECONDS)), 30.0)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _read_cred_secret(secret_name: str) -> str:
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
        raise BrokerError("encrypted cred returned an empty secret")
    return value


def _read_from_norman_keys(secret_name: str) -> str:
    try:
        service_token = _read_cred_secret(KEYS_SERVICE_TOKEN_SECRET)
    except BrokerError as exc:
        raise NormanKeysUnavailableError(
            "Norman Keys service credentials are unavailable"
        ) from exc

    payload = {
        "name": secret_name,
        "reason": "Networking TUI approved device access",
        "requester_type": "agent",
        "requester_id": _first_env("NORMAN_NETWORKING_REQUESTER_ID")
        or "networking-tui",
        "session_id": _first_env("NORMAN_NETWORKING_SESSION_ID") or "networking-tui",
        "lane": _first_env("NORMAN_NETWORKING_LANE") or "personal",
        "intent": "networking-tui-secret-broker",
        "target_host": _first_env("NORMAN_KEYS_TARGET_HOST") or socket.gethostname(),
    }
    request = urllib.request.Request(
        _keys_secret_get_url(),
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {service_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NormanKeysAliasMissingError(
                "alias is not provisioned in Norman Keys"
            ) from exc
        if exc.code in {403, 409}:
            raise BrokerError(
                "Norman Keys requires policy approval before this alias can be issued"
            ) from exc
        raise NormanKeysUnavailableError(
            "Norman Keys service request did not complete"
        ) from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise NormanKeysUnavailableError("Norman Keys service is unavailable") from exc

    try:
        parsed: Any = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise NormanKeysUnavailableError(
            "Norman Keys returned an invalid secret response"
        ) from exc
    if not isinstance(parsed, dict):
        raise NormanKeysUnavailableError(
            "Norman Keys returned an invalid secret response"
        )
    value = _clean(parsed.get("value") or parsed.get("secret"))
    if not value:
        raise NormanKeysUnavailableError(
            "Norman Keys returned an empty secret response"
        )
    return value


def _read_secret(secret_name: str) -> str:
    if secret_name not in NETWORKING_SECRETS:
        raise BrokerError("requested alias is not approved for networking TUI use")

    # Both the Keys service token and encrypted fallback are available only in
    # the scoped systemd credential context.
    _credential_passphrase_file()
    keys_alias_missing = False
    try:
        return _read_from_norman_keys(secret_name)
    except NormanKeysAliasMissingError:
        keys_alias_missing = True
    except NormanKeysUnavailableError:
        pass

    try:
        return _read_cred_secret(secret_name)
    except BrokerError as exc:
        if keys_alias_missing:
            raise BrokerError(
                "approved alias is not provisioned in Norman Keys or the encrypted "
                "fallback vault; add the logical alias through Norman Keys"
            ) from exc
        raise BrokerError(
            "approved alias is unavailable from Norman Keys and the encrypted "
            "fallback vault"
        ) from exc


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
                "norman-networking-secret-broker",
                message,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        pass


def get_networking_secret(secret_name: str) -> int:
    secret = _read_secret(secret_name)
    _audit("issued", secret_name)
    print(secret)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Broker approved networking device credentials from Norman cred."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("get", help="print one approved networking secret")
    get.add_argument("secret")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    secret_name = _clean(getattr(args, "secret", ""))
    try:
        return get_networking_secret(secret_name)
    except BrokerError as exc:
        _audit("denied", secret_name)
        print(f"Norman networking secret broker failed: {exc}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
