import importlib.util
import base64
import json
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

    assert row["status"] == "smoke_backed"
    assert row["target_worker"] == "spark-151"
    assert row["accepted_count"] == 1
    assert row["cold_sample_count"] == 0
    assert row["warm_sample_count"] == 1
    assert row["benchmark_gate"]["gate"] == "smoke"
    assert row["promotion_authoritative"] is False
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
    assert packet["source"] == {
        "kind": "live_route_proof_probe",
        "frontdoor": "https://llm.home.arpa",
        "selection_method": "uplink_route_proof_live_probe",
        "transport_generated_at": "2026-07-09T14:00:00Z",
        "capability_schema_generated_at": "2026-07-09T14:00:00Z",
        "generated_at_is_transport_freshness_authority": False,
        "transport_freshness_field": "source.transport_generated_at",
    }
    assert packet["aggregate"]["accepted_count"] == 6
    assert len(packet["shareable_view"]["recommended_roles"]) == 6
    contracts = {row["contract_id"]: row for row in packet["capability_contracts"]}
    assert contracts["chat"]["default_model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert contracts["chat"]["status"] == "smoke_backed"
    assert contracts["chat"]["benchmark_confidence"] == "smoke"
    assert contracts["chat"]["transport_gate"]["gate"] == "smoke"
    assert contracts["chat"]["benchmark_gate"]["gate"] == "smoke"
    assert contracts["chat"]["capability_suite_id"] == "planner_router"
    assert contracts["chat"]["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "source": "capability_suite_cases_defined_unproven",
    }
    assert contracts["chat"]["production_route_requires_capability_gate"] is True
    assert contracts["chat"]["capability_promotion_authoritative"] is False
    assert contracts["chat"]["promotion_authoritative"] is False
    assert contracts["chat"]["coverage_ratio"] == 1.0
    assert contracts["code_risk"]["default_model"] == "qwen3.6:27b"
    assert contracts["code_risk"]["capability_suite_id"] == "coder"
    assert contracts["embed"]["dispatch"] == "embedding_proxy"
    assert contracts["embed"]["capability_suite_id"] == "reranker"
    assert contracts["rerank"]["dispatch"] == "rerank_proxy"
    assert contracts["rerank"]["capability_suite_id"] == "reranker"
    assert contracts["safety_privacy_classify"]["dispatch"] == "safety_proxy"
    assert contracts["safety_privacy_classify"]["capability_suite_id"] == "safety"
    assert contracts["doc_parse"]["dispatch"] == "ocr_proxy"
    assert contracts["doc_parse"]["capability_suite_id"] == "ocr"
    suites = packet["capability_suites"]
    assert suites["planner_router"]["status"] == "cases_defined_unproven"
    assert suites["planner_router"]["capability_gate"]["gate"] == "unproven"
    assert (
        suites["planner_router"]["capability_gate"]["promotion_authoritative"] is False
    )
    assert suites["planner_router"]["suite_version"] == ("2026-07-11.compositional-v1")
    assert len(suites["planner_router"]["suite_hash"]) == 64
    assert len(suites["planner_router"]["cases"][0]["case_hash"]) == 64
    assert suites["planner_router"]["case_count"] >= 30
    assert suites["coder"]["status"] == "cases_defined_unproven"
    assert suites["coder"]["capability_gate"]["gate"] == "unproven"
    assert suites["coder"]["capability_gate"]["promotion_authoritative"] is False
    assert suites["coder"]["case_count"] >= 30
    assert suites["verifier_judge"]["status"] == "cases_defined_unproven"
    assert suites["verifier_judge"]["capability_gate"]["gate"] == "unproven"
    assert (
        suites["verifier_judge"]["capability_gate"]["promotion_authoritative"] is False
    )
    assert suites["verifier_judge"]["case_count"] >= 30
    assert suites["reranker"]["status"] == "cases_defined_unproven"
    assert suites["reranker"]["capability_gate"]["gate"] == "unproven"
    assert suites["reranker"]["capability_gate"]["promotion_authoritative"] is False
    assert 25 <= suites["reranker"]["case_count"] <= 40
    assert suites["safety"]["status"] == "cases_defined_unproven"
    assert suites["safety"]["capability_gate"]["gate"] == "unproven"
    assert suites["safety"]["capability_gate"]["promotion_authoritative"] is False
    assert suites["safety"]["case_count"] == 50
    assert suites["ocr"]["status"] == "cases_defined_unproven"
    assert suites["ocr"]["capability_gate"]["gate"] == "unproven"
    assert suites["ocr"]["capability_gate"]["promotion_authoritative"] is False
    assert suites["ocr"]["case_count"] == 100
    assert suites["asr"]["status"] == "cases_defined_unproven"
    assert suites["asr"]["capability_gate"]["gate"] == "unproven"
    assert suites["asr"]["capability_gate"]["promotion_authoritative"] is False
    assert suites["asr"]["case_count"] == 30
    manifest = packet["capability_execution_manifest"]
    assert manifest["schema"] == module.CAPABILITY_EXECUTION_MANIFEST_SCHEMA
    assert manifest["manifest_id"] == "uplink-test:capability-execution"
    assert manifest["status"] == "criteria_defined_unexecuted"
    assert manifest["promotion_authoritative"] is False
    assert manifest["suite_case_counts"] == {
        "asr": 30,
        "coder": 36,
        "ocr": 100,
        "planner_router": 32,
        "reranker": 30,
        "safety": 50,
        "verifier_judge": 38,
    }
    assert len(manifest["suites"]["ocr"]["suite_hash"]) == 64
    assert len(manifest["suites"]["ocr"]["cases"][0]["case_hash"]) == 64
    assert manifest["suites"]["ocr"]["cases"][0]["case_revision"] == (
        "2026-07-11.compositional-v1"
    )
    assert manifest["total_case_count"] == 316
    assert module.validate_capability_execution_manifest(manifest) == []


def test_build_packet_preserves_derived_transport_provenance():
    module = load_module()
    row = module.row_from_probe(
        spec=module.CHAT_PROBES[0],
        payload={
            "model": module.CHAT_PROBES[0].model,
            "choices": [{"message": {"content": module.CHAT_PROBES[0].expected}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5},
            "norllama": {
                "upstream": "http://192.168.2.151:18151",
                "output_shape": "complete",
            },
        },
        elapsed_ms=1100,
    )

    packet = module.build_packet(
        rows=[row],
        frontdoor="https://llm.home.arpa",
        generated_at="2026-07-11T15:30:52Z",
        packet_id="derived-packet",
        source_kind="derived_capability_overlay",
        parent_packet_id="uplink-route-proof-194fbd9bbfdc",
        parent_packet_sha256="a" * 64,
        transport_generated_at="2026-07-10T13:08:39Z",
    )

    assert packet["source"]["kind"] == "derived_capability_overlay"
    assert packet["source"]["parent_packet_id"] == "uplink-route-proof-194fbd9bbfdc"
    assert packet["source"]["parent_packet_sha256"] == "a" * 64
    assert packet["source"]["transport_generated_at"] == "2026-07-10T13:08:39Z"
    assert packet["source"]["capability_schema_generated_at"] == "2026-07-11T15:30:52Z"
    assert packet["source"]["generated_at_is_transport_freshness_authority"] is False
    assert packet["source"]["transport_freshness_field"] == (
        "source.transport_generated_at"
    )


def test_benchmark_status_requires_distinct_cold_and_warm_for_production():
    module = load_module()

    assert module.benchmark_status_for_counts(1) == "smoke_backed"
    assert module.benchmark_status_for_counts(3) == "staging_backed"
    assert module.benchmark_status_for_counts(5) == "staging_backed"
    assert (
        module.benchmark_status_for_counts(
            5,
            cold_sample_count=1,
            warm_sample_count=1,
        )
        == "production_backed"
    )


def test_capability_execution_manifest_is_runner_ready_but_unproven():
    module = load_module()

    manifest = module.capability_execution_manifest(
        generated_at="2026-07-11T15:00:00Z",
        manifest_id="capability-manifest-test",
    )

    assert manifest["schema"] == module.CAPABILITY_EXECUTION_MANIFEST_SCHEMA
    assert manifest["manifest_id"] == "capability-manifest-test"
    assert manifest["status"] == "criteria_defined_unexecuted"
    assert manifest["promotion_authoritative"] is False
    assert manifest["suite_count"] == 7
    assert manifest["suite_case_counts"]["safety"] == 50
    assert manifest["suite_case_counts"]["ocr"] == 100
    assert manifest["suite_case_counts"]["asr"] == 30
    assert manifest["total_case_count"] == sum(manifest["suite_case_counts"].values())
    assert "observed_worker" in manifest["required_receipt_fields"]
    assert "execution_mode" in manifest["required_receipt_fields"]
    assert "receipt_audit" in manifest["required_receipt_fields"]
    assert "Dry-run, shadow, synthetic" in manifest["promotion_requirements"][1]

    safety_case = manifest["suites"]["safety"]["cases"][3]
    assert safety_case["case_id"] == "safety-004-plaintext-secret-file"
    assert safety_case["prompt"]
    assert safety_case["input_spec"]["prompt"] == safety_case["prompt"]
    assert len(safety_case["input_hash"]) == 64
    assert safety_case["expected_label"] == "secret_request"
    assert safety_case["expected_policy_action"] == "block"
    assert safety_case["required_live_proof"]["execution_mode"] == "live"
    assert safety_case["required_live_proof"]["cloud_proxy"] is False

    ocr_case = manifest["suites"]["ocr"]["cases"][4]
    assert ocr_case["case_id"] == "ocr-005-invoice-adversarial-overlay"
    assert ocr_case["expected_policy_action"] == "extract_ignore_injection"
    assert "prompt_injection" in ocr_case["expected_specialist_lanes"]

    asr_case = manifest["suites"]["asr"]["cases"][2]
    assert asr_case["case_id"] == "asr-003-meeting-notes-long-streaming"
    assert asr_case["expected_route_mode"] == "cloud_llm_offline"
    assert asr_case["cloud_policy"] == "cloud_llm_disabled"

    assert module.validate_capability_execution_manifest(manifest) == []


def test_capability_execution_manifest_validator_rejects_bad_proof():
    module = load_module()

    manifest = module.capability_execution_manifest(manifest_id="bad-proof-test")
    manifest["suites"]["safety"]["cases"][0]["expected_label"] = ""
    manifest["suites"]["asr"]["cases"][0]["required_live_proof"]["execution_mode"] = (
        "shadow"
    )
    manifest["suites"]["ocr"]["suite_hash"] = ""
    manifest["suites"]["reranker"]["cases"][0]["prompt"] = ""
    manifest["promotion_authoritative"] = True

    failures = module.validate_capability_execution_manifest(manifest)

    assert "manifest_must_not_be_promotion_authoritative" in failures
    assert "ocr:missing_suite_hash" in failures
    assert "reranker:reranker-001-basic-text-relevance:missing_prompt" in failures
    assert "safety:safety-001-benign-status-summary:missing_expected_label" in failures
    assert (
        "asr:asr-001-meeting-notes-clean-short:missing_live_proof_contract" in failures
    )


def test_packet_cli_accepts_transport_provenance(monkeypatch):
    module = load_module()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "route_proof_benchmark_packet.py",
            "--source-kind",
            "derived_capability_overlay",
            "--parent-packet-id",
            "uplink-route-proof-194fbd9bbfdc",
            "--parent-packet-sha256",
            "a" * 64,
            "--transport-generated-at",
            "2026-07-10T13:08:39Z",
        ],
    )

    args = module.parse_args()

    assert args.source_kind == "derived_capability_overlay"
    assert args.parent_packet_id == "uplink-route-proof-194fbd9bbfdc"
    assert args.parent_packet_sha256 == "a" * 64
    assert args.transport_generated_at == "2026-07-10T13:08:39Z"


