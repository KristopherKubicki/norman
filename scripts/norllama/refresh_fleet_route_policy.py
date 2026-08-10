#!/usr/bin/env python3
"""Atomically refresh one validated Norllama route policy across the fleet."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
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


TARGETS = (
    {
        "name": "spark-150",
        "ssh": "kristopher@192.168.2.150",
        "identity_file": "/home/kristopher/.ssh/id_ed25519_netops_codex",
        "policy_path": "/home/kristopher/norllama/route_policy.json",
        "url": "http://192.168.2.150:18151",
    },
    {
        "name": "spark-151",
        "ssh": "kristopher@192.168.2.151",
        "identity_file": "/home/kristopher/.ssh/id_ed25519_netops_codex",
        "policy_path": "/home/kristopher/norllama/route_policy.json",
        "url": "http://192.168.2.151:18151",
    },
    {
        "name": "mac-mini",
        "ssh": "k@192.168.2.133",
        "identity_file": "/home/kristopher/.ssh/id_ed25519_macmini_codex",
        "policy_path": "/Users/k/norllama/route_policy.json",
        "url": "http://192.168.2.133:18151",
    },
)
ENDPOINTS = ("/healthz", "/readyz", "/asr-readyz", "/v1/models")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def write_output(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def add_alert_contract(report: dict[str, Any]) -> dict[str, Any]:
    targets = report.get("targets") if isinstance(report.get("targets"), list) else []
    expected = len(targets)
    if not expected:
        preflight = report.get("preflight")
        expected = len(preflight) if isinstance(preflight, list) else len(TARGETS)
    active = sum(
        isinstance(target, dict) and target.get("status") == "active"
        for target in targets
    )
    failed = report.get("status") != "ok"
    report["summary"] = {
        "active": active if report.get("mode") == "apply" else expected,
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


def remote(target: dict[str, str], command: str, *, input_text: str = "") -> subprocess.CompletedProcess[str]:
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


def copy_to_remote(path: Path, target: dict[str, str], destination: str) -> subprocess.CompletedProcess[str]:
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


def remote_validate(target: dict[str, str], path: str, policy_id: str) -> tuple[bool, str]:
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


def promote(target: dict[str, str], live: str, pending: str, backup: str) -> tuple[bool, str]:
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


def rollback(target: dict[str, str], live: str, backup: str) -> None:
    remote(target, "sh -s -- " + " ".join([live, backup]), input_text="""\
set -eu
live=$1
backup=$2
test -s "$backup"
mv "$backup" "$live"
""")


def cleanup(target: dict[str, str], *paths: str) -> None:
    remote(target, "rm -f -- " + " ".join(paths))


def verify_live(target: dict[str, str], policy_id: str) -> tuple[bool, str]:
    for endpoint in ENDPOINTS:
        status, payload = http_json(f"{target['url']}{endpoint}")
        if status != 200:
            return False, f"{endpoint} returned {status}"
        if endpoint == "/readyz":
            policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
            if policy.get("policy_id") != policy_id or not payload.get("ready"):
                return False, "readyz did not report the promoted eligible policy"
    return True, ""


def select_targets(names: Sequence[str] | None) -> tuple[dict[str, str], ...]:
    requested = set(names or ())
    return tuple(item for item in TARGETS if not requested or item["name"] in requested)


def refresh(*, targets: Sequence[dict[str, str]], apply: bool) -> dict[str, Any]:
    generations: list[int] = []
    preflight: list[dict[str, Any]] = []
    for target in targets:
        status, payload = http_json(f"{target['url']}/readyz")
        policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        generation = policy.get("refresh_generation")
        healthy = status == 200 and bool(payload.get("ready")) and isinstance(generation, int)
        preflight.append({"name": target["name"], "ready": healthy, "status": status})
        if healthy:
            generations.append(generation)
    generation = max(generations, default=0) + 1
    policy = generate_route_policy_artifact(generation=generation)
    validation = validate_route_policy_artifact(policy)
    report: dict[str, Any] = {
        "schema": "norman.norllama.fleet-policy-refresh.v1",
        "checked_at": utc_now(),
        "mode": "apply" if apply else "dry-run",
        "policy_id": policy["policy_id"],
        "refresh_generation": generation,
        "validation": validation,
        "preflight": preflight,
        "targets": [],
        "status": "blocked",
    }
    if not validation.get("production_route_eligible") or not all(item["ready"] for item in preflight):
        report["error"] = "policy validation or worker readiness preflight failed"
        return report
    if not apply:
        report["status"] = "ok"
        report["targets"] = [{"name": item["name"], "status": "planned"} for item in targets]
        return report

    operation = uuid.uuid4().hex
    promoted: list[tuple[dict[str, str], str]] = []
    with tempfile.TemporaryDirectory(prefix="norllama-fleet-policy-") as temporary:
        local_policy = Path(temporary) / "route_policy.json"
        write_route_policy_artifact(policy, local_policy)
        for target in targets:
            live = target["policy_path"]
            pending = f"{live}.fleet-incoming-{operation}"
            backup = f"{live}.fleet-previous-{operation}"
            copied = copy_to_remote(local_policy, target, pending)
            valid, detail = remote_validate(target, pending, policy["policy_id"])
            if copied.returncode or not valid:
                cleanup(target, pending)
                report["error"] = f"{target['name']} staging failed: {copied.stderr or detail}"
                break
            report["targets"].append({"name": target["name"], "status": "staged"})
        else:
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
                    {"name": item["name"], "status": "active" if item["name"] == target["name"] else item["status"]}
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
    parser.add_argument("--apply", action="store_true", help="Promote the generated policy.")
    parser.add_argument("--target", action="append", choices=[item["name"] for item in TARGETS])
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = refresh(targets=select_targets(args.target), apply=args.apply)
    except Exception as exc:
        report = {
            "schema": "norman.norllama.fleet-policy-refresh.v1",
            "checked_at": utc_now(),
            "mode": "apply" if args.apply else "dry-run",
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
