from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "local_model_skill_floor.py"
    )
    spec = importlib.util.spec_from_file_location("local_model_skill_floor", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["local_model_skill_floor"] = module
    spec.loader.exec_module(module)
    return module


def _skill(
    skill_id: str,
    *,
    tier: str,
    family: str = "retrieval",
    validator: bool = True,
    lower_final: bool = True,
    final_authority: bool = False,
) -> dict:
    return {
        "skill_id": skill_id,
        "domain": "gold-book",
        "family": family,
        "label": skill_id.replace("_", " ").title(),
        "requires_tools": family in {"code", "retrieval"},
        "requires_code": family == "code",
        "requires_state_change": False,
        "requires_high_authority": final_authority,
        "model_routing_decision": {
            "minimum_model_tier": tier,
            "requires_5_4_verifier": tier == "bedrock_gpt_5_4_xhigh_verifier",
            "requires_5_5_final": tier == "bedrock_gpt_5_5_xhigh_final",
            "escalate_to_5_4_when": ["validator fails"],
            "escalate_to_5_5_when": ["final authority"],
        },
        "lower_model_readiness": {
            "can_shadow_roll_out_lower_final": lower_final,
            "has_deterministic_validator": validator,
            "validator_gate": "fixture validator",
        },
        "targets": {
            "operational_accuracy": 0.94,
            "strict_accuracy": 0.9,
            "max_overreach_risk": 0.04,
        },
    }


def test_local_model_skill_floor_selects_minimum_live_model() -> None:
    module = _load_module()
    ollama = {
        "schema": "norman.tui.ollama-sense.v1",
        "endpoints": [
            {
                "endpoint": "http://192.168.2.150:11434",
                "ok": True,
                "models": ["gpt-oss:20b", "llama3.2:1b"],
            },
            {
                "endpoint": "http://192.168.2.151:11434",
                "ok": True,
                "models": ["gpt-oss:120b", "qwen3.5:122b-a10b-q4_K_M"],
            },
        ],
    }
    matrix = {
        "schema": "norman.work-domain-skill-benchmark.v1",
        "rows": [
            _skill("small_case", tier="small_bedrock_worker"),
            _skill("medium_case", tier="medium_bedrock_worker"),
            _skill(
                "final_case",
                tier="bedrock_gpt_5_5_xhigh_final",
                final_authority=True,
            ),
        ],
    }

    report = module.build_report(matrix, ollama)
    rows = {row["skill_id"]: row for row in report["rows"]}

    assert report["schema"] == "norman.local-model-skill-floor.v1"
    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0
    trial = report["low_model_trial_benchmark"]
    profiles = {row["id"]: row for row in trial["profiles"]}
    assert trial["schema"] == "norman.low-model-trial-benchmark.v1"
    assert trial["model_calls_executed"] == 0
    assert trial["try_now_profile_count"] >= 4
    assert profiles["gpt_5_4_mini_worker"]["try_now"] is True
    assert profiles["gpt_5_4_mini_worker"]["try_now_candidate_count"] > 0
    assert profiles["gpt_5_4_mini_worker"]["final_authority_hold_count"] >= 1
    assert "live mutation" in profiles["gpt_5_4_mini_worker"]["not_allowed_use"]
    capability = profiles["gpt_5_4_mini_worker"]["capability_summary"]
    assert capability["schema"] == "norman.model-capability-row.v1"
    assert capability["accuracy_targets"]["evidence_type"] == (
        "modeled_skill_matrix_targets"
    )
    assert capability["accuracy_targets"]["target_strict_accuracy_median"] == 0.9
    assert capability["verifier_required_count"] > 0
    assert (
        "final authority stays with Bedrock 5.5 or operator approval"
        in capability["cannot_do"]
    )
    assert trial["capability_matrix"][0]["schema"] == "norman.model-capability-row.v1"
    assert profiles["tiny_local_text_1b_4b"]["blocked_count"] > 0
    assert report["summary"]["low_model_try_now_profile_count"] >= 5
    assert report["summary"]["live_low_model_try_now_profile_count"] >= 2
    assert report["summary"]["best_live_low_model_try_now_profile"].startswith("live_")
    assert rows["small_case"]["selected_local_model"] == "gpt-oss:20b"
    assert rows["small_case"]["allowed_role"] == "validator_bounded_final_candidate"
    assert rows["medium_case"]["selected_local_model"] == "gpt-oss:120b"
    assert rows["medium_case"]["allowed_role"] == "validator_bounded_final_candidate"
    assert rows["final_case"]["selected_local_model"] == "gpt-oss:120b"
    assert rows["final_case"]["allowed_role"] == "draft_only"
    assert (
        rows["final_case"]["local_floor_status"]
        == "local_draft_only_final_authority_hold"
    )


def test_local_model_skill_floor_merges_vllm_inventory() -> None:
    module = _load_module()
    ollama = {
        "schema": "norman.tui.ollama-sense.v1",
        "endpoints": [
            {
                "endpoint": "http://192.168.2.150:11434",
                "ok": True,
                "models": ["qwen3:8b"],
            }
        ],
    }
    vllm = {
        "schema": "norman.tui.vllm-sense.v1",
        "endpoints": [
            {
                "endpoint": "http://spark-1.home.arpa:8000",
                "ok": True,
                "models": ["Qwen/Qwen3-Coder-30B-A3B"],
            }
        ],
    }
    matrix = {
        "schema": "norman.work-domain-skill-benchmark.v1",
        "rows": [_skill("code_case", tier="small_bedrock_worker", family="code")],
    }

    report = module.build_report(matrix, ollama, extra_sense_reports=[vllm])
    row = report["rows"][0]

    assert "norman.tui.vllm-sense.v1" in report["source_sense_schemas"]
    assert row["selected_local_model"] == "Qwen/Qwen3-Coder-30B-A3B"
    assert row["selected_local_endpoint"] == "http://spark-1.home.arpa:8000"
    assert row["selected_local_model_family"] == "coder"
    assert row["selected_local_provider"] == "vllm"
    assert row["selected_local_runtime_class"] == "spark_vllm"
    assert row["offline_optimizer_state"] == "spark_vllm_selected"
    assert report["summary"]["online_spark_vllm_model_count"] == 1
    assert report["summary"]["spark_vllm_selected_skill_count"] == 1


def test_local_model_skill_floor_uses_norllama_inventory_and_benchmark_packet() -> None:
    module = _load_module()
    matrix = {
        "schema": "norman.work-domain-skill-benchmark.v1",
        "rows": [_skill("planner_case", tier="medium_bedrock_worker")],
    }
    capabilities = {
        "schema": "norman.norllama.capabilities.v1",
        "frontdoor": "https://llm.home.arpa",
        "models": [{"model": "qwen3.6:27b"}],
    }
    packet = {
        "schema": "norman.norllama.route-proof-benchmark-packet.v1",
        "rows": [
            {
                "model": "qwen3.6:27b",
                "benchmark_status": "production_backed",
            }
        ],
    }

    report = module.build_report(
        matrix,
        {},
        norllama_capabilities=capabilities,
        benchmark_packet=packet,
    )
    row = report["rows"][0]

    assert "norman.norllama-capabilities-sense.v1" in report["source_sense_schemas"]
    assert report["norllama_inventory"]["connected"] is True
    assert report["benchmark_packet"]["connected"] is True
    assert report["summary"]["norllama_inventory_model_count"] == 1
    assert report["summary"]["benchmark_packet_model_count"] == 1
    assert row["selected_local_model"] == "qwen3.6:27b"
    assert row["selected_local_provider"] == "norllama"
    assert row["selected_local_benchmark_state"] == "production_backed"
    assert row["selected_local_benchmark_backed"] is True


def test_local_model_skill_floor_prefers_spark_vllm_over_same_class_ollama() -> None:
    module = _load_module()
    ollama = {
        "schema": "norman.tui.ollama-sense.v1",
        "endpoints": [
            {
                "endpoint": "http://192.168.2.150:11434",
                "ok": True,
                "models": ["qwen3-coder:30b-a3b-q4_K_M"],
            }
        ],
    }
    vllm = {
        "schema": "norman.tui.vllm-sense.v1",
        "endpoints": [
            {
                "endpoint": "http://spark-1.home.arpa:8000",
                "ok": True,
                "models": ["Qwen/Qwen3-Coder-30B-A3B"],
            }
        ],
    }
    matrix = {
        "schema": "norman.work-domain-skill-benchmark.v1",
        "rows": [_skill("code_case", tier="small_bedrock_worker", family="code")],
    }

    row = module.build_report(matrix, ollama, extra_sense_reports=[vllm])["rows"][0]

    assert row["selected_local_model"] == "Qwen/Qwen3-Coder-30B-A3B"
    assert row["selected_local_endpoint"] == "http://spark-1.home.arpa:8000"
    assert row["selected_local_provider"] == "vllm"
    assert row["selected_local_runtime_class"] == "spark_vllm"
    assert row["spark_vllm_candidate_count"] == 1
    assert row["ollama_candidate_count"] == 1


def test_local_model_skill_floor_cli_outputs_json_and_markdown(tmp_path: Path) -> None:
    module = _load_module()
    skill_matrix = tmp_path / "skills.json"
    ollama_sense = tmp_path / "ollama.json"
    vllm_sense = tmp_path / "vllm.json"
    output_json = tmp_path / "floors.json"
    output_md = tmp_path / "floors.md"
    skill_matrix.write_text(
        json.dumps(
            {
                "schema": "norman.work-domain-skill-benchmark.v1",
                "rows": [
                    _skill("code_case", tier="small_bedrock_worker", family="code")
                ],
            }
        ),
        encoding="utf-8",
    )
    ollama_sense.write_text(
        json.dumps(
            {
                "schema": "norman.tui.ollama-sense.v1",
                "endpoints": [
                    {
                        "endpoint": "http://192.168.2.150:11434",
                        "ok": True,
                        "models": ["qwen3-coder:30b-a3b-q4_K_M", "gpt-oss:20b"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    vllm_sense.write_text(
        json.dumps(
            {
                "schema": "norman.tui.vllm-sense.v1",
                "endpoints": [
                    {
                        "endpoint": "http://spark-1.home.arpa:8000",
                        "ok": True,
                        "models": ["meta-llama/Llama-3.1-70B-Instruct"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        module.main(
            [
                "--skill-matrix-json",
                str(skill_matrix),
                "--ollama-sense-json",
                str(ollama_sense),
                "--vllm-sense-json",
                str(vllm_sense),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ]
        )
        == 0
    )
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["rows"][0]["selected_local_model"] == "qwen3-coder:30b-a3b-q4_K_M"
    assert report["rows"][0]["offline_optimizer_state"] == (
        "ollama_fallback_no_usable_spark_vllm"
    )
    assert report["summary"]["online_spark_vllm_model_count"] == 1
    assert report["summary"]["ollama_fallback_skill_count"] == 1
    markdown = output_md.read_text(encoding="utf-8")
    assert "Local Model Skill Floors" in markdown
    assert "Spark/vLLM selected skills" in markdown
    assert "Model Capability Matrix" in markdown
    assert "Low-Level Trial Benchmark" in markdown
    assert "gpt_5_4_mini_worker" in markdown


def test_local_model_skill_floor_cli_tolerates_missing_sense_files(
    tmp_path: Path,
) -> None:
    module = _load_module()
    skill_matrix = tmp_path / "skills.json"
    output_json = tmp_path / "floors.json"
    output_md = tmp_path / "floors.md"
    skill_matrix.write_text(
        json.dumps(
            {
                "schema": "norman.work-domain-skill-benchmark.v1",
                "rows": [
                    _skill("lookup", tier="small_bedrock_worker"),
                    _skill(
                        "final_case",
                        tier="bedrock_gpt_5_5_xhigh_final",
                        final_authority=True,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        module.main(
            [
                "--skill-matrix-json",
                str(skill_matrix),
                "--ollama-sense-json",
                str(tmp_path / "missing-ollama.json"),
                "--vllm-sense-json",
                str(tmp_path / "missing-vllm.json"),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ]
        )
        == 0
    )

    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["summary"]["online_local_model_count"] == 0
    assert report["summary"]["online_spark_vllm_model_count"] == 0
    assert report["summary"]["live_low_model_try_now_profile_count"] == 0
    assert report["low_model_trial_benchmark"]["best_try_now_profile"]


def test_local_model_skill_floor_ranks_newer_qwen_variants() -> None:
    module = _load_module()

    assert module._model_capacity("dimavz/whisper-tiny:latest") == (0, "non_text")
    assert module._model_capacity("nomic-embed-text:latest") == (0, "non_text")
    assert module._model_capacity("unrecognized-local-model:latest") == (
        0,
        "unknown_unranked",
    )
    assert module._model_capacity("qwen3:8b") == (2, "small_local_worker")
    assert module._model_capacity("gemma3:4b") == (1, "tiny_text_worker")
    assert module._model_capacity("qwen3-coder-next:q4_K_M") == (3, "coder")
    assert module._model_capacity("qwen3-vl:30b-a3b-instruct-q4_K_M") == (
        2,
        "vision_local_worker",
    )
    assert module._model_capacity("qwen2.5vl:7b") == (
        2,
        "vision_local_worker",
    )
    assert module._model_capacity("qwen3.6:35b-a3b-q4_K_M") == (
        3,
        "large_local_worker",
    )


def test_local_model_skill_floor_does_not_select_non_text_models_for_text_work() -> (
    None
):
    module = _load_module()
    ollama = {
        "endpoints": [
            {
                "endpoint": "http://192.168.2.133:11434",
                "ok": True,
                "models": [
                    "dimavz/whisper-tiny:latest",
                    "llama3.2-vision:11b",
                    "qwen3:8b",
                ],
            }
        ]
    }
    matrix = {
        "rows": [
            _skill("lookup", tier="small_bedrock_worker", family="retrieval"),
            _skill("vision", tier="small_bedrock_worker", family="vision"),
        ]
    }

    rows = {row["skill_id"]: row for row in module.build_report(matrix, ollama)["rows"]}

    assert rows["lookup"]["selected_local_model"] == "qwen3:8b"
    assert rows["lookup"]["selected_local_model_family"] == "small_local_worker"
    assert rows["lookup"]["selected_local_runtime_class"] == "ollama"
    assert rows["vision"]["selected_local_model"] == "llama3.2-vision:11b"
    assert rows["vision"]["selected_local_model_family"] == "vision_local_worker"
