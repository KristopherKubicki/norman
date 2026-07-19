#!/usr/bin/env python3
"""Run a dependency-aware benchmark plan with a durable lease and task state."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "norman.norllama.benchmark-orchestration-state.v1"
TERMINAL_STATES = {"complete", "failed", "blocked"}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _clean(value: Any) -> str:
    return str(value or "").strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp_path.replace(path)


def task_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = {
        _clean(task.get("id")): dict(task)
        for task in plan.get("tasks") or []
        if isinstance(task, dict) and _clean(task.get("id"))
    }
    if not tasks:
        raise ValueError("plan must define at least one task")
    for task_id, task in tasks.items():
        for dependency in task.get("depends_on") or []:
            if _clean(dependency) not in tasks:
                raise ValueError(
                    f"task {task_id} references unknown dependency {dependency}"
                )
    return tasks


def new_state(plan: dict[str, Any]) -> dict[str, Any]:
    tasks = task_map(plan)
    return {
        "schema": SCHEMA,
        "plan_schema": _clean(plan.get("schema")),
        "plan_id": _clean(plan.get("plan_id")) or "unnamed-plan",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "lease": {},
        "tasks": {
            task_id: {
                "state": "pending",
                "attempt_count": 0,
                "updated_at": utc_now(),
            }
            for task_id in tasks
        },
    }


def ready_task_ids(plan: dict[str, Any], state: dict[str, Any]) -> list[str]:
    tasks = task_map(plan)
    task_states = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
    ready: list[str] = []
    for task_id, task in tasks.items():
        row = (
            task_states.get(task_id)
            if isinstance(task_states.get(task_id), dict)
            else {}
        )
        status = _clean(row.get("state")) or "pending"
        if status in TERMINAL_STATES or status == "running":
            continue
        dependencies = [_clean(value) for value in task.get("depends_on") or []]
        dependency_states = [
            _clean((task_states.get(dependency) or {}).get("state"))
            for dependency in dependencies
        ]
        if any(
            dependency_state in {"failed", "blocked"}
            for dependency_state in dependency_states
        ):
            row.update(
                {
                    "state": "blocked",
                    "reason": "dependency_failed_or_blocked",
                    "updated_at": utc_now(),
                }
            )
            task_states[task_id] = row
            continue
        if all(
            dependency_state == "complete" for dependency_state in dependency_states
        ):
            ready.append(task_id)
    return ready


def apply_task_result(
    *,
    state: dict[str, Any],
    task: dict[str, Any],
    returncode: int,
) -> None:
    task_id = _clean(task.get("id"))
    row = state["tasks"][task_id]
    attempts = int(row.get("attempt_count") or 0) + 1
    retry_limit = max(1, int(task.get("max_attempts") or 1))
    row.update(
        {
            "attempt_count": attempts,
            "returncode": int(returncode),
            "updated_at": utc_now(),
            "state": "complete"
            if returncode == 0
            else "retryable"
            if attempts < retry_limit
            else "failed",
        }
    )


def _lease_path(state_path: Path) -> Path:
    return state_path.with_suffix(f"{state_path.suffix}.lock")


def acquire_lease(state_path: Path, *, ttl_seconds: float) -> Path:
    lease_path = _lease_path(state_path)
    now = time.time()
    if lease_path.exists() and now - lease_path.stat().st_mtime > ttl_seconds:
        lease_path.unlink()
    try:
        descriptor = os.open(lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise RuntimeError(f"orchestrator lease is held: {lease_path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "acquired_at": utc_now(),
            },
            handle,
        )
    return lease_path


def run_command_with_lease(
    command: list[str],
    *,
    lease_path: Path,
    lease_seconds: float,
) -> int:
    """Run one task while keeping its cross-process lease fresh."""

    refresh_seconds = max(1.0, min(60.0, float(lease_seconds) / 3.0))
    process = subprocess.Popen(command)
    while True:
        try:
            return int(process.wait(timeout=refresh_seconds))
        except subprocess.TimeoutExpired:
            lease_path.touch()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--lease-seconds", type=float, default=1800.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = load_json(args.plan)
    state = load_json(args.state) if args.state.exists() else new_state(plan)
    lease_path = acquire_lease(args.state, ttl_seconds=max(1.0, args.lease_seconds))
    try:
        state["lease"] = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at": utc_now(),
        }
        ready = ready_task_ids(plan, state)
        tasks = task_map(plan)
        executed: list[dict[str, Any]] = []
        for task_id in ready[: max(0, args.max_tasks)]:
            task = tasks[task_id]
            row = state["tasks"][task_id]
            command = task.get("command")
            if not isinstance(command, list) or not command:
                row.update(
                    {
                        "state": "blocked",
                        "reason": "missing_command",
                        "updated_at": utc_now(),
                    }
                )
                continue
            if args.dry_run:
                executed.append(
                    {"task_id": task_id, "command": command, "state": "ready"}
                )
                continue
            row.update(
                {"state": "running", "started_at": utc_now(), "updated_at": utc_now()}
            )
            write_json(args.state, state)
            returncode = run_command_with_lease(
                command,
                lease_path=lease_path,
                lease_seconds=max(1.0, args.lease_seconds),
            )
            apply_task_result(state=state, task=task, returncode=returncode)
            executed.append(
                {
                    "task_id": task_id,
                    "returncode": returncode,
                    "state": state["tasks"][task_id]["state"],
                }
            )
        state["updated_at"] = utc_now()
        if not args.dry_run:
            write_json(args.state, state)
        print(
            json.dumps(
                {"state": state, "ready": ready, "executed": executed},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        lease_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
