from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norman_keys_capability_rollout.py"
    )
    spec = importlib.util.spec_from_file_location(
        "norman_keys_capability_rollout", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create_metadata_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            create table keys_host_enrollments (
                id integer primary key, host_id text, hostname text, status text,
                capability_names json
            );
            create table keys_capabilities (
                id integer primary key, name text, enabled boolean, executor_kind text
            );
            create table keys_capability_policies (
                id integer primary key, capability_id integer, enabled boolean
            );
            """
        )


def test_rollout_report_requires_all_estate_hosts(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "keys.db"
    _create_metadata_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "insert into keys_host_enrollments values (1, 'hal', 'hal.home.arpa', 'active', ?)",
            (json.dumps(["network.inspect"]),),
        )
        db.execute(
            "insert into keys_capabilities values (1, 'network.inspect', 1, 'receipt')"
        )
        db.execute("insert into keys_capability_policies values (1, 1, 1)")

    report = module.build_rollout_report(db_path)

    assert report["ready"] is False
    assert report["summary"]["status"] == "incomplete"
    assert report["hosts"][0]["ready"] is True
    assert {item["host_id"] for item in report["hosts"] if not item["ready"]} == {
        "norman",
        "netops",
    }
    assert "networking/firewall" not in json.dumps(report)


def test_rollout_report_marks_all_hosts_ready_with_enabled_bindings(
    tmp_path: Path,
) -> None:
    module = _load_module()
    db_path = tmp_path / "keys.db"
    _create_metadata_db(db_path)
    with sqlite3.connect(db_path) as db:
        for index, host in enumerate(("hal", "norman", "netops"), start=1):
            db.execute(
                "insert into keys_host_enrollments values (?, ?, ?, 'active', ?)",
                (index, host, f"{host}.home.arpa", json.dumps(["estate.receipt"])),
            )
        db.execute(
            "insert into keys_capabilities values (1, 'estate.receipt', 1, 'receipt')"
        )
        db.execute("insert into keys_capability_policies values (1, 1, 1)")

    report = module.build_rollout_report(db_path)

    assert report["ready"] is True
    assert report["summary"]["ready_hosts"] == 3
    assert all(item["ready"] for item in report["hosts"])