def test_capability_manifest_only_cli_writes_without_live_probes(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_module()
    output = tmp_path / "capability-manifest.json"

    def fail_probe(*args, **kwargs):
        raise AssertionError("manifest-only mode must not run live probes")

    monkeypatch.setattr(module, "run_chat_probe", fail_probe)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "route_proof_benchmark_packet.py",
            "--capability-manifest-only",
            "--capability-manifest-output",
            str(output),
            "--packet-id",
            "manifest-cli-test",
        ],
    )

    assert module.main() == 0
    captured = json.loads(capsys.readouterr().out)
    manifest = json.loads(output.read_text())

    assert captured["output"] == str(output)
    assert captured["manifest_id"] == "manifest-cli-test"
    assert captured["validation_failures"] == []
    assert manifest["manifest_id"] == "manifest-cli-test"
    assert manifest["suite_case_counts"]["ocr"] == 100
    assert manifest["suite_case_counts"]["asr"] == 30


def test_aggregate_probe_rows_promotes_only_with_cold_and_warm_samples():
    module = load_module()
    spec = module.CHAT_PROBES[0]
    rows = []
    for index in range(5):
        row = module.row_from_probe(
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
            elapsed_ms=1000 + index,
        )
        rows.append(
            module.apply_sample_kind(
                row,
                sample_kind="cold" if index == 0 else "warm",
            )
        )

    aggregated = module.aggregate_probe_rows(rows)

    assert len(aggregated) == 1
    row = aggregated[0]
    assert row["accepted_count"] == 5
    assert row["total_count"] == 5
    assert row["cold_sample_count"] == 1
    assert row["warm_sample_count"] == 4
    assert row["benchmark_status"] == "production_backed"
    assert row["benchmark_gate"]["gate"] == "production"
    assert row["promotion_authoritative"] is True
    assert row["coverage_ratio"] == 1.0
    assert row["observed_workers"] == ["spark-151"]


