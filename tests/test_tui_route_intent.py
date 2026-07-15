from app.services.tui_route_intent import (
    classify_key_terms,
    deterministic_local_verifier_block,
    is_broad_planning,
    is_quick_status,
    is_route_status_diagnostic,
    operator_intent_class,
    requested_action,
)


def test_typo_status_is_quick_status() -> None:
    result = classify_key_terms("stauts? updates?")

    assert result["quick_status"] is True
    assert result["requested_action"] == "status"
    assert result["operator_intent_class"] == "status"
    assert result["deterministic_block"] == ""


def test_broad_tui_fork_prompt_is_not_status() -> None:
    prompt = "what happened with the plan for forking TUIs into multiple sessions?"

    assert is_broad_planning(prompt) is True
    assert is_quick_status(prompt) is False
    assert is_route_status_diagnostic(prompt) is False
    assert requested_action(prompt) == "operator_prompt"
    assert operator_intent_class(prompt) == "operator_prompt"
    assert (
        deterministic_local_verifier_block(
            prompt,
            action="operator_prompt",
            intent_class="operator_prompt",
        )
        == "broad_planning_request"
    )


def test_route_status_diagnostic_stays_status() -> None:
    prompt = "why did uplink route that status prompt to the wrong model?"

    assert is_route_status_diagnostic(prompt) is True
    assert requested_action(prompt) == "status"
    assert operator_intent_class(prompt) == "status"


def test_terse_commands_have_control_intents() -> None:
    assert requested_action("go ahead") == "proceed_or_next"
    assert operator_intent_class("go ahead") == "proceed"
    assert operator_intent_class("retry") == "retry"
    assert operator_intent_class("stop") == "stop"
    assert operator_intent_class("undo the last thing") == "undo_gate"
