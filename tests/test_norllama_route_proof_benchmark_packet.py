import importlib.util
import base64
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


def test_ocr_smoke_fixture_is_valid_png():
    module = load_module()

    image = base64.b64decode(module.OCR_SMOKE_PNG_BASE64)

    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_worker_from_route_uses_gateway_headers():
    module = load_module()

    worker, upstream = module.worker_from_route(
        {},
        {"x-norllama-upstream": "http://192.168.2.150:18151"},
    )

    assert worker == "spark-150"
    assert upstream == "http://192.168.2.150:18151"

    worker, upstream = module.worker_from_route(
        {"selected_worker": "spark150", "upstream": "http://192.168.2.150:18151"},
        {},
    )

    assert worker == "spark-150"
    assert upstream == "http://192.168.2.150:18151"


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


def test_tool_row_keeps_failed_specialist_probe_out_of_benchmark_backing():
    module = load_module()

    row = module.tool_row(
        lane_id="ocr",
        model="paddleocr:PP-OCRv6-small",
        profile="paddleocr_small_route_proof",
        use_for="local OCR",
        guardrail="Verify extracted facts.",
        capability_class="ocr",
        accepted=False,
        elapsed_ms=220,
        headers={"x-norllama-upstream": "http://192.168.2.150:18151"},
        output_shape="empty",
        input_tokens=1,
        total_tokens=1,
    )

    assert row["benchmark_status"] == "failed"
    assert row["observed_worker"] == "spark-150"
    assert row["accepted_count"] == 0
    assert row["empty_response_rate"] == 1
    assert row["verifier_rejection_rate"] == 1
    assert row["output_shape_valid"] is False
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
    rows.append(
        module.tool_row(
            lane_id="embedding",
            model="bge-m3:latest",
            profile="bge_m3_embedding_route_proof",
            use_for="local text memory embeddings",
            guardrail="Use for retrieval only.",
            capability_class="embed",
            accepted=True,
            elapsed_ms=55,
            headers={"x-norllama-upstream": "http://192.168.2.150:18151"},
            input_tokens=4,
            total_tokens=4,
        )
    )
    rows.append(
        module.tool_row(
            lane_id="rerank",
            model="BAAI/bge-reranker-v2-m3",
            profile="bge_reranker_cross_encoder_route_proof",
            use_for="local evidence reranking",
            guardrail="Use as an ordering signal.",
            capability_class="rerank",
            accepted=True,
            elapsed_ms=80,
            headers={"x-norllama-upstream": "http://192.168.2.150:18151"},
            input_tokens=3,
            total_tokens=3,
        )
    )
    rows.append(
        module.tool_row(
            lane_id="safety",
            model="Qwen/Qwen3Guard-Stream-0.6B",
            profile="qwen3guard_stream_route_proof",
            use_for="local safety classification",
            guardrail="Use as a preflight classifier.",
            capability_class="safety",
            accepted=True,
            elapsed_ms=90,
            headers={"x-norllama-upstream": "http://192.168.2.150:18151"},
            input_tokens=6,
            total_tokens=6,
        )
    )
    rows.append(
        module.tool_row(
            lane_id="ocr",
            model="paddleocr:PP-OCRv6-small",
            profile="paddleocr_small_route_proof",
            use_for="local OCR",
            guardrail="Verify extracted facts.",
            capability_class="ocr",
            accepted=True,
            elapsed_ms=140,
            headers={"x-norllama-upstream": "http://192.168.2.150:18151"},
            input_tokens=1,
            total_tokens=1,
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
    assert packet["aggregate"]["accepted_count"] == 6
    assert len(packet["shareable_view"]["recommended_roles"]) == 6
    contracts = {row["contract_id"]: row for row in packet["capability_contracts"]}
    assert contracts["chat"]["default_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert contracts["code_risk"]["default_model"] == "qwen3.6:27b"
    assert contracts["embed"]["dispatch"] == "embedding_proxy"
    assert contracts["rerank"]["dispatch"] == "rerank_proxy"
    assert contracts["safety_privacy_classify"]["dispatch"] == "safety_proxy"
    assert contracts["doc_parse"]["dispatch"] == "ocr_proxy"