def test_planner_router_capability_cases_cover_release_blockers():
    module = load_module()

    cases = module.planner_router_capability_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert len(cases) >= 30
    assert len(by_id) == len(cases)
    assert all(case["expected_output_shape"] == "complete" for case in cases)
    assert all(case["benchmark_assertions"] for case in cases)

    route_modes = {case["expected_route_mode"] for case in cases}
    assert "local_first" in route_modes
    assert "controlled_escalation" in route_modes
    assert "cloud_llm_offline" in route_modes
    assert "degraded_local" in route_modes
    assert "lab_or_degraded" in route_modes

    providers = {case["expected_provider"] for case in cases}
    assert "norllama" in providers
    assert "perplexity_web" in providers
    assert "local_tool" in providers

    specialist_lanes = {
        lane for case in cases for lane in case.get("expected_specialist_lanes", [])
    }
    assert {
        "receipt_auditor",
        "tool_call_risk_classifier",
        "difficulty_estimator",
        "regret_predictor",
        "browser_trace_compressor",
        "screenshot_state_classifier",
        "non_answer_detector",
        "patch_blast_radius_estimator",
        "memory_write_gate",
        "local_hallucination_firewall",
        "ocr",
        "asr",
        "rerank",
        "safety",
        "prompt_injection",
    }.issubset(specialist_lanes)

    deterministic_experts = {
        expert
        for case in cases
        for expert in case.get("expected_deterministic_experts", [])
    }
    assert {"semgrep", "pytest", "mypy", "ruff", "xgrammar"}.issubset(
        deterministic_experts
    )

    assert (
        by_id["planner-router-026-mac-mini-only"]["expected_worker_policy"]
        == "mac-mini-tiny-only"
    )
    assert (
        by_id["planner-router-023-stale-benchmark"]["expected_route_mode"]
        == "degraded_local"
    )
    assert (
        by_id["planner-router-017-web-research-cloud-llm-off"]["cloud_policy"]
        == "web_search_allowed_cloud_llm_disabled"
    )
    assert (
        by_id["planner-router-031-gui-grounding-lab"]["expected_route_mode"]
        == "lab_or_degraded"
    )


