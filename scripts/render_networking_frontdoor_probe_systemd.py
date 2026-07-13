#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_REPO_ROOT = "/home/debian/code/norman"
DEFAULT_OUTPUT_PATH = "/var/lib/norman/frontdoor-road-health.json"
DEFAULT_PYTHON = ".venv/bin/python"
DEFAULT_TIMER_INTERVAL = "2min"


def _script_path(repo_root: str) -> str:
    return str(Path(repo_root) / "scripts" / "check_frontdoor_tls.py")


def _python_path(repo_root: str, python: str) -> str:
    path = Path(python)
    if path.is_absolute():
        return str(path)
    return str(Path(repo_root) / path)


def render_service(
    *,
    repo_root: str = DEFAULT_REPO_ROOT,
    python: str = DEFAULT_PYTHON,
    output_path: str = DEFAULT_OUTPUT_PATH,
    timeout_seconds: int = 3,
) -> str:
    return f"""[Unit]
Description=Norman road/mobile frontdoor probe
Wants=network-online.target tailscaled.service
After=network-online.target tailscaled.service

[Service]
Type=oneshot
User=debian
Group=debian
WorkingDirectory={repo_root}
StateDirectory=norman
ExecStart={_python_path(repo_root, python)} {_script_path(repo_root)} --profile road --dns-profile networking --no-trust-check --timeout {timeout_seconds} --json --output {output_path} --exit-zero
"""


def render_timer(*, interval: str = DEFAULT_TIMER_INTERVAL) -> str:
    return f"""[Unit]
Description=Run Norman road/mobile frontdoor probe

[Timer]
OnBootSec=45s
OnUnitActiveSec={interval}
AccuracySec=15s
Unit=norman-frontdoor-probe.service

[Install]
WantedBy=timers.target
"""


def render_all(
    *,
    repo_root: str = DEFAULT_REPO_ROOT,
    python: str = DEFAULT_PYTHON,
    output_path: str = DEFAULT_OUTPUT_PATH,
    timeout_seconds: int = 3,
    interval: str = DEFAULT_TIMER_INTERVAL,
) -> str:
    return (
        "# /etc/systemd/system/norman-frontdoor-probe.service\n"
        + render_service(
            repo_root=repo_root,
            python=python,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
        )
        + "\n# /etc/systemd/system/norman-frontdoor-probe.timer\n"
        + render_timer(interval=interval)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render networking-host systemd units for the Norman frontdoor probe."
    )
    parser.add_argument("--repo-root", default=DEFAULT_REPO_ROOT)
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--timeout", type=int, default=3)
    parser.add_argument("--interval", default=DEFAULT_TIMER_INTERVAL)
    parser.add_argument(
        "--unit",
        choices=("service", "timer", "all"),
        default="all",
        help="Which systemd unit content to render.",
    )
    args = parser.parse_args()
    if args.unit == "service":
        print(
            render_service(
                repo_root=args.repo_root,
                python=args.python,
                output_path=args.output,
                timeout_seconds=args.timeout,
            )
        )
        return
    if args.unit == "timer":
        print(render_timer(interval=args.interval))
        return
    print(
        render_all(
            repo_root=args.repo_root,
            python=args.python,
            output_path=args.output,
            timeout_seconds=args.timeout,
            interval=args.interval,
        )
    )


if __name__ == "__main__":
    main()
