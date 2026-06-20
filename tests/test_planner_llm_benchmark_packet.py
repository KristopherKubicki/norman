from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    script = scripts_dir / "planner_llm_benchmark_packet.py"
    spec = importlib.util.spec_from_file_location(
        "planner_llm_benchmark_packet", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["planner_llm_benchmark_packet"] = module
    spec.loader.exec_module(module)
    return module


def test_packet_includes_catalog_models_cases_and_dgx_spark_promotion_policy() -> None:
    module = _load_module()

    packet = module.build_packet()

    assert packet["schema"] == "norman.planner-llm-benchmark-packet.v1"
    assert packet["dry_run_only"] is True
    assert packet["model_calls_executed"] == 0
    assert packet["summary"]["model_count"] >= 20
    assert packet["summary"]["case_count"] >= 6
    assert packet["summary"]["prompt_count"] == (
        packet["summary"]["model_count"] * packet["summary"]["case_count"]
    )
    assert packet["summary"]["local_dgx_spark_model_count"] >= 2
    assert packet["summary"]["estimated_cloud_run_cost_usd"] > 0

    route_ids = {model["route_id"] for model in packet["models"]}
    assert "local_dgx_spark_qwen3_coder_30b" in route_ids
    assert "local_dgx_spark2_gpt_oss_120b" in route_ids
    assert "openai_direct_gpt_5_5_standard" in route_ids

    local = next(
        model
        for model in packet["models"]
        if model["route_id"] == "local_dgx_spark_qwen3_coder_30b"
    )
    assert local["accounting"]["marginal_token_cost_usd"] == 0.0
    assert local["accounting"]["requires_runtime_health"] is True
    assert local["accounting"]["requires_promotion_record"] is True
    assert (
        packet["promotion_policy"]["local_model_roles"]["final_authority"]["allowed"]
        is False
    )
    assert "account_scope" in packet["promotion_policy"]["required_metrics"]


def test_answer_template_covers_every_prompt() -> None:
    module = _load_module()
    packet = module.build_packet()

    template = module.answer_template(packet)

    assert template["schema"] == "norman.planner-llm-benchmark-answers.v1"
    assert len(template["answers"]) == packet["summary"]["prompt_count"]
    first = template["answers"][0]
    assert first["prompt_id"] == packet["prompts"][0]["prompt_id"]
    assert "latency_ms" in first
    assert "runtime_health_status" in first
    assert "verifier_acceptance" in first


def test_packet_cli_writes_json_markdown_prompts_and_template(tmp_path: Path) -> None:
    output_json = tmp_path / "packet.json"
    output_md = tmp_path / "packet.md"
    prompts_jsonl = tmp_path / "prompts.jsonl"
    answers_template = tmp_path / "answers.template.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_llm_benchmark_packet.py",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--prompts-jsonl",
            str(prompts_jsonl),
            "--answers-template-json",
            str(answers_template),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    packet = json.loads(output_json.read_text(encoding="utf-8"))
    prompt_lines = [
        json.loads(line)
        for line in prompts_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    template = json.loads(answers_template.read_text(encoding="utf-8"))

    assert len(prompt_lines) == packet["summary"]["prompt_count"]
    assert len(template["answers"]) == packet["summary"]["prompt_count"]
    assert "Planner LLM Benchmark Packet" in output_md.read_text(encoding="utf-8")
    assert prompt_lines[0]["schema"] == "norman.planner-llm-benchmark-prompt.v1"
