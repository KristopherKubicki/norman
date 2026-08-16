#!/usr/bin/env python3
"""Atomically refresh one validated Norllama route policy across the fleet."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence
from urllib.error import URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.norllama.route_policy_artifact import (
    generate_route_policy_artifact,
    validate_route_policy_artifact,
    write_route_policy_artifact,
)
from app.core.estate_registry import load_fleet_topology


ENDPOINTS = ("/healthz", "/readyz", "/asr-readyz", "/v1/models")


def fleet_targets() -> tuple[dict[str, Any], ...]:
    targets: list[dict[str, Any]] = []
    workers = load_fleet_topology()["workers"]
    ordered = sorted(
        workers.items(),
        key=lambda item: (
            str((item[1] if isinstance(item[1], dict) else {}).get("role"))
            == "fallback",
        ),
    )
    for worker_id, raw in ordered:
        row = raw if isinstance(raw, dict) else {}
        management = (
            row.get("management") if isinstance(row.get("management"), dict) else {}
        )
        address = str(row.get("address") or "").strip()
        user = str(management.get("ssh_user") or "").strip()
        identity = str(management.get("identity_file") or "").strip()
        policy_path = str(management.get("policy_path") or "").strip()
        port = int(row.get("gateway_port") or 0)
        if not all((address, user, identity, policy_path, port)):
            continue
        targets.append(
            {
                "name": str(row.get("health_name") or worker_id),
                "ssh": f"{user}@{address}",
                "identity_file": identity,
                "policy_path": policy_path,
                "url": f"http://{address}:{port}",
                "endpoints": (
                    ENDPOINTS
                    if str(management.get("asr_unit") or "").strip()
                    else tuple(item for item in ENDPOINTS if item != "/asr-readyz")
                ),
            }
        )
    return tuple(targets)


TARGETS = fleet_targets()


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def write_output(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def next_policy_path(live: str) -> str:
    path = PurePosixPath(live)
    return str(path.with_name(f"{path.stem}.next{path.suffix}"))


def add_alert_contract(report: dict[str, Any]) -> dict[str, Any]:
    targets = report.get("targets") if isinstance(report.get("targets"), list) else []
    preflight = report.get("preflight")
    if isinstance(preflight, list):
        expected = max(len(targets), len(preflight))
    elif targets:
        expected = len(targets)
    else:
        expected = len(TARGETS)
    active = sum(
        isinstance(target, dict) and target.get("status") in {"active", "staged"}
        for target in targets
    )
    failed = report.get("status") != "ok"
    report["summary"] = {
        "active": active if report.get("mode") in {"apply", "stage"} else expected,
        "expected": expected,
        "fail": 1 if failed else 0,
        "warn": 0,
    }
    if failed:
        report["issues"] = [
            {
                "severity": "fail",
                "host": "norllama-fleet",
                "instance": "route-policy-refresh",
                "check": "refresh",
                "detail": str(report.get("error") or "route policy refresh failed"),
            }
        ]
    else:
        report["issues"] = []
    return report


def http_json(url: str) -> tuple[int, dict[str, Any]]:
    try:
        with urlopen(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
            return response.status, data if isinstance(data, dict) else {}
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return 0, {}


def remote(
    target: dict[str, Any], command: str, *, input_text: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "IdentitiesOnly=yes",
            "-i",
            target["identity_file"],
            target["ssh"],
            command,
        ],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        timeout=25,
    )


def copy_to_remote(
    path: Path, target: dict[str, Any], destination: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "scp",
            "-q",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "IdentitiesOnly=yes",
            "-i",
            target["identity_file"],
            str(path),
            f"{target['ssh']}:{destination}",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def remote_validate(
    target: dict[str, Any], path: str, policy_id: str
) -> tuple[bool, str]:
    script = """\
import json
import os
import sys
path, expected = sys.argv[1], sys.argv[2]
root = os.path.dirname(path)
sys.path.insert(0, root)
from app.services.norllama.route_policy_artifact import validate_route_policy_artifact
with open(path, encoding="utf-8") as handle:
    policy = json.load(handle)
validation = validate_route_policy_artifact(policy)
if policy.get("policy_id") != expected or not validation.get("production_route_eligible"):
    raise SystemExit(json.dumps({"policy_id": policy.get("policy_id"), "validation": validation}))
