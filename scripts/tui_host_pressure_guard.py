#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

import tui_host_recovery as recovery


DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "NORMAN_TUI_HOST_PRESSURE_GUARD_STATE",
        "/home/kristopher/.local/state/norman/tui-host-pressure-guard-state.json",
    )
)
DEFAULT_OUTPUT_JSON = Path(
    os.environ.get(
        "NORMAN_TUI_HOST_PRESSURE_GUARD_JSON",
        "/home/kristopher/.local/state/norman/tui-host-pressure-guard.json",
    )
)
DEFAULT_CRITICAL_THRESHOLD = int(
    os.environ.get("NORMAN_TUI_HOST_PRESSURE_GUARD_CRITICAL_THRESHOLD", "2")
)


ObserveFn = Callable[[recovery.RecoveryTarget], dict[str, Any]]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _coerce_float(value: Any) -> float:
    try:
        return max(0.0, float(str(value or "0").strip()))
    except (TypeError, ValueError):
        return 0.0


def _ratio(used: Any, total: Any) -> float:
    total_value = _coerce_float(total)
    if total_value <= 0:
        return 0.0
    return min(1.0, _coerce_float(used) / total_value)


def _psi_avg10(path: Path, category: str) -> float | None:
    for raw in _read_text(path).splitlines():
        fields = raw.split()
        if not fields or fields[0] != category:
            continue
        for field in fields[1:]:
            key, separator, value = field.partition("=")
            if key != "avg10" or not separator:
                continue
            try:
                return max(0.0, float(value))
            except ValueError:
                return None
    return None


