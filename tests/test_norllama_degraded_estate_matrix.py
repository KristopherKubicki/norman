from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_matrix():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "degraded_estate_matrix.py"
    )
    spec = importlib.util.spec_from_file_location("degraded_estate_matrix", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_drill():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "degraded_estate_drill_evidence.py"
    )
    spec = importlib.util.spec_from_file_location(
        "degraded_estate_drill_evidence", script
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def snapshots_fixture() -> dict:
    route_policy = {
        "allow_cloud_proxy": False,
        "allow_cloud_tool_proxy": False,
        "escalation_policy": "explicit_cloud_only",
        "cloud_policy": {"cloud_proxy_counts_as_cloud": True},
        "capability_gates": {"unproven_allows_manual_or_lab_only": True},
        "benchmark_gates": {
            "production_route_requires_capability_gate": True,
            "capability_gate_exemptions": {
                "low_risk_local_text_non_mutating": {
                    "cloud_allowed": False,
                    "mutation_allowed": False,
                }
            },
        },
    }
    return {
        "readyz": {
            "http_status": 200,
            "payload": {
                "policy": {
                    "lifecycle_state": "valid",
                    "integrity_valid": True,
                }
            },
        },
        "warm_policy": {
            "http_status": 200,
            "payload": {
                "route_policy": route_policy,
                "policy_lifecycle": {"state": "valid"},
            },
        },
        "models": {
            "http_status": 200,
            "payload": {
                "data": [
                    {
                        "id": "qwen3.6:27b",
                        "hosts": ["http://192.168.2.151:18151"],
                    },
                    {
                        "id": "qwen3.6:35b-a3b-q4_K_M",
                        "hosts": ["http://192.168.2.151:18151"],
                    },
                    {
                        "id": "paddleocr:PP-OCRv6-small",
                        "hosts": ["http://192.168.2.150:18151"],
                    },
                    {
                        "id": "BAAI/bge-reranker-v2-m3",
                        "hosts": ["http://192.168.2.150:18151"],
                    },
                    {
                        "id": "bge-m3:latest",
                        "hosts": ["http://192.168.2.150:18151"],
                    },
                ]
            },
        },
        "overview": {
            "http_status": 200,
            "payload": {
                "health": {
                    "downstreams": {
                        "ocr": [
                            {
                                "base_url": "http://127.0.0.1:8098",
                                "status": "error",
                            }
                        ]
                    }
                }
            },
        },
    }


def test_degraded_matrix_passes_non_disruptive_scenarios_and_marks_outages_open():
    matrix = load_matrix()

    packet = matrix.evaluate_matrix(snapshots_fixture())

    by_id = {item["scenario_id"]: item for item in packet["scenarios"]}
    assert by_id["all_nodes_healthy"]["status"] == "pass"
    assert by_id["cloud_llm_disabled"]["status"] == "pass"
    assert by_id["capability_packet_unproven"]["status"] == "pass"
    assert by_id["specialist_service_unavailable"]["status"] == "pass"
    assert by_id["spark_151_unavailable"]["status"] == "not_exercised"
    assert packet["passed"] is False
    assert "spark_151_unavailable" in packet["release_gate"]["not_exercised"]


def test_degraded_matrix_accepts_external_outage_evidence():
    matrix = load_matrix()
    drill = load_drill()
    receipt = drill.base_receipt(
        policy=drill.active_policy(),
        request_id="test:spark-151-unavailable",
        task_kind="chat",
        model="qwen3.6:27b",
        target_worker="spark-151",
        observed_worker="spark-150",
        fallback_reason="test fallback",
    )
    external = {
        "scenarios": {
            "spark_151_unavailable": {
                "status": "pass",
                "summary": "spark-151 isolated; gateway failed over honestly",
                "evidence": {
                    "evidence_kind": "test_route_receipt_drill",
                    "captured_at": "2026-07-13T00:00:00Z",
                    "non_disruptive_drill": True,
                    "hidden_cloud_fallback": False,
                    "cloud_proxy_counted_as_local": False,
                    "route_receipt": receipt,
                },
            }
        }
    }

    packet = matrix.evaluate_matrix(snapshots_fixture(), external_evidence=external)

    by_id = {item["scenario_id"]: item for item in packet["scenarios"]}
    assert by_id["spark_151_unavailable"]["status"] == "pass"
    assert (
        by_id["spark_151_unavailable"]["evidence"]["route_receipt"]["fallback_used"]
        is True
    )


def test_degraded_matrix_rejects_unvalidated_external_pass_evidence():
    matrix = load_matrix()
    external = {
        "scenarios": {
            "spark_151_unavailable": {
                "status": "pass",
                "summary": "trust me",
                "evidence": {"fallback_used": True},
            }
        }
    }

    packet = matrix.evaluate_matrix(snapshots_fixture(), external_evidence=external)

    by_id = {item["scenario_id"]: item for item in packet["scenarios"]}
    assert by_id["spark_151_unavailable"]["status"] == "fail"
    assert "route_receipt_missing" in by_id["spark_151_unavailable"]["failures"]


def test_degraded_matrix_accepts_generated_drill_evidence():
    matrix = load_matrix()
    drill = load_drill()

    packet = matrix.evaluate_matrix(
        snapshots_fixture(),
        external_evidence=drill.build_packet(),
    )

    by_id = {item["scenario_id"]: item for item in packet["scenarios"]}
    assert packet["passed"] is True
    assert packet["not_exercised_count"] == 0
    assert by_id["worker_substitution"]["evidence"]["route_receipt_audit"]["pass"]
    assert by_id["policy_refresh_failure"]["status"] == "pass"


def test_degraded_matrix_fails_hidden_cloud_policy():
    matrix = load_matrix()
    snapshots = snapshots_fixture()
    snapshots["warm_policy"]["payload"]["route_policy"]["allow_cloud_proxy"] = True

    packet = matrix.evaluate_matrix(snapshots)

    by_id = {item["scenario_id"]: item for item in packet["scenarios"]}
    assert by_id["cloud_llm_disabled"]["status"] == "fail"
    assert "allow_cloud_proxy_not_false" in by_id["cloud_llm_disabled"]["failures"]
    assert packet["release_gate"]["failed"] == ["cloud_llm_disabled"]