def test_planner_router_capability_suite_is_not_promotion_authoritative():
    module = load_module()

    suite = module.planner_router_capability_suite()

    assert suite["suite_id"] == "planner_router"
    assert suite["status"] == "cases_defined_unproven"
    assert suite["benchmark_class"] == "capability"
    assert suite["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "transport_backing_is_not_capability_backing": True,
        "production_capability_requires_executed_cases": True,
    }
    assert suite["case_count"] >= suite["required_case_count_for_production_capability"]
    assert "cloud_llm_offline" in suite["coverage"]["route_modes"]
    assert "world_model" in suite["coverage"]["lanes"]
    assert "safety" in suite["coverage"]["specialist_lanes"]
    assert "semgrep" in suite["coverage"]["deterministic_experts"]


def test_coder_capability_cases_cover_code_release_workflows():
    module = load_module()

    cases = module.coder_capability_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert len(cases) >= 30
    assert len(by_id) == len(cases)
    assert all(case["expected_output_shape"] == "complete" for case in cases)
    assert all(case["benchmark_assertions"] for case in cases)

    route_modes = {case["expected_route_mode"] for case in cases}
    assert "local_first" in route_modes
    assert "policy_gate" in route_modes
    assert "controlled_escalation" in route_modes
    assert "cloud_llm_offline" in route_modes

    lanes = {case["expected_lane"] for case in cases}
    assert {"coder", "patch_blast_radius_estimator", "security_scan"}.issubset(lanes)

    specialist_lanes = {
        lane for case in cases for lane in case.get("expected_specialist_lanes", [])
    }
    assert {
        "receipt_auditor",
        "tool_call_risk_classifier",
        "patch_blast_radius_estimator",
        "regret_predictor",
        "memory_write_gate",
        "local_hallucination_firewall",
        "non_answer_detector",
    }.issubset(specialist_lanes)

    deterministic_experts = {
        expert
        for case in cases
        for expert in case.get("expected_deterministic_experts", [])
    }
    assert {
        "codeql",
        "semgrep",
        "gitleaks",
        "trufflehog",
        "syft",
        "grype",
        "osv-scanner",
        "xgrammar",
        "pytest",
        "mypy",
        "ruff",
    }.issubset(deterministic_experts)

    assert by_id["coder-017-secret-scan"]["expected_deterministic_experts"] == [
        "gitleaks",
        "trufflehog",
    ]
    assert by_id["coder-018-dependency-vulnerability"][
        "expected_deterministic_experts"
    ] == ["syft", "grype", "osv-scanner"]
    assert (
        by_id["coder-029-cloud-disabled-code-task"]["expected_route_mode"]
        == "cloud_llm_offline"
    )
    assert by_id["coder-035-rollback-plan"]["expected_route_mode"] == (
        "controlled_escalation"
    )


def test_coder_capability_suite_is_not_promotion_authoritative():
    module = load_module()

    suite = module.coder_capability_suite()

    assert suite["suite_id"] == "coder"
    assert suite["status"] == "cases_defined_unproven"
    assert suite["benchmark_class"] == "capability"
    assert suite["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "transport_backing_is_not_capability_backing": True,
        "production_capability_requires_executed_cases": True,
    }
    assert suite["case_count"] >= suite["required_case_count_for_production_capability"]
    assert "security_scan" in suite["coverage"]["lanes"]
    assert "cloud_llm_offline" in suite["coverage"]["route_modes"]
    assert "patch_blast_radius_estimator" in suite["coverage"]["specialist_lanes"]
    assert "codeql" in suite["coverage"]["deterministic_experts"]
    assert "osv-scanner" in suite["coverage"]["deterministic_experts"]


def test_verifier_judge_capability_cases_cover_acceptance_and_release_gates():
    module = load_module()

    cases = module.verifier_judge_capability_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert len(cases) >= 30
    assert len(by_id) == len(cases)
    assert all(case["expected_output_shape"] == "complete" for case in cases)
    assert all(case["benchmark_assertions"] for case in cases)

    route_modes = {case["expected_route_mode"] for case in cases}
    assert "local_first" in route_modes
    assert "policy_gate" in route_modes
    assert "controlled_escalation" in route_modes
    assert "cloud_llm_offline" in route_modes
    assert "degraded_local" in route_modes

    lanes = {case["expected_lane"] for case in cases}
    assert {
        "judge",
        "verifier",
        "receipt_auditor",
        "non_answer_detector",
        "local_hallucination_firewall",
    }.issubset(lanes)

    specialist_lanes = {
        lane for case in cases for lane in case.get("expected_specialist_lanes", [])
    }
    assert {
        "receipt_auditor",
        "non_answer_detector",
        "local_hallucination_firewall",
        "rerank",
        "prompt_injection",
        "safety",
        "regret_predictor",
        "patch_blast_radius_estimator",
        "ocr",
        "asr",
        "embedding",
    }.issubset(specialist_lanes)

    deterministic_experts = {
        expert
        for case in cases
        for expert in case.get("expected_deterministic_experts", [])
    }
    assert {
        "codeql",
        "semgrep",
        "gitleaks",
        "trufflehog",
        "syft",
        "grype",
        "osv-scanner",
        "xgrammar",
        "pytest",
        "mypy",
        "ruff",
    }.issubset(deterministic_experts)

    assert by_id["verifier-016-secret-finding"]["expected_route_mode"] == (
        "policy_gate"
    )
    assert (
        by_id["verifier-020-cloud-escalation-justified"]["expected_route_mode"]
        == "controlled_escalation"
    )
    assert (
        by_id["verifier-022-cloud-disabled-hidden-fallback"]["cloud_policy"]
        == "cloud_llm_disabled"
    )
    assert (
        by_id["verifier-027-heavy-judge-placement"]["expected_worker_policy"]
        == "spark-151-warm-on-demand"
    )
    assert (
        by_id["verifier-028-mac-mini-heavy-block"]["expected_worker_policy"]
        == "mac-mini-tiny-only"
    )


