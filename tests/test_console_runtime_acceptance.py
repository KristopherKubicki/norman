from __future__ import annotations

import json
import os

from app.services.console_runtime.acceptance import (
    ACCEPTANCE_GATE_SCHEMA,
    acceptance_release_gate,
    latest_acceptance_gate,
)


def _result(target: str, *, passed: bool = True, cloud_tokens: int = 0):
    return {
        "target": target,
        "scenario": "canary",
        "passed": passed,
        "failures": [] if passed else ["visible response did not match"],
        "receipt": {
            "available": True,
            "job_status": "done",
            "kernel_owned_turn": True,
            "selected_worker": "mac-mini-133",
            "observed_worker": "mac-mini-133",
            "observed_worker_source": "gateway_response",
            "execution_mode": "live",
            "output_shape": "complete",
            "local_tokens": 42,
            "cloud_proxy": False,
            "receipt_audit": {"status": "pass", "pass": True, "failures": []},
            "completion_gate": {"status": "pass", "gate_passed": True},
            "goal_cloud_tokens": cloud_tokens,
            "ledger_cloud_tokens": cloud_tokens,
            "local_first_status": "on_target",
            "model_completed_count": 1,
        },
    }


def _report(*results, generated_at=1000):
    return {
        "schema": "norman.tui-kernel-acceptance.v1",
        "run_id": "acceptance-test",
        "generated_at": generated_at,
        "passed": all(item["passed"] for item in results),
        "pass_count": sum(1 for item in results if item["passed"]),
        "total_count": len(results),
        "results": list(results),
    }


def test_acceptance_release_gate_passes_complete_local_first_report():
    targets = ["norman", "housebot"]
    gate = acceptance_release_gate(
        _report(*[_result(target) for target in targets], generated_at=900),
        now=1000,
        required_targets=targets,
        max_age_seconds=3600,
        path="tmp/tuiacc-test.json",
    )

    assert gate["schema"] == ACCEPTANCE_GATE_SCHEMA
    assert gate["status"] == "pass"
    assert gate["passed"] is True
    assert gate["pass_percent"] == 100.0
    assert gate["release_gate"] == {
        "all_required_targets_present": True,
        "all_results_passed": True,
        "receipts_complete": True,
        "worker_attribution_complete": True,
        "observed_worker_proof": True,
        "live_execution": True,
        "complete_output_shape": True,
        "positive_local_tokens": True,
        "receipt_audit_passed": True,
        "completion_gate_passed": True,
        "no_cloud_proxy": True,
        "zero_cloud_tokens": True,
        "local_first_on_target": True,
        "model_completion_visible": True,
        "fresh": True,
    }


def test_acceptance_release_gate_fails_stale_partial_cloud_report():
    gate = acceptance_release_gate(
        _report(_result("norman", cloud_tokens=4), generated_at=1),
        now=5000,
        required_targets=["norman", "housebot"],
        max_age_seconds=60,
    )

    assert gate["status"] == "stale"
    assert gate["passed"] is False
    assert gate["missing_targets"] == ["housebot"]
    assert gate["release_gate"]["zero_cloud_tokens"] is False
    assert any("cloud/proxy tokens present" in item for item in gate["failures"])
    assert any("report is stale" in item for item in gate["failures"])


def test_acceptance_release_gate_fails_without_live_route_proof():
    weak = _result("norman")
    weak["receipt"] = {
        "available": True,
        "job_status": "done",
        "kernel_owned_turn": True,
        "selected_worker": "spark-151",
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "local_first_status": "on_target",
        "model_completed_count": 1,
    }

    gate = acceptance_release_gate(
        _report(weak, generated_at=900),
        now=1000,
        required_targets=["norman"],
        max_age_seconds=3600,
    )

    assert gate["status"] == "fail"
    assert gate["passed"] is False
    assert gate["release_gate"]["observed_worker_proof"] is False
    assert gate["release_gate"]["live_execution"] is False
    assert gate["release_gate"]["complete_output_shape"] is False
    assert gate["release_gate"]["positive_local_tokens"] is False
    assert gate["release_gate"]["receipt_audit_passed"] is False
    assert gate["release_gate"]["completion_gate_passed"] is False
    assert any("missing observed worker proof" in item for item in gate["failures"])
    assert any("missing live execution proof" in item for item in gate["failures"])


def test_latest_acceptance_gate_reads_newest_matching_report(tmp_path, monkeypatch):
    older = tmp_path / "tuiacc-old.json"
    newer = tmp_path / "tuiacc-new.json"
    older.write_text(
        json.dumps(_report(_result("norman"), generated_at=1)),
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps(
            _report(
                _result("norman"),
                _result("housebot"),
                generated_at=1000,
            )
        ),
        encoding="utf-8",
    )
    os.utime(older, (100.0, 100.0))
    os.utime(newer, (200.0, 200.0))
    monkeypatch.setattr(
        "app.services.console_runtime.acceptance.settings.tui_acceptance_required_targets",
        ["norman", "housebot"],
    )
    monkeypatch.setattr(
        "app.services.console_runtime.acceptance.settings.tui_acceptance_report_max_age_seconds",
        3600,
    )

    gate = latest_acceptance_gate(
        pattern=str(tmp_path / "tuiacc-*.json"),
        now=1001,
    )

    assert gate["status"] == "pass"
    assert gate["report_path"] == str(newer)
    assert gate["targets"] == ["housebot", "norman"]
