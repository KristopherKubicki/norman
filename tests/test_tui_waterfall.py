from app.services.tui_waterfall import (
    build_tui_waterfall,
    sanitize_tui_waterfall_decision,
    waterfall_allows_bedrock_retry,
)


CAPACITY = {
    "enabled": True,
    "selected": True,
    "state": "available",
    "fresh": True,
    "chatgpt_auth_verified": True,
}


def build_decision(**overrides):
    options = {
        "requested_runtime": "codex",
        "requested_model": "gpt-5.6",
        "requested_service_tier": "default",
        "base_runtime": "codex",
        "base_model": "gpt-5.6",
        "base_service_tier": "default",
        "bedrock_runtime": "codex",
        "bedrock_model": "openai.gpt-5.6",
        "bedrock_service_tier": "bedrock-emergency",
        "route_lock": False,
        "subscription": CAPACITY,
        "norllama_available": True,
        "norllama_safe_final": True,
        "bedrock_available": True,
    }
    options.update(overrides)
    return build_tui_waterfall(**options)


def exhausted_capacity():
    return {**CAPACITY, "selected": False, "state": "blocked"}


def test_fresh_verified_capacity_selects_subscription_flex():
    decision = build_decision()

    assert decision["waterfall_stage"] == "subscription_flex"
    assert decision["selected_service_tier"] == "flex"
    assert decision["bedrock_auto_authorized"] is False


def test_deterministic_status_has_a_zero_token_local_route_proof():
    decision = build_decision(
        requested_runtime="localllm",
        requested_model="deterministic-status",
        requested_service_tier="default",
        base_runtime="localllm",
        base_model="deterministic-status",
        base_service_tier="default",
        subscription={},
        norllama_available=False,
        norllama_safe_final=False,
        deterministic_status=True,
    )

    assert decision["waterfall_stage"] == "deterministic_status"
    assert decision["route_source"] == "deterministic_tui_status"
    assert decision["charge_basis"] == "zero_token_deterministic"
    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "deterministic-status"
    assert decision["selected_service_tier"] == "default"
    assert sanitize_tui_waterfall_decision(decision) == decision


def test_deterministic_command_has_a_zero_token_local_route_proof():
    decision = build_decision(
        requested_runtime="localllm",
        requested_model="deterministic-command",
        requested_service_tier="default",
        base_runtime="localllm",
        base_model="deterministic-command",
        base_service_tier="default",
        subscription={},
        norllama_available=False,
        norllama_safe_final=False,
        deterministic_command=True,
    )

    assert decision["waterfall_stage"] == "deterministic_command"
    assert decision["route_source"] == "deterministic_tui_command"
    assert decision["charge_basis"] == "zero_token_deterministic"
    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "deterministic-command"
    assert decision["selected_service_tier"] == "default"
    assert sanitize_tui_waterfall_decision(decision) == decision


def test_deterministic_command_requires_an_exact_unlocked_route_proof():
    decision = build_decision(
        requested_runtime="localllm",
        requested_model="deterministic-command",
        requested_service_tier="default",
        base_runtime="localllm",
        base_model="deterministic-command",
        base_service_tier="default",
        subscription={},
        norllama_available=False,
        norllama_safe_final=False,
        deterministic_command=True,
    )

    for tampered in (
        {**decision, "selected_model": "deterministic-status"},
        {**decision, "selected_service_tier": "flex"},
        {**decision, "requested_model": "gpt-5.6"},
        {**decision, "route_lock": True},
    ):
        assert sanitize_tui_waterfall_decision(tampered) == {}
    assert (
        build_decision(
            requested_runtime="localllm",
            requested_model="deterministic-command",
            requested_service_tier="default",
            base_runtime="localllm",
            base_model="deterministic-command",
            base_service_tier="default",
            subscription={},
            norllama_available=False,
            norllama_safe_final=False,
            deterministic_status=True,
            deterministic_command=True,
        )
        == {}
    )


def test_verified_exhaustion_uses_norllama_before_bedrock():
    decision = build_decision(subscription=exhausted_capacity())

    assert decision["waterfall_stage"] == "norllama_pool"
    assert decision["selected_runtime"] == "localllm"
    assert decision["selected_model"] == "norllama"
    assert decision["attempts"] == ["subscription_flex", "norllama_pool"]
    assert decision["bedrock_auto_authorized"] is False