def test_verifier_judge_capability_suite_is_not_promotion_authoritative():
    module = load_module()

    suite = module.verifier_judge_capability_suite()

    assert suite["suite_id"] == "verifier_judge"
    assert suite["status"] == "cases_defined_unproven"
    assert suite["benchmark_class"] == "capability"
    assert suite["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "transport_backing_is_not_capability_backing": True,
        "production_capability_requires_executed_cases": True,
    }
    assert suite["case_count"] >= suite["required_case_count_for_production_capability"]
    assert "cloud_llm_offline" in suite["coverage"]["route_modes"]
    assert "receipt_auditor" in suite["coverage"]["lanes"]
    assert "local_hallucination_firewall" in suite["coverage"]["specialist_lanes"]
    assert "gitleaks" in suite["coverage"]["deterministic_experts"]
    assert "xgrammar" in suite["coverage"]["deterministic_experts"]


def test_reranker_capability_cases_cover_evidence_selection_workflows():
    module = load_module()

    cases = module.reranker_capability_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert 25 <= len(cases) <= 40
    assert len(by_id) == len(cases)
    assert all(case["expected_output_shape"] == "complete" for case in cases)
    assert all(case["benchmark_assertions"] for case in cases)

    route_modes = {case["expected_route_mode"] for case in cases}
    assert "local_first" in route_modes
    assert "policy_gate" in route_modes
    assert "controlled_escalation" in route_modes
    assert "cloud_llm_offline" in route_modes
    assert "degraded_local" in route_modes

    lanes = {case["expected_lane"] for case in cases}
    assert lanes == {"rerank"}

    providers = {case["expected_provider"] for case in cases}
    assert {"norllama", "local_tool"}.issubset(providers)

    specialist_lanes = {
        lane for case in cases for lane in case.get("expected_specialist_lanes", [])
    }
    assert {
        "embedding",
        "rerank",
        "prompt_injection",
        "safety",
        "browser_trace_compressor",
        "ocr",
        "screenshot_state_classifier",
        "asr",
        "memory_write_gate",
        "receipt_auditor",
        "regret_predictor",
        "judge",
    }.issubset(specialist_lanes)

    tags = {tag for case in cases for tag in case.get("tags", [])}
    assert {
        "text",
        "code",
        "logs",
        "browser",
        "perplexity",
        "ocr",
        "asr",
        "vision",
        "multimodal",
        "prompt_injection",
        "secrets",
        "latency",
        "worker_attribution",
        "token_budget",
    }.issubset(tags)

    assert by_id["reranker-006-prompt-injection-demotion"]["risk_level"] == "high"
    assert by_id["reranker-012-scout-search-results"]["cloud_policy"] == (
        "web_search_allowed_cloud_llm_disabled"
    )
    assert (
        by_id["reranker-020-cloud-escalation-minimal-packet"]["expected_route_mode"]
        == "controlled_escalation"
    )
    assert (
        by_id["reranker-021-empty-candidates"]["expected_route_mode"]
        == "degraded_local"
    )
    assert (
        by_id["reranker-027-worker-attribution"]["expected_worker_policy"]
        == "spark-150-specialist"
    )
    assert (
        "rerank_not_final_authority"
        in by_id["reranker-028-cross-lane-no-reasoning-authority"][
            "benchmark_assertions"
        ]
    )


def test_reranker_capability_suite_is_not_promotion_authoritative():
    module = load_module()

    suite = module.reranker_capability_suite()

    assert suite["suite_id"] == "reranker"
    assert suite["status"] == "cases_defined_unproven"
    assert suite["benchmark_class"] == "capability"
    assert suite["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "transport_backing_is_not_capability_backing": True,
        "production_capability_requires_executed_cases": True,
    }
    assert suite["required_case_count_for_production_capability"] == 25
    assert 25 <= suite["case_count"] <= 40
    assert "rerank" in suite["coverage"]["lanes"]
    assert "cloud_llm_offline" in suite["coverage"]["route_modes"]
    assert "prompt_injection" in suite["coverage"]["specialist_lanes"]
    assert "asr" in suite["coverage"]["specialist_lanes"]
    assert "rerank_not_final_authority" in suite["required_common_assertions"][4]


