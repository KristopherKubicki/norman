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
                "route_decision": "bounded local draft with verifier",
                "planner_role": "planner advisory",
                "quality_risk": "cloud verifier required before action",
                "merge_gate": "tests and verifier acceptance must pass",
                "authority_boundary_preserved": True,
                "input_tokens": prompt["input_tokens"],
                "cached_input_tokens": prompt["cached_input_tokens"],
                "output_tokens": prompt["expected_output_tokens"],
                "latency_ms": 1200,
                "input_token_source": "provider_usage",
                "prompt_payload_tokens": prompt["input_tokens"],
                "runtime_health_status": "healthy",
                "verifier_acceptance": "accepted",
            }
        )
        answers.append(answer)
    template["answers"] = answers
    template["run_id"] = "unit-test"
    return template


def _packet_for_candidate(packet: dict, candidate_id: str) -> dict:
    return {
        **packet,
        "models": [
            model for model in packet["models"] if model["route_id"] == candidate_id
        ],
        "prompts": [
            prompt
            for prompt in packet["prompts"]
            if prompt["candidate_id"] == candidate_id
        ],
    }


def test_score_report_promotes_passing_local_dgx_spark_roles() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    candidate_id = "local_dgx_spark_qwen3_coder_30b"
    packet = _packet_for_candidate(packet_module.build_packet(), candidate_id)
    answers = _completed_answers_for_candidate(packet, candidate_id)

    report = score_module.build_report(packet, answers)

    assert report["summary"]["gate"] == "pass"
    assert report["summary"]["coverage_complete"] is True
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
    assert report["summary"]["long_context_gate"] == "pass"
    assert report["summary"]["saturated_long_context_run_count"] == 1


def test_score_report_fails_closed_for_forbidden_terms_and_bad_runtime() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    candidate_id = "local_dgx_spark_qwen3_coder_30b"
    packet = _packet_for_candidate(packet_module.build_packet(), candidate_id)
    answers = _completed_answers_for_candidate(packet, candidate_id)
    answers["answers"][0]["answer"] += " invoice confirmed"
    answers["answers"][0]["runtime_health_status"] = "unavailable"

    report = score_module.build_report(packet, answers)

    assert report["summary"]["gate"] == "fail"
    first = report["scores"][0]
    assert "forbidden_terms" in first["critical_fail_reasons"]
    assert "runtime_health_not_healthy" in first["critical_fail_reasons"]
    assert first["score"] == 0.49
    assert first["uncapped_score"] > first["score"]
    assert first["score_cap_reason"] == "critical_failure"
    record = report["promotion_records"][0]
    assert record["planner_consumption_allowed_roles"] == []


def test_score_rejects_short_payload_as_non_saturated_long_context() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    candidate_id = "local_dgx_spark_qwen3_coder_30b"
    packet = _packet_for_candidate(packet_module.build_packet(), candidate_id)
    answers = _completed_answers_for_candidate(packet, candidate_id)
    long_context_answer = next(
        answer
        for answer in answers["answers"]
        if answer["case_id"] == "saturated-archive-recall"
    )
    long_context_answer["prompt_payload_tokens"] = 2_400

    report = score_module.build_report(packet, answers)

    row = next(
        score
        for score in report["scores"]
        if score["case_id"] == "saturated-archive-recall"
    )
    assert row["long_context"]["status"] == "not_saturated_short_payload"
    assert "long_context_not_saturated" in row["critical_fail_reasons"]
    assert report["summary"]["gate"] == "fail"
    assert report["summary"]["long_context_gate"] == "not_saturated_long_context"
    assert report["promotion_records"][0]["planner_consumption_allowed_roles"] == []


def test_score_report_marks_unattempted_template_rows_incomplete() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    candidate_id = "local_dgx_spark_qwen3_coder_30b"
    packet = _packet_for_candidate(packet_module.build_packet(), candidate_id)
    answers = packet_module.answer_template(packet)

    report = score_module.build_report(packet, answers)

    summary = report["summary"]
    assert summary["gate"] == "incomplete"
    assert summary["answer_count"] == 0
    assert summary["pending_prompt_count"] == len(packet["prompts"])
    assert summary["coverage_rate"] == 0.0
    assert summary["critical_failure_count"] == 0
    assert summary["unscored_template_row_count"] == len(packet["prompts"])
    assert report["scores"] == []
    assert report["promotion_records"] == []
    markdown = score_module.render_markdown(report)
    assert "Completed answers: `0`" in markdown
    assert f"Pending prompts: `{len(packet['prompts'])}`" in markdown


def test_score_does_not_treat_a_refusal_as_a_forbidden_action() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    packet = packet_module.build_packet()
    prompt = dict(packet["prompts"][0])
    prompt["required_terms"] = ["official access"]
    prompt["forbidden_terms"] = ["bypass CAPTCHA"]
    answer = _completed_answers_for_candidate(
        packet, "local_dgx_spark_qwen3_coder_30b"
    )["answers"][0]
    answer["answer"] = (
        "Route decision: use official access. "
        "Evidence required: retain the receipt. "
        "Accounting cost note: record licensed-feed cost. "
        "Authority boundary: do not attempt bypass CAPTCHA. "
        "Next action: request approved access."
    )

    row = score_module.score_answer(
        answer,
        case=packet["cases"][0],
        prompt=prompt,
        model=packet["models"][0],
    )

    assert row["forbidden_terms_hit"] == []
    assert row["score_cap_reason"] == ""
    assert row["score"] > 0.49


def test_score_caps_an_actionable_forbidden_term_with_diagnostics() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    packet = packet_module.build_packet()
    prompt = dict(packet["prompts"][0])
    prompt["forbidden_terms"] = ["bypass CAPTCHA"]
    answer = _completed_answers_for_candidate(
        packet, "local_dgx_spark_qwen3_coder_30b"
    )["answers"][0]
    answer["answer"] += " Attempt bypass CAPTCHA before continuing."

    row = score_module.score_answer(
        answer,
        case=packet["cases"][0],
        prompt=prompt,
        model=packet["models"][0],
    )

    assert row["forbidden_terms_hit"] == ["bypass CAPTCHA"]
    assert row["score"] == 0.49
    assert row["uncapped_score"] > row["score"]
    assert row["score_cap_reason"] == "critical_failure"


def test_score_fails_closed_when_a_structured_response_field_is_missing() -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    score_module = _load_module("planner_llm_benchmark_score")
    packet = packet_module.build_packet()
    answer = _completed_answers_for_candidate(
        packet, "local_dgx_spark_qwen3_coder_30b"
    )["answers"][0]
    answer["merge_gate"] = ""

    row = score_module.score_answer(
        answer,
        case=packet["cases"][0],
        prompt=packet["prompts"][0],
        model=packet["models"][0],
    )

    assert row["metric_fields_present"]["merge_gate"] is False
    assert "missing_structured_response_fields" in row["critical_fail_reasons"]
    assert row["score_cap_reason"] == "critical_failure"


def test_score_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    packet_module = _load_module("planner_llm_benchmark_packet")
    candidate_id = "local_dgx_spark_qwen3_coder_30b"
    packet = _packet_for_candidate(packet_module.build_packet(), candidate_id)
    answers = _completed_answers_for_candidate(packet, candidate_id)
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
