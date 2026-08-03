#!/usr/bin/env python3
"""Bounded local-host resource guard for Codex-driven filesystem scans."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA = "norman.tui.local-host-pressure-guard.v1"
DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "NORMAN_TUI_LOCAL_HOST_PRESSURE_GUARD_STATE",
        "/home/kristopher/.local/state/norman/tui-local-host-pressure-guard-state.json",
    )
)
DEFAULT_OUTPUT_JSON = Path(
    os.environ.get(
        "NORMAN_TUI_LOCAL_HOST_PRESSURE_GUARD_JSON",
        "/home/kristopher/.local/state/norman/tui-local-host-pressure-guard.json",
    )
)
DEFAULT_IO_FULL_THRESHOLD = float(
    os.environ.get("NORMAN_TUI_LOCAL_HOST_IO_FULL_THRESHOLD", "10")
)
DEFAULT_SCAN_READ_BYTES_PER_SECOND = int(
    os.environ.get(
        "NORMAN_TUI_LOCAL_HOST_SCAN_READ_BYTES_PER_SECOND",
        str(100 * 1024 * 1024),
    )
)
DEFAULT_SUSTAINED_SAMPLES = int(
    os.environ.get("NORMAN_TUI_LOCAL_HOST_SUSTAINED_SAMPLES", "2")
)
DEFAULT_MIN_ROOT_FREE_BYTES = int(
    os.environ.get(
        "NORMAN_TUI_LOCAL_HOST_MIN_ROOT_FREE_BYTES",
        str(20 * 1024 * 1024 * 1024),
    )
)
DEFAULT_MIN_ROOT_FREE_RATIO = float(
    os.environ.get("NORMAN_TUI_LOCAL_HOST_MIN_ROOT_FREE_RATIO", "0.05")
)
DEFAULT_RECENT_ACTIONS = 20
BROAD_SCAN_EXECUTABLES = frozenset({"find", "rg"})
DEFAULT_BROAD_ROOTS = ("/", "/home", "/home/kristopher", "/tmp", "/var/tmp")
RG_LONG_OPTIONS_WITH_VALUE = frozenset(
    {
        "--after-context",
        "--before-context",
        "--context",
        "--dfa-size-limit",
        "--encoding",
        "--engine",
        "--file",
        "--glob",
        "--iglob",
        "--ignore-file",
        "--max-columns",
        "--max-columns-preview",
        "--max-count",
        "--max-depth",
        "--max-filesize",
        "--path-separator",
        "--pre",
        "--pre-glob",
        "--regex-size-limit",
        "--replace",
        "--regexp",
        "--sort",
        "--sortr",
        "--threads",
        "--type",
        "--type-add",
        "--type-clear",
        "--type-not",
    }
)
RG_SHORT_OPTIONS_WITH_VALUE = frozenset(
    {"A", "B", "C", "E", "e", "f", "g", "j", "m", "r", "t", "T"}
)
RG_EXPLICIT_PATTERN_OPTIONS = frozenset({"--file", "--regexp", "-e", "-f"})

SignalFn = Callable[[int, signal.Signals], None]
IdentityFn = Callable[[int], tuple[int, str] | None]


def _utc_now(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_stat(pid: int, *, proc_root: Path) -> tuple[int, int, str] | None:
    raw = _read_text(proc_root / str(pid) / "stat").strip()
    if ")" not in raw:
        return None
    _before, _separator, after = raw.rpartition(")")
    fields = after.split()
    if len(fields) <= 19:
        return None
    try:
        return int(fields[1]), int(fields[19]), fields[0]
    except ValueError:
        return None


def _read_io(pid: int, *, proc_root: Path) -> dict[str, int]:
    values = {"read_bytes": 0, "write_bytes": 0}
    for raw in _read_text(proc_root / str(pid) / "io").splitlines():
        key, separator, value = raw.partition(":")
        if separator and key in values:
            try:
                values[key] = max(0, int(value.strip()))
            except ValueError:
                continue
    return values


def _read_cmdline(pid: int, *, proc_root: Path) -> list[str]:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [
        value.decode("utf-8", errors="replace") for value in raw.split(b"\0") if value
    ]


def _process_snapshot(pid: int, *, proc_root: Path) -> dict[str, Any] | None:
    stat = _read_stat(pid, proc_root=proc_root)
    if not stat:
        return None
    ppid, start_time_ticks, process_state = stat
    process_dir = proc_root / str(pid)
    try:
        cwd = os.readlink(process_dir / "cwd")
    except OSError:
        cwd = ""
    try:
        uid = process_dir.stat().st_uid
    except OSError:
        uid = None
    command = _read_cmdline(pid, proc_root=proc_root)
    comm = _read_text(process_dir / "comm").strip()
    executable = Path(command[0]).name if command else comm
    io = _read_io(pid, proc_root=proc_root)
    return {
        "pid": pid,
        "ppid": ppid,
        "start_time_ticks": start_time_ticks,
        "state": process_state,
        "uid": uid,
        "cwd": cwd,
        "comm": comm,
        "executable": executable,
        "argv": command,
        "command": " ".join(command),
        **io,
    }


def _read_psi(path: Path) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for raw in _read_text(path).splitlines():
        fields = raw.split()
        if not fields:
            continue
        category = fields[0]
        values: dict[str, float] = {}
        for field in fields[1:]:
            key, separator, value = field.partition("=")
            if not separator:
                continue
            try:
                values[key] = float(value)
            except ValueError:
                continue
        result[category] = values
    return result


def _read_meminfo(proc_root: Path) -> dict[str, int]:
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


def _disk_snapshot(path: Path) -> dict[str, Any]:
    try:
        stat = os.statvfs(path)
    except OSError as exc:
        return {"path": str(path), "error": str(exc)}
    block_size = int(stat.f_frsize or stat.f_bsize or 1)
    total = int(stat.f_blocks) * block_size
    free = int(stat.f_bavail) * block_size
    used = max(0, total - free)
    return {
        "path": str(path),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "free_ratio": round(free / max(1, total), 4),
    }


def collect_observation(
    *,
    proc_root: Path = Path("/proc"),
    root_path: Path = Path("/"),
    now: float | None = None,
) -> dict[str, Any]:
    observed_at = time.time() if now is None else float(now)
    processes: list[dict[str, Any]] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            pid = int(entry.name)
        except ValueError:
            continue
        snapshot = _process_snapshot(pid, proc_root=proc_root)
        if snapshot:
            processes.append(snapshot)
    meminfo = _read_meminfo(proc_root)
    swap_total = int(meminfo.get("SwapTotal") or 0)
    swap_free = int(meminfo.get("SwapFree") or 0)
    return {
        "checked_at_epoch": int(observed_at),
        "checked_at": _utc_now(observed_at),
        "pressure": {
            "io": _read_psi(proc_root / "pressure" / "io"),
            "memory": _read_psi(proc_root / "pressure" / "memory"),
            "cpu": _read_psi(proc_root / "pressure" / "cpu"),
        },
        "memory": {
            "total_bytes": int(meminfo.get("MemTotal") or 0),
            "available_bytes": int(meminfo.get("MemAvailable") or 0),
            "swap_total_bytes": swap_total,
            "swap_free_bytes": swap_free,
            "swap_used_bytes": max(0, swap_total - swap_free),
            "swap_used_ratio": round(
                max(0, swap_total - swap_free) / max(1, swap_total), 4
            )
            if swap_total
            else 0.0,
        },
        "root_filesystem": _disk_snapshot(root_path),
        "processes": processes,
    }


def _coerce_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _io_full_avg10(observation: dict[str, Any]) -> float:
    pressure = observation.get("pressure")
    if not isinstance(pressure, dict):
        return 0.0
    io = pressure.get("io")
    if not isinstance(io, dict):
        return 0.0
    full = io.get("full")
    if not isinstance(full, dict):
        return 0.0
    return _coerce_float(full.get("avg10"))


def _process_key(process: dict[str, Any]) -> str:
    return "{pid}:{start}".format(
        pid=_coerce_int(process.get("pid")),
        start=_coerce_int(process.get("start_time_ticks")),
    )


def _is_codex(process: dict[str, Any]) -> bool:
    return str(process.get("comm") or "") == "codex" or (
        str(process.get("executable") or "") == "codex"
    )


def _nearest_codex_ancestor(
    process: dict[str, Any], process_by_pid: dict[int, dict[str, Any]]
) -> dict[str, Any] | None:
    pid = _coerce_int(process.get("ppid"))
    seen: set[int] = set()
    while pid > 1 and pid not in seen and len(seen) < 64:
        seen.add(pid)
        parent = process_by_pid.get(pid)
        if not parent:
            return None
        if _is_codex(parent):
            return parent
        pid = _coerce_int(parent.get("ppid"))
    return None


def _absolute_target(value: str, *, cwd: str) -> str:
    if value == ".":
        return os.path.normpath(cwd or ".")
    if value == "..":
        return os.path.normpath(os.path.join(cwd or ".", value))
    if os.path.isabs(value):
        return os.path.normpath(value)
    return ""


def _matching_broad_roots(
    values: list[str], *, cwd: str, broad_roots: tuple[str, ...]
) -> list[str]:
    targets: list[str] = []
    for value in values:
        target = _absolute_target(value, cwd=cwd)
        if target and target in broad_roots and target not in targets:
            targets.append(target)
    return targets


def _find_path_args(argv: list[str]) -> list[str]:
    """Return only find starting points, never expression operands."""

    paths: list[str] = []
    index = 1
    while index < len(argv):
        value = argv[index]
        if value in {"-H", "-L", "-P"}:
            index += 1
            continue
        if value in {"-D", "-O"}:
            index += 2
            continue
        if value.startswith("-D") or value.startswith("-O"):
            index += 1
            continue
        if value.startswith("-") or value in {"!", "(", ")"}:
            break
        paths.append(value)
        index += 1
    return paths


def _rg_path_args(argv: list[str]) -> list[str]:
    """Conservatively separate ripgrep patterns, option values, and paths."""

    positionals: list[str] = []
    files_mode = False
    explicit_pattern = False
    options_ended = False
    skip_next = False

    for value in argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if not options_ended and value == "--":
            options_ended = True
            continue
        if not options_ended and value == "--files":
            files_mode = True
            continue
        if not options_ended and value.startswith("--"):
            option = value.partition("=")[0]
            if option in RG_EXPLICIT_PATTERN_OPTIONS:
                explicit_pattern = True
            if "=" not in value and option in RG_LONG_OPTIONS_WITH_VALUE:
                skip_next = True
            continue
        if not options_ended and value.startswith("-") and value != "-":
            short_option = value[:2]
            if short_option in RG_EXPLICIT_PATTERN_OPTIONS:
                explicit_pattern = True
            if (
                len(value) == 2
                and len(short_option) == 2
                and short_option[1] in RG_SHORT_OPTIONS_WITH_VALUE
            ):
                skip_next = True
            continue
        positionals.append(value)

    if files_mode or explicit_pattern:
        return positionals
    return positionals[1:]


def _broad_targets(
    process: dict[str, Any], *, broad_roots: tuple[str, ...]
) -> list[str]:
    executable = str(process.get("executable") or "")
    argv = [value for value in process.get("argv") or [] if isinstance(value, str)]
    if not argv:
        return []
    cwd = str(process.get("cwd") or "")
    if executable == "find":
        return _matching_broad_roots(
            _find_path_args(argv), cwd=cwd, broad_roots=broad_roots
        )
    if executable == "rg":
        return _matching_broad_roots(
            _rg_path_args(argv), cwd=cwd, broad_roots=broad_roots
        )
    return []


def _rate(
    process: dict[str, Any],
    previous: dict[str, Any],
    *,
    observed_at: int,
) -> tuple[float, float]:
    if _coerce_int(previous.get("start_time_ticks")) != _coerce_int(
        process.get("start_time_ticks")
    ):
        return 0.0, 0.0
    elapsed = observed_at - _coerce_int(previous.get("observed_at_epoch"))
    if elapsed <= 0:
        return 0.0, 0.0
    read_rate = (
        max(
            0,
            _coerce_int(process.get("read_bytes"))
            - _coerce_int(previous.get("read_bytes")),
        )
        / elapsed
    )
    write_rate = (
        max(
            0,
            _coerce_int(process.get("write_bytes"))
            - _coerce_int(previous.get("write_bytes")),
        )
        / elapsed
    )
    return read_rate, write_rate


def _process_sample(
    process: dict[str, Any], *, observed_at: int, breach_count: int
) -> dict[str, Any]:
    return {
        "pid": _coerce_int(process.get("pid")),
        "start_time_ticks": _coerce_int(process.get("start_time_ticks")),
        "read_bytes": _coerce_int(process.get("read_bytes")),
        "write_bytes": _coerce_int(process.get("write_bytes")),
        "observed_at_epoch": observed_at,
        "breach_count": breach_count,
    }


def _public_process(
    process: dict[str, Any],
    *,
    read_rate: float,
    write_rate: float,
    codex: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "pid": _coerce_int(process.get("pid")),
        "start_time_ticks": _coerce_int(process.get("start_time_ticks")),
        "state": str(process.get("state") or ""),
        "executable": str(process.get("executable") or ""),
        "cwd": str(process.get("cwd") or ""),
        "command": str(process.get("command") or ""),
        "read_bytes_per_second": round(read_rate, 1),
        "write_bytes_per_second": round(write_rate, 1),
        "codex_ancestor_pid": _coerce_int(codex.get("pid")) if codex else None,
        "codex_ancestor_start_time_ticks": (
            _coerce_int(codex.get("start_time_ticks")) if codex else None
        ),
    }


def _root_disk_low(
    root_filesystem: dict[str, Any],
    *,
    min_free_bytes: int,
    min_free_ratio: float,
) -> bool:
    if root_filesystem.get("error"):
        return False
    return _coerce_int(root_filesystem.get("free_bytes")) < max(0, min_free_bytes) or (
        _coerce_float(root_filesystem.get("free_ratio")) < max(0.0, min_free_ratio)
    )


def _make_issue(
    *,
    severity: str,
    check: str,
    detail: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "host": "local-host",
        "instance": "<host>",
        "check": check,
        "detail": detail,
    }


def evaluate(
    observation: dict[str, Any],
    state: dict[str, Any],
    *,
    io_full_threshold: float = DEFAULT_IO_FULL_THRESHOLD,
    min_read_bytes_per_second: int = DEFAULT_SCAN_READ_BYTES_PER_SECOND,
    sustained_samples: int = DEFAULT_SUSTAINED_SAMPLES,
    broad_roots: tuple[str, ...] = DEFAULT_BROAD_ROOTS,
    min_root_free_bytes: int = DEFAULT_MIN_ROOT_FREE_BYTES,
    min_root_free_ratio: float = DEFAULT_MIN_ROOT_FREE_RATIO,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Classify a bounded observation and return report, next state, and actions."""

    if observation.get("checked_at_epoch") is None:
        observed_at = int(time.time())
    else:
        observed_at = _coerce_int(observation.get("checked_at_epoch"))
    next_state = dict(state) if isinstance(state, dict) else {}
    previous_samples = next_state.get("process_samples")
    if not isinstance(previous_samples, dict):
        previous_samples = {}

    processes = [
        process
        for process in observation.get("processes") or []
        if isinstance(process, dict) and _coerce_int(process.get("pid")) > 0
    ]
    process_by_pid = {_coerce_int(process["pid"]): process for process in processes}
    io_full = _io_full_avg10(observation)
    io_pressure = io_full >= max(0.0, io_full_threshold)
    pressure_count = _coerce_int(next_state.get("io_pressure_count"))
    pressure_count = pressure_count + 1 if io_pressure else 0

    scan_candidates: list[dict[str, Any]] = []
    unconfirmed_high_io: list[dict[str, Any]] = []
    top_agent_io: list[dict[str, Any]] = []
    top_process_io: list[dict[str, Any]] = []
    process_samples: dict[str, dict[str, Any]] = {}
    for process in processes:
        key = _process_key(process)
        previous = previous_samples.get(key)
        if not isinstance(previous, dict):
            previous = {}
        read_rate, write_rate = _rate(process, previous, observed_at=observed_at)
        codex = _nearest_codex_ancestor(process, process_by_pid)
        public_process = _public_process(
            process,
            read_rate=read_rate,
            write_rate=write_rate,
            codex=codex,
        )
        top_process_io.append(public_process)
        if codex or _is_codex(process):
            top_agent_io.append(public_process)

        broad_targets = _broad_targets(process, broad_roots=broad_roots)
        prior_breach_count = _coerce_int(previous.get("breach_count"))
        is_confirmed_candidate = bool(codex and broad_targets)
        is_high_read = io_pressure and read_rate >= max(0, min_read_bytes_per_second)
        if is_high_read and not (
            is_confirmed_candidate and str(codex.get("state") or "") != "T"
        ):
            if not codex:
                reason = "no Codex ancestor; automatic pause is forbidden"
            elif not broad_targets:
                reason = (
                    "not a permitted broad find or rg scan; automatic pause is "
                    "forbidden"
                )
            else:
                reason = "Codex ancestor is already paused; automatic pause is skipped"
            unconfirmed_high_io.append(
                {
                    **public_process,
                    "broad_targets": broad_targets,
                    "reason": reason,
                }
            )
        breach = (
            is_confirmed_candidate
            and io_pressure
            and read_rate >= max(0, min_read_bytes_per_second)
            and str(codex.get("state") or "") != "T"
        )
        breach_count = prior_breach_count + 1 if breach else 0
        process_samples[key] = _process_sample(
            process, observed_at=observed_at, breach_count=breach_count
        )
        if not is_confirmed_candidate:
            continue
        scan_candidates.append(
            {
                **_public_process(
                    process,
                    read_rate=read_rate,
                    write_rate=write_rate,
                    codex=codex,
                ),
                "command": str(process.get("command") or ""),
                "broad_targets": broad_targets,
                "breach_count": breach_count,
                "required_sustained_samples": max(1, sustained_samples),
                "eligible_to_pause": breach_count >= max(1, sustained_samples),
            }
        )

    actions_by_codex: dict[str, dict[str, Any]] = {}
    threshold = max(1, sustained_samples)
    for candidate in scan_candidates:
        if not candidate["eligible_to_pause"]:
            continue
        codex_pid = _coerce_int(candidate.get("codex_ancestor_pid"))
        codex_start = _coerce_int(candidate.get("codex_ancestor_start_time_ticks"))
        codex_key = f"{codex_pid}:{codex_start}"
        action = actions_by_codex.setdefault(
            codex_key,
            {
                "action": "interrupt_scan_and_pause_codex",
                "codex_pid": codex_pid,
                "codex_start_time_ticks": codex_start,
                "scan_processes": [],
                "reason": (
                    "sustained broad filesystem scan exceeded the read-rate and "
                    "host I/O pressure thresholds"
                ),
                "resume_command": f"kill -CONT -- {codex_pid}",
                "cancel_command": f"kill -TERM -- {codex_pid}",
            },
        )
        action["scan_processes"].append(
            {
                "pid": _coerce_int(candidate["pid"]),
                "start_time_ticks": _coerce_int(candidate["start_time_ticks"]),
                "command": str(candidate["command"]),
                "broad_targets": candidate["broad_targets"],
                "read_bytes_per_second": candidate["read_bytes_per_second"],
            }
        )
    action_plans = list(actions_by_codex.values())

    root_filesystem = observation.get("root_filesystem")
    if not isinstance(root_filesystem, dict):
        root_filesystem = {}
    disk_low = _root_disk_low(
        root_filesystem,
        min_free_bytes=min_root_free_bytes,
        min_free_ratio=min_root_free_ratio,
    )
    disk_count = _coerce_int(next_state.get("root_disk_low_count"))
    disk_count = disk_count + 1 if disk_low else 0

    issues: list[dict[str, str]] = []
    if pressure_count >= threshold and not action_plans:
        issues.append(
            _make_issue(
                severity="warn",
                check="io_full_pressure",
                detail="sustained local I/O full pressure; inspect the guard report",
            )
        )
    if pressure_count >= threshold and unconfirmed_high_io:
        broad_unconfirmed = [
            item
            for item in unconfirmed_high_io
            if item.get("broad_targets") and not item.get("codex_ancestor_pid")
        ]
        other_unconfirmed = [
            item for item in unconfirmed_high_io if item not in broad_unconfirmed
        ]
        if broad_unconfirmed:
            issues.append(
                _make_issue(
                    severity="warn",
                    check="unconfirmed_high_io_scan",
                    detail=(
                        "sustained broad scan has no Codex ancestor and was not "
                        "paused; inspect the guard report"
                    ),
                )
            )
        if other_unconfirmed:
            issues.append(
                _make_issue(
                    severity="warn",
                    check="unconfirmed_high_io_process",
                    detail=(
                        "sustained high-I/O process is outside the automatic-pause "
                        "policy; inspect the guard report"
                    ),
                )
            )
    if disk_count >= threshold:
        issues.append(
            _make_issue(
                severity="warn",
                check="root_disk_headroom",
                detail=(
                    "root filesystem free space is below the local guard threshold; "
                    "inspect cleanup state and the guard report"
                ),
            )
        )

    top_agent_io.sort(
        key=lambda item: (
            _coerce_float(item.get("read_bytes_per_second"))
            + _coerce_float(item.get("write_bytes_per_second"))
        ),
        reverse=True,
    )
    top_process_io.sort(
        key=lambda item: (
            _coerce_float(item.get("read_bytes_per_second"))
            + _coerce_float(item.get("write_bytes_per_second"))
        ),
        reverse=True,
    )
    unconfirmed_high_io.sort(
        key=lambda item: (
            _coerce_float(item.get("read_bytes_per_second"))
            + _coerce_float(item.get("write_bytes_per_second"))
        ),
        reverse=True,
    )
    if action_plans:
        status = "offender_ready_to_pause"
        admission = {
            "action": "pause_confirmed_offender",
            "reason": "confirmed broad Codex filesystem scan under sustained I/O pressure",
        }
    elif pressure_count >= threshold:
        status = "degraded"
        admission = {
            "action": "defer_background_work",
            "reason": "sustained local I/O pressure",
        }
    elif io_pressure or disk_low:
        status = "watching"
        admission = {
            "action": "defer_background_work" if io_pressure else "accept_new_work",
            "reason": (
                "local I/O pressure is being sampled"
                if io_pressure
                else "root filesystem headroom is low"
            ),
        }
    else:
        status = "healthy"
        admission = {"action": "accept_new_work", "reason": "host pressure normal"}

    report = {
        "schema": SCHEMA,
        "checked_at": str(observation.get("checked_at") or _utc_now(observed_at)),
        "checked_at_epoch": observed_at,
        "status": status,
        "summary": {
            "active": len(processes),
            "expected": len(processes),
            "fail": 0,
            "warn": len(issues),
            "scan_candidates": len(scan_candidates),
            "unconfirmed_high_io": len(unconfirmed_high_io),
            "actions_ready": len(action_plans),
        },
        "admission": admission,
        "kpis": {
            "io_full_avg10": round(io_full, 2),
            "io_pressure_samples": pressure_count,
            "memory_available_bytes": _coerce_int(
                (observation.get("memory") or {}).get("available_bytes")
                if isinstance(observation.get("memory"), dict)
                else 0
            ),
            "swap_used_ratio": _coerce_float(
                (observation.get("memory") or {}).get("swap_used_ratio")
                if isinstance(observation.get("memory"), dict)
                else 0
            ),
            "root_free_bytes": _coerce_int(root_filesystem.get("free_bytes")),
            "root_free_ratio": _coerce_float(root_filesystem.get("free_ratio")),
        },
        "pressure": observation.get("pressure")
        if isinstance(observation.get("pressure"), dict)
        else {},
        "memory": observation.get("memory")
        if isinstance(observation.get("memory"), dict)
        else {},
        "root_filesystem": root_filesystem,
        "top_agent_io": top_agent_io[:10],
        "top_process_io": top_process_io[:10],
        "scan_candidates": scan_candidates,
        "unconfirmed_high_io": unconfirmed_high_io[:10],
        "actions": [
            {**action, "applied": False, "result": "observe_only"}
            for action in action_plans
        ],
        "issues": issues,
    }
    next_state.update(
        {
            "schema": SCHEMA,
            "last_observed_at_epoch": observed_at,
            "io_pressure_count": pressure_count,
            "root_disk_low_count": disk_count,
            "process_samples": process_samples,
        }
    )
    return report, next_state, action_plans


