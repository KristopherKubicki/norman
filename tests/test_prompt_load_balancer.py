from app.services.prompt_load_balancer import (
    balance_prompt,
    prompt_load_balancer_capabilities,
    provider_adapter_decision,
)
from app.services.prompt_provider_facade import (
    FacadeError,
    execute_openai_chat_facade,
    execute_openai_responses_facade,
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


def test_openai_chat_adapter_transparent_log_only_is_advisory():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "status?"}],
            "norman": {"adapter_mode": "transparent_log_only"},
        },
    )

    assert result["adapter_mode"] == "transparent_log_only"
    assert result["adapter_mode_policy"]["enforcement_level"] == "observe_only"
    assert result["adapter_mode_policy"]["mutates_request"] is False
    assert result["adapter_mode_policy"]["blocks_request"] is False
    assert result["advisory_only"] is True
    assert result["integration_contract"]["transparent_network_interception"] is False
    assert result["integration_contract"]["client_action"] == (
        "forward_original_provider_request_after_recording_route_receipt"
    )


def test_openai_chat_adapter_guardrail_mode_can_hold_risky_prompts():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload={
            "model": "gpt-5.5",
            "messages": [
                {
                    "role": "user",
                    "content": "restart uplink and push the deployment",
                }
            ],
            "norman": {"adapter_mode": "guardrail"},
        },
    )

    assert result["adapter_mode"] == "guardrail"
    assert result["adapter_mode_policy"]["blocks_request"] is True
    assert result["norman_route"]["recommendation"]["requires_approval"] is True
    assert result["next_hop"] == "local_preflight_or_approval"


def test_openai_chat_adapter_strict_local_disables_cloud_escalation():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "review release policy proof"}],
            "norman": {"adapter_mode": "strict_local"},
        },
    )

    assert result["adapter_mode"] == "strict_local"
    assert result["adapter_mode_policy"]["cloud_allowed"] is False
    assert result["cloud_position"] == "disabled"
    assert result["selected_runtime"] == "localllm"


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
    assert "intelligence" in {
        item["mode"] for item in capabilities["intermediary_modes"]
    }
    assert "transparent_log_only" in {
        item["mode"] for item in capabilities["intermediary_modes"]
    }
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