def test_verified_exhaustion_uses_bedrock_only_without_safe_pool():
    decision = build_decision(
        subscription=exhausted_capacity(),
        norllama_available=False,
        norllama_safe_final=False,
    )

    assert decision["waterfall_stage"] == "bedrock_verified_exhaustion"
    assert decision["bedrock_auto_authorized"] is True
    assert decision["attempts"] == [
        "subscription_flex",
        "norllama_pool",
        "bedrock_verified_exhaustion",
    ]


def test_stale_or_unknown_verified_capacity_selects_one_flex_probe():
    for capacity in (
        {**CAPACITY, "selected": False, "fresh": False, "state": "available"},
        {**CAPACITY, "selected": False, "state": "unknown"},
    ):
        decision = build_decision(
            subscription=capacity,
            norllama_available=False,
            norllama_safe_final=False,
        )

        assert decision["waterfall_stage"] == "subscription_flex_probe"
        assert decision["selected_runtime"] == "codex"
        assert decision["selected_service_tier"] == "flex"
        assert decision["attempts"] == ["subscription_flex_probe"]
        assert decision["bedrock_auto_authorized"] is False
        assert not waterfall_allows_bedrock_retry(decision)


def test_disabled_or_unverified_capacity_blocks_automatic_bedrock():
    for capacity in (
        {**CAPACITY, "enabled": False, "selected": False},
        {**CAPACITY, "selected": False, "chatgpt_auth_verified": False},
    ):
        decision = build_decision(
            subscription=capacity,
            norllama_available=False,
            norllama_safe_final=False,
        )

        assert decision["waterfall_stage"] == "blocked"
        assert decision["blocked"] is True
        assert decision["bedrock_auto_authorized"] is False


def test_fresh_verified_blocked_capacity_stays_fallback_eligible():
    decision = build_decision(
        subscription=exhausted_capacity(),
        norllama_available=False,
        norllama_safe_final=False,
    )

    assert decision["waterfall_stage"] == "bedrock_verified_exhaustion"
    assert decision["bedrock_auto_authorized"] is True


def test_operator_locked_bedrock_is_manual():
    decision = build_decision(
        requested_service_tier="bedrock-emergency",
        base_service_tier="bedrock-emergency",
        route_lock=True,
        subscription={**CAPACITY, "selected": False, "state": "unknown"},
    )

    assert decision["waterfall_stage"] == "bedrock_manual"
    assert decision["route_lock"] is True
    assert decision["bedrock_auto_authorized"] is False
    assert not waterfall_allows_bedrock_retry(decision)


def test_secondary_or_tertiary_manual_bedrock_route_is_labeled_paid_manual():
    decision = build_decision(
        requested_service_tier="bedrock-failover-2",
        base_service_tier="bedrock-failover-2",
        route_lock=True,
        subscription={**CAPACITY, "selected": False, "state": "unknown"},
        manual_bedrock_available=True,
    )

    assert decision["waterfall_stage"] == "bedrock_manual"
    assert decision["selected_service_tier"] == "bedrock-failover-2"
    assert decision["charge_basis"] == "provider_invoice_estimate"
    assert decision["bedrock_auto_authorized"] is False


def test_unconfigured_manual_bedrock_route_is_not_allowed_through():
    decision = build_decision(
        requested_service_tier="bedrock-failover",
        base_service_tier="bedrock-failover",
        route_lock=True,
        subscription={**CAPACITY, "selected": False, "state": "unknown"},
        manual_bedrock_available=False,
    )

    assert decision["waterfall_stage"] == "blocked_manual_bedrock"
    assert decision["blocked"] is True
    assert decision["bedrock_auto_authorized"] is False


def test_generic_codex_route_lock_is_not_bedrock_manual():
    decision = build_decision(
        requested_service_tier="priority",
        base_service_tier="priority",
        route_lock=True,
    )

    assert decision["waterfall_stage"] == "route_lock"
    assert decision["route_lock"] is True
    assert not waterfall_allows_bedrock_retry(decision)


