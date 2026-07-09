from __future__ import annotations

from scripts import tui_kernel_acceptance as acceptance


def test_form_payload_uses_locked_local_llm_route():
    target = acceptance.default_targets()["norman"]
    scenario = acceptance.default_scenarios()["canary"]
    run = acceptance.materialize_scenario(scenario, target, run_id="r1")

    payload = acceptance.form_payload(run)

    assert payload["runtime"] == "localllm"
    assert payload["model"] == "gemma3:1b"
    assert payload["route_lock"] == "1"
    assert payload["job_budget"] == "2m"
    assert run.expected_response == "DONE local visible r1-norman-canary"


def test_select_scenarios_all_includes_deeper_smokes():
    scenarios = acceptance.select_scenarios("all")

    names = {scenario.name for scenario in scenarios}
    assert {
        "canary",
        "route_receipt",
        "workspace_preflight",
        "specialist_visibility",
    }.issubset(names)


def test_select_targets_rejects_unknown_names():
    try:
        acceptance.select_targets("norman,missing")
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("unknown target should fail")


def test_runtime_api_url_normalizes_api_bases():
    assert (
        acceptance._runtime_api_url(
            "https://norman.home.arpa/api/v1", "/console-runtime/jobs/j1"
        )
        == "https://norman.home.arpa/api/v1/console-runtime/jobs/j1"
    )
    assert (
        acceptance._runtime_api_url(
            "https://norman.home.arpa/api", "/console-runtime/jobs/j1"
        )
        == "https://norman.home.arpa/api/v1/console-runtime/jobs/j1"
    )
    assert (
        acceptance._runtime_api_url(
            "https://norman.home.arpa", "/console-runtime/jobs/j1"
        )
        == "https://norman.home.arpa/api/v1/console-runtime/jobs/j1"
    )


def test_receipt_from_activity_snapshot_maps_route_summary():
    snapshot = {
        "job": {
            "job_id": "turn-test",
            "status": "done",
            "last_error": "",
            "metadata": {"kernel_owned_turn": True, "task_kind": "literal_response"},
            "contract": {
                "route_policy": {},
                "authority_flags": {},
                "metadata": {},
            },
        },
        "route_summary": {
            "usage_ledger": {
                "offline_tokens": 12,
                "cloud_llm_tokens": 0,
                "cloud_proxy_tokens": 0,
                "other_cloud_tokens": 0,
                "by_provider": {"norllama": 12},
            },
            "local_first_kpi": {
                "offline_tokens": 12,
                "cloud_llm_tokens": 0,
                "status": "on_target",
                "readiness_percent": 100,
            },
            "model": {"completed": 1, "latest": {"model": "gemma3:1b"}},
            "planner": {"latest": {}},
            "route": {"latest": {}},
            "workers": {"by_id": {"spark-150": 1}},
            "spark_evidence_count": 1,
        },
        "events": [
            {
                "event_type": "model.completed",
                "category": "model",
                "payload": {
                    "route_receipt": {
                        "selected_model": "gemma3:1b",
                        "selected_worker": "spark-150",
                    }
                },
            }
        ],
    }

    receipt = acceptance._receipt_from_activity_snapshot("turn-test", snapshot)

    assert receipt["available"] is True
    assert receipt["job_status"] == "done"
    assert receipt["kernel_owned_turn"] is True
    assert receipt["task_kind"] == "literal_response"
    assert receipt["selected_worker"] == "spark-150"
    assert receipt["goal_local_tokens"] == 12
    assert receipt["ledger_cloud_tokens"] == 0
    assert receipt["local_first_status"] == "on_target"


def test_event_worker_id_prefers_norllama_model_attribution():
    payload = {
        "worker_id": "kernel-worker",
        "attribution": {
            "worker_id": "mac-mini-133",
            "worker_endpoint": "http://192.168.2.133:18151",
        },
        "metadata": {
            "norllama_receipt": {
                "metadata": {
                    "route_receipt": {
                        "selected_worker": "spark-150",
                    }
                }
            }
        },
    }

    assert acceptance._event_worker_id(payload) == "spark-150"


def test_validate_acceptance_passes_complete_local_receipt():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r2",
    )
    job_id = "turn-norman-test"
    probe = {
        "ok": True,
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "gemma3:1b",
        "selected_worker": "mac-mini-133",
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
    }

    passed, failures, proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is True
    assert failures == []
    assert proof["receipt"]["selected_worker"] == "mac-mini-133"


def test_validate_acceptance_rejects_cloud_tokens_and_missing_worker():
    target = acceptance.default_targets()["norman"]
    run = acceptance.materialize_scenario(
        acceptance.default_scenarios()["canary"],
        target,
        run_id="r3",
    )
    job_id = "turn-norman-test"
    probe = {
        "ok": True,
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "gemma3:1b",
        "selected_worker": "",
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 2,
        "ledger_cloud_tokens": 2,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "watch",
        "model_completed_count": 1,
    }

    passed, failures, _proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is False
    assert "receipt recorded cloud LLM tokens" in failures
    assert "usage ledger recorded cloud/proxy tokens" in failures
    assert "receipt did not record worker attribution" in failures
    assert "local-first KPI is watch" in failures


def test_validate_acceptance_can_require_spark_evidence():
    target = acceptance.default_targets()["norman"]
    scenario = acceptance.AcceptanceScenario(
        name="spark_required",
        message_template="Reply exactly: {expected_response}",
        expected_template="DONE spark {nonce}",
        min_spark_evidence_count=1,
    )
    run = acceptance.materialize_scenario(scenario, target, run_id="r4")
    job_id = "turn-norman-spark-test"
    probe = {
        "ok": True,
        "status": {
            "pending": False,
            "last_prompt": run.message,
            "last_response": run.expected_response,
            "last_error": "",
            "last_console_runtime_job_id": job_id,
        },
    }
    receipt = {
        "available": True,
        "job_id": job_id,
        "job_status": "done",
        "last_error": "",
        "kernel_owned_turn": True,
        "task_kind": "literal_response",
        "selected_model": "gemma3:1b",
        "selected_worker": "mac-mini-133",
        "goal_local_tokens": 77,
        "goal_cloud_tokens": 0,
        "ledger_cloud_tokens": 0,
        "ledger_by_provider": {"norllama": 77},
        "local_first_status": "on_target",
        "model_completed_count": 1,
        "spark_evidence_count": 0,
    }

    passed, failures, _proof = acceptance.validate_acceptance(
        target,
        run,
        probe,
        receipt,
    )

    assert passed is False
    assert any("spark evidence count" in failure for failure in failures)
