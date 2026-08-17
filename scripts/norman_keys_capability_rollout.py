#!/usr/bin/env python3
"""Report Norman Keys capability-delivery readiness without touching secrets.

The checker reads only Norman Keys metadata tables.  It never resolves an alias,
loads a secret provider, inspects an environment value, or invokes a broker.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "norman.db"
REQUIRED_HOSTS = ("hal", "norman", "netops")


def _rows(db: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    db.row_factory = sqlite3.Row
    return [dict(row) for row in db.execute(query)]


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _required_tables_present(db: sqlite3.Connection) -> bool:
    expected = {
        "keys_host_enrollments",
        "keys_capabilities",
        "keys_capability_policies",
    }
    tables = {
        str(row[0])
        for row in db.execute("select name from sqlite_master where type='table'")
    }
    return expected.issubset(tables)


def build_rollout_report(
    db_path: Path, *, required_hosts: tuple[str, ...] = REQUIRED_HOSTS
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "norman.keys.capability-rollout.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "db_path": str(db_path),
        "required_hosts": list(required_hosts),
        "hosts": [],
        "summary": {},
        "ready": False,
        "notes": [
            "Metadata-only report: no secret aliases are resolved or revealed.",
            "An enabled receipt executor proves enrollment/policy flow only; install an approved server-side executor before a privileged side effect.",
        ],
    }
    if not db_path.exists():
        report["summary"] = {"status": "missing_database", "ready_hosts": 0}
        return report
    with sqlite3.connect(db_path) as db:
        if not _required_tables_present(db):
            report["summary"] = {"status": "migration_required", "ready_hosts": 0}
            return report
        enrollments = {
            str(row["host_id"]): row
            for row in _rows(db, "select * from keys_host_enrollments order by host_id")
        }
        capabilities = {
            str(row["name"]): row
            for row in _rows(db, "select * from keys_capabilities order by name")
        }
        policies = _rows(db, "select * from keys_capability_policies order by id")

    ready_hosts = 0
    for host_id in required_hosts:
        enrollment = enrollments.get(host_id)
        row: dict[str, Any] = {
            "host_id": host_id,
            "enrolled": bool(enrollment),
            "status": str(enrollment.get("status") if enrollment else "missing"),
            "hostname": str(enrollment.get("hostname") if enrollment else ""),
            "capabilities": [],
            "issues": [],
        }
        if not enrollment:
            row["issues"].append("host enrollment is missing")
        elif str(enrollment.get("status")) != "active":
            row["issues"].append("host enrollment is not active")
        for name in _json_list(
            enrollment.get("capability_names") if enrollment else "[]"
        ):
            capability = capabilities.get(name)
            active_policies = (
                [
                    policy
                    for policy in policies
                    if int(policy["capability_id"]) == int(capability["id"])
                    and bool(policy["enabled"])
                ]
                if capability
                else []
            )
            state = {
                "name": name,
                "enabled": bool(capability and capability["enabled"]),
                "executor_kind": str(capability["executor_kind"]) if capability else "",
                "policy_count": len(active_policies),
                "ready": bool(capability and capability["enabled"] and active_policies),
            }
            row["capabilities"].append(state)
            if not state["ready"]:
                row["issues"].append(
                    f"capability {name} lacks enabled binding or policy"
                )
        if enrollment and not row["capabilities"]:
            row["issues"].append("no capability names are enrolled")
        row["ready"] = not row["issues"]
        ready_hosts += int(row["ready"])
        report["hosts"].append(row)
    report["summary"] = {
        "status": "ready" if ready_hosts == len(required_hosts) else "incomplete",
        "ready_hosts": ready_hosts,
        "required_host_count": len(required_hosts),
        "capability_count": len(capabilities),
        "enabled_capability_count": sum(
            bool(row["enabled"]) for row in capabilities.values()
        ),
    }
    report["ready"] = ready_hosts == len(required_hosts)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--required-host", action="append", default=[])
    args = parser.parse_args(argv)
    hosts = tuple(args.required_host) if args.required_host else REQUIRED_HOSTS
    report = build_rollout_report(args.db, required_hosts=hosts)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