def test_default_tier_cannot_be_selected_as_automatic_bedrock():
    decision = build_decision(
        bedrock_service_tier="default",
        subscription=exhausted_capacity(),
        norllama_available=False,
        norllama_safe_final=False,
    )

    assert decision["waterfall_stage"] == "blocked"
    assert decision["blocked"] is True
    assert not waterfall_allows_bedrock_retry(decision)


def test_default_tier_route_lock_is_preserved_without_bedrock_retry():
    decision = build_decision(
        route_lock=True,
        subscription={**CAPACITY, "selected": False, "state": "unknown"},
    )

    assert decision["waterfall_stage"] == "route_lock"
    assert decision["selected_service_tier"] == "default"
    assert not waterfall_allows_bedrock_retry(decision)


def test_direct_tier_usage_limit_recovery_selects_bedrock_default():
    decision = build_decision(
        requested_service_tier="flex",
        base_service_tier="default",
        direct_tier_usage_limit_recovery=True,
    )

    assert decision["waterfall_stage"] == "bedrock_direct_limit_recovery"
    assert decision["selected_runtime"] == "codex"
    assert decision["selected_service_tier"] == "default"
    assert decision["bedrock_auto_authorized"] is True
    assert decision["direct_tier_usage_limit_recovery"] is True


def test_direct_tier_usage_limit_recovery_receipt_is_static_and_sanitized():
    decision = sanitize_tui_waterfall_decision(
        {
            "stage": "bedrock_direct_limit_recovery",
            "selected": True,
            "blocked": False,
            "requested_runtime": "codex",
            "requested_model": "gpt-5.6",
            "requested_service_tier": "priority",
            "selected_runtime": "codex",
            "selected_model": "openai.gpt-5.6",
            "selected_service_tier": "default",
            "route_lock": False,
            "direct_tier_usage_limit_recovery": True,
            "recent_usage_limit_count": 9,
            "latest_usage_limit_at": 1781539006,
            "target_profile_v2": "private-profile",
            "target_aws_profile": "private-aws-profile",
            "target_aws_region": "us-east-2",
            "provider_error_text": "private provider error",
            "subscription_capacity": {"state": "available"},
        }
    )

    assert decision["waterfall_stage"] == "bedrock_direct_limit_recovery"
    assert decision["direct_tier_usage_limit_recovery"] is True
    assert decision["attempts"] == ["direct_tier_usage_limit_recovery"]
    assert decision["charge_basis"] == "provider_invoice_estimate"
    assert "recent_usage_limit_count" not in decision
    assert "latest_usage_limit_at" not in decision
    assert "target_profile_v2" not in decision
    assert "target_aws_profile" not in decision
    assert "target_aws_region" not in decision
    assert "provider_error_text" not in decision


def test_tampered_direct_tier_usage_limit_recovery_is_rejected_without_retry():
    decision = build_decision(
        requested_service_tier="flex",
        base_service_tier="default",
        direct_tier_usage_limit_recovery=True,
    )

    for tampered in (
        {**decision, "selected_service_tier": "flex"},
        {**decision, "route_lock": True},
        {**decision, "direct_tier_usage_limit_recovery": False},
        {**decision, "requested_service_tier": "default"},
    ):
        assert sanitize_tui_waterfall_decision(tampered) == {}
        assert not waterfall_allows_bedrock_retry(tampered)

    assert not waterfall_allows_bedrock_retry(decision)