print(json.dumps({"policy_id": policy.get("policy_id"), "validation": validation}))
"""
    result = remote(
        target,
        f"python3 - {path!s} {policy_id!s}",
        input_text=script,
    )
    return result.returncode == 0, (result.stdout or result.stderr).strip()


def remote_checksum(
    target: dict[str, Any], path: str, expected_sha256: str
) -> tuple[bool, str]:
    result = remote(target, f"sha256sum -- {path!s}")
    detail = (result.stdout or result.stderr).strip()
    actual = detail.split(maxsplit=1)[0] if detail else ""
    return result.returncode == 0 and actual == expected_sha256, detail


def promote(
    target: dict[str, Any], live: str, pending: str, backup: str
) -> tuple[bool, str]:
    result = remote(
        target,
        "sh -s -- " + " ".join([live, pending, backup]),
        input_text="""\
set -eu
live=$1
pending=$2
backup=$3
test -s "$pending"
cp -p "$live" "$backup"
mv "$pending" "$live"
""",
    )
    return result.returncode == 0, (result.stdout or result.stderr).strip()


def stage_for_activation(
    target: dict[str, Any], staged: str, pending: str, backup: str
) -> tuple[bool, str]:
    result = remote(
        target,
        "sh -s -- " + " ".join([staged, pending, backup]),
        input_text="""\
set -eu
staged=$1
pending=$2
backup=$3
test -s "$pending"
if test -e "$staged"; then
    cp -p "$staged" "$backup"
else
    : > "$backup.absent"
fi
mv "$pending" "$staged"
""",
    )
    return result.returncode == 0, (result.stdout or result.stderr).strip()


def rollback(target: dict[str, Any], live: str, backup: str) -> None:
    remote(
        target,
        "sh -s -- " + " ".join([live, backup]),
        input_text="""\
set -eu
live=$1
backup=$2
test -s "$backup"
mv "$backup" "$live"
""",
    )


def rollback_staged(target: dict[str, Any], staged: str, backup: str) -> None:
    remote(
        target,
        "sh -s -- " + " ".join([staged, backup]),
        input_text="""\
set -eu
staged=$1
backup=$2
if test -s "$backup"; then
    mv "$backup" "$staged"
elif test -e "$backup.absent"; then
    rm -f -- "$staged" "$backup.absent"