def _current_identity(
    pid: int, *, proc_root: Path = Path("/proc")
) -> tuple[int, str] | None:
    stat = _read_stat(pid, proc_root=proc_root)
    if not stat:
        return None
    _ppid, start_time_ticks, process_state = stat
    return start_time_ticks, process_state


def apply_action_plan(
    action: dict[str, Any],
    *,
    identity_fn: IdentityFn,
    signal_fn: SignalFn = os.kill,
) -> dict[str, Any]:
    """Interrupt each confirmed scan, then pause its still-identical Codex parent."""

    codex_pid = _coerce_int(action.get("codex_pid"))
    codex_start = _coerce_int(action.get("codex_start_time_ticks"))
    identity = identity_fn(codex_pid)
    if not identity or identity[0] != codex_start:
        return {**action, "applied": False, "result": "codex_identity_changed"}
    if identity[1] == "T":
        return {**action, "applied": False, "result": "codex_already_paused"}

    interrupted: list[int] = []
    for scan in action.get("scan_processes") or []:
        if not isinstance(scan, dict):
            continue
        scan_pid = _coerce_int(scan.get("pid"))
        scan_start = _coerce_int(scan.get("start_time_ticks"))
        scan_identity = identity_fn(scan_pid)
        if not scan_identity or scan_identity[0] != scan_start:
            continue
        try:
            signal_fn(scan_pid, signal.SIGINT)
        except OSError as exc:
            return {
                **action,
                "applied": False,
                "result": f"scan_interrupt_failed: {type(exc).__name__}: {exc}",
                "interrupted_scan_pids": interrupted,
            }
        interrupted.append(scan_pid)

    if not interrupted:
        return {**action, "applied": False, "result": "scan_identity_changed"}
    identity = identity_fn(codex_pid)
    if not identity or identity[0] != codex_start:
        return {
            **action,
            "applied": False,
            "result": "codex_identity_changed_after_interrupt",
            "interrupted_scan_pids": interrupted,
        }
    try:
        signal_fn(codex_pid, signal.SIGSTOP)
    except OSError as exc:
        return {
            **action,
            "applied": False,
            "result": f"codex_pause_failed: {type(exc).__name__}: {exc}",
            "interrupted_scan_pids": interrupted,
        }
    return {
        **action,
        "applied": True,
        "result": "scan_interrupted_codex_paused",
        "interrupted_scan_pids": interrupted,
    }