def test_safety_capability_cases_cover_labeled_query_groups():
    module = load_module()

    cases = module.safety_capability_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert len(cases) == 50
    assert len(by_id) == len(cases)
    assert all(case["expected_lane"] == "safety" for case in cases)
    assert all(case["expected_label"] for case in cases)
    assert all(case["expected_policy_action"] for case in cases)
    assert all(case["benchmark_assertions"] for case in cases)

    labels = {case["expected_label"] for case in cases}
    assert {
        "benign",
        "privacy_sensitive",
        "secret_request",
        "prompt_injection",
        "tool_risk_low",
        "tool_risk_high",
        "web_search_allowed",
        "cloud_escalation",
        "policy_block",
        "malware_or_abuse",
        "credential_exfiltration",
        "data_loss_risk",
        "ambiguous",
        "copyright_sensitive",
        "regulated_advice",
        "degraded_safety",
    }.issubset(labels)

    actions = {case["expected_policy_action"] for case in cases}
    assert {
        "allow",
        "allow_with_caveat",
        "block",
        "degrade",
        "redact",
        "require_approval",
        "require_local_preflight",
        "route_to_web_search",
    }.issubset(actions)

    route_modes = {case["expected_route_mode"] for case in cases}
    assert {
        "local_first",
        "policy_gate",
        "cloud_llm_offline",
        "controlled_escalation",
        "degraded_local",
    }.issubset(route_modes)

    specialist_lanes = {
        lane for case in cases for lane in case.get("expected_specialist_lanes", [])
    }
    assert {
        "safety",
        "prompt_injection",
        "tool_call_risk_classifier",
        "memory_write_gate",
        "local_hallucination_firewall",
        "browser_trace_compressor",
        "ocr",
        "asr",
        "rerank",
        "receipt_auditor",
        "difficulty_estimator",
        "regret_predictor",
    }.issubset(specialist_lanes)

    deterministic_experts = {
        expert
        for case in cases
        for expert in case.get("expected_deterministic_experts", [])
    }
    assert {"semgrep", "pytest", "osv-scanner", "grype", "gitleaks"}.issubset(
        deterministic_experts
    )

    assert (
        by_id["safety-004-plaintext-secret-file"]["expected_policy_action"] == "block"
    )
    assert (
        by_id["safety-012-mutating-shell"]["expected_policy_action"]
        == "require_approval"
    )
    assert by_id["safety-016-perplexity-web-search"]["cloud_policy"] == (
        "web_search_allowed_cloud_llm_disabled"
    )
    assert (
        by_id["safety-016-perplexity-web-search"]["expected_policy_action"]
        == "route_to_web_search"
    )
    assert (
        by_id["safety-020-cloud-disabled-hidden-fallback"]["expected_route_mode"]
        == "cloud_llm_offline"
    )
    assert (
        by_id["safety-020-cloud-disabled-hidden-fallback"]["expected_policy_action"]
        == "block"
    )
    assert (
        "cloud_proxy_not_counted_local"
        in by_id["safety-038-model-proxy-cloud"]["benchmark_assertions"]
    )


def test_safety_capability_suite_is_not_promotion_authoritative():
    module = load_module()

    suite = module.safety_capability_suite()

    assert suite["suite_id"] == "safety"
    assert suite["status"] == "cases_defined_unproven"
    assert suite["benchmark_class"] == "capability"
    assert suite["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "transport_backing_is_not_capability_backing": True,
        "production_capability_requires_executed_cases": True,
    }
    assert suite["required_case_count_for_production_capability"] == 50
    assert suite["case_count"] == 50
    assert suite["coverage"]["lanes"] == ["safety"]
    assert "cloud_llm_offline" in suite["coverage"]["route_modes"]
    assert "prompt_injection" in suite["coverage"]["specialist_lanes"]
    assert "action_block" in suite["coverage"]["tags"]
    assert "label_privacy_sensitive" in suite["coverage"]["tags"]
    assert "expected_label" in suite["required_common_assertions"][0]
    assert "expected_policy_action" in suite["required_common_assertions"][0]


