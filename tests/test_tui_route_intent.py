from app.services.tui_route_intent import (
    button_intent,
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
    assert requested_action("make it so") == "proceed_or_next"
    assert operator_intent_class("go ahead") == "proceed"
    assert operator_intent_class("make it so") == "proceed"
    assert operator_intent_class("retry") == "retry"
    assert operator_intent_class("stop") == "stop"
    assert operator_intent_class("undo the last thing") == "undo_gate"


def test_reply_tail_button_intents_are_explicit() -> None:
    cases = {
        "dig": ("dig_deeper", "deep_dive"),
        "go deeper on that": ("dig_deeper", "deep_dive"),
        "simpler": ("simplify_response", "simplify_response"),
        "make this plain english": ("simplify_response", "simplify_response"),
        "verify": ("verify_response", "verify_or_audit"),
        "double check this": ("verify_response", "verify_or_audit"),
        "copy": ("copy_response", "copy_response"),
        "handoff this to scout": ("handoff_or_relay", "handoff_or_relay"),
    }

    for prompt, (expected_button, expected_intent) in cases.items():
        assert button_intent(prompt) == expected_button
        assert requested_action(prompt) == expected_button
        assert operator_intent_class(prompt) == expected_intent
        assert classify_key_terms(prompt)["button_intent"] == expected_button
        assert classify_key_terms(prompt)["requested_action"] == expected_button
        assert classify_key_terms(prompt)["deterministic_block"] == (
            f"deterministic_action_{expected_button}"
        )
