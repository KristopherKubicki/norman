import importlib.util
import sys
from pathlib import Path


def load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "route_proof_benchmark_packet.py"
    )
    spec = importlib.util.spec_from_file_location(
        "route_proof_benchmark_packet", script
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_worker_from_url_maps_spark_hosts():
    module = load_module()

    assert module.worker_from_url("http://192.168.2.150:18151") == "spark-150"
    assert module.worker_from_url("http://192.168.2.151:18151") == "spark-151"
    assert module.worker_from_url("http://192.168.2.133:18151") == "mac-mini-133"


def test_row_from_probe_records_worker_tokens_and_quality_gates():
    module = load_module()
    spec = module.CHAT_PROBES[0]
    payload = {
        "model": spec.model,
        "choices": [
            {"message": {"content": f"{spec.expected}\n"}},
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
        },
        "norllama": {
            "upstream": "http://192.168.2.151:18151",
            "output_shape": "complete",
        },
    }

    row = module.row_from_probe(spec=spec, payload=payload, elapsed_ms=900)

    assert row["status"] == "benchmark_backed"
    assert row["target_worker"] == "spark-151"
    assert row["accepted_count"] == 1
    assert row["timeout_rate"] == 0
    assert row["empty_response_rate"] == 0
    assert row["zero_token_rate"] == 0
    assert row["progress_only_rate"] == 0
    assert row["output_shape_valid"] is True
    assert row["usage_bucket"] == "offline_local"


def test_build_packet_includes_shareable_roles_and_contracts():
    module = load_module()
    rows = []
    for spec in module.CHAT_PROBES[:2]:
        rows.append(
            module.row_from_probe(
                spec=spec,
                payload={
                    "model": spec.model,
                    "choices": [{"message": {"content": spec.expected}}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 5},
                    "norllama": {
                        "upstream": "http://192.168.2.151:18151",
                        "output_shape": "complete",
                    },
                },
                elapsed_ms=1100,
            )
        )

    packet = module.build_packet(
        rows=rows,
        frontdoor="https://llm.home.arpa",
        generated_at="2026-07-09T14:00:00Z",
        packet_id="uplink-test",
    )

    assert packet["schema"] == module.SCHEMA
    assert packet["packet_id"] == "uplink-test"
    assert packet["aggregate"]["accepted_count"] == 2
    assert len(packet["shareable_view"]["recommended_roles"]) == 2
    contracts = {row["contract_id"]: row for row in packet["capability_contracts"]}
    assert contracts["chat"]["default_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert contracts["code_risk"]["default_model"] == "qwen3.6:27b"
