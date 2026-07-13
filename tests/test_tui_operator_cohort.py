from __future__ import annotations

from scripts import tui_operator_cohort as cohort


def _result(
    *,
    passed: bool = True,
    local_tokens: int = 100,
    cloud_tokens: int = 0,
    worker: str = "spark-151",
    audit: bool = True,
    gate: bool = True,
    visible: bool = True,
    route: bool = True,
    cloud_proxy: bool = False,
) -> dict:
    return {
        "target": "norman",
        "scenario": "service_status_json",
        "passed": passed,
        "route_proof_passed": route,
        "visible_delivery_passed": visible,
        "receipt": {
            "goal_local_tokens": local_tokens,
            "goal_cloud_tokens": cloud_tokens,
            "ledger_cloud_tokens": 0,
            "cloud_proxy": cloud_proxy,
            "observed_worker": worker,
            "observed_worker_source": "gateway_response" if worker else "",
            "receipt_audit": {"status": "pass" if audit else "fail"},
            "completion_gate": {"gate_passed": gate},
        },
    }


def test_cohort_scenarios_are_unlocked_auto_routes():
    tasks = cohort.select_tasks("default")
    scenario = cohort.cohort_scenario(tasks[0])

    assert scenario.runtime == "auto"
    assert scenario.model == ""
    assert scenario.route_lock is False
    assert scenario.expected_task_kind == "chat"
    assert scenario.require_exact_ask_job_id is True


def test_build_matrix_limits_turns_across_targets():
    targets = list(cohort.acceptance.default_targets().values())[:2]
    tasks = cohort.select_tasks("default")

    matrix = cohort.build_matrix(targets, tasks, run_id="r1", turn_limit=5)

    assert len(matrix) == 5
    assert {run.scenario.route_lock for _target, run in matrix} == {False}
    assert {run.scenario.runtime for _target, run in matrix} == {"auto"}


def test_cohort_summary_passes_release_thresholds():
    results = [_result() for _ in range(20)]

    summary = cohort.build_summary(results)
    gate = cohort.gate_summary(summary, min_turns=20)

    assert summary["fully_local_rate"] == 1.0
    assert summary["receipt_audit_coverage"] == 1.0
    assert summary["completion_gate_coverage"] == 1.0
    assert summary["observed_worker_coverage"] == 1.0
    assert summary["hidden_cloud_fallback_count"] == 0
    assert summary["cloud_llm_turns_displaced_floor"] == 20
    assert gate["passed"] is True


def test_cohort_gate_rejects_hidden_cloud_and_missing_worker():
    results = [_result() for _ in range(18)]
    results.append(_result(cloud_tokens=50))
    results.append(_result(worker=""))

    summary = cohort.build_summary(results)
    gate = cohort.gate_summary(summary, min_turns=20)

    assert gate["passed"] is False
    assert "observed_worker_coverage" in gate["missing"]
    assert "hidden_cloud_fallback" in gate["missing"]
    assert "cloud_tokens" in gate["missing"]


def test_cohort_gate_rejects_failed_audit_or_completion_gate():
    results = [_result() for _ in range(18)]
    results.append(_result(audit=False))
    results.append(_result(gate=False))

    summary = cohort.build_summary(results)
    gate = cohort.gate_summary(summary, min_turns=20)

    assert gate["passed"] is False
    assert "receipt_audit_coverage" in gate["missing"]
    assert "completion_gate_coverage" in gate["missing"]