def _mock_local_chat(messages, model, **kwargs):
    return {
        "model": model,
        "choices": [{"message": {"content": "local ok"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        "headers": {"x-norllama-worker-endpoint": "http://192.168.2.151:18151"},
        "raw": {"messages": messages, "kwargs": kwargs},
    }


def _proxy_headers(monkeypatch):
    monkeypatch.setenv("NORMAN_PROMPT_PROXY_TOKEN", "proxy-token")
    return {"Authorization": "Bearer proxy-token"}


def _local_route_envelope(**overrides):
    route = {
        "local": True,
        "cloud_proxy": False,
        "attribution": {
            "route_policy_authorization": {
                "allowed": True,
                "integrity_valid": True,
                "lifecycle_state": "valid",
                "default_route_allowed": True,
            }
        },
    }
    recommendation = {
        "execution_allowed": True,
        "requires_approval": False,
        "task_kind": "summarize",
        "reasoning_tier": "simple",
    }
    decision = {"allowed": True}
    route.update(overrides.pop("route", {}))
    recommendation.update(overrides.pop("recommendation", {}))
    decision.update(overrides.pop("decision", {}))
    envelope = {
        "selected_runtime": "localllm",
        "selected_provider": "norllama",
        "selected_model": "qwen3.6:35b-a3b-q4_K_M",
        "norman_route": {
            "route": route,
            "recommendation": recommendation,
            "decision": decision,
        },
    }
    envelope.update(overrides)
    return envelope


def test_openai_compat_chat_completions_routes_local_first(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", _mock_local_chat)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "status?"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"] == "local ok"
    assert payload["model"].startswith("qwen3.6")
    assert payload["usage"]["total_tokens"] == 6
    assert payload["norman"]["local_execution"] is True
    assert payload["norman"]["cloud_forwarding"] is False
    assert payload["norman"]["route"]["selected_runtime"] == "localllm"
    assert payload["norman"]["route"]["selected_provider"] == "norllama"
    assert payload["norman"]["norllama"]["observed_worker"] == "spark-151"
    assert payload["norman"]["norllama"]["observed_worker_source"] == "gateway_headers"


def test_openai_compat_chat_completions_streams_sse(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", _mock_local_chat)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "status?"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert "data:" in response.text
    assert "local ok" in response.text
    assert "data: [DONE]" in response.text


def test_openai_compat_responses_routes_local_first(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", _mock_local_chat)

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "gpt-5.5", "input": "status?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "response"
    assert payload["status"] == "completed"
    assert payload["output_text"] == "local ok"
    assert payload["usage"]["total_tokens"] == 6
    assert payload["norman"]["local_execution"] is True


def test_openai_compat_models_requires_proxy_token_when_configured(
    test_app,
    monkeypatch,
):
    headers = _proxy_headers(monkeypatch)

    denied = test_app.get("/v1/models")
    assert denied.status_code == 401
    assert denied.json()["error"]["type"] == "authentication_error"

    allowed = test_app.get(
        "/v1/models",
        headers=headers,
    )
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["object"] == "list"
    assert payload["norman"]["base_url"] == "/v1"


def test_openai_compat_auth_fails_closed_without_facade_token(test_app, monkeypatch):
    monkeypatch.delenv("NORMAN_PROMPT_PROXY_TOKEN", raising=False)

    for method, path, body in [
        ("get", "/v1/models", None),
        (
            "post",
            "/v1/chat/completions",
            {"model": "gpt-5.5", "messages": [{"role": "user", "content": "status?"}]},
        ),
        ("post", "/v1/responses", {"model": "gpt-5.5", "input": "status?"}),
    ]:
        request = getattr(test_app, method)
        response = request(path, json=body) if body is not None else request(path)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "proxy_token_not_configured"


def test_openai_compat_rejects_unsupported_tool_parameters(test_app, monkeypatch):
    headers = _proxy_headers(monkeypatch)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "status?"}],
            "tools": [{"type": "function", "name": "shell"}],
        },
    )

    assert response.status_code == 501
    error = response.json()["error"]
    assert error["type"] == "unsupported_parameter"
    assert error["param"] == "tools"


def test_openai_compat_blocks_requires_approval_before_model_call(monkeypatch):
    import app.services.prompt_provider_facade as facade

    calls = []
    monkeypatch.setattr(
        facade,
        "provider_adapter_decision",
        lambda **kwargs: _local_route_envelope(
            recommendation={"execution_allowed": False, "requires_approval": True}
        ),
    )
    monkeypatch.setattr(
        facade.norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: calls.append(kwargs) or _mock_local_chat([], "qwen3.6:27b"),
    )

    try:
        execute_openai_chat_facade(
            {"model": "gpt-5.5", "messages": [{"role": "user", "content": "restart"}]}
        )
    except FacadeError as exc:
        assert exc.code == "facade_policy_blocked"
    else:
        raise AssertionError("expected facade policy block")

    assert calls == []


def test_openai_compat_rejects_inconsistent_or_cloud_proxy_routes(monkeypatch):
    import app.services.prompt_provider_facade as facade

    variants = [
        _local_route_envelope(selected_runtime="openai", selected_provider="norllama"),
        _local_route_envelope(selected_runtime="localllm", selected_provider="openai"),
        _local_route_envelope(route={"local": False, "cloud_proxy": True}),
    ]
    calls = []
    monkeypatch.setattr(
        facade.norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: calls.append(kwargs) or _mock_local_chat([], "qwen3.6:27b"),
    )

    for route in variants:
        monkeypatch.setattr(facade, "provider_adapter_decision", lambda **_: route)
        try:
            execute_openai_chat_facade(
                {
                    "model": "gpt-5.5",
                    "messages": [{"role": "user", "content": "status?"}],
                }
            )
        except FacadeError as exc:
            assert exc.code == "facade_policy_blocked"
        else:
            raise AssertionError("expected local-only predicate failure")

    assert calls == []


def test_openai_compat_rejects_unprivileged_raw_backend_model(monkeypatch):
    import app.services.prompt_provider_facade as facade

    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    try:
        execute_openai_chat_facade(
            {
                "model": "qwen3.6:35b-a3b-q4_K_M",
                "messages": [{"role": "user", "content": "status?"}],
            }
        )
    except FacadeError as exc:
        assert exc.code == "raw_model_not_allowed"
    else:
        raise AssertionError("expected raw model rejection")


def test_openai_compat_responses_routes_once_and_preserves_instructions(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    decisions = []
    invocations = []

    def fake_decision(**kwargs):
        decisions.append(kwargs)
        return _local_route_envelope(selected_model="qwen3.6:27b")

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"])

    monkeypatch.setattr(facade, "provider_adapter_decision", fake_decision)
    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)

    response = execute_openai_responses_facade(
        {
            "model": "gpt-5.5",
            "instructions": "Answer briefly.",
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "Preserve this role."}],
                },
                {"role": "user", "content": "status?"},
            ],
        }
    )

    assert response["object"] == "response"
    assert len(decisions) == 1
    assert len(invocations) == 1
    assert invocations[0]["model"] == "qwen3.6:27b"
    assert invocations[0]["messages"] == [
        {"role": "system", "content": "Answer briefly."},
        {"role": "developer", "content": "Preserve this role."},
        {"role": "user", "content": "status?"},
    ]


