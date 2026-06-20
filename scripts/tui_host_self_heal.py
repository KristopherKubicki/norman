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


DEFAULT_HEALTH_JSON = Path(
    os.environ.get(
        "NORMAN_TUI_FLEET_HEALTH_JSON",
        "/home/kristopher/.local/state/norman/tui-fleet-doctor.json",
    )
)
DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "NORMAN_TUI_HOST_SELF_HEAL_STATE",
        "/home/kristopher/.local/state/norman/tui-host-self-heal-state.json",
    )
)
DEFAULT_OUTPUT_JSON = Path(
    os.environ.get(
        "NORMAN_TUI_HOST_SELF_HEAL_JSON",
        "/home/kristopher/.local/state/norman/tui-host-self-heal.json",
    )
)
DEFAULT_FAILURE_THRESHOLD = int(
    os.environ.get("NORMAN_TUI_HOST_SELF_HEAL_FAILURE_THRESHOLD", "2")
)


ObserveFn = Callable[[recovery.RecoveryTarget], dict[str, Any]]
RebootFn = Callable[[recovery.RecoveryTarget], recovery.CommandResult]


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _issue_signature(issue: dict[str, Any]) -> str:
    return "|".join(
        str(issue.get(key) or "").strip()
        for key in ("severity", "host", "instance", "check", "detail")
    )


def recoverable_issue(issue: dict[str, Any], *, target_name: str) -> bool:
    if str(issue.get("severity") or "").strip().lower() != "fail":
        return False
    if str(issue.get("host") or "").strip() != target_name:
        return False
    if str(issue.get("instance") or "").strip() != "<host>":
        return False
    check = str(issue.get("check") or "").strip()
    detail = str(issue.get("detail") or "")
    if check == "host-pressure" and "critical host pressure" in detail:
        return True
    if check == "scan" and (
        "SSH banner timeout" in detail
        or "no SSH banner" in detail
        or "recovery available: scripts/tui_host_recovery.py" in detail
    ):
        return True
    return False


def _coerce_float(value: Any) -> float:
    try:
        return float(str(value or "0").strip())
    except (TypeError, ValueError):
        return 0.0


def _probe_is_healthy(detail: Any) -> bool:
    return str(detail or "").strip() == "responded"


def observation_supports_graceful_reboot(observation: dict[str, Any]) -> bool:
    status = observation.get("pct_status") if isinstance(observation, dict) else {}
    status_stdout = str(status.get("stdout") if isinstance(status, dict) else "")
    pct_running = "status: running" in status_stdout
    probes = observation.get("probes") if isinstance(observation, dict) else {}
    probe_failed = any(
        not _probe_is_healthy(detail)
        for detail in (probes.values() if isinstance(probes, dict) else [])
    )
    current = observation.get("pvesh_status_json")
    if not isinstance(current, dict):
        current = {}
    pressure_critical = (
        _coerce_float(current.get("pressureiosome")) >= 80.0
        or _coerce_float(current.get("pressurememorysome")) >= 60.0
    )
    return pct_running and (probe_failed or pressure_critical)


def _target_state(state: dict[str, Any], target_name: str) -> dict[str, Any]:
    targets = state.setdefault("targets", {})
    if not isinstance(targets, dict):
        state["targets"] = targets = {}
    item = targets.setdefault(target_name, {})
    if not isinstance(item, dict):
        targets[target_name] = item = {}
    return item


