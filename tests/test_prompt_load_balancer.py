from app.services.prompt_load_balancer import (
    balance_prompt,
    prompt_load_balancer_capabilities,
)


def test_prompt_load_balancer_routes_typo_status_prompts_local_first():
    result = balance_prompt(
        prompt="stauts? any updates please",
        source="uplink",
        session="uplink-codex",
    )

    assert result["schema"] == "norman.prompt-load-balancer.v1"
    assert result["mode"] == "prompt_load_balancer"
    assert result["classification"]["intent"] == "quick_status"
    assert result["classification"]["task_kind"] == "summarize"
    assert result["reasoning_profile"]["tier"] == "simple"
    assert result["routing_strategy"]["strategy"] == "simple_local"
    assert result["route"]["provider"] == "norllama"
    assert result["route"]["local"] is True
    assert result["route"]["cloud_proxy"] is False
    assert result["recommendation"]["selected_runtime"] == "localllm"
    assert result["recommendation"]["local_first"] is True
    assert result["recommendation"]["cloud_last_resort"] is True
    assert result["recommendation"]["reasoning_tier"] == "simple"
    assert result["recommendation"]["primary_executor"] == "deterministic_prompt_gate"
    assert result["recommendation"]["next_hop"] == "console_runtime_kernel"
    assert result["route_receipt_preview"]["execution_performed"] is False


def test_prompt_load_balancer_keeps_requested_cloud_as_preference_until_forced():
    result = balance_prompt(
        prompt="status?",
        requested_runtime="codex",
        requested_model="gpt-5.5",
        force_requested_runtime=False,
    )

    assert result["classification"]["intent"] == "quick_status"
    assert result["route"]["provider"] == "norllama"
    assert result["route"]["cloud_proxy"] is False
    assert result["recommendation"]["selected_runtime"] == "localllm"


def test_prompt_load_balancer_requires_preflight_for_external_mutations():
    result = balance_prompt(
        prompt="please restart uplink and deploy the fix",
        source="uplink",
    )

    assert result["classification"]["risk_class"] == "external_mutation"
    assert result["classification"]["risk_level"] == "high"
    assert result["classification"]["requires_approval"] is True
    assert result["reasoning_profile"]["tier"] == "high_reasoning"
    assert result["routing_strategy"]["strategy"] == "local_high_reasoning"
    assert result["route"]["provider"] == "norllama"
    assert result["route"]["cloud_proxy"] is False
    assert result["recommendation"]["execution_allowed"] is False
    assert result["recommendation"]["next_hop"] == "local_preflight_or_approval"
    assert result["recommendation"]["cloud_last_resort"] is True


def test_prompt_load_balancer_routes_artifacts_to_local_specialist_strategy():
    result = balance_prompt(
        prompt="transcribe this clip and summarize the action items",
        artifacts=[
            {
                "name": "meeting.wav",
                "content_type": "audio/wav",
                "sha256": "abc",
            }
        ],
    )

    assert result["classification"]["task_kind"] == "asr"
    assert result["reasoning_profile"]["tier"] == "specialist"
    assert result["routing_strategy"]["strategy"] == "local_specialist"
    assert result["recommendation"]["primary_executor"] == "norllama_asr"
    assert result["recommendation"]["selected_runtime"] == "localllm"


def test_prompt_load_balancer_marks_policy_work_as_high_reasoning_local_first():
    result = balance_prompt(
        prompt=(
            "Review the routing architecture and policy proof before release; "
            "explain whether the failover design is safe."
        ),
    )

    assert result["classification"]["intent"] == "verify_or_audit"
    assert result["reasoning_profile"]["tier"] == "high_reasoning"
    assert result["routing_strategy"]["strategy"] == "local_high_reasoning"
    assert result["routing_strategy"]["cloud_position"] == (
        "last_resort_after_local_receipt"
    )
    assert result["recommendation"]["primary_executor"] == (
        "spark_high_reasoning_local"
    )
    assert result["recommendation"]["selected_runtime"] == "localllm"


def test_prompt_load_balancer_only_uses_cloud_when_explicitly_forced():
    result = balance_prompt(
        prompt="Use Bedrock to judge this high-regret rollout.",
        requested_runtime="bedrock",
        requested_model="bedrock-test-model",
        force_requested_runtime=True,
        allow_cloud_escalation=True,
    )

    assert result["route"]["provider"] == "aws-bedrock"
    assert result["route"]["cloud_proxy"] is True
    assert result["route"]["local"] is False
    assert result["recommendation"]["selected_runtime"] == "aws-bedrock"
    assert result["recommendation"]["cloud_last_resort"] is True


def test_prompt_load_balancer_capabilities_document_intermediary_mode():
    capabilities = prompt_load_balancer_capabilities()

    assert capabilities["available"] is True
    assert capabilities["mode"] == "prompt_load_balancer"
    assert capabilities["supports"]["deterministic_prefilter"] is True
    assert capabilities["supports"]["reasoning_tier_selection"] is True
    assert capabilities["supports"]["local_first"] is True
    assert capabilities["supports"]["cloud_last_resort"] is True
    assert capabilities["supports"]["provider_adapter_mode"] is True
    assert capabilities["supports"]["transparent_mitm_required"] is False
    assert "high_reasoning" in capabilities["reasoning_tiers"]
    assert "provider_adapter" in {
        item["mode"] for item in capabilities["integration_modes"]
    }
    assert "quick_status" in capabilities["quick_intents"]


def test_prompt_router_api_returns_load_balancer_decision(test_app):
    response = test_app.post(
        "/api/v1/prompt-router/route",
        json={"prompt": "status?", "source": "norman", "session": "norman-codex"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "norman.prompt-load-balancer.v1"
    assert payload["classification"]["intent"] == "quick_status"
    assert payload["route"]["provider"] == "norllama"
    assert payload["recommendation"]["selected_runtime"] == "localllm"


def test_prompt_router_api_rejects_blank_prompt(test_app):
    response = test_app.post("/api/v1/prompt-router/route", json={"prompt": " "})

    assert response.status_code == 400
