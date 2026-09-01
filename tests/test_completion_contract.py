from app.services.completion_contract import response_promises_unfinished_work


def test_detects_observed_direct_cli_short_stops() -> None:
    responses = [
        "I need to check the portal contract reference before connecting.",
        (
            "I need to connect to the Ops Portal MCP to check queue status. "
            "Let me first check if the launcher script is available."
        ),
        "Next, I will query the live queue and report back.",
        "We should inspect the worker health before answering.",
        "I'm still checking the live console state.",
    ]

    assert all(response_promises_unfinished_work(item) for item in responses)


def test_allows_results_and_real_blockers() -> None:
    responses = [
        "The queue currently contains 197 jobs; 12 workers are active.",
        "I checked the queue: it is healthy and no jobs are stuck.",
        "If you want, I'll also inspect the dead-letter queue.",
        "I need your approval to deploy the change. Please approve it first.",
        "I can't proceed because the Ops token is missing. Please provide it.",
    ]

    assert not any(response_promises_unfinished_work(item) for item in responses)
