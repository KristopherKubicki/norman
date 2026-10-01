from app.services.work_classification import (
    WORK_CLASSIFICATION_SCHEMA,
    classify_work,
    sanitize_work_classification,
    work_classification_summary,
)


def test_trusted_status_and_command_handlers_are_deterministic():
    status = classify_work(deterministic_kind="status")
    command = classify_work(deterministic_kind="command")

    assert status["work_class"] == "deterministic"
    assert status["execution_authority"] == "none"
    assert status["evidence_required"] == "deterministic_receipt"
    assert command["reason_codes"] == ["trusted_deterministic_command"]
    assert sanitize_work_classification(status) == status


def test_prompt_words_alone_do_not_create_a_deterministic_classification():
    result = classify_work(
        prompt_classification={"task_kind": "summarize", "risk_level": "low"}
    )

    assert result["work_class"] == "local"
    assert result["reason_codes"] == ["local_safe_analysis"]


def test_local_review_covers_code_verification_planning_scout_and_kpis():
    assert classify_work(task_kind="code")["work_class"] == "local_review"
    assert classify_work(task_kind="verify")["work_class"] == "local_review"
    assert classify_work(task_kind="plan")["work_class"] == "local_review"
    assert classify_work(task_kind="scout")["work_class"] == "local_review"
    assert classify_work(task_kind="kpi")["work_class"] == "local_review"


def test_external_or_destructive_work_remains_human_approved():
    result = classify_work(
        prompt_classification={
            "requires_approval": True,
            "external_side_effects_possible": True,
            "risk_level": "high",
        }
    )

    assert result["work_class"] == "approval_required"
    assert result["execution_authority"] == "none"
    assert result["human_approval_required"] is True
    assert result["evidence_required"] == "approval_receipt"


def test_forced_or_effective_frontier_runtime_is_explicitly_classified():
    forced = classify_work(
        requested_runtime="codex",
        force_requested_runtime=True,
    )
    effective = classify_work(
        effective_runtime="qwen",
        task_kind="plan",
    )

    assert forced["work_class"] == "frontier"
    assert "forced_frontier_route" in forced["reason_codes"]
    assert effective["work_class"] == "frontier"
    assert "effective_frontier_runtime" in effective["reason_codes"]


def test_requested_frontier_fallback_to_local_keeps_local_review_requirements():
    assert (
        classify_work(
            requested_runtime="codex",
            effective_runtime="localllm",
            task_kind="plan",
        )["work_class"]
        == "local_review"
    )


def test_malformed_or_tampered_contract_is_rejected():
    value = classify_work(task_kind="code")
    value["operator_summary"] = "caller-provided summary"
    assert sanitize_work_classification(value) == {}

    value = classify_work(task_kind="code")
    value["reason_codes"] = ["unknown"]
    assert sanitize_work_classification(value) == {}

    assert (
        sanitize_work_classification(
            {
                "schema": WORK_CLASSIFICATION_SCHEMA,
                "work_class": "unknown",
            }
        )
        == {}
    )
    assert work_classification_summary(classify_work(task_kind="plan")).startswith(
        "local review:"
    )
