from app.services.prompt_load_balancer import (
    balance_prompt,
    prompt_load_balancer_capabilities,
    provider_adapter_decision,
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


def test_openai_chat_adapter_routes_status_local_first():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload={
            "model": "gpt-5.5",
            "messages": [
                {"role": "system", "content": "You are Uplink."},
                {"role": "user", "content": "status?"},
            ],
            "norman": {
                "source": "uplink",
                "session": "uplink-codex",
            },
        },
    )

    assert result["schema"] == "norman.prompt-provider-adapter.v1"
    assert result["mode"] == "provider_adapter"
    assert result["provider"] == "openai"
    assert result["endpoint"] == "openai.chat.completions"
    assert result["adapter_mode"] == "route_only"
    assert result["execution_performed"] is False
    assert result["transparent_mitm"] is False
    assert result["caller_request"]["model"] == "gpt-5.5"
    assert result["selected_runtime"] == "localllm"
    assert result["selected_provider"] == "norllama"
    assert result["norman_route"]["classification"]["intent"] == "quick_status"
    assert result["norman_route"]["routing_strategy"]["strategy"] == "simple_local"


def test_openai_chat_adapter_only_forces_cloud_when_explicit():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "status?"}],
            "norman": {
                "force_requested_runtime": True,
                "allow_cloud_escalation": True,
            },
        },
    )

    assert result["selected_runtime"] == "openai"
    assert result["selected_provider"] == "openai"
    assert result["norman_route"]["route"]["cloud_proxy"] is True


def test_openai_chat_adapter_does_not_trust_caller_route_policy():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "status?"}],
            "norman": {
                "route_policy": {
                    "provider": "openai",
                    "allow_cloud_proxy": True,
                    "route_lock": True,
                    "model": "gpt-5.5",
                }
            },
        },
    )

    assert result["caller_request"]["route_policy_supplied"] is True
    assert result["caller_request"]["route_policy_trusted"] is False
    assert result["selected_runtime"] == "localllm"
    assert result["selected_provider"] == "norllama"


def test_openai_responses_adapter_extracts_structured_input():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.responses",
        payload={
            "model": "gpt-5.5",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Review the routing proof before release.",
                        }
                    ],
                }
            ],
        },
    )

    assert "Review the routing proof" in result["normalized_prompt"]
    assert result["norman_route"]["reasoning_profile"]["tier"] == "high_reasoning"
    assert result["selected_runtime"] == "localllm"


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
    assert capabilities["supports"]["openai_chat_completions_adapter"] is True
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


def test_prompt_router_openai_chat_adapter_api(test_app):
    response = test_app.post(
        "/api/v1/prompt-router/adapters/openai/chat/completions",
        json={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "stauts?"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "norman.prompt-provider-adapter.v1"
    assert payload["selected_runtime"] == "localllm"
    assert payload["norman_route"]["classification"]["intent"] == "quick_status"


def test_prompt_router_openai_chat_adapter_rejects_missing_prompt(test_app):
    response = test_app.post(
        "/api/v1/prompt-router/adapters/openai/chat/completions",
        json={"model": "gpt-5.5", "messages": []},
    )

    assert response.status_code == 400
