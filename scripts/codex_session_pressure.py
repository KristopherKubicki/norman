#!/usr/bin/env python3
"""Report oversized active Codex sessions without changing their process state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "norman.codex.session-pressure.v1"
MIB = 1024 * 1024
GIB = 1024 * MIB
DEFAULT_OUTPUT_JSON = Path(
    os.environ.get(
        "NORMAN_CODEX_SESSION_PRESSURE_JSON",
        str(Path.home() / ".local/state/norman/codex-session-pressure.json"),
    )
)
DEFAULT_SESSION_SIZE_LIMIT_MIB = float(
    os.environ.get("NORMAN_CODEX_SESSION_SIZE_LIMIT_MIB", "512")
)
DEFAULT_PROCESS_PSS_LIMIT_MIB = float(
    os.environ.get("NORMAN_CODEX_PROCESS_PSS_LIMIT_MIB", "2048")
)
DEFAULT_SESSION_AGE_HOURS = float(
    os.environ.get("NORMAN_CODEX_SESSION_AGE_HOURS", "48")
)
DEFAULT_SESSION_TAIL_BYTES = int(
    os.environ.get("NORMAN_CODEX_SESSION_TAIL_BYTES", str(4 * MIB))
)
DEFAULT_SESSION_TAIL_EVENTS = int(
    os.environ.get("NORMAN_CODEX_SESSION_TAIL_EVENTS", "400")
)
DEFAULT_RECENT_SESSIONS_PER_HOME = int(
    os.environ.get("NORMAN_CODEX_RECENT_SESSIONS_PER_HOME", "4")
)
DEFAULT_COMPACTION_STOP_COUNT = int(
    os.environ.get("NORMAN_CODEX_COMPACTION_STOP_COUNT", "3")
)
DEFAULT_REPEATED_TOOL_STOP_COUNT = int(
    os.environ.get("NORMAN_CODEX_REPEATED_TOOL_STOP_COUNT", "3")
)
DEFAULT_TOOL_DENSITY_WARN_COUNT = int(
    os.environ.get("NORMAN_CODEX_TOOL_DENSITY_WARN_COUNT", "80")
)
PASSIVE_REPEAT_TOOL_NAMES = frozenset({"get_goal", "write_stdin"})
SESSION_ID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def _utc_timestamp(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def _default_codex_homes() -> list[Path]:
    configured = os.environ.get("CODEX_HOME", "").strip()
    homes = [Path(configured).expanduser()] if configured else []
    homes.extend([Path.home() / ".codex", Path.home() / ".codex-work"])
    return list(dict.fromkeys(path.resolve() for path in homes))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_cmdline(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    return [
        value.decode("utf-8", errors="replace") for value in raw.split(b"\0") if value
    ]


def _is_codex_process(process_dir: Path) -> bool:
    command = _read_cmdline(process_dir / "cmdline")
    executable = Path(command[0]).name if command else ""
    comm = _read_text(process_dir / "comm").strip()
    return executable == "codex" or comm == "codex"


def _read_smaps_rollup(process_dir: Path) -> dict[str, int]:
    values = {"pss_bytes": 0, "swap_pss_bytes": 0}
    for raw in _read_text(process_dir / "smaps_rollup").splitlines():
        key, separator, value = raw.partition(":")
        if not separator:
            continue
        fields = value.split()
        if not fields:
            continue
        try:
            bytes_value = max(0, int(fields[0])) * 1024
        except ValueError:
            continue
        if key == "Pss":
            values["pss_bytes"] = bytes_value
        elif key == "SwapPss":
            values["swap_pss_bytes"] = bytes_value
    return values


def _session_id(path: Path) -> str:
    match = SESSION_ID_RE.search(path.stem)
    return match.group(1).lower() if match else path.stem


def _session_started_epoch(path: Path, sessions_root: Path) -> float | None:
    try:
        relative = path.relative_to(sessions_root)
        year, month, day = (int(value) for value in relative.parts[:3])
        return datetime(year, month, day, tzinfo=timezone.utc).timestamp()
    except (IndexError, TypeError, ValueError):
        return None


def _session_record(path: Path, *, home: Path, now: float) -> dict[str, Any]:
    sessions_root = home / "sessions"
    started_epoch = _session_started_epoch(path, sessions_root)
    try:
        stat = path.stat()
        size_bytes = int(stat.st_size)
        modified_epoch = float(stat.st_mtime)
    except OSError:
        size_bytes = 0
        modified_epoch = 0.0
    if started_epoch is None:
        started_epoch = modified_epoch or None
    return {
        "session_id": _session_id(path),
        "path": str(path),
        "codex_home": str(home),
        "size_bytes": size_bytes,
        "size_mib": round(size_bytes / MIB, 1),
        "modified_at": _utc_timestamp(modified_epoch) if modified_epoch else None,
        "started_at": _utc_timestamp(started_epoch) if started_epoch else None,
        "age_seconds": max(0, int(now - started_epoch)) if started_epoch else None,
        "active_pids": [],
        "run_health": {
            "state": "not_scanned",
            "signals": [],
            "metrics": {},
        },
    }


def _read_jsonl_tail(
    path: Path, *, max_bytes: int, max_events: int
) -> list[dict[str, Any]]:
    if max_bytes <= 0 or max_events <= 0:
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            offset = max(0, size - max_bytes)
            handle.seek(offset)
            raw = handle.read(max_bytes)
    except OSError:
        return []
    if offset:
        separator = raw.find(b"\n")
        raw = raw[separator + 1 :] if separator >= 0 else b""
    events: deque[dict[str, Any]] = deque(maxlen=max_events)
    for line in raw.splitlines():
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return list(events)


def _normalized_tool_input(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return " ".join(value.split())
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def _tail_run_health(
    path: Path,
    *,
    max_bytes: int,
    max_events: int,
    compaction_stop_count: int,
    repeated_tool_stop_count: int,
    tool_density_warn_count: int,
) -> dict[str, Any]:
    events = _read_jsonl_tail(path, max_bytes=max_bytes, max_events=max_events)
    compacted_events = 0
    context_compacted_events = 0
    tool_signatures: list[tuple[str, str]] = []
    last_turn_tokens = 0
    cumulative_tokens = 0

    for event in events:
        event_type = str(event.get("type") or "").strip().lower()
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        payload_type = str(payload.get("type") or "").strip().lower()
        if event_type == "compacted":
            compacted_events += 1
        elif payload_type == "context_compacted":
            context_compacted_events += 1
        if payload_type in {"function_call", "custom_tool_call"}:
            name = str(payload.get("name") or "").strip()
            arguments = payload.get("arguments", payload.get("input"))
            fingerprint = hashlib.sha256(
                f"{name}\0{_normalized_tool_input(arguments)}".encode("utf-8")
            ).hexdigest()
            tool_signatures.append((name, fingerprint))
        if payload_type == "token_count":
            info = payload.get("info")
            info = info if isinstance(info, dict) else {}
            last = info.get("last_token_usage")
            total = info.get("total_token_usage")
            last = last if isinstance(last, dict) else {}
            total = total if isinstance(total, dict) else {}
            last_turn_tokens = max(last_turn_tokens, int(last.get("total_tokens") or 0))
            cumulative_tokens = max(
                cumulative_tokens, int(total.get("total_tokens") or 0)
            )

    compactions = compacted_events or context_compacted_events
    maximum_tool_repeat = 0
    current_tool_repeat = 0
    previous_tool_signature = ""
    active_tool_signatures = [
        signature
        for name, signature in tool_signatures
        if name not in PASSIVE_REPEAT_TOOL_NAMES
    ]
    for signature in active_tool_signatures:
        if signature == previous_tool_signature:
            current_tool_repeat += 1
        else:
            previous_tool_signature = signature
            current_tool_repeat = 1
        maximum_tool_repeat = max(maximum_tool_repeat, current_tool_repeat)
    signals: list[dict[str, Any]] = []

    def add(code: str, severity: str, observed: int, threshold: int) -> None:
        signals.append(
            {
                "code": code,
                "severity": severity,
                "observed": observed,
                "threshold": threshold,
            }
        )

    if compactions >= compaction_stop_count:
        add(
            "compaction_loop",
            "stop",
            compactions,
            compaction_stop_count,
        )
    if maximum_tool_repeat >= repeated_tool_stop_count:
        add(
            "repeated_tool_call_loop",
            "stop",
            maximum_tool_repeat,
            repeated_tool_stop_count,
        )
    if len(tool_signatures) >= tool_density_warn_count:
        add(
            "tool_call_density",
            "warn",
            len(tool_signatures),
            tool_density_warn_count,
        )
    state = (
        "stop"
        if any(item["severity"] == "stop" for item in signals)
        else ("warn" if signals else "normal")
    )
    return {
        "state": state,
        "signals": signals,
        "metrics": {
            "tail_events": len(events),
            "compactions": compactions,
            "tool_calls": len(tool_signatures),
            "maximum_tool_call_repeat": maximum_tool_repeat,
            "last_turn_tokens": last_turn_tokens,
            "cumulative_tokens": cumulative_tokens,
        },
        "scan": {
            "max_bytes": max_bytes,
            "max_events": max_events,
        },
    }


def _iter_session_files(home: Path) -> Iterable[Path]:
    sessions_root = home / "sessions"
    if not sessions_root.is_dir():
        return []
    try:
        return sorted(
            (
                path
                for path in sessions_root.rglob("*.jsonl")
                if path.is_file() and not path.is_symlink()
            ),
            key=str,
        )
    except OSError:
        return []


def _normalize_fd_target(target: str) -> Path:
    clean = target.removesuffix(" (deleted)")
    return Path(clean)


def _belongs_to_homes(path: Path, homes: list[Path]) -> Path | None:
    for home in homes:
        try:
            path.relative_to(home / "sessions")
        except ValueError:
            continue
        return home
    return None


def _active_codex_processes(
    homes: list[Path], *, proc_root: Path
) -> tuple[list[dict[str, Any]], dict[str, set[int]]]:
    processes: list[dict[str, Any]] = []
    session_pids: dict[str, set[int]] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return processes, session_pids

    for entry in entries:
        try:
            pid = int(entry.name)
        except ValueError:
            continue
        if not _is_codex_process(entry):
            continue
        fd_dir = entry / "fd"
        active_paths: list[str] = []
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            fds = []
        for fd in fds:
            try:
                target = _normalize_fd_target(os.readlink(fd))
            except OSError:
                continue
            home = _belongs_to_homes(target, homes)
            if home is None or target.suffix != ".jsonl":
                continue
            path_text = str(target)
            if path_text not in active_paths:
                active_paths.append(path_text)
            session_pids.setdefault(path_text, set()).add(pid)
        if not active_paths:
            continue
        command = _read_cmdline(entry / "cmdline")
        memory = _read_smaps_rollup(entry)
        processes.append(
            {
                "pid": pid,
                "command": " ".join(command),
                "active_session_paths": sorted(active_paths),
                **memory,
                "pss_mib": round(memory["pss_bytes"] / MIB, 1),
                "swap_pss_mib": round(memory["swap_pss_bytes"] / MIB, 1),
            }
        )
    return sorted(processes, key=lambda item: int(item["pid"])), session_pids


def collect_snapshot(
    codex_homes: Iterable[Path],
    *,
    proc_root: Path = Path("/proc"),
    now: float | None = None,
    session_tail_bytes: int = DEFAULT_SESSION_TAIL_BYTES,
    session_tail_events: int = DEFAULT_SESSION_TAIL_EVENTS,
    recent_sessions_per_home: int = DEFAULT_RECENT_SESSIONS_PER_HOME,
    compaction_stop_count: int = DEFAULT_COMPACTION_STOP_COUNT,
    repeated_tool_stop_count: int = DEFAULT_REPEATED_TOOL_STOP_COUNT,
    tool_density_warn_count: int = DEFAULT_TOOL_DENSITY_WARN_COUNT,
) -> dict[str, Any]:
    """Collect session files and the Codex processes holding them open."""

    observed_at = time.time() if now is None else float(now)
    homes = list(dict.fromkeys(path.expanduser().resolve() for path in codex_homes))
    sessions_by_path: dict[str, dict[str, Any]] = {}
    for home in homes:
        for path in _iter_session_files(home):
            record = _session_record(path, home=home, now=observed_at)
            sessions_by_path[record["path"]] = record

    processes, session_pids = _active_codex_processes(homes, proc_root=proc_root)
    for path_text, pids in session_pids.items():
        record = sessions_by_path.get(path_text)
        if record is None:
            home = _belongs_to_homes(Path(path_text), homes)
            if home is None:
                continue
            record = _session_record(Path(path_text), home=home, now=observed_at)
            sessions_by_path[path_text] = record
        record["active_pids"] = sorted(pids)

    scan_paths = {
        path for path, record in sessions_by_path.items() if record.get("active_pids")
    }
    for home in homes:
        home_sessions = [
            record
            for record in sessions_by_path.values()
            if record.get("codex_home") == str(home)
        ]
        home_sessions.sort(
            key=lambda item: (
                str(item.get("modified_at") or ""),
                str(item.get("path") or ""),
            ),
            reverse=True,
        )
        scan_paths.update(
            str(record.get("path") or "")
            for record in home_sessions[: max(0, recent_sessions_per_home)]
        )
    for path_text in scan_paths:
        record = sessions_by_path.get(path_text)
        if record is None:
            continue
        record["run_health"] = _tail_run_health(
            Path(path_text),
            max_bytes=max(0, session_tail_bytes),
            max_events=max(0, session_tail_events),
            compaction_stop_count=max(1, compaction_stop_count),
            repeated_tool_stop_count=max(1, repeated_tool_stop_count),
            tool_density_warn_count=max(1, tool_density_warn_count),
        )

    return {
        "checked_at": _utc_timestamp(observed_at),
        "checked_at_epoch": int(observed_at),
        "codex_homes": [str(path) for path in homes],
        "run_health_limits": {
            "session_tail_bytes": max(0, session_tail_bytes),
            "session_tail_events": max(0, session_tail_events),
            "compaction_stop_count": max(1, compaction_stop_count),
            "repeated_tool_stop_count": max(1, repeated_tool_stop_count),
            "tool_density_warn_count": max(1, tool_density_warn_count),
        },
        "sessions": sorted(
            sessions_by_path.values(),
            key=lambda item: (str(item["codex_home"]), str(item["path"])),
        ),
        "processes": processes,
    }


def _issue(severity: str, check: str, detail: str) -> dict[str, str]:
    return {
        "severity": severity,
        "host": "local-host",
        "instance": "<host>",
        "check": check,
        "detail": detail,
    }


def evaluate_snapshot(
    snapshot: dict[str, Any],
    *,
    session_size_limit_mib: float = DEFAULT_SESSION_SIZE_LIMIT_MIB,
    process_pss_limit_mib: float = DEFAULT_PROCESS_PSS_LIMIT_MIB,
    session_age_hours: float = DEFAULT_SESSION_AGE_HOURS,
) -> dict[str, Any]:
    """Classify session-memory pressure and offer a human-controlled recovery."""

    size_limit_bytes = max(0, int(session_size_limit_mib * MIB))
    pss_limit_bytes = max(0, int(process_pss_limit_mib * MIB))
    age_limit_seconds = max(0, int(session_age_hours * 60 * 60))
    run_health_limits = snapshot.get("run_health_limits")
    run_health_limits = run_health_limits if isinstance(run_health_limits, dict) else {}
    issues: list[dict[str, str]] = []
    sessions: list[dict[str, Any]] = []
    oversized_active = 0
    long_lived_active = 0
    runaway_active = 0

    for raw in snapshot.get("sessions") or []:
        if not isinstance(raw, dict):
            continue
        session = dict(raw)
        active_pids = [
            int(pid)
            for pid in session.get("active_pids") or []
            if isinstance(pid, int) or str(pid).isdigit()
        ]
        size_bytes = int(session.get("size_bytes") or 0)
        age_seconds = session.get("age_seconds")
        run_health = session.get("run_health")
        run_health = run_health if isinstance(run_health, dict) else {}
        runaway_stop = run_health.get("state") == "stop"
        session["resume_blocked"] = size_bytes >= size_limit_bytes or runaway_stop
        session["resume_block_reason"] = (
            "session JSONL exceeds the configured resume limit"
            if size_bytes >= size_limit_bytes
            else (
                "recent session events indicate a runaway loop" if runaway_stop else ""
            )
        )
        if active_pids and runaway_stop:
            runaway_active += 1
            signal_codes = ",".join(
                str(item.get("code") or "")
                for item in run_health.get("signals") or []
                if isinstance(item, dict)
            )
            issues.append(
                _issue(
                    "fail",
                    "active_session_runaway",
                    (
                        f"active session {session['session_id']} has runaway "
                        f"signals ({signal_codes or 'unknown'}); stop after the "
                        "current safe boundary, preserve a handoff, and start fresh"
                    ),
                )
            )
        elif active_pids and run_health.get("state") == "warn":
            issues.append(
                _issue(
                    "warn",
                    "active_session_churn",
                    (
                        f"active session {session['session_id']} has unusually dense "
                        "recent tool activity; reduce or batch the next operation"
                    ),
                )
            )
        session["resume_block_reason"] = (
            session["resume_block_reason"] if session["resume_blocked"] else ""
        )
        if active_pids and session["resume_blocked"]:
            oversized_active += 1
            issues.append(
                _issue(
                    "warn",
                    "active_session_size",
                    (
                        f"active session {session['session_id']} is "
                        f"{session['size_mib']} MiB across PID(s) "
                        f"{','.join(str(pid) for pid in active_pids)}; "
                        "preserve a handoff and start a fresh session"
                    ),
                )
            )
        if (
            active_pids
            and isinstance(age_seconds, int)
            and age_seconds >= age_limit_seconds
        ):
            long_lived_active += 1
            issues.append(
                _issue(
                    "warn",
                    "active_session_age",
                    (
                        f"active session {session['session_id']} has been open for "
                        f"{round(age_seconds / 3600, 1)} hours; rotate through a "
                        "human-reviewed handoff"
                    ),
                )
            )
        sessions.append(session)

    large_processes = 0
    total_pss = 0
    total_swap_pss = 0
    processes: list[dict[str, Any]] = []
    for raw in snapshot.get("processes") or []:
        if not isinstance(raw, dict):
            continue
        process = dict(raw)
        pss_bytes = int(process.get("pss_bytes") or 0)
        swap_pss_bytes = int(process.get("swap_pss_bytes") or 0)
        total_pss += pss_bytes
        total_swap_pss += swap_pss_bytes
        process["pss_limit_exceeded"] = pss_bytes >= pss_limit_bytes
        if process["pss_limit_exceeded"]:
            large_processes += 1
            issues.append(
                _issue(
                    "fail",
                    "codex_process_pss",
                    (
                        f"Codex PID {process.get('pid')} uses "
                        f"{process.get('pss_mib')} MiB PSS "
                        f"({process.get('swap_pss_mib')} MiB SwapPss); "
                        "save a handoff, exit it, then start fresh"
                    ),
                )
            )
        processes.append(process)

    active_sessions = [session for session in sessions if session.get("active_pids")]
    status = (
        "fail"
        if any(item["severity"] == "fail" for item in issues)
        else ("warn" if issues else "ok")
    )
    return {
        "schema": SCHEMA,
        "checked_at": str(snapshot.get("checked_at") or ""),
        "status": status,
        "summary": {
            "active": len(active_sessions),
            "expected": len(active_sessions),
            "fail": sum(item["severity"] == "fail" for item in issues),
            "warn": sum(item["severity"] == "warn" for item in issues),
        },
        "kpis": {
            "session_count": len(sessions),
            "active_session_count": len(active_sessions),
            "oversized_active_session_count": oversized_active,
            "long_lived_active_session_count": long_lived_active,
            "runaway_active_session_count": runaway_active,
            "codex_process_count": len(processes),
            "large_codex_process_count": large_processes,
            "codex_process_pss_bytes": total_pss,
            "codex_process_swap_pss_bytes": total_swap_pss,
            "codex_process_swap_pss_mib": round(total_swap_pss / MIB, 1),
        },
        "limits": {
            "session_size_mib": session_size_limit_mib,
            "process_pss_mib": process_pss_limit_mib,
            "session_age_hours": session_age_hours,
            "session_tail_bytes": int(
                run_health_limits.get("session_tail_bytes", DEFAULT_SESSION_TAIL_BYTES)
            ),
            "session_tail_events": int(
                run_health_limits.get(
                    "session_tail_events", DEFAULT_SESSION_TAIL_EVENTS
                )
            ),
            "compaction_stop_count": int(
                run_health_limits.get(
                    "compaction_stop_count", DEFAULT_COMPACTION_STOP_COUNT
                )
            ),
            "repeated_tool_stop_count": int(
                run_health_limits.get(
                    "repeated_tool_stop_count",
                    DEFAULT_REPEATED_TOOL_STOP_COUNT,
                )
            ),
            "tool_density_warn_count": int(
                run_health_limits.get(
                    "tool_density_warn_count", DEFAULT_TOOL_DENSITY_WARN_COUNT
                )
            ),
        },
        "issues": issues,
        "sessions": sessions,
        "processes": processes,
        "recommendation": (
            "Monitoring never deletes, signals, or terminates active sessions. "
            "For a flagged session, preserve a concise handoff, exit it normally, "
            "then start a fresh Codex session."
        ),
    }


def resume_decision(report: dict[str, Any], target: str) -> dict[str, Any]:
    """Return whether a direct Codex resume target is safe to load."""

    sessions = [item for item in report.get("sessions") or [] if isinstance(item, dict)]
    normalized_target = target.strip().lower()
    if not normalized_target:
        return {
            "target": "",
            "action": "warn",
            "reason": (
                "bare `resume` opens Codex's picker; it cannot be filtered here. "
                "Avoid oversized sessions and prefer a fresh session after a handoff."
            ),
        }
    if normalized_target == "last":
        matches = sorted(
            sessions,
            key=lambda item: (
                str(item.get("modified_at") or ""),
                str(item.get("path") or ""),
            ),
            reverse=True,
        )
        matches = matches[:1]
    else:
        matches = [
            item
            for item in sessions
            if str(item.get("session_id") or "").lower().startswith(normalized_target)
        ]
    if not matches:
        return {
            "target": target,
            "action": "allow",
            "reason": "resume target is not present in this CODEX_HOME",
        }
    if len(matches) > 1:
        return {
            "target": target,
            "action": "warn",
            "reason": "resume target is ambiguous; select a full session ID",
        }
    session = matches[0]
    if session.get("resume_blocked"):
        return {
            "target": target,
            "action": "block",
            "session_id": session.get("session_id"),
            "path": session.get("path"),
            "reason": (
                f"{session.get('resume_block_reason')}; preserve a handoff and "
                "start fresh"
            ),
        }
    return {
        "target": target,
        "action": "allow",
        "session_id": session.get("session_id"),
        "path": session.get("path"),
        "reason": "resume target is within the configured session-size limit",
    }


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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report active Codex session pressure without changing sessions."
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        action="append",
        default=[],
        help="CODEX_HOME to inspect. May be repeated.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument(
        "--session-size-limit-mib", type=float, default=DEFAULT_SESSION_SIZE_LIMIT_MIB
    )
    parser.add_argument(
        "--process-pss-limit-mib", type=float, default=DEFAULT_PROCESS_PSS_LIMIT_MIB
    )
    parser.add_argument(
        "--session-age-hours", type=float, default=DEFAULT_SESSION_AGE_HOURS
    )
    parser.add_argument(
        "--session-tail-bytes", type=int, default=DEFAULT_SESSION_TAIL_BYTES
    )
    parser.add_argument(
        "--session-tail-events", type=int, default=DEFAULT_SESSION_TAIL_EVENTS
    )
    parser.add_argument(
        "--recent-sessions-per-home",
        type=int,
        default=DEFAULT_RECENT_SESSIONS_PER_HOME,
    )
    parser.add_argument(
        "--compaction-stop-count", type=int, default=DEFAULT_COMPACTION_STOP_COUNT
    )
    parser.add_argument(
        "--repeated-tool-stop-count",
        type=int,
        default=DEFAULT_REPEATED_TOOL_STOP_COUNT,
    )
    parser.add_argument(
        "--tool-density-warn-count",
        type=int,
        default=DEFAULT_TOOL_DENSITY_WARN_COUNT,
    )
    parser.add_argument(
        "--resume-target",
        default=None,
        help="Check `last` or a direct Codex session ID before resuming it.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    homes = args.codex_home or _default_codex_homes()
    snapshot = collect_snapshot(
        homes,
        session_tail_bytes=max(0, int(args.session_tail_bytes)),
        session_tail_events=max(0, int(args.session_tail_events)),
        recent_sessions_per_home=max(0, int(args.recent_sessions_per_home)),
        compaction_stop_count=max(1, int(args.compaction_stop_count)),
        repeated_tool_stop_count=max(1, int(args.repeated_tool_stop_count)),
        tool_density_warn_count=max(1, int(args.tool_density_warn_count)),
    )
    report = evaluate_snapshot(
        snapshot,
        session_size_limit_mib=max(0.0, float(args.session_size_limit_mib)),
        process_pss_limit_mib=max(0.0, float(args.process_pss_limit_mib)),
        session_age_hours=max(0.0, float(args.session_age_hours)),
    )
    if not args.no_write:
        _write_json(args.output_json, report)

    resume = None
    if args.resume_target is not None:
        resume = resume_decision(report, str(args.resume_target))
    if not args.quiet:
        if args.json:
            payload: dict[str, Any] = {"report": report}
            if resume is not None:
                payload["resume"] = resume
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif resume is not None:
            print(f"resume {resume['action']}: {resume['reason']}")
        else:
            print(
                "codex session pressure: "
                f"{report['status']} active={report['kpis']['active_session_count']} "
                f"oversized={report['kpis']['oversized_active_session_count']} "
                f"large_processes={report['kpis']['large_codex_process_count']}"
            )
    return 3 if resume and resume["action"] == "block" else 0


if __name__ == "__main__":
    raise SystemExit(main())
