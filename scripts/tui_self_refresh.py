#!/usr/bin/env python3
"""Operator-consented helper for refreshing a TUI web wrapper."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_target() -> str:
    return (
        os.environ.get("NORMAN_TUI_REFRESH_TARGET")
        or os.environ.get("NORMAN_CODEX_AGENT_NAME")
        or os.environ.get("NORMAN_CODEX_SESSION")
        or os.environ.get("HOUSEBOT_CODEX_AGENT_NAME")
        or os.environ.get("HOUSEBOT_CODEX_SESSION")
        or "norman"
    ).strip()


def normalize_target(value: str) -> str:
    clean = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "norman-console": "norman",
        "norman-codex": "norman",
        "norman-prime": "norman",
        "controlplane": "control-plane",
        "control-plane-tui": "control-plane",
        "panel-bot": "panelbot",
    }
    return aliases.get(clean, clean)


def build_sync_command(repo_root: Path, target: str, *, force: bool) -> list[str]:
    command = [
        str(repo_root / ".venv" / "bin" / "python"),
        str(repo_root / "scripts" / "sync_agent_console_template.py"),
        "--targets",
        normalize_target(target),
        "--restart-web-only",
    ]
    if force:
        command.append("--force-restart")
    return command


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=default_target(),
        help="Console or host target to refresh. Defaults to the current TUI identity when available.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(default_repo_root()),
        help="Path to the Norman repo root.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow cutting off an active prompt by passing --force-restart to the sync helper.",
    )
    parser.add_argument(
        "--operator-consent-cutoff",
        action="store_true",
        help="Required with --force. Records that the operator explicitly allowed cutting off the active turn.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Wait before the first refresh attempt.",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="Number of guarded retry attempts. Useful without --force while waiting for a turn to finish.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=5.0,
        help="Delay between retry attempts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would run without refreshing anything.",
    )
    return parser.parse_args(argv)


def run_refresh(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    target = normalize_target(args.target)
    force = bool(args.force)
    if force and not args.operator_consent_cutoff:
        print(
            "Refusing forced self-refresh without --operator-consent-cutoff.",
            file=sys.stderr,
        )
        return 2

    command = build_sync_command(repo_root, target, force=force)
    if args.dry_run:
        print(" ".join(command))
        return 0

    attempts = max(1, int(args.attempts or 1))
    delay_seconds = max(0.0, float(args.delay_seconds or 0))
    interval_seconds = max(0.0, float(args.interval_seconds or 0))
    if delay_seconds:
        print(f"Waiting {delay_seconds:g}s before refreshing {target}.", flush=True)
        time.sleep(delay_seconds)

    last_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, attempts + 1):
        print(
            f"Refreshing {target} web wrapper "
            f"({attempt}/{attempts}, force={str(force).lower()}).",
            flush=True,
        )
        result = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        last_result = result
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        skipped = "skip web restart" in (result.stdout or "")
        if result.returncode == 0 and not skipped:
            return 0
        if force:
            return result.returncode or 1
        if attempt < attempts and interval_seconds:
            time.sleep(interval_seconds)
    return (last_result.returncode if last_result else 1) or 1


def main(argv: list[str] | None = None) -> int:
    return run_refresh(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
