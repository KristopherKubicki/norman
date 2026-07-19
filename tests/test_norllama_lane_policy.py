from app.services.norllama.lane_policy import lane_policy_for_model


def test_gpt_oss_is_code_draft_only() -> None:
    policy = lane_policy_for_model(
        model="gpt-oss:120b",
        lane="coder",
        benchmark_quality={"eligible": True},
    )

    assert policy["allowed"] is True
    assert policy["route_mode"] == "code_draft_with_verifier"
    assert policy["requires_deterministic_verifier"] is True
    assert policy["final_authority"] is False

    rejected = lane_policy_for_model(
        model="gpt-oss:120b",
        lane="planner",
        benchmark_quality={"eligible": True},
    )
    assert rejected["allowed"] is False
    assert rejected["route_mode"] == "blocked"


def test_gemma_semantic_score_does_not_grant_governed_execution_lane() -> None:
    policy = lane_policy_for_model(
        model="gemma4:31b",
        lane="summarizer",
        benchmark_quality={"eligible": True},
    )
    assert policy["allowed"] is True
    assert policy["route_mode"] == "structured_draft_with_verifier"

    blocked = lane_policy_for_model(
        model="gemma4:31b",
        lane="verifier",
        benchmark_quality={"eligible": True},
    )
    assert blocked["allowed"] is False
    assert "not eligible" in blocked["reason"]


def test_qwen_is_general_local_floor_but_never_final_authority() -> None:
    policy = lane_policy_for_model(
        model="qwen3.6:35b-a3b-q4_K_M",
        lane="planner",
        benchmark_quality={"eligible": True},
    )

    assert policy["allowed"] is True
    assert policy["route_mode"] == "local_draft_with_verifier"
    assert policy["requires_cloud_final_for_actions"] is True
    assert policy["final_authority"] is False