fi
""",
    )


def cleanup(target: dict[str, Any], *paths: str) -> None:
    remote(target, "rm -f -- " + " ".join(paths))


def verify_live(target: dict[str, Any], policy_id: str) -> tuple[bool, str]:
    for endpoint in target.get("endpoints") or ENDPOINTS:
        status, payload = http_json(f"{target['url']}{endpoint}")
        if status != 200:
            return False, f"{endpoint} returned {status}"
        if endpoint == "/readyz":
            policy = (
                payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
            )
            if policy.get("policy_id") != policy_id or not payload.get("ready"):
                return False, "readyz did not report the promoted eligible policy"
    return True, ""


def select_targets(names: Sequence[str] | None) -> tuple[dict[str, Any], ...]:
    requested = set(names or ())
    return tuple(item for item in TARGETS if not requested or item["name"] in requested)


def refresh(
    *,
    targets: Sequence[dict[str, Any]],
    apply: bool,
    stage_only: bool = False,
) -> dict[str, Any]:
    generations: list[int] = []
    preflight: list[dict[str, Any]] = []
    for target in targets:
        status, payload = http_json(f"{target['url']}/readyz")
        policy = (
            payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        )
        generation = policy.get("refresh_generation")
        healthy = (
            status == 200 and bool(payload.get("ready")) and isinstance(generation, int)
        )
        preflight.append({"name": target["name"], "ready": healthy, "status": status})
        if healthy:
            generations.append(generation)
    generation = max(generations, default=0) + 1
    policy = generate_route_policy_artifact(generation=generation)
    validation = validate_route_policy_artifact(policy)
    report: dict[str, Any] = {
        "schema": "norman.norllama.fleet-policy-refresh.v1",
        "checked_at": utc_now(),
        "mode": "stage" if apply and stage_only else "apply" if apply else "dry-run",
        "policy_id": policy["policy_id"],
        "refresh_generation": generation,
        "validation": validation,
        "preflight": preflight,
        "targets": [],
        "status": "blocked",
    }
    if not validation.get("production_route_eligible") or not all(
        item["ready"] for item in preflight
    ):
        report["error"] = "policy validation or worker readiness preflight failed"
        return report
    if not apply:
        report["status"] = "ok"
        report["targets"] = [
            {
                "name": item["name"],
                "status": "planned-stage" if stage_only else "planned",
            }
            for item in targets
        ]
        return report

    operation = uuid.uuid4().hex
    promoted: list[tuple[dict[str, Any], str]] = []
    staged_targets: list[tuple[dict[str, Any], str, str]] = []
    with tempfile.TemporaryDirectory(prefix="norllama-fleet-policy-") as temporary:
        local_policy = Path(temporary) / "route_policy.json"
        write_route_policy_artifact(policy, local_policy)
        local_sha256 = hashlib.sha256(local_policy.read_bytes()).hexdigest()
        for target in targets:
            live = target["policy_path"]
            pending = f"{live}.fleet-incoming-{operation}"
            backup = f"{live}.fleet-previous-{operation}"
            copied = copy_to_remote(local_policy, target, pending)
            if stage_only:
                valid, detail = remote_checksum(target, pending, local_sha256)
            else:
                valid, detail = remote_validate(target, pending, policy["policy_id"])
            if copied.returncode or not valid:
                cleanup(target, pending)
                report["error"] = (
                    f"{target['name']} staging failed: {copied.stderr or detail}"
                )
                break
            report["targets"].append({"name": target["name"], "status": "staged"})
        else:
            if stage_only:
                for target in targets:
                    live = target["policy_path"]
                    pending = f"{live}.fleet-incoming-{operation}"
                    staged = next_policy_path(live)
                    backup = f"{staged}.fleet-previous-{operation}"
                    changed, detail = stage_for_activation(
                        target, staged, pending, backup
                    )
                    if not changed:
                        report["error"] = (
                            f"{target['name']} stage-only activation failed: {detail}"
                        )
                        break
                    staged_targets.append((target, staged, backup))
                else:
                    for target, _staged, backup in staged_targets:
                        cleanup(target, backup, f"{backup}.absent")
                    report["status"] = "ok"
                    return report
                for target, staged, backup in reversed(staged_targets):
                    rollback_staged(target, staged, backup)
                report["rollback_performed"] = bool(staged_targets)
                return report
            for target in targets:
                live = target["policy_path"]
                pending = f"{live}.fleet-incoming-{operation}"
                backup = f"{live}.fleet-previous-{operation}"
                changed, detail = promote(target, live, pending, backup)
                if not changed:
                    report["error"] = f"{target['name']} promotion failed: {detail}"
                    break
                promoted.append((target, backup))
                verified, detail = verify_live(target, policy["policy_id"])
                if not verified:
                    report["error"] = f"{target['name']} readiness failed: {detail}"
                    break
                report["targets"] = [
                    {
                        "name": item["name"],
                        "status": "active"
                        if item["name"] == target["name"]
                        else item["status"],
                    }
                    for item in report["targets"]
                ]
            else:
                for target, backup in promoted:
                    cleanup(target, backup)
                report["status"] = "ok"
                return report
    for target, backup in reversed(promoted):
        rollback(target, target["policy_path"], backup)
    report["rollback_performed"] = bool(promoted)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Promote the generated policy."
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="Validate and write route_policy.next.json without changing live policy.",
    )
    parser.add_argument(
        "--target", action="append", choices=[item["name"] for item in TARGETS]
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = refresh(
            targets=select_targets(args.target),
            apply=args.apply,
            stage_only=args.stage_only,
        )
    except Exception as exc:
        report = {
            "schema": "norman.norllama.fleet-policy-refresh.v1",
            "checked_at": utc_now(),
            "mode": (
                "stage"
                if args.apply and args.stage_only
                else "apply"
                if args.apply
                else "dry-run"
            ),
            "status": "blocked",
            "error": f"{type(exc).__name__}: {exc}",
        }
    report = add_alert_contract(report)
    if args.output:
        write_output(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