def evaluate(
    health: dict[str, Any],
    state: dict[str, Any],
    *,
    target_name: str,
    failure_threshold: int,
    execute: bool,
    approved: bool,
    settle_seconds: int,
    observe_fn: ObserveFn = recovery.observe_target,
    reboot_fn: RebootFn = recovery.execute_graceful_reboot,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = recovery.RECOVERY_TARGETS[target_name]
    next_state = dict(state) if isinstance(state, dict) else {}
    target_state = _target_state(next_state, target_name)
    issues = [
        issue
        for issue in health.get("issues") or []
        if isinstance(issue, dict) and recoverable_issue(issue, target_name=target_name)
    ]
    signatures = sorted(_issue_signature(issue) for issue in issues)
    checked_at = str(health.get("checked_at") or "")
    prior_signatures = target_state.get("last_signatures")
    prior_checked_at = str(target_state.get("last_checked_at") or "")

    if not issues:
        target_state.update(
            {
                "failure_count": 0,
                "last_checked_at": checked_at,
                "last_signatures": [],
                "last_status": "healthy",
            }
        )
        return {
            "target": target_name,
            "status": "healthy",
            "recoverable_issue_count": 0,
            "failure_count": 0,
            "action": "none",
        }, next_state

    failure_count = int(target_state.get("failure_count") or 0)
    if checked_at != prior_checked_at or signatures != prior_signatures:
        failure_count += 1
    target_state.update(
        {
            "failure_count": failure_count,
            "last_checked_at": checked_at,
            "last_signatures": signatures,
            "last_status": "watching",
        }
    )

    decision: dict[str, Any] = {
        "target": target_name,
        "status": "watching",
        "recoverable_issue_count": len(issues),
        "failure_count": failure_count,
        "failure_threshold": failure_threshold,
        "issues": issues,
        "action": "none",
    }
    if failure_count < max(1, failure_threshold):
        return decision, next_state

    observation = observe_fn(target)
    decision["observation"] = observation
    if not observation_supports_graceful_reboot(observation):
        target_state["last_status"] = "not_wedged"
        decision.update({"status": "not_wedged", "action": "none"})
        return decision, next_state

    if not execute:
        target_state["last_status"] = "would_recover"
        decision.update(
            {
                "status": "would_recover",
                "action": "graceful_reboot",
                "execute_required": True,
            }
        )
        return decision, next_state
    if not approved:
        target_state["last_status"] = "approval_required"
        decision.update(
            {
                "status": "approval_required",
                "action": "none",
                "execute_required": True,
            }
        )
        return decision, next_state

    action = reboot_fn(target)
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    post_observation = observe_fn(target)
    action_payload = recovery._result_payload(action)
    recovered = bool(action.returncode == 0)
    target_state.update(
        {
            "failure_count": 0 if recovered else failure_count,
            "last_status": "recovered" if recovered else "recovery_failed",
            "last_action_returncode": action.returncode,
        }
    )
    decision.update(
        {
            "status": "recovered" if recovered else "recovery_failed",
            "action": "graceful_reboot",
            "action_result": action_payload,
            "post_observation": post_observation,
        }
    )
    return decision, next_state


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Conservative self-heal wrapper for repeatedly wedged TUI hosts."
    )
    parser.add_argument(
        "--target", choices=sorted(recovery.RECOVERY_TARGETS), required=True
    )
    parser.add_argument("--health-json", type=Path, default=DEFAULT_HEALTH_JSON)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--threshold", type=int, default=DEFAULT_FAILURE_THRESHOLD)
    parser.add_argument("--settle-seconds", type=int, default=10)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Required with --execute; authorizes graceful reboot only.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.execute and not args.approved:
        print("--execute requires --approved", file=sys.stderr)
        return 2
    health = _load_json(args.health_json, {})
    state = _load_json(args.state, {})
    decision, next_state = evaluate(
        health,
        state,
        target_name=args.target,
        failure_threshold=max(1, int(args.threshold or 1)),
        execute=bool(args.execute),
        approved=bool(args.approved),
        settle_seconds=max(0, int(args.settle_seconds or 0)),
    )
    _write_json(args.state, next_state)
    _write_json(args.json_output, decision)
    if args.json:
        print(json.dumps(decision, indent=2, sort_keys=True))
    else:
        print(
            "{target}: status={status} action={action} failures={count}/{threshold}".format(
                target=args.target,
                status=decision.get("status"),
                action=decision.get("action"),
                count=decision.get("failure_count", 0),
                threshold=decision.get("failure_threshold", args.threshold),
            )
        )
    return 1 if decision.get("status") == "recovery_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
