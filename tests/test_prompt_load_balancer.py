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
    assert result["route"]["provider"] == "norllama"
    assert result["route"]["local"] is True
    assert result["route"]["cloud_proxy"] is False
    assert result["recommendation"]["selected_runtime"] == "localllm"
    assert result["recommendation"]["local_first"] is True
    assert result["recommendation"]["cloud_last_resort"] is True
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
    assert result["route"]["provider"] == "norllama"
    assert result["route"]["cloud_proxy"] is False
    assert result["recommendation"]["execution_allowed"] is False
    assert result["recommendation"]["next_hop"] == "local_preflight_or_approval"
    assert result["recommendation"]["cloud_last_resort"] is True


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
    assert capabilities["supports"]["local_first"] is True
    assert capabilities["supports"]["cloud_last_resort"] is True
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