def test_ocr_capability_cases_cover_mixed_document_workflows():
    module = load_module()

    cases = module.ocr_capability_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert len(cases) == 100
    assert len(by_id) == len(cases)
    assert all(case["expected_lane"] == "ocr" for case in cases)
    assert all(case["expected_provider"] == "norllama" for case in cases)
    assert all(
        case["expected_worker_policy"] == "spark-150-specialist" for case in cases
    )
    assert all(case["expected_label"] for case in cases)
    assert all(case["expected_policy_action"] for case in cases)
    assert all(
        "structured_fields_do_not_use_cloud_llm" in case["benchmark_assertions"]
        for case in cases
    )

    labels = {case["expected_label"] for case in cases}
    assert {
        "invoice",
        "receipt",
        "purchase_order",
        "bank_statement",
        "tax_form",
        "medical_form",
        "insurance_card",
        "id_card",
        "shipping_label",
        "product_label",
        "warranty_card",
        "lab_report",
        "utility_bill",
        "contract_page",
        "whiteboard",
        "ui_error_screenshot",
        "terminal_screenshot",
        "chart_dashboard",
        "handwritten_note",
        "spreadsheet_table",
    } == labels

    actions = {case["expected_policy_action"] for case in cases}
    assert {
        "extract",
        "extract_with_redaction",
        "extract_with_confidence",
        "extract_structured",
        "extract_ignore_injection",
        "redact_and_ignore_injection",
    }.issubset(actions)

    route_modes = {case["expected_route_mode"] for case in cases}
    assert {
        "local_first",
        "policy_gate",
        "cloud_llm_offline",
        "degraded_local",
    } == route_modes

    specialist_lanes = {
        lane for case in cases for lane in case.get("expected_specialist_lanes", [])
    }
    assert {
        "ocr",
        "safety",
        "prompt_injection",
        "screenshot_state_classifier",
        "rerank",
        "receipt_auditor",
        "local_hallucination_firewall",
        "memory_write_gate",
    }.issubset(specialist_lanes)

    deterministic_experts = {
        expert
        for case in cases
        for expert in case.get("expected_deterministic_experts", [])
    }
    assert deterministic_experts == {"xgrammar"}

    tags = {tag for case in cases for tag in case.get("tags", [])}
    assert {
        "clean",
        "mobile_photo",
        "low_contrast",
        "multi_page",
        "prompt_injection",
        "pdf",
        "table",
        "screenshot",
        "handwriting",
        "privacy",
        "chart",
    }.issubset(tags)

    assert by_id["ocr-001-invoice-clean-single-page"]["expected_label"] == "invoice"
    assert (
        by_id["ocr-001-invoice-clean-single-page"]["expected_policy_action"]
        == "extract"
    )
    assert by_id["ocr-004-invoice-multi-page-pdf"]["cloud_policy"] == (
        "cloud_llm_disabled"
    )
    assert (
        by_id["ocr-005-invoice-adversarial-overlay"]["expected_route_mode"]
        == "policy_gate"
    )
    assert (
        "injected_text_not_obeyed"
        in by_id["ocr-005-invoice-adversarial-overlay"]["benchmark_assertions"]
    )
    assert (
        by_id["ocr-016-bank-statement-clean-single-page"]["expected_policy_action"]
        == "extract_with_redaction"
    )
    assert (
        by_id["ocr-020-bank-statement-adversarial-overlay"]["expected_policy_action"]
        == "redact_and_ignore_injection"
    )
    assert (
        "redact_sensitive_fields"
        in by_id["ocr-017-bank-statement-skewed-mobile-photo"]["required_operations"]
    )
    assert (
        "redact_sensitive_fields"
        in by_id["ocr-018-bank-statement-low-contrast-noisy-scan"][
            "required_operations"
        ]
    )
    assert (
        "redact_sensitive_fields"
        in by_id["ocr-019-bank-statement-multi-page-pdf"]["required_operations"]
    )
    assert (
        "preserve_page_boundaries"
        in by_id["ocr-019-bank-statement-multi-page-pdf"]["required_operations"]
    )
    assert (
        "ignore_untrusted_instructions"
        in by_id["ocr-020-bank-statement-adversarial-overlay"]["required_operations"]
    )
    assert (
        by_id["ocr-020-bank-statement-adversarial-overlay"]["injection_policy"]
        == "extract_but_do_not_obey"
    )
    assert (
        by_id["ocr-028-medical-form-low-contrast-noisy-scan"]["expected_route_mode"]
        == "degraded_local"
    )
    assert (
        "uncertain_text_not_fabricated"
        in by_id["ocr-028-medical-form-low-contrast-noisy-scan"]["benchmark_assertions"]
    )
    assert (
        by_id["ocr-100-spreadsheet-table-adversarial-overlay"]["expected_label"]
        == "spreadsheet_table"
    )


def test_ocr_capability_suite_is_not_promotion_authoritative():
    module = load_module()

    suite = module.ocr_capability_suite()

    assert suite["suite_id"] == "ocr"
    assert suite["status"] == "cases_defined_unproven"
    assert suite["benchmark_class"] == "capability"
    assert suite["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "transport_backing_is_not_capability_backing": True,
        "production_capability_requires_executed_cases": True,
    }
    assert suite["required_case_count_for_production_capability"] == 100
    assert suite["case_count"] == 100
    assert suite["coverage"]["lanes"] == ["ocr"]
    assert "cloud_llm_offline" in suite["coverage"]["route_modes"]
    assert "degraded_local" in suite["coverage"]["route_modes"]
    assert "prompt_injection" in suite["coverage"]["specialist_lanes"]
    assert "local_hallucination_firewall" in suite["coverage"]["specialist_lanes"]
    assert "xgrammar" in suite["coverage"]["deterministic_experts"]
    assert {
        "emit_confidence",
        "ignore_untrusted_instructions",
        "preserve_page_boundaries",
        "redact_sensitive_fields",
    }.issubset(set(suite["coverage"]["required_operations"]))
    assert "action_extract_structured" in suite["coverage"]["tags"]
    assert "label_id_card" in suite["coverage"]["tags"]
    assert "not transport reachability alone" in suite["required_common_assertions"][-1]