def test_sanitizer_drops_probe_and_pool_details_with_stable_order():
    decision = sanitize_tui_waterfall_decision(
        {
            "stage": "norllama_pool",
            "selected": True,
            "blocked": False,
            "selected_runtime": "localllm",
            "selected_model": "norllama",
            "selected_service_tier": "default",
            "norllama_pool": "default",
            "local_final_authority": True,
            "attempts": ["bedrock_verified_exhaustion", "norllama_pool"],
            "reason": "http://pool.example/internal",
            "fallback_reason": "secret",
            "route_source": "worker-123",
            "local_endpoint": "http://pool.example",
            "local_candidates": ["unsafe-model"],
            "local_health": {"endpoint": "http://pool.example"},
            "local_mesh": {"nodes": ["spark"]},
            "local_cooldowns": [{"endpoint": "http://pool.example"}],
            "headers": {"Authorization": "secret"},
            "raw_payload": {"token": "secret"},
            "subscription_capacity": exhausted_capacity(),
        }
    )

    assert list(decision) == [
        "schema",
        "selected",
        "blocked",
        "requested_runtime",
        "requested_model",
        "requested_service_tier",
        "selected_runtime",
        "selected_model",
        "selected_service_tier",
        "stage",
        "waterfall_stage",
        "route_source",
        "reason",
        "fallback_reason",
        "attempts",
        "waterfall_attempt_count",
        "route_lock",
        "bedrock_auto_authorized",
        "subscription_capacity",
        "charge_basis",
        "norllama_pool",
        "local_final_authority",
    ]
    assert decision["attempts"] == ["subscription_flex", "norllama_pool"]
    assert decision["reason"] == (
        "verified subscription exhaustion selected the Norllama pool"
    )
    assert "local_endpoint" not in decision
    assert "local_candidates" not in decision
    assert "local_health" not in decision
    assert "local_mesh" not in decision
    assert "local_cooldowns" not in decision
    assert "headers" not in decision
    assert "raw_payload" not in decision


def test_only_bedrock_stages_authorize_bedrock_retry():
    assert waterfall_allows_bedrock_retry(
        build_decision(
            subscription=exhausted_capacity(),
            norllama_available=False,
            norllama_safe_final=False,
        )
    )
    assert not waterfall_allows_bedrock_retry(build_decision(route_lock=True))
    assert not waterfall_allows_bedrock_retry(build_decision())
    assert not waterfall_allows_bedrock_retry(
        build_decision(subscription=exhausted_capacity())
    )


def test_tampered_route_evidence_cannot_authorize_bedrock_retry():
    verified_exhaustion = build_decision(
        subscription=exhausted_capacity(),
        norllama_available=False,
        norllama_safe_final=False,
    )
    invalid_decisions = [
        {**verified_exhaustion, "selected_runtime": "localllm"},
        {**verified_exhaustion, "selected_service_tier": "flex"},
        {**verified_exhaustion, "selected_model": ""},
        {
            **verified_exhaustion,
            "subscription_capacity": {
                **verified_exhaustion["subscription_capacity"],
                "enabled": False,
            },
        },
        {**verified_exhaustion, "route_lock": True},
    ]

    for decision in invalid_decisions:
        assert sanitize_tui_waterfall_decision(decision) == {}
        assert not waterfall_allows_bedrock_retry(decision)


def test_tampered_subscription_probe_proof_is_rejected():
    probe = build_decision(
        subscription={**CAPACITY, "selected": False, "state": "unknown"},
        norllama_available=False,
        norllama_safe_final=False,
    )
    invalid_decisions = [
        {**probe, "selected_runtime": "localllm"},
        {**probe, "selected_service_tier": "default"},
        {
            **probe,
            "subscription_capacity": {
                **probe["subscription_capacity"],
                "fresh": True,
                "state": "available",
            },
        },
        {
            **probe,
            "subscription_capacity": {
                **probe["subscription_capacity"],
                "chatgpt_auth_verified": False,
            },
        },
    ]

    for decision in invalid_decisions:
        assert sanitize_tui_waterfall_decision(decision) == {}
        assert not waterfall_allows_bedrock_retry(decision)


def test_tampered_subscription_flex_proof_is_rejected():
    direct_flex = build_decision()
    invalid_decisions = [
        {
            **direct_flex,
            "subscription_capacity": {
                **direct_flex["subscription_capacity"],
                "enabled": False,
            },
        },
        {
            **direct_flex,
            "subscription_capacity": {
                **direct_flex["subscription_capacity"],
                "selected": False,
            },
        },
        {
            **direct_flex,
            "subscription_capacity": {
                **direct_flex["subscription_capacity"],
                "state": "unknown",
            },
        },
        {
            **direct_flex,
            "subscription_capacity": {
                **direct_flex["subscription_capacity"],
                "fresh": False,
            },
        },
        {
            **direct_flex,
            "subscription_capacity": {
                **direct_flex["subscription_capacity"],
                "chatgpt_auth_verified": False,
            },
        },
    ]

    for decision in invalid_decisions:
        assert sanitize_tui_waterfall_decision(decision) == {}
