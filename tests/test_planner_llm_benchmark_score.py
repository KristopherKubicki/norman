from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module(name: str):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    script = scripts_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _completed_answers_for_candidate(packet: dict, candidate_id: str) -> dict:
    template = _load_module("planner_llm_benchmark_packet").answer_template(packet)
    prompts = [
        prompt for prompt in packet["prompts"] if prompt["candidate_id"] == candidate_id
    ]
    answers = []
    for prompt in prompts:
        answer = next(
            row
            for row in template["answers"]
            if row["prompt_id"] == prompt["prompt_id"]
        )
        answer.update(
            {
                "answer": (
                    "Route decision: use bounded local draft with verifier. "
                    "Evidence required: command artifact, receipt, and next action. "
                    "Accounting cost note: write tokens, latency, USD, and ledger basis. "
                    "Authority boundary: frontier or human keeps ultimate approval. "
                    "Next action: checkpoint any blocker. "
                    + " ".join(prompt["required_terms"])
                ),
                "input_tokens": prompt["input_tokens"],
                "cached_input_tokens": prompt["cached_input_tokens"],
                "output_tokens": prompt["expected_output_tokens"],
                "latency_ms": 1200,
                "runtime_health_status": "healthy",
                "verifier_acceptance": "accepted",
            }
        )
        answers.append(answer)
    template["answers"] = answers
    template["run_id"] = "unit-test"
    return template


def test_score_report_promotes_passing_local_dgx_spark_roles() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    packet = packet_module.build_packet()
    candidate_id = "local_dgx_spark_qwen3_coder_30b"
    answers = _completed_answers_for_candidate(packet, candidate_id)

    report = score_module.build_report(packet, answers)

    assert report["summary"]["gate"] == "pass"
    records = {
        (record["candidate_id"], record["account_scope"]): record
        for record in report["promotion_records"]
    }
    personal = records[(candidate_id, "personal")]
    assert personal["weighted_score"] >= 0.91
    assert personal["critical_failure_count"] == 0
    assert "planner_advisory" in personal["planner_consumption_allowed_roles"]
    assert "bounded_local_execute" in personal["planner_consumption_allowed_roles"]
    assert "final_authority" not in personal["planner_consumption_allowed_roles"]


def test_score_report_fails_closed_for_forbidden_terms_and_bad_runtime() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    packet = packet_module.build_packet()
    candidate_id = "local_dgx_spark_qwen3_coder_30b"
    answers = _completed_answers_for_candidate(packet, candidate_id)
    answers["answers"][0]["answer"] += " invoice confirmed"
    answers["answers"][0]["runtime_health_status"] = "unavailable"

    report = score_module.build_report(packet, answers)

    assert report["summary"]["gate"] == "fail"
    first = report["scores"][0]
    assert "forbidden_terms" in first["critical_fail_reasons"]
    assert "runtime_health_not_healthy" in first["critical_fail_reasons"]
    record = report["promotion_records"][0]
    assert record["planner_consumption_allowed_roles"] == []


def test_score_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    packet = packet_module.build_packet()
    answers = _completed_answers_for_candidate(
        packet, "local_dgx_spark_qwen3_coder_30b"
    )
    packet_json = tmp_path / "packet.json"
    answers_json = tmp_path / "answers.json"
    output_json = tmp_path / "score.json"
    output_md = tmp_path / "score.md"
    packet_json.write_text(json.dumps(packet), encoding="utf-8")
    answers_json.write_text(json.dumps(answers), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/planner_llm_benchmark_score.py",
            "--packet-json",
            str(packet_json),
            "--answers-json",
            str(answers_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["schema"] == "norman.planner-llm-benchmark-score.v1"
    assert "Planner LLM Benchmark Score" in output_md.read_text(encoding="utf-8")
