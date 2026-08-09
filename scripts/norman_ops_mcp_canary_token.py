#!/usr/bin/env python3
"""Resolve the dedicated read-only Ops MCP canary credential."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SECRET = "control-plane/ops-mcp-canary-key"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_BROKER_COMMAND = Path("/usr/local/sbin/norman-ops-mcp-canary-broker")


def _clean(value: object) -> str:
    return str(value or "").strip()


def _timeout_seconds() -> float:
    try:
        return max(
            0.1,
            float(
                _clean(os.getenv("NORMAN_OPS_MCP_CANARY_TOKEN_TIMEOUT_SECONDS"))
                or DEFAULT_TIMEOUT_SECONDS
            ),
        )
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _broker_command() -> list[str]:
    configured = _clean(os.getenv("NORMAN_OPS_MCP_CANARY_BROKER"))
    candidate = Path(configured).expanduser() if configured else DEFAULT_BROKER_COMMAND
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return []
    return [str(candidate), "get"]


def resolve_token() -> str:
    command = _broker_command()
    if not command:
        return ""
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=_timeout_seconds(),
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return ""
    return _clean(result.stdout)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secret",
        default=DEFAULT_SECRET,
        help="Fixed logical Ops MCP canary secret name",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if _clean(args.secret) != DEFAULT_SECRET:
        print("The requested Ops MCP canary secret is not approved.", file=sys.stderr)
        return 2
    token = resolve_token()
    if not token:
        print(
            "Unable to resolve the dedicated Ops MCP canary credential.",
            file=sys.stderr,
        )
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