def _add_applied_action_issues(
    report: dict[str, Any], actions: list[dict[str, Any]]
) -> None:
    successful = [action for action in actions if action.get("applied")]
    report["actions"] = actions
    if not successful:
        if actions:
            report["issues"].append(
                _make_issue(
                    severity="warn",
                    check="automatic_pause_not_applied",
                    detail=(
                        "a confirmed broad scan could not be paused safely; "
                        "inspect the guard report"
                    ),
                )
            )
            report["summary"]["warn"] = len(report["issues"])
        return
    for action in successful:
        report["issues"].append(
            _make_issue(
                severity="fail",
                check="automatic_codex_pause",
                detail=(
                    "paused a confirmed broad filesystem scan; "
                    f"resume with {action['resume_command']} or cancel with "
                    f"{action['cancel_command']}; inspect the guard report"
                ),
            )
        )
    report["summary"]["fail"] = len(successful)
    report["summary"]["warn"] = len(report["issues"]) - len(successful)
    report["status"] = "offender_paused"
    report["admission"] = {
        "action": "paused_offending_agent",
        "reason": "a confirmed broad Codex filesystem scan was interrupted and paused",
    }


def run_guard(
    *,
    state_path: Path,
    output_path: Path,
    apply: bool,
    proc_root: Path = Path("/proc"),
    root_path: Path = Path("/"),
    now: float | None = None,
    io_full_threshold: float = DEFAULT_IO_FULL_THRESHOLD,
    min_read_bytes_per_second: int = DEFAULT_SCAN_READ_BYTES_PER_SECOND,
    sustained_samples: int = DEFAULT_SUSTAINED_SAMPLES,
    min_root_free_bytes: int = DEFAULT_MIN_ROOT_FREE_BYTES,
    min_root_free_ratio: float = DEFAULT_MIN_ROOT_FREE_RATIO,
    signal_fn: SignalFn = os.kill,
) -> dict[str, Any]:
    observation = collect_observation(proc_root=proc_root, root_path=root_path, now=now)
    state = _load_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    report, next_state, action_plans = evaluate(
        observation,
        state,
        io_full_threshold=io_full_threshold,
        min_read_bytes_per_second=min_read_bytes_per_second,
        sustained_samples=sustained_samples,
        min_root_free_bytes=min_root_free_bytes,
        min_root_free_ratio=min_root_free_ratio,
    )
    if apply:
        actions = [
            apply_action_plan(
                action,
                identity_fn=lambda pid: _current_identity(pid, proc_root=proc_root),
                signal_fn=signal_fn,
            )
            for action in action_plans
        ]
        _add_applied_action_issues(report, actions)
        history = next_state.get("recent_actions")
        if not isinstance(history, list):
            history = []
        history.extend(
            {
                "checked_at": report["checked_at"],
                "codex_pid": action["codex_pid"],
                "result": action["result"],
                "resume_command": action["resume_command"],
                "cancel_command": action["cancel_command"],
            }
            for action in actions
            if action.get("applied")
        )
        next_state["recent_actions"] = history[-DEFAULT_RECENT_ACTIONS:]
    else:
        report["actions"] = [
            {**action, "applied": False, "result": "observe_only"}
            for action in action_plans
        ]
    report["recent_actions"] = next_state.get("recent_actions") or []
    _write_json(state_path, next_state)
    _write_json(output_path, report)
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Observe local host pressure and pause only confirmed Codex broad "
            "filesystem scans."
        )
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--io-full-threshold", type=float, default=DEFAULT_IO_FULL_THRESHOLD
    )
    parser.add_argument(
        "--scan-read-bytes-per-second",
        type=int,
        default=DEFAULT_SCAN_READ_BYTES_PER_SECOND,
    )
    parser.add_argument(
        "--sustained-samples", type=int, default=DEFAULT_SUSTAINED_SAMPLES
    )
    parser.add_argument(
        "--min-root-free-bytes", type=int, default=DEFAULT_MIN_ROOT_FREE_BYTES
    )
    parser.add_argument(
        "--min-root-free-ratio", type=float, default=DEFAULT_MIN_ROOT_FREE_RATIO
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    report = run_guard(
        state_path=args.state,
        output_path=args.json_output,
        apply=args.apply,
        io_full_threshold=max(0.0, args.io_full_threshold),
        min_read_bytes_per_second=max(0, args.scan_read_bytes_per_second),
        sustained_samples=max(1, args.sustained_samples),
        min_root_free_bytes=max(0, args.min_root_free_bytes),
        min_root_free_ratio=max(0.0, args.min_root_free_ratio),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        admission = report.get("admission") or {}
        print(
            "local host guard: status={status} admission={action} "
            "candidates={candidates} actions={actions}".format(
                status=report.get("status"),
                action=admission.get("action"),
                candidates=report.get("summary", {}).get("scan_candidates", 0),
                actions=len(report.get("actions") or []),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