def test_asr_capability_cases_cover_mixed_audio_workflows():
    module = load_module()

    cases = module.asr_capability_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert len(cases) == 30
    assert len(by_id) == len(cases)
    assert all(case["expected_lane"] == "asr" for case in cases)
    assert all(case["expected_provider"] == "norllama" for case in cases)
    assert all(case["expected_worker_policy"] == "spark-151-media" for case in cases)
    assert all(case["expected_label"] for case in cases)
    assert all(case["expected_policy_action"] for case in cases)
    assert all(
        "transcript_segments_do_not_use_cloud_llm" in case["benchmark_assertions"]
        for case in cases
    )

    labels = {case["expected_label"] for case in cases}
    assert {
        "meeting",
        "voice_command",
        "dictation",
        "voicemail",
        "support_call",
        "field_recording",
        "lecture",
        "screen_recording",
        "podcast",
        "multilingual",
    } == labels

    actions = {case["expected_policy_action"] for case in cases}
    assert {
        "transcribe",
        "transcribe_with_diarization",
        "transcribe_with_redaction",
        "transcribe_with_redaction_and_confidence",
        "transcribe_with_confidence",
        "transcribe_with_timestamps",
        "transcribe_with_alignment",
        "transcribe_streaming",
        "transcribe_language_spans",
    }.issubset(actions)

    route_modes = {case["expected_route_mode"] for case in cases}
    assert {"local_first", "degraded_local", "cloud_llm_offline"} == route_modes

    specialist_lanes = {
        lane for case in cases for lane in case.get("expected_specialist_lanes", [])
    }
    assert {
        "asr",
        "safety",
        "local_hallucination_firewall",
        "rerank",
        "receipt_auditor",
        "memory_write_gate",
        "forced_aligner",
    }.issubset(specialist_lanes)

    deterministic_experts = {
        expert
        for case in cases
        for expert in case.get("expected_deterministic_experts", [])
    }
    assert deterministic_experts == {"xgrammar"}

    tags = {tag for case in cases for tag in case.get("tags", [])}
    assert {
        "faster_whisper",
        "clean",
        "noise",
        "multispeaker",
        "long_audio",
        "streaming",
        "timestamps",
        "privacy",
        "screen_recording",
        "multilingual",
    }.issubset(tags)

    assert (
        by_id["asr-001-meeting-notes-clean-short"]["expected_policy_action"]
        == "transcribe_with_diarization"
    )
    assert (
        by_id["asr-002-meeting-notes-noisy-multispeaker"]["expected_route_mode"]
        == "degraded_local"
    )
    assert (
        "diarization"
        in by_id["asr-002-meeting-notes-noisy-multispeaker"]["required_operations"]
    )
    assert (
        "emit_confidence"
        in by_id["asr-002-meeting-notes-noisy-multispeaker"]["required_operations"]
    )
    assert (
        "overlap_not_fabricated"
        in by_id["asr-002-meeting-notes-noisy-multispeaker"]["benchmark_assertions"]
    )
    assert by_id["asr-003-meeting-notes-long-streaming"]["cloud_policy"] == (
        "cloud_llm_disabled"
    )
    assert (
        by_id["asr-010-voicemail-clean-short"]["expected_policy_action"]
        == "transcribe_with_redaction"
    )
    assert (
        by_id["asr-011-voicemail-noisy-multispeaker"]["expected_policy_action"]
        == "transcribe_with_redaction_and_confidence"
    )
    assert (
        "redact_sensitive_fields"
        in by_id["asr-012-voicemail-long-streaming"]["required_operations"]
    )
    assert (
        "streaming" in by_id["asr-012-voicemail-long-streaming"]["required_operations"]
    )
    assert (
        by_id["asr-022-screen-recording-clean-short"]["expected_policy_action"]
        == "transcribe_with_alignment"
    )
    assert (
        "ui_alignment"
        in by_id["asr-024-screen-recording-long-streaming"]["required_operations"]
    )
    assert (
        "streaming"
        in by_id["asr-024-screen-recording-long-streaming"]["required_operations"]
    )
    assert (
        "ui_event_alignment_recorded"
        in by_id["asr-022-screen-recording-clean-short"]["benchmark_assertions"]
    )
    assert (
        by_id["asr-030-multilingual-clip-long-streaming"]["expected_label"]
        == "multilingual"
    )
    assert (
        "language_spans"
        in by_id["asr-029-multilingual-clip-noisy-multispeaker"]["required_operations"]
    )
    assert (
        "language_spans"
        in by_id["asr-030-multilingual-clip-long-streaming"]["required_operations"]
    )


def test_asr_capability_suite_is_not_promotion_authoritative():
    module = load_module()

    suite = module.asr_capability_suite()

    assert suite["suite_id"] == "asr"
    assert suite["status"] == "cases_defined_unproven"
    assert suite["benchmark_class"] == "capability"
    assert suite["capability_gate"] == {
        "gate": "unproven",
        "promotion_authoritative": False,
        "transport_backing_is_not_capability_backing": True,
        "production_capability_requires_executed_cases": True,
    }
    assert suite["required_case_count_for_production_capability"] == 30
    assert suite["case_count"] == 30
    assert suite["coverage"]["lanes"] == ["asr"]
    assert "cloud_llm_offline" in suite["coverage"]["route_modes"]
    assert "degraded_local" in suite["coverage"]["route_modes"]
    assert "forced_aligner" in suite["coverage"]["specialist_lanes"]
    assert "local_hallucination_firewall" in suite["coverage"]["specialist_lanes"]
    assert "xgrammar" in suite["coverage"]["deterministic_experts"]
    assert {
        "diarization",
        "emit_confidence",
        "language_spans",
        "preserve_chunk_boundaries",
        "redact_sensitive_fields",
        "streaming",
        "ui_alignment",
    }.issubset(set(suite["coverage"]["required_operations"]))
    assert "action_transcribe_streaming" in suite["coverage"]["tags"]
    assert "label_meeting" in suite["coverage"]["tags"]
    assert "not transport reachability alone" in suite["required_common_assertions"][-1]
