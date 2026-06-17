#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_IDENTITY_FILE = Path("~/.ssh/norman_tui_deploy_ed25519").expanduser()


@dataclass(frozen=True)
class RecoveryTarget:
    name: str
    lan_host: str
    public_host: str
    proxmox_host: str
    proxmox_node: str
    container_id: str
    identity_file: Path = DEFAULT_IDENTITY_FILE
    ssh_user: str = "root"
    graceful_timeout_seconds: int = 60
    verify_ports: tuple[int, ...] = (22, 80, 8781)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], int], CommandResult]


RECOVERY_TARGETS = {
    "work-special": RecoveryTarget(
        name="work-special",
        lan_host="192.168.2.147",
        public_host="work-special.home.arpa",
        proxmox_host="proxmox.home.arpa",
        proxmox_node="vm",
        container_id="147",
    )
}


def ssh_prefix(target: RecoveryTarget) -> list[str]:
    return [
        "ssh",
        "-i",
        str(target.identity_file),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        f"{target.ssh_user}@{target.proxmox_host}",
    ]


def pct_command(target: RecoveryTarget, *args: str) -> list[str]:
    return [*ssh_prefix(target), "pct", *args]


def pvesh_current_status_command(target: RecoveryTarget) -> list[str]:
    return [
        *ssh_prefix(target),
        "pvesh",
        "get",
        f"/nodes/{target.proxmox_node}/lxc/{target.container_id}/status/current",
        "--output-format",
        "json",
    ]


def run_command(command: list[str], timeout_seconds: int) -> CommandResult:
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or f"timed out after {timeout_seconds}s",
        )
    return CommandResult(
        command=command,
        returncode=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def tcp_probe(host: str, port: int, *, timeout_seconds: float = 2.0) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
            sock.settimeout(timeout_seconds)
            if port != 22:
                sock.sendall(f"GET / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
            try:
                data = sock.recv(64)
            except socket.timeout:
                label = "SSH banner" if port == 22 else "HTTP bytes"
                return f"connected; no {label} within {timeout_seconds:g}s"
            return "responded" if data else "closed"
    except socket.timeout:
        return "TCP timeout"
    except OSError as exc:
        return f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else exc}"


def _result_payload(result: CommandResult) -> dict[str, Any]:
    return {
        "command": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "ok": result.returncode == 0,
    }


def observe_target(
    target: RecoveryTarget,
    *,
    command_runner: CommandRunner = run_command,
) -> dict[str, Any]:
    probes = {
        f"{target.public_host}:{port}": tcp_probe(target.public_host, port)
        for port in target.verify_ports
    }
    status = command_runner(pct_command(target, "status", target.container_id), 10)
    current = command_runner(pvesh_current_status_command(target), 10)
    current_json: dict[str, Any] = {}
    if current.returncode == 0 and current.stdout.strip():
        try:
            parsed = json.loads(current.stdout)
            if isinstance(parsed, dict):
                current_json = parsed
        except json.JSONDecodeError:
            current_json = {}
    return {
        "target": target.name,
        "probes": probes,
        "pct_status": _result_payload(status),
        "pvesh_status": _result_payload(current),
        "pvesh_status_json": current_json,
    }


def recovery_plan(target: RecoveryTarget) -> dict[str, Any]:
    reboot = pct_command(
        target,
        "reboot",
        target.container_id,
        "--timeout",
        str(target.graceful_timeout_seconds),
    )
    fallback = pct_command(target, "stop", target.container_id)
    restart = pct_command(target, "start", target.container_id)
    return {
        "target": target.name,
        "container_id": target.container_id,
        "approval_required": True,
        "default_mode": "observe_only",
        "first_action": {
            "kind": "graceful_reboot",
            "command": reboot,
            "why": "Use when TCP connects but SSH/HTTP/TUI requests stop completing and pct exec/status indicates the LXC is wedged.",
        },
        "fallback_action": {
            "kind": "hard_stop_start",
            "commands": [fallback, restart],
            "why": "Use only if graceful reboot times out and the operator approves the stronger recovery.",
        },
        "post_checks": [
            f"ssh root@{target.lan_host} hostname",
            f"curl -I http://{target.public_host}/",
            "python3 scripts/tui_fleet_doctor.py --targets work-special --json",
        ],
    }


def execute_graceful_reboot(
    target: RecoveryTarget,
    *,
    command_runner: CommandRunner = run_command,
) -> CommandResult:
    return command_runner(
        pct_command(
            target,
            "reboot",
            target.container_id,
            "--timeout",
            str(target.graceful_timeout_seconds),
        ),
        target.graceful_timeout_seconds + 30,
    )


def render_markdown(payload: dict[str, Any]) -> str:
    plan = payload["plan"]
    lines = [
        f"# TUI Host Recovery: {payload['target']}",
        "",
        f"Mode: `{payload['mode']}`",
        f"Approval required: `{str(plan['approval_required']).lower()}`",
        "",
        "## Plan",
        "",
        f"- First action: `{ ' '.join(plan['first_action']['command']) }`",
        f"- Fallback action: `{ ' && '.join(' '.join(cmd) for cmd in plan['fallback_action']['commands']) }`",
        "",
        "## Observation",
        "",
    ]
    observation = payload.get("observation") or {}
    for name, detail in (observation.get("probes") or {}).items():
        lines.append(f"- {name}: {detail}")
    status = observation.get("pct_status") or {}
    if status:
        lines.append(
            f"- pct status: rc={status.get('returncode')} {status.get('stdout') or status.get('stderr')}"
        )
    current = observation.get("pvesh_status_json") or {}
    if current:
        lines.append(
            "- pressure: cpu_some={cpu} io_some={io} mem_some={mem}".format(
                cpu=current.get("pressurecpusome", "unknown"),
                io=current.get("pressureiosome", "unknown"),
                mem=current.get("pressurememorysome", "unknown"),
            )
        )
    action = payload.get("action")
    if action:
        lines.extend(
            [
                "",
                "## Action",
                "",
                f"- rc={action.get('returncode')}",
                f"- stdout={action.get('stdout') or ''}",
                f"- stderr={action.get('stderr') or ''}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_payload(
    target: RecoveryTarget,
    *,
    mode: str,
    observation: dict[str, Any],
    action: CommandResult | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target": target.name,
        "mode": mode,
        "plan": recovery_plan(target),
        "observation": observation,
    }
    if action is not None:
        payload["action"] = _result_payload(action)
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Approval-gated host recovery helper for wedged TUI hosts."
    )
    parser.add_argument("--target", choices=sorted(RECOVERY_TARGETS), required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Required with --execute; means the operator approved this recovery.",
    )
    parser.add_argument("--settle-seconds", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    target = RECOVERY_TARGETS[args.target]
    if args.execute and not args.approved:
        print(
            "--execute requires --approved after explicit operator approval",
            file=sys.stderr,
        )
        return 2

    observation = observe_target(target)
    action = None
    mode = "observe_only"
    if args.execute:
        mode = "approved_graceful_reboot"
        action = execute_graceful_reboot(target)
        time.sleep(max(0, int(args.settle_seconds or 0)))
        observation = observe_target(target)

    payload = build_payload(target, mode=mode, observation=observation, action=action)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_markdown(payload), end="")
    return 0 if action is None or action.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
