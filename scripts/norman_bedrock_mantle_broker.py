#!/usr/bin/env python3
"""Mint an approved Bedrock Mantle bearer token from encrypted AWS credentials."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from aws_bedrock_token_generator import BedrockTokenGenerator
from botocore.credentials import Credentials


DEFAULT_CRED_BIN = Path("/usr/local/bin/cred")
MANTLE_SECRET_ALIAS = "networking/bedrock-mantle"
AWS_CREDENTIALS_ALIAS = "norman/bedrock-fallback"


class BrokerError(RuntimeError):
    """Expected broker failure that must not disclose credentials or bearer tokens."""


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


def _credential_value(bundle: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean(bundle.get(key))
        if value:
            return value
    return ""


def _parse_aws_credentials(raw_value: str) -> Credentials:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise BrokerError("encrypted cred returned invalid AWS credentials") from exc
    if not isinstance(parsed, Mapping):
        raise BrokerError("encrypted cred returned invalid AWS credentials")
    bundle = parsed.get("credentials")
    if not isinstance(bundle, Mapping):
        bundle = parsed
    access_key_id = _credential_value(
        bundle,
        "aws_access_key_id",
        "access_key_id",
        "AWS_ACCESS_KEY_ID",
        "AccessKeyId",
    )
    secret_access_key = _credential_value(
        bundle,
        "aws_secret_access_key",
        "secret_access_key",
        "AWS_SECRET_ACCESS_KEY",
        "SecretAccessKey",
    )
    session_token = _credential_value(
        bundle,
        "aws_session_token",
        "session_token",
        "AWS_SESSION_TOKEN",
        "SessionToken",
    )
    if not access_key_id or not secret_access_key:
        raise BrokerError("encrypted cred returned incomplete AWS credentials")
    return Credentials(access_key_id, secret_access_key, session_token or None)


def _read_aws_credentials() -> Credentials:
    try:
        result = subprocess.run(
            _cred_command("get", AWS_CREDENTIALS_ALIAS),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        raise BrokerError("encrypted cred lookup failed") from exc
    raw_value = _clean(result.stdout)
    if not raw_value:
        raise BrokerError("encrypted cred returned empty AWS credentials")
    return _parse_aws_credentials(raw_value)


def _region() -> str:
    for name in (
        "NORMAN_BEDROCK_MANTLE_REGION",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    ):
        value = _clean(os.getenv(name))
        if value:
            return value
    raise BrokerError("Bedrock Mantle region is unavailable")


def _mint_token(credentials: Credentials, region: str) -> str:
    try:
        token = _clean(BedrockTokenGenerator().get_token(credentials, region))
    except Exception as exc:
        raise BrokerError("Bedrock Mantle bearer token generation failed") from exc
    if not token:
        raise BrokerError("Bedrock Mantle bearer token generation returned empty")
    return token


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
                "norman-bedrock-mantle-broker",
                message,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        pass


def get_mantle_token(secret_name: str) -> str:
    if secret_name != MANTLE_SECRET_ALIAS:
        raise BrokerError("requested alias is not approved for Bedrock Mantle use")
    return _mint_token(_read_aws_credentials(), _region())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mint approved Bedrock Mantle bearer tokens from Norman cred."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("get", help="print one approved bearer token")
    get.add_argument("secret")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    secret_name = _clean(getattr(args, "secret", ""))
    try:
        token = get_mantle_token(secret_name)
    except BrokerError as exc:
        _audit("denied", secret_name)
        print(f"Norman Bedrock Mantle broker failed: {exc}.", file=sys.stderr)
        return 1
    _audit("issued", secret_name)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
