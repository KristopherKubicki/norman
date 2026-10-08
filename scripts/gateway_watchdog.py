#!/usr/bin/env python3
"""Observe Norman independently of its API; cautiously recover a wedged process."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import tempfile
import urllib.error
import urllib.request

SCHEMA = "norman.gateway-health.v1"
GRACE = 180
COOLDOWN = 900


def health_probe() -> int:
    try:
        response = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3)
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return 0
    with response:
        try:
            body = json.loads(response.read(65536))
            return 200 if isinstance(body, dict) and body.get("status") == "ok" else 503
        except (OSError, ValueError):
            # HTTP answered: invalid or incomplete health JSON is not a dead
            # listener and must not trigger the transport-only restart rule.
            return 503


def service_state() -> dict:
    result = subprocess.run(
        [
            "systemctl",
            "list-units",
            "norman-production@*.service",
            "--all",
            "--output=json",
            "--no-pager",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    units = [
        row["unit"]
        for row in json.loads(result.stdout)
        if row.get("active") in {"active", "activating", "deactivating"}
    ]
    if len(units) != 1 or not re.fullmatch(
        r"norman-production@[0-9a-f]{7,40}\.service", units[0]
    ):
        return {"ActiveState": "unknown"}
    result = subprocess.run(
        [
            "systemctl",
            "show",
            units[0],
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "UnitFileState",
            "-p",
            "ActiveEnterTimestampMonotonic",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return {
        "unit": units[0],
        **dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        ),
    }


def valid_timestamp(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def recovery_state_valid(previous: dict) -> bool:
    """Malformed budgets must never become fresh automatic-action budgets."""
    return (
        not previous.get("recovery_state_invalid")
        and (
            previous.get("down_since") is None
            or valid_timestamp(previous["down_since"])
        )
        and isinstance(previous.get("restart_attempts", []), list)
        and all(valid_timestamp(item) for item in previous.get("restart_attempts", []))
        and valid_timestamp(previous.get("last_diagnosis_attempt", 0))
    )


@contextmanager
def state_lock(path: Path):
    """Serialize scheduled and manual runs before reading their shared budget."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def observe(
    previous: dict,
    service: dict,
    code: int,
    now: float,
    uptime: float,
    maintenance: bool,
) -> tuple[dict, bool]:
    """Pure state machine: never restart an intentional stop or model outage."""
    valid = recovery_state_valid(previous)
    budget = previous if valid else {}
    down_since = (
        now
        if code == 200
        else min(
            now,
            float(
                budget.get("down_since")
                if budget.get("down_since") is not None
                else now
            ),
        )
    )
    elapsed = max(0, int(now - down_since))
    actions = [t for t in budget.get("restart_attempts", []) if now - t < 3600]
    phase = "ready" if code == 200 else "unavailable"
    if code != 200 and service.get("ActiveState") in {"activating", "deactivating"}:
        phase = "restarting" if elapsed < GRACE else "recovery_stalled"
    elif code != 200 and elapsed < GRACE:
        phase = "recovering"
    if maintenance:
        phase = "maintenance"
    repair = (
        valid
        and code == 0
        and not maintenance
        and elapsed >= GRACE
        and uptime >= GRACE
        and service.get("ActiveState") == "active"
        and service.get("SubState") == "running"
        and service.get("UnitFileState") == "enabled"
        and bool(service.get("unit"))
        and len(actions) < 2
        and (not actions or now - max(actions) >= COOLDOWN)
    )
    messages = {
        "ready": "Backend HTTP health is ready; model availability is checked separately.",
        "recovering": "Backend is unavailable. Waiting within the recovery grace period; no restart ETA is guaranteed.",
        "restarting": "Backend service is starting or stopping. Keep the session; check again shortly.",
        "recovery_stalled": "Backend restart exceeded the grace period. Operator attention is required.",
        "unavailable": "Backend remains unavailable. Preserve the session and use local rescue for diagnosis.",
        "maintenance": "Operator maintenance is active; watchdog restart is suspended.",
    }
    return {
        "schema": SCHEMA,
        "checked_at": now,
        "phase": phase,
        "backend_http": code,
        "down_since": None if code == 200 else down_since,
        "unavailable_seconds": elapsed,
        "retry_after_seconds": 0 if phase == "ready" else 10,
        "message": messages[phase],
        "restart_attempts": actions,
        "model_readiness": "not_checked",
        "automatic_recovery_eligible": repair,
        "recovery_state_invalid": not valid,
        "recovery_state_message": "Automatic recovery is suspended; restore or reconcile the damaged budget receipt."
        if not valid
        else "",
    }, repair


def read_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {"recovery_state_invalid": True}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {"recovery_state_invalid": True}


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(state, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
            temporary.replace(path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state", type=Path, default=Path("/var/lib/norman/gateway-health/status.json")
    )
    parser.add_argument(
        "--maintenance", type=Path, default=Path("/run/norman-gateway-maintenance.json")
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Allow bounded try-restart of an enabled, running, unresponsive production unit",
    )
    args = parser.parse_args()
    with state_lock(args.state) as acquired:
        return run(args) if acquired else 0


def run(args: argparse.Namespace) -> int:
    now = time.time()
    previous = read_state(args.state)
    service = service_state()
    entered = float(service.get("ActiveEnterTimestampMonotonic") or 0) / 1e6
    uptime = max(0, time.monotonic() - entered) if entered else 0
    until = read_state(args.maintenance).get("until")
    maintenance = args.maintenance.exists() and (
        type(until) not in (int, float) or not math.isfinite(until) or until > now
    )
    state, repair = observe(previous, service, health_probe(), now, uptime, maintenance)
    if repair and args.repair:
        # Record before the side effect: failures consume the bounded budget too.
        state["restart_attempts"].append(now)
        state["phase"] = "restart_requested"
        state["message"] = (
            "Watchdog requested one bounded restart after 180 seconds without HTTP health."
        )
        write_state(args.state, state)
        result = subprocess.run(
            ["systemctl", "--no-block", "try-restart", service["unit"]],
            timeout=5,
            check=False,
        )
        state["restart_request_succeeded"] = result.returncode == 0
    write_state(args.state, state)
    if state["phase"] != previous.get("phase"):
        print(json.dumps(state), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