def test_openai_compat_responses_can_return_explicit_tool_call(monkeypatch):
    import app.services.prompt_provider_facade as facade

    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )
    monkeypatch.setattr(
        facade.norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: _mock_local_chat(
            kwargs["messages"],
            kwargs["model"],
        )
        | {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"shell","arguments":{"cmd":"pwd"}}}'
                        )
                    }
                }
            ]
        },
    )

    response = execute_openai_responses_facade(
        {
            "model": "gpt-5.5",
            "input": "check the repo",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "shell",
                        "description": "Run a shell command.",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        }
    )

    assert response["output_text"] == ""
    assert response["output"][0]["type"] == "function_call"
    assert response["output"][0]["name"] == "shell"
    assert response["output"][0]["arguments"] == '{"cmd":"pwd"}'
    compat = response["norman"]["responses_compatibility"]
    assert compat["tools_declared"] == 1
    assert compat["tool_calls_returned"] == 1
    assert response["norman"]["route_receipt"]["schema"] == (
        "norman.norllama.route-receipt.v1"
    )


def test_openai_compat_responses_replays_previous_response_and_tool_output(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    invocations = []
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"])

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)

    first = execute_openai_responses_facade(
        {"model": "gpt-5.5", "input": "remember alpha"}
    )
    second = execute_openai_responses_facade(
        {
            "model": "gpt-5.5",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_shell",
                    "output": "tool says beta",
                },
                {"role": "user", "content": "continue"},
            ],
        }
    )

    assert second["norman"]["responses_compatibility"]["history_replayed"] is True
    replayed = invocations[-1]["messages"]
    assert {"role": "assistant", "content": "local ok"} in replayed
    assert {
        "role": "tool",
        "content": "Tool output for call_shell: tool says beta",
    } in replayed
    assert {"role": "user", "content": "continue"} in replayed


def test_openai_compat_proxy_observability_records_success_without_prompt_leak(
    test_app,
    monkeypatch,
):
    from app.services.prompt_provider_facade import norllama_gateway
    from app.services.proxy_observability import reset_proxy_events

    reset_proxy_events()
    headers = {
        **_proxy_headers(monkeypatch),
        "X-Norman-Client": "codex-work",
        "X-Norman-Team": "platform",
    }
    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", _mock_local_chat)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "status? secret-value"}],
        },
    )

    assert response.status_code == 200
    summary = test_app.get("/v1/norman/proxy/summary", headers=headers).json()
    assert summary["schema"] == "norman.proxy.observability-summary.v1"
    assert summary["event_count"] == 1
    assert summary["local_execution_count"] == 1
    assert summary["local_route_rate_pct"] == 100.0
    assert summary["release_proof_success_count"] == 1
    assert summary["release_proof_rate_pct"] == 100.0
    assert summary["route_receipt_count"] == 1
    assert summary["receipt_audit_pass_count"] == 1
    assert summary["completion_gate_pass_count"] == 1
    assert summary["receiptless_success_count"] == 0
    assert summary["audit_failed_success_count"] == 0
    assert summary["completion_gate_failed_success_count"] == 0
    assert summary["unknown_execution_mode_success_count"] == 0
    assert summary["usage_totals"]["local_tokens"] == 6
    assert summary["usage_totals"]["cloud_llm_tokens"] == 0
    assert summary["by_client"]["codex-work"] == 1
    assert summary["by_worker"]["spark-151"] == 1
    assert summary["alerts"] == []

    events = test_app.get("/v1/norman/proxy/events", headers=headers).json()["events"]
    assert len(events) == 1
    assert events[0]["prompt_sha256"]
    assert events[0]["prompt_chars"] == len("status? secret-value")
    assert events[0]["route_receipt_present"] is True
    assert events[0]["receipt_audit_passed"] is True
    assert events[0]["completion_gate_passed"] is True
    assert events[0]["execution_mode"] == "prompt_intermediary_openai_facade"
    assert events[0]["policy_id"]
    assert "secret-value" not in str(events[0])


