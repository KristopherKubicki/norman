from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_adapter():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "scout_resource_meter_adapter.py"
    )
    spec = importlib.util.spec_from_file_location(
        "scout_resource_meter_adapter", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scout_resource_meter_builds_queue_and_kpi_counts() -> None:
    module = _load_adapter()
    now_ts = module.parse_timestamp("2026-05-09T04:00:00Z")
    agent_requests = {
        "requests": [
            {"status": "accepted", "created_at": "2026-05-09T01:00:00Z"},
            {"status": "accepted", "created_at": "2026-05-09T02:00:00Z"},
            {"status": "running", "started_at": "2026-05-09T03:30:00Z"},
            {"status": "done", "updated_at": "2026-05-09T03:45:00Z"},
        ]
    }
    pp_status = {
        "queued": 73,
        "blocked": 84,
        "captured": 2,
        "submitted": 0,
    }
    monitor = {"warnings": ["pp_job_not_captured"]}

    meter = module.build_resource_meter(
        agent_requests=agent_requests,
        pp_status=pp_status,
        monitor=monitor,
        generated_at="2026-05-09T04:00:00Z",
        now_ts=now_ts,
        sources=["agent_requests_latest.json", "pp_mining_status", "scout_monitor"],
    )

    assert meter["version"] == "norman.queue-resource-meter.v1"
    assert meter["read_only"] is True
    assert meter["tone"] == "danger"
    assert meter["domain"]["accepted"] == 2
    assert meter["domain"]["queued"] == 73
    assert meter["domain"]["done"] == 1
    assert meter["domain"]["backlog"] == 75
    assert meter["executor"]["running"] == 1
    assert meter["executor"]["blocked"] == 84
    assert meter["executor"]["captured"] == 2
    assert meter["warnings"] == ["pp_job_not_captured"]
    assert [item["id"] for item in meter["kpi_meters"]] == [
        "scout_accepted",
        "pp_queued",
        "pp_blocked",
        "scout_oldest",
    ]
    assert meter["kpi_meters"][2]["tone"] == "danger"
    assert meter["kpi_meters"][3]["value"] == "3h"
    assert meter["kpi_meters"][3]["tone"] == "warn"


def test_scout_resource_meter_cli_writes_payload(tmp_path: Path) -> None:
    module = _load_adapter()
    agent_requests = tmp_path / "agent_requests_latest.json"
    pp_status = tmp_path / "pp_mining_status.json"
    output = tmp_path / "resource_meter.json"
    agent_requests.write_text(
        json.dumps({"accepted": 10, "queued": 0, "running": 0, "done": 1}),
        encoding="utf-8",
    )
    pp_status.write_text(
        json.dumps({"queued": 73, "blocked": 84, "captured": 2, "submitted": 0}),
        encoding="utf-8",
    )

    assert (
        module.main(
            [
                "--agent-requests",
                str(agent_requests),
                "--pp-status",
                str(pp_status),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["domain"]["accepted"] == 10
    assert payload["domain"]["queued"] == 73
    assert payload["executor"]["blocked"] == 84
    assert len(payload["kpi_meters"]) == 3
