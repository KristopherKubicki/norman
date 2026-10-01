from app.services.run_health import RunHealthPolicy, evaluate_proxy_run_health


def _event(
    *,
    prompt: str,
    status: str = "success",
    tokens: int = 0,
    chain_depth: int = 0,
    watchdog: str = "normal",
    workflow: str = "",
) -> dict:
    return {
        "prompt_sha256": prompt,
        "request_shape_sha256": "shape",
        "workflow_sha256": workflow,
        "status": status,
        "usage": {"total_tokens": tokens},
        "tool_chain": {
            "chain_depth": chain_depth,
            "watchdog_state": watchdog,
        },
    }


def test_run_health_is_normal_for_varied_successful_traffic() -> None:
    report = evaluate_proxy_run_health(
        [
            _event(prompt="a", tokens=1000),
            _event(prompt="b", tokens=1200, chain_depth=2),
            _event(prompt="c", tokens=900),
        ]
    )

    assert report["state"] == "normal"
    assert report["recommended_action"] == "continue"
    assert report["signals"] == []


def test_run_health_stops_repeated_prompt_and_failure_loops() -> None:
    policy = RunHealthPolicy(
        repeated_prompt_warn=2,
        repeated_prompt_stop=3,
        consecutive_failures_warn=2,
        consecutive_failures_stop=3,
    )
    report = evaluate_proxy_run_health(
        [
            _event(prompt="same", status="error"),
            _event(prompt="same", status="error"),
            _event(prompt="same", status="error"),
        ],
        policy=policy,
    )

    assert report["state"] == "stop"
    assert report["recommended_action"] == "stop_and_checkpoint"
    assert {item["code"] for item in report["signals"]} == {
        "consecutive_failure_loop",
        "repeated_prompt_loop",
    }


def test_run_health_warns_on_deep_and_repaired_tool_chains() -> None:
    report = evaluate_proxy_run_health(
        [
            _event(prompt="a", chain_depth=8, watchdog="repaired"),
            _event(prompt="b", watchdog="repaired"),
        ]
    )

    assert report["state"] == "warn"
    assert {item["code"] for item in report["signals"]} == {
        "deep_tool_chain",
        "tool_continuation_repair_churn",
    }


def test_run_health_stops_when_token_window_is_exhausted() -> None:
    report = evaluate_proxy_run_health(
        [
            _event(prompt="a", tokens=110_000),
            _event(prompt="b", tokens=100_000),
        ]
    )

    assert report["state"] == "stop"
    assert report["metrics"]["total_tokens"] == 210_000
    assert report["signals"][0]["code"] == "token_window_exhausted"


def test_run_health_scopes_repetition_to_the_latest_workflow() -> None:
    policy = RunHealthPolicy(repeated_prompt_warn=2, repeated_prompt_stop=3)
    report = evaluate_proxy_run_health(
        [
            _event(prompt="same", workflow="workflow-a"),
            _event(prompt="same", workflow="workflow-a"),
            _event(prompt="same", workflow="workflow-b"),
        ],
        policy=policy,
    )

    assert report["state"] == "normal"
    assert report["workflow_sha256"] == "workflow-b"
    assert report["bounded_event_count"] == 3
    assert report["window_event_count"] == 1