def test_openai_compat_proxy_observability_reports_auth_and_unsupported_alerts(
    test_app,
    monkeypatch,
):
    from app.services.proxy_observability import reset_proxy_events

    reset_proxy_events()
    headers = _proxy_headers(monkeypatch)

    denied = test_app.get("/v1/models")
    assert denied.status_code == 401

    unsupported = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "gpt-5.5",
            "input": "status?",
            "background": True,
        },
    )
    assert unsupported.status_code == 501

    alerts = test_app.get("/v1/norman/proxy/alerts", headers=headers).json()
    kinds = {item["kind"] for item in alerts["alerts"]}
    assert "proxy_auth_failures" in kinds
    assert "proxy_unsupported_client_semantics" in kinds

    dashboard = test_app.get("/v1/norman/proxy/dashboard", headers=headers).json()
    assert dashboard["schema"] == "norman.proxy.dashboard.v1"
    assert any(widget["id"] == "alerts" for widget in dashboard["widgets"])


def test_proxy_observability_flags_cloud_forwarding_and_missing_worker():
    from app.services.proxy_observability import (
        proxy_observability_summary,
        record_proxy_event,
        reset_proxy_events,
    )

    reset_proxy_events()
    record_proxy_event(
        endpoint="/v1/chat/completions",
        method="POST",
        request_id="cloud-test",
        status="success",
        http_status=200,
        payload={"model": "gpt-5.5", "messages": [{"content": "status?"}]},
        response={
            "model": "gpt-5.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "norman": {
                "local_execution": False,
                "cloud_forwarding": True,
                "route": {
                    "selected_runtime": "openai",
                    "selected_provider": "openai",
                    "norman_route": {"route": {"cloud_proxy": True}},
                },
            },
        },
    )
    record_proxy_event(
        endpoint="/v1/chat/completions",
        method="POST",
        request_id="workerless-test",
        status="success",
        http_status=200,
        payload={"model": "norman-local", "messages": [{"content": "status?"}]},
        response={
            "model": "qwen3.6:27b",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "norman": {
                "local_execution": True,
                "cloud_forwarding": False,
                "norllama": {},
            },
        },
    )

    summary = proxy_observability_summary()
    kinds = {item["kind"] for item in summary["alerts"]}
    assert summary["cloud_tokens"] == 15
    assert summary["workerless_local_success_count"] == 1
    assert summary["receiptless_success_count"] == 2
    assert summary["release_proof_success_count"] == 0
    assert summary["unknown_execution_mode_success_count"] == 2
    assert "proxy_cloud_route_observed" in kinds
    assert "proxy_missing_worker_attribution" in kinds
    assert "proxy_missing_route_receipt" in kinds
    assert "proxy_unknown_execution_mode" in kinds


def test_proxy_observability_flags_failed_receipts_and_completion_gates():
    from app.services.proxy_observability import (
        proxy_observability_summary,
        record_proxy_event,
        reset_proxy_events,
    )

    reset_proxy_events()
    record_proxy_event(
        endpoint="/v1/chat/completions",
        method="POST",
        request_id="audit-test",
        status="success",
        http_status=200,
        payload={"model": "norman-local", "messages": [{"content": "status?"}]},
        response={
            "model": "qwen3.6:27b",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "norman": {
                "local_execution": True,
                "cloud_forwarding": False,
                "norllama": {"observed_worker": "spark-151"},
                "route_receipt": {
                    "request_id": "audit-test",
                    "job_id": "audit-test",
                    "invocation_id": "audit-test",
                    "execution_mode": "prompt_intermediary_openai_facade",
                    "observed_worker": "spark-151",
                    "usage_bucket": "offline_local",
                    "receipt_audit": {
                        "status": "fail",
                        "pass": False,
                        "failures": ["bad policy"],
                    },
                    "completion_gate": {"gate_passed": False},
                },
            },
        },
    )

    summary = proxy_observability_summary()
    kinds = {item["kind"] for item in summary["alerts"]}
    assert summary["route_receipt_count"] == 1
    assert summary["receipt_audit_pass_count"] == 0
    assert summary["completion_gate_pass_count"] == 0
    assert summary["audit_failed_success_count"] == 1
    assert summary["completion_gate_failed_success_count"] == 1
    assert summary["release_proof_success_count"] == 0
    assert "proxy_receipt_audit_failed" in kinds
    assert "proxy_completion_gate_failed" in kinds