def _meminfo_values(proc_root: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for raw in _read_text(proc_root / "meminfo").splitlines():
        key, separator, raw_value = raw.partition(":")
        if not separator:
            continue
        fields = raw_value.split()
        if not fields:
            continue
        try:
            values[key] = max(0, int(fields[0]) * 1024)
        except ValueError:
            continue
    return values


def local_pressure_status(*, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    """Return host pressure only when the remote status API omits it."""

    meminfo = _meminfo_values(proc_root)
    total_memory = int(meminfo.get("MemTotal") or 0)
    available_memory = int(meminfo.get("MemAvailable") or 0)
    total_swap = int(meminfo.get("SwapTotal") or 0)
    free_swap = int(meminfo.get("SwapFree") or 0)
    return {
        "mem": max(0, total_memory - available_memory),
        "maxmem": total_memory,
        "swap": max(0, total_swap - free_swap),
        "maxswap": total_swap,
        "pressurecpusome": _psi_avg10(proc_root / "pressure" / "cpu", "some"),
        "pressureiosome": _psi_avg10(proc_root / "pressure" / "io", "some"),
        "pressurememorysome": _psi_avg10(proc_root / "pressure" / "memory", "some"),
        "pressurememoryfull": _psi_avg10(proc_root / "pressure" / "memory", "full"),
        "pressureiofull": _psi_avg10(proc_root / "pressure" / "io", "full"),
    }


def _sample_value(
    current: dict[str, Any],
    local_current: dict[str, Any],
    key: str,
) -> tuple[Any, str]:
    value = current.get(key)
    if value is not None and str(value).strip() != "":
        return value, "pvesh"
    value = local_current.get(key)
    if value is not None and str(value).strip() != "":
        return value, "local"
    return None, "unavailable"


def _target_state(state: dict[str, Any], target_name: str) -> dict[str, Any]:
    targets = state.setdefault("targets", {})
    if not isinstance(targets, dict):
        state["targets"] = targets = {}
    item = targets.setdefault(target_name, {})
    if not isinstance(item, dict):
        targets[target_name] = item = {}
    return item


def pressure_sample(
    current: dict[str, Any],
    *,
    local_current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_current = local_current or {}
    values_and_sources = {
        key: _sample_value(current, local_current, key)
        for key in (
            "mem",
            "maxmem",
            "swap",
            "maxswap",
            "pressurecpusome",
            "pressureiosome",
            "pressurememorysome",
            "pressurememoryfull",
            "pressureiofull",
        )
    }
    values = {key: item[0] for key, item in values_and_sources.items()}
    return {
        "memory_used_ratio": _ratio(values["mem"], values["maxmem"]),
        "swap_used_ratio": _ratio(values["swap"], values["maxswap"]),
        "cpu_some": _coerce_float(values["pressurecpusome"]),
        "io_some": _coerce_float(values["pressureiosome"]),
        "memory_some": _coerce_float(values["pressurememorysome"]),
        "memory_full": _coerce_float(values["pressurememoryfull"]),
        "io_full": _coerce_float(values["pressureiofull"]),
        "raw": {
            **values,
        },
        "sources": {key: item[1] for key, item in values_and_sources.items()},
    }


def pressure_reasons(sample: dict[str, Any]) -> tuple[list[str], list[str]]:
    watch: list[str] = []
    critical: list[str] = []
    if sample["memory_used_ratio"] >= 0.97:
        critical.append("memory_used_ratio>=0.97")
    elif sample["memory_used_ratio"] >= 0.90:
        watch.append("memory_used_ratio>=0.90")
    if sample["swap_used_ratio"] >= 0.70:
        critical.append("swap_used_ratio>=0.70")
    elif sample["swap_used_ratio"] >= 0.25:
        watch.append("swap_used_ratio>=0.25")
    elif sample["swap_used_ratio"] > 0:
        watch.append("swap_used_ratio>0")
    if sample["memory_some"] >= 60.0:
        critical.append("memory_some>=60")
    elif sample["memory_some"] >= 20.0:
        watch.append("memory_some>=20")
    if sample["memory_full"] >= 20.0:
        critical.append("memory_full>=20")
    elif sample["memory_full"] >= 5.0:
        watch.append("memory_full>=5")
    if sample["io_some"] >= 80.0:
        critical.append("io_some>=80")
    elif sample["io_some"] >= 50.0:
        watch.append("io_some>=50")
    if sample["io_full"] >= 40.0:
        critical.append("io_full>=40")
    elif sample["io_full"] >= 10.0:
        watch.append("io_full>=10")
    return watch, critical


def evaluate(
    observation: dict[str, Any],
    state: dict[str, Any],
    *,
    target_name: str,
    critical_threshold: int,
    observed_at: int | None = None,
    local_current: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    observed_at = int(time.time()) if observed_at is None else int(observed_at)
    next_state = dict(state) if isinstance(state, dict) else {}
    target_state = _target_state(next_state, target_name)
    current = observation.get("pvesh_status_json")
    if not isinstance(current, dict):
        current = {}
    sample = pressure_sample(current, local_current=local_current)
    watch_reasons, critical_reasons = pressure_reasons(sample)
    critical_count = int(target_state.get("critical_count") or 0)
    if critical_reasons:
        critical_count += 1
    else:
        critical_count = 0
    target_state.update(
        {
            "critical_count": critical_count,
            "last_observed_at": observed_at,
            "last_watch_reasons": watch_reasons,
            "last_critical_reasons": critical_reasons,
        }
    )
    threshold = max(1, int(critical_threshold or 1))
    if critical_reasons and critical_count >= threshold:
        status = "critical"
        admission = {
            "action": "block_new_work",
            "reason": "; ".join(critical_reasons),
        }
    elif critical_reasons:
        status = "critical_watching"
        admission = {
            "action": "defer_heavy_work",
            "reason": "; ".join(critical_reasons),
        }
    elif watch_reasons:
        status = "watching"
        defer_heavy = any(reason != "swap_used_ratio>0" for reason in watch_reasons)
        admission = {
            "action": "defer_heavy_work" if defer_heavy else "accept_new_work",
            "reason": "; ".join(watch_reasons),
        }
    else:
        status = "healthy"
        admission = {"action": "accept_new_work", "reason": "host pressure normal"}
    decision = {
        "schema": "norman.tui.host-pressure-guard.v1",
        "target": target_name,
        "status": status,
        "checked_at_epoch": observed_at,
        "sample": sample,
        "watch_reasons": watch_reasons,
        "critical_reasons": critical_reasons,
        "critical_count": critical_count,
        "critical_threshold": threshold,
        "admission": admission,
    }
    return decision, next_state


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify TUI host memory/IO pressure before self-heal is needed."
    )
    parser.add_argument(
        "--target", choices=sorted(recovery.RECOVERY_TARGETS), required=True
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--threshold", type=int, default=DEFAULT_CRITICAL_THRESHOLD)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    observe_fn: ObserveFn = recovery.observe_target,
) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    target = recovery.RECOVERY_TARGETS[args.target]
    observation = observe_fn(target)
    state = _load_json(args.state, {})
    decision, next_state = evaluate(
        observation,
        state,
        target_name=args.target,
        critical_threshold=max(1, int(args.threshold or 1)),
        local_current=local_pressure_status(),
    )
    _write_json(args.state, next_state)
    _write_json(args.json_output, decision)
    if args.json:
        print(json.dumps(decision, indent=2, sort_keys=True))
    else:
        admission = decision.get("admission") or {}
        print(
            "{target}: status={status} admission={action} reason={reason}".format(
                target=args.target,
                status=decision.get("status"),
                action=admission.get("action"),
                reason=admission.get("reason"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
