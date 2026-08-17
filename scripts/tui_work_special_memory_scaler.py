#!/usr/bin/env python3
"""Safely raise the work-special LXC memory ceiling under sustained pressure.

LXC memory is a live cgroup limit rather than VM ballooning.  This controller
only increases the ceiling: it never shrinks a running container, restarts a
container, or changes the Proxmox node configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import tui_host_recovery as recovery

SCHEMA = "norman.tui.work-special-memory-scaler.v1"
TARGET_NAME = "work-special"
MIB = 1024 * 1024
GIB = 1024 * MIB
DEFAULT_BASELINE_MIB = int(
    os.environ.get("NORMAN_WORK_SPECIAL_MEMORY_BASELINE_MIB", "8192")
)
DEFAULT_MAX_MIB = int(os.environ.get("NORMAN_WORK_SPECIAL_MEMORY_MAX_MIB", "10240"))
DEFAULT_STEP_MIB = int(os.environ.get("NORMAN_WORK_SPECIAL_MEMORY_STEP_MIB", "1024"))
DEFAULT_NODE_RESERVE_BYTES = int(
    os.environ.get("NORMAN_WORK_SPECIAL_NODE_MEMORY_RESERVE_BYTES", str(4 * GIB))
)
DEFAULT_SUSTAINED_SAMPLES = int(
    os.environ.get("NORMAN_WORK_SPECIAL_MEMORY_SUSTAINED_SAMPLES", "2")
)
DEFAULT_MEMORY_RATIO_THRESHOLD = float(
    os.environ.get("NORMAN_WORK_SPECIAL_MEMORY_RATIO_THRESHOLD", "0.90")
)
DEFAULT_MEMORY_PSI_THRESHOLD = float(
    os.environ.get("NORMAN_WORK_SPECIAL_MEMORY_PSI_THRESHOLD", "20")
)
DEFAULT_SWAP_RATIO_THRESHOLD = float(
    os.environ.get("NORMAN_WORK_SPECIAL_SWAP_RATIO_THRESHOLD", "0.25")
)
DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "NORMAN_WORK_SPECIAL_MEMORY_SCALER_STATE",
        "/home/kristopher/.local/state/norman/work-special-memory-scaler-state.json",
    )
)
DEFAULT_OUTPUT_PATH = Path(
    os.environ.get(
        "NORMAN_WORK_SPECIAL_MEMORY_SCALER_JSON",
        "/home/kristopher/.local/state/norman/work-special-memory-scaler.json",
    )
)

CommandRunner = Callable[[list[str], int], recovery.CommandResult]


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    temporary.replace(path)


def _number(payload: dict[str, Any], key: str) -> float:
    try:
        return max(0.0, float(str(payload.get(key) or "0")))
    except (TypeError, ValueError):
        return 0.0


def _pressure_reasons(current: dict[str, Any]) -> list[str]:
    memory_ratio = _number(current, "mem") / max(1.0, _number(current, "maxmem"))
    swap_ratio = _number(current, "swap") / max(1.0, _number(current, "maxswap"))
    reasons: list[str] = []
    if memory_ratio >= DEFAULT_MEMORY_RATIO_THRESHOLD:
        reasons.append(f"memory_used_ratio>={DEFAULT_MEMORY_RATIO_THRESHOLD:.2f}")
    if swap_ratio >= DEFAULT_SWAP_RATIO_THRESHOLD:
        reasons.append(f"swap_used_ratio>={DEFAULT_SWAP_RATIO_THRESHOLD:.2f}")
    if _number(current, "pressurememorysome") >= DEFAULT_MEMORY_PSI_THRESHOLD:
        reasons.append(f"memory_some>={DEFAULT_MEMORY_PSI_THRESHOLD:.0f}")
    return reasons


def node_memory_status_command(target: recovery.RecoveryTarget) -> list[str]:
    return [
        *recovery.remote_command(target, "pvesh", "get"),
        f"/nodes/{target.proxmox_node}/status",
        "--output-format",
        "json",
    ]


def observe(
    target: recovery.RecoveryTarget,
    *,
    command_runner: CommandRunner = recovery.run_command,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    current_result = command_runner(recovery.pvesh_current_status_command(target), 10)
    node_result = command_runner(node_memory_status_command(target), 10)
    current: dict[str, Any] = {}
    node: dict[str, Any] = {}
    for result, destination in ((current_result, current), (node_result, node)):
        if result.returncode != 0 or not result.stdout.strip():
            continue
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            destination.update(value)
    return current, node, [current_result.stderr.strip(), node_result.stderr.strip()]


def resize_command(target: recovery.RecoveryTarget, memory_mib: int) -> list[str]:
    return recovery.pct_command(
        target, "set", target.container_id, "--memory", str(memory_mib)
    )


def evaluate(
    current: dict[str, Any],
    node: dict[str, Any],
    state: dict[str, Any],
    *,
    baseline_mib: int = DEFAULT_BASELINE_MIB,
    max_mib: int = DEFAULT_MAX_MIB,
    step_mib: int = DEFAULT_STEP_MIB,
    node_reserve_bytes: int = DEFAULT_NODE_RESERVE_BYTES,
    sustained_samples: int = DEFAULT_SUSTAINED_SAMPLES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current_mib = int(_number(current, "maxmem") / MIB)
    if current_mib <= 0:
        current_mib = baseline_mib
    current_mib = max(baseline_mib, current_mib)
    reasons = _pressure_reasons(current)
    next_state = dict(state) if isinstance(state, dict) else {}
    sustained = int(next_state.get("sustained_pressure_samples") or 0)
    sustained = sustained + 1 if reasons else 0
    next_state["sustained_pressure_samples"] = sustained
    next_state["last_memory_mib"] = current_mib
    next_state["last_reasons"] = reasons

    requested_mib = min(max_mib, current_mib + max(1, step_mib))
    requested_bytes = (requested_mib - current_mib) * MIB
    node_memory = node.get("memory") if isinstance(node.get("memory"), dict) else {}
    node_available = _number(node_memory, "available")
    headroom_ok = node_available >= node_reserve_bytes + requested_bytes
    eligible = bool(reasons) and sustained >= max(1, sustained_samples)
    action = "none"
    reason = "pressure normal"
    if not reasons:
        reason = "pressure normal; never auto-shrink"
    elif current_mib >= max_mib:
        reason = "at configured memory ceiling"
    elif not eligible:
        action = "watch"
        reason = "awaiting sustained pressure samples"
    elif not headroom_ok:
        action = "hold"
        reason = "Proxmox node reserve would be violated"
    else:
        action = "grow"
        reason = "sustained container pressure with verified node headroom"

    decision = {
        "schema": SCHEMA,
        "target": TARGET_NAME,
        "checked_at_epoch": int(time.time()),
        "current_memory_mib": current_mib,
        "baseline_memory_mib": baseline_mib,
        "maximum_memory_mib": max_mib,
        "step_memory_mib": step_mib,
        "candidate_memory_mib": requested_mib,
        "sustained_pressure_samples": sustained,
        "required_sustained_samples": max(1, sustained_samples),
        "pressure_reasons": reasons,
        "node_available_bytes": int(node_available),
        "node_reserve_bytes": node_reserve_bytes,
        "headroom_ok": headroom_ok,
        "action": action,
        "reason": reason,
    }
    return decision, next_state


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    command_runner: CommandRunner = recovery.run_command,
) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    target = recovery.RECOVERY_TARGETS[TARGET_NAME]
    current, node, errors = observe(target, command_runner=command_runner)
    decision, state = evaluate(current, node, _load_json(args.state, {}))
    decision["observation_errors"] = [error for error in errors if error]
    if args.apply and decision["action"] == "grow":
        result = command_runner(
            resize_command(target, int(decision["candidate_memory_mib"])), 20
        )
        decision["resize"] = recovery._result_payload(result)
        if result.returncode == 0:
            decision["action"] = "grew"
            state["sustained_pressure_samples"] = 0
        else:
            decision["action"] = "resize_failed"
            return_code = 1
            _write_json(args.state, state)
            _write_json(args.json_output, decision)
            return return_code
    _write_json(args.state, state)
    _write_json(args.json_output, decision)
    if args.json:
        print(json.dumps(decision, indent=2, sort_keys=True))
    else:
        print(
            f"{TARGET_NAME}: action={decision['action']} "
            f"memory={decision['current_memory_mib']}MiB reason={decision['reason']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
