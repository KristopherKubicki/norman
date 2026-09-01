import asyncio
import json
import logging
import threading
import time
from pathlib import Path

import httpx
import pytest
import requests

from app.core.estate_registry import resident_model
from app.services.console_runtime.types import ModelResult, ModelUsage
from app.services.prompt_load_balancer import (
    balance_prompt,
    prompt_load_balancer_capabilities,
    provider_adapter_decision,
)
from app.services.norllama import gateway as norllama_gateway
from app.services.norllama.route_policy import ROUTE_POLICY_PLACEMENT
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
    assert result["reasoning_orchestration"]["reasoning_tier"]["tier"] == "instant"
    assert result["work_classification"]["work_class"] == "local"
    assert (
        result["recommendation"]["work_classification"]
        == (result["work_classification"])
    )
    assert (
        result["route_receipt_preview"]["work_classification"]
        == (result["work_classification"])
    )
    assert (
        "kpi.status_snapshot" in result["reasoning_orchestration"]["selected_skill_ids"]
    )
    assert result["recommendation"]["max_tool_iterations"] == 1
    assert result["recommendation"]["continuous_tool_use"] is False
    assert result["route_receipt_preview"]["execution_performed"] is False
    assert result["route_receipt_preview"]["reasoning_receipt"]["schema"] == (
        "norman.reasoning-orchestrator.receipt.v1"
    )


def test_prompt_load_balancer_routes_broad_tui_planning_to_local_reasoning():
    result = balance_prompt(
        prompt="what happened with the plan for forking TUIs into multiple sessions?",
        source="uplink",
        session="uplink-codex",
    )

    assert result["classification"]["intent"] == "planning_or_architecture"
    assert result["classification"]["task_kind"] == "plan"
    assert result["classification"]["signals"]["status"] is False
    assert result["reasoning_profile"]["tier"] == "high_reasoning"
    assert result["routing_strategy"]["strategy"] == "local_high_reasoning"
    assert result["route"]["provider"] == "norllama"
    assert result["route"]["local"] is True
    assert result["route"]["cloud_proxy"] is False
    assert result["recommendation"]["selected_runtime"] == "localllm"
    assert result["recommendation"]["cloud_last_resort"] is True
    assert result["work_classification"]["work_class"] == "local_review"
    assert (
        result["reasoning_orchestration"]["work_classification"]
        == (result["work_classification"])
    )


def test_prompt_load_balancer_routes_reply_tail_buttons() -> None:
    simpler = balance_prompt(prompt="simpler")
    verify = balance_prompt(prompt="verify")
    dig = balance_prompt(prompt="dig")
    copy = balance_prompt(prompt="copy")

    assert simpler["classification"]["intent"] == "simplify_response"
    assert simpler["reasoning_profile"]["tier"] == "simple"
    assert simpler["recommendation"]["selected_runtime"] == "localllm"

    assert verify["classification"]["intent"] == "verify_or_audit"
    assert verify["reasoning_profile"]["tier"] == "high_reasoning"
    assert verify["routing_strategy"]["strategy"] == "local_high_reasoning"
    assert verify["recommendation"]["selected_runtime"] == "localllm"

    assert dig["classification"]["intent"] == "deep_dive"
    assert dig["reasoning_profile"]["tier"] == "high_reasoning"
    assert dig["recommendation"]["selected_runtime"] == "localllm"

    assert copy["classification"]["intent"] == "copy_response"
    assert copy["stateful_control"]["applies"] is True
    assert copy["recommendation"]["selected_action"] == (
        "deterministic_copy_latest_response"
    )
    assert copy["recommendation"]["execution_allowed"] is True


def test_prompt_load_balancer_blocks_unbound_handoff_button() -> None:
    result = balance_prompt(prompt="handoff this to scout")

    assert result["classification"]["intent"] == "handoff_or_relay"
    assert result["stateful_control"]["applies"] is True
    assert result["recommendation"]["tool_selection"] == "relay_broker"
    assert result["recommendation"]["execution_allowed"] is False
    assert (
        "no_active_job_bound_to_terse_command" in result["stateful_control"]["blockers"]
    )


def test_prompt_load_balancer_bad_route_corpus_stays_local_first():
    corpus_path = (
        Path(__file__).resolve().parents[1] / "db" / "prompt_bad_route_corpus.json"
    )
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    assert corpus["schema"] == "norman.prompt-bad-route-corpus.v2"
    for case in corpus["cases"]:
        result = balance_prompt(
            prompt=case["prompt"],
            requested_runtime="codex",
            requested_model="gpt-5.5",
            force_requested_runtime=False,
            context=case.get("context", {}),
        )

        assert result["classification"]["intent"] == case["expected_intent"]
        assert result["recommendation"]["selected_runtime"] == case["expected_runtime"]
        assert result["route"]["provider"] == "norllama"
        assert result["route"]["local"] is True
        assert result["route"]["cloud_proxy"] is False
        assert result["recommendation"]["requires_approval"] is bool(
            case["requires_approval"]
        )
        assert result["recommendation"]["selected_action"] == case["expected_action"]
        assert (
            result["recommendation"]["execution_permission"]
            == case["expected_execution_permission"]
        )
        assert result["recommendation"]["tool_selection"]
        assert result["recommendation"]["control_route"] == "local_control_prefilter"
        assert result["recommendation"]["visible_response"]
        assert result["stateful_control"]["receipt"]["required"] is True


def test_prompt_load_balancer_blocks_unbound_go_ahead_for_risky_pending_action():
    result = balance_prompt(
        prompt="go ahead",
        context={
            "active_job_count": 1,
            "active_job_id": "deploy-42",
            "target_identity": "deploy-42",
            "pending_action_kind": "deploy_release",
            "pending_action_risk": "prod_write",
            "pending_action_digest": "sha256:deploy42",
        },
    )

    assert result["classification"]["intent"] == "continue_work"
    assert result["stateful_control"]["execution_permission"] == "blocked"
    assert "missing_valid_bound_approval" in result["stateful_control"]["blockers"]
    assert result["recommendation"]["execution_allowed"] is False
    assert result["recommendation"]["requires_approval"] is True
    assert result["recommendation"]["next_hop"] == "local_preflight_or_approval"


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
    assert result["work_classification"]["work_class"] == "approval_required"


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
    assert (
        "kpi.release_packet" in result["reasoning_orchestration"]["selected_skill_ids"]
    )
    assert result["recommendation"]["continuous_tool_use"] is True
    assert result["recommendation"]["max_tool_iterations"] >= 8


def test_prompt_load_balancer_adds_kpi_skill_orchestration_for_cutover_work():
    result = balance_prompt(
        prompt=(
            "Build the cutover KPI packet: signed receipts, local/cloud/search "
            "ledger, benchmark freshness, and 20 operator turns."
        ),
        source="norman",
        session="norman-codex",
    )

    plan = result["reasoning_orchestration"]
    assert plan["schema"] == "norman.reasoning-orchestrator.plan.v1"
    assert "kpi.receipt_integrity" in plan["selected_skill_ids"]
    assert "kpi.operator_cohort" in plan["selected_skill_ids"]
    assert "kpi.cost_counterfactual" in plan["selected_skill_ids"]
    assert plan["tool_plan"]["continuous_tool_use"] is True
    assert "signed_receipt_ledger" in plan["tool_plan"]["required_tools"]
    assert "usage_bucket_validator" in plan["tool_plan"]["verification_tools"]
    assert result["recommendation"]["cloud_last_resort"] is True
    assert (
        result["route_receipt_preview"]["reasoning_receipt"]["plan_id"]
        == (plan["plan_id"])
    )


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
    assert result["work_classification"]["work_class"] == "frontier"
    assert "effective_frontier_runtime" in result["work_classification"]["reason_codes"]


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
                    "gateway_route": "forged-route",
                    "source_tui": "forged-tui",
                }
            },
        },
    )

    assert result["caller_request"]["route_policy_supplied"] is True
    assert result["caller_request"]["route_policy_trusted"] is False
    assert result["trusted_gateway_context"] == {}
    assert result["selected_runtime"] == "localllm"
    assert result["selected_provider"] == "norllama"


def test_openai_chat_adapter_retains_server_supplied_gateway_context():
    gateway = {
        "gateway_route": "gold-book",
        "source_tui": "gold-book",
        "policy_scope": "tui:gold-book",
    }
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.chat.completions",
        payload={
            "model": "norman-code",
            "messages": [{"role": "user", "content": "status?"}],
        },
        trusted_context=gateway,
    )

    assert result["trusted_gateway_context"] == gateway
    assert result["caller_request"]["trusted_gateway_context"] is True
    assert (
        result["norman_route"]["decision"]["metadata"]["route_policy"]["gateway_route"]
        == "gold-book"
    )


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


def test_openai_responses_adapter_classifies_latest_user_turn_only():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.responses",
        payload={
            "model": "norman-code",
            "input": [
                {
                    "role": "developer",
                    "content": "Do not stop at analysis; restart only when asked.",
                },
                {
                    "role": "user",
                    "content": "Repository instruction: deploy changes after release review.",
                },
                {
                    "role": "system",
                    "content": (
                        "Tool contract: shell commands can restart services or "
                        "delete temporary files."
                    ),
                },
                {"role": "user", "content": "Reply with exactly: route-ok"},
            ],
        },
    )

    assert result["normalized_prompt"] == "Reply with exactly: route-ok"
    assert result["caller_request"]["policy_prompt_source"] == "latest_user_turn"
    assert result["norman_route"]["classification"]["risk_class"] == "read_only"
    assert result["norman_route"]["recommendation"]["requires_approval"] is False
    assert result["norman_route"]["recommendation"]["execution_allowed"] is True


def test_openai_responses_adapter_routes_incident_handoff_filename_as_read_only():
    prompt = (
        "Can you look into this incident and give me recommendations? "
        "~/code/norman/docs/spark_network_dhcp_incident_handoff.md"
    )
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.responses",
        payload={
            "model": "gpt-5.6-terra",
            "input": prompt,
        },
    )

    assert result["normalized_prompt"] == prompt
    assert result["norman_route"]["classification"]["risk_class"] == "read_only"
    assert result["norman_route"]["classification"]["intent"] != "handoff_or_relay"
    assert result["norman_route"]["recommendation"]["requires_approval"] is False
    assert result["norman_route"]["recommendation"]["execution_allowed"] is True


def test_openai_responses_adapter_still_blocks_mutating_latest_user_turn():
    result = provider_adapter_decision(
        provider="openai",
        endpoint="openai.responses",
        payload={
            "model": "norman-code",
            "input": [
                {
                    "role": "developer",
                    "content": "Answer helpfully and do not execute commands yourself.",
                },
                {
                    "role": "user",
                    "content": "Restart the Goldbook production service.",
                },
            ],
        },
    )

    assert result["norman_route"]["classification"]["risk_class"] == (
        "external_mutation"
    )
    assert result["norman_route"]["recommendation"]["requires_approval"] is True
    assert result["norman_route"]["recommendation"]["execution_allowed"] is False


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
    assert capabilities["supports"]["reasoning_orchestration"] is True
    assert capabilities["supports"]["skill_registry"] is True
    assert capabilities["supports"]["kpi_background_skills"] is True
    assert capabilities["supports"]["continuous_tool_use_plan"] is True
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
    assert "kpi.status_snapshot" in capabilities["skill_registry"]["skill_ids"]
    assert capabilities["kpi_background_loop"]["cloud_allowed"] is False


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


def _mock_bedrock_result(
    text: str = "cloud ok",
    *,
    model: str = "openai.gpt-5.6-terra",
    metadata: dict | None = None,
) -> ModelResult:
    return ModelResult(
        provider="bedrock",
        model=model,
        text=text,
        usage=ModelUsage(input_tokens=7, output_tokens=3, total_tokens=10),
        metadata=metadata or {},
    )


def _install_bedrock_stub(
    monkeypatch,
    *,
    result: ModelResult | None = None,
    error: Exception | None = None,
    delay_seconds: float = 0.0,
):
    from app.services import prompt_provider_facade

    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_enabled",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_aws_region",
        "us-east-2",
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_credentials_secret",
        "test/bedrock-fallback",
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_explicit_cloud_mantle_api_key_secret",
        "test/bedrock-mantle",
        raising=False,
    )
    calls = []

    class StubBedrockModelAdapter:
        def invoke(self, request):
            calls.append(request)
            if delay_seconds:
                time.sleep(delay_seconds)
            if error is not None:
                raise error
            return result or _mock_bedrock_result()

    monkeypatch.setattr(
        prompt_provider_facade,
        "BedrockModelAdapter",
        StubBedrockModelAdapter,
    )
    return calls


def test_explicit_cloud_timeout_is_independent_from_short_provider_timeout(
    monkeypatch,
):
    from app.services import prompt_provider_facade

    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "llm_provider_timeout_seconds",
        30,
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "console_runtime_bedrock_timeout_seconds",
        300,
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_explicit_cloud_timeout_seconds",
        1200,
        raising=False,
    )

    assert prompt_provider_facade._explicit_cloud_timeout_seconds() == 1200


def test_explicit_cloud_timeout_is_capped_at_thirty_minutes(monkeypatch):
    from app.services import prompt_provider_facade

    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_explicit_cloud_timeout_seconds",
        7200,
        raising=False,
    )

    assert prompt_provider_facade._explicit_cloud_timeout_seconds() == 1800


def test_explicit_cloud_timeout_failure_is_classified_without_error_text():
    from app.services import prompt_provider_facade

    try:
        try:
            raise TimeoutError("provider detail must remain private")
        except TimeoutError as exc:
            raise RuntimeError("sanitized wrapper") from exc
    except RuntimeError as exc:
        assert (
            prompt_provider_facade._explicit_cloud_failure_code(exc)
            == "explicit_cloud_selection_timeout"
        )


class _MockNativeStreamResponse:
    def __init__(self, lines, *, headers=None):
        self._lines = list(lines)
        self.headers = dict(headers or {})
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            if decode_unicode or not isinstance(line, str):
                yield line
            else:
                yield line.encode("utf-8")

    def close(self):
        self.closed = True


def _response_sse_events(body):
    events = []
    for block in body.split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = line.removeprefix("data: ")
        if data:
            events.append((event, data))
    return events


def _gateway_headers(route: str = "norman"):
    return {"X-Norman-Gateway-Route": route}


def _proxy_headers(monkeypatch, *, route: str = "norman"):
    monkeypatch.setenv("NORMAN_PROMPT_PROXY_TOKEN", "proxy-token")
    return {
        "Authorization": "Bearer proxy-token",
        **_gateway_headers(route),
    }


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


def _capacity_mesh(
    *,
    frontdoor_reachable=True,
    spark_150_reachable=True,
    spark_151_reachable=True,
    spark_150_models=None,
    spark_151_models=None,
    cache_status="refresh",
):
    model = resident_model()
    return {
        "frontdoor": {
            "reachable": frontdoor_reachable,
            "status": "ok" if frontdoor_reachable else "error",
            "models": [model],
        },
        "workers": [
            {
                "id": "mac-mini-133",
                "role": "fallback",
                "memory_gb": 16,
                "reachable": True,
                "status": "ok",
                "models": [model],
            },
            {
                "id": "spark-150",
                "role": "production",
                "memory_gb": 128,
                "reachable": spark_150_reachable,
                "status": "ok" if spark_150_reachable else "error",
                "models": list(
                    spark_150_models if spark_150_models is not None else [model]
                ),
            },
            {
                "id": "spark-151",
                "role": "production",
                "memory_gb": 128,
                "reachable": spark_151_reachable,
                "status": "ok" if spark_151_reachable else "error",
                "models": list(
                    spark_151_models if spark_151_models is not None else [model]
                ),
            },
        ],
        "cache": {
            "status": cache_status,
            "age_seconds": 0,
            "ttl_seconds": 15,
        },
    }


def test_openai_compat_chat_completions_routes_local_first(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch, route="gold-book")
    invocations = []

    def invoke_local_chat(*args, **kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(*args, **kwargs)

    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", invoke_local_chat)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "norman-code",
            "messages": [{"role": "user", "content": "status?"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"] == "local ok"
    assert payload["model"] == resident_model()
    assert payload["usage"]["total_tokens"] == 6
    assert payload["norman"]["local_execution"] is True
    assert payload["norman"]["cloud_forwarding"] is False
    assert payload["norman"]["route"]["selected_runtime"] == "localllm"
    assert payload["norman"]["route"]["selected_provider"] == "norllama"
    assert payload["norman"]["norllama"]["observed_worker"] == "spark-151"
    assert payload["norman"]["norllama"]["observed_worker_source"] == "gateway_headers"
    gateway = {
        "gateway_route": "gold-book",
        "source_tui": "gold-book",
        "policy_scope": "tui:gold-book",
    }
    assert payload["norman"]["gateway"] == gateway
    assert payload["norman"]["route"]["trusted_gateway_context"] == gateway
    receipt = payload["norman"]["facade_receipt"]
    assert receipt["metadata"]["gateway_route"] == "gold-book"
    assert receipt["output"]["source_tui"] == "gold-book"
    assert invocations[0]["correlation_headers"]["X-Norman-Gateway-Route"] == (
        "gold-book"
    )
    assert invocations[0]["correlation_headers"]["X-Norman-Source-Tui"] == ("gold-book")
    assert invocations[0]["correlation_headers"]["X-Norman-Policy-Scope"] == (
        "tui:gold-book"
    )


def test_openai_compat_chat_completions_streams_sse(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", _mock_local_chat)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "norman-code",
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
        json={"model": "norman-code", "input": "status?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "response"
    assert payload["status"] == "completed"
    assert payload["output_text"] == "local ok"
    assert payload["usage"]["total_tokens"] == 6
    assert payload["norman"]["local_execution"] is True


@pytest.mark.parametrize("model", ["gpt-5.6-terra", "openai.gpt-5.6-terra"])
def test_openai_compat_responses_rejects_explicit_cloud_model_for_tui(
    test_app, monkeypatch, model
):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    local_calls = []
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: local_calls.append(kwargs) or _mock_local_chat([], ""),
    )
    bedrock_calls = _install_bedrock_stub(monkeypatch)

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": model, "input": "status?"},
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "tool_capable_model_required"
    assert error["param"] == "model"
    assert "Use norman-code" in error["message"]
    assert error["norman"] == {
        "selected_model": model,
        "required_model": "norman-code",
        "cloud_fallback": "automatic_for_retryable_local_failure",
    }
    assert local_calls == []
    assert bedrock_calls == []


def test_openai_compat_responses_rejects_streaming_explicit_cloud_model_for_tui(
    test_app, monkeypatch
):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    local_calls = []
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: local_calls.append(kwargs),
    )
    bedrock_calls = _install_bedrock_stub(monkeypatch)

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "gpt-5.6-sol", "input": "status?", "stream": True},
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "tool_capable_model_required"
    assert error["param"] == "model"
    assert local_calls == []
    assert bedrock_calls == []


def test_openai_compat_chat_completions_rejects_explicit_cloud_model_for_tui(
    test_app, monkeypatch
):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    local_calls = []
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: local_calls.append(kwargs) or _mock_local_chat([], ""),
    )
    bedrock_calls = _install_bedrock_stub(monkeypatch)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "gpt-5.6-terra",
            "messages": [{"role": "user", "content": "status?"}],
        },
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "tool_capable_model_required"
    assert error["param"] == "model"
    assert "Use norman-code" in error["message"]
    assert local_calls == []
    assert bedrock_calls == []


def test_openai_compat_rejects_unapproved_explicit_cloud_model(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    local_calls = []
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: local_calls.append(kwargs) or _mock_local_chat([], ""),
    )
    bedrock_calls = _install_bedrock_stub(monkeypatch)

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "gpt-unknown", "input": "status?"},
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "unsupported_model"
    assert error["param"] == "model"
    assert local_calls == []
    assert bedrock_calls == []


def test_openai_compat_responses_streams_incremental_sse_with_admission_feedback(
    test_app, monkeypatch
):
    response = _MockNativeStreamResponse(
        [
            '{"model":"qwen3-coder:30b","response":"Hello, "}',
            '{"model":"qwen3-coder:30b","response":"world!\\n"}',
            (
                '{"model":"qwen3-coder:30b","done":true,'
                '"prompt_eval_count":4,"eval_count":2}'
            ),
        ],
        headers={
            "X-Norllama-Admission": "queued",
            "X-Norllama-Queue-Wait-Ms": "42",
            "X-Norllama-Queue-Depth": "1",
            "X-Norllama-Queue-Limit": "1",
            "X-Norllama-Active": "1",
            "X-Norllama-Active-Limit": "1",
        },
    )
    invocations = []

    def invoke_local_stream(**kwargs):
        invocations.append(kwargs)
        return norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        invoke_local_stream,
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={"model": "norman-code", "input": "say hello", "stream": True},
    )

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-cache"
    assert result.headers["x-accel-buffering"] == "no"
    events = _response_sse_events(result.text)
    event_types = [event for event, _data in events]
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    deltas = [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.output_text.delta"
    ]
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )
    admission = {
        "schema": "norman.stream-admission.v1",
        "state": "queued",
        "queue_wait_ms": 42,
        "queue_depth": 1,
        "queue_limit": 1,
        "active": 1,
        "active_limit": 1,
    }

    assert event_types[:2] == ["response.created", "response.in_progress"]
    assert event_types[-2:] == ["response.completed", ""]
    assert [payload["sequence_number"] for payload in payloads] == list(
        range(len(payloads))
    )
    assert "".join(deltas) == "Hello, world!\n"
    assert completed["output_text"] == "Hello, world!\n"
    assert completed["norman"]["streaming_mode"] == "incremental_sse"
    assert completed["norman"]["stream_admission"] == admission
    assert "stream_admission" not in payloads[0]["response"].get("norman", {})
    assert any(
        payload["response"].get("norman", {}).get("stream_admission") == admission
        for payload in payloads
        if payload["type"] == "response.in_progress"
    )
    assert invocations[0]["correlation_headers"]["X-Norman-Execution-Mode"] == (
        "prompt_intermediary_openai_facade"
    )
    assert response.closed is True


@pytest.mark.parametrize(
    "fragments",
    [
        pytest.param(
            [
                "{",
                '"tool',
                '_call":{"name":"ticket_search","arguments":{"query":"P0"}}}',
            ],
            id="split-after-object-open",
        ),
        pytest.param(
            [
                " \n{ \n",
                '"tool',
                '_call" : { "name" : "ticket_search", '
                '"arguments" : { "query" : "P0" } } }',
            ],
            id="whitespace-and-split-tool-key",
        ),
        pytest.param(
            [
                " \n\t",
                "{",
                ' "tool_call"',
                ':{"name":"ticket_search","arguments":{"query":"P0"}}}',
            ],
            id="leading-whitespace-in-own-chunk",
        ),
    ],
)
def test_openai_compat_responses_stream_keeps_tool_envelopes_out_of_text(
    test_app, monkeypatch, fragments
):
    response = _MockNativeStreamResponse(
        [
            *[
                json.dumps(
                    {
                        "model": "qwen3-coder:30b",
                        "response": fragment,
                    }
                )
                for fragment in fragments
            ],
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        ),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={
            "model": "norman-code",
            "input": "Find the highest priority ticket.",
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "name": "ticket_search",
                    "description": "Search Jira tickets.",
                    "parameters": {"type": "object"},
                }
            ],
        },
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    output_items = [
        payload["item"]
        for payload in payloads
        if payload["type"] == "response.output_item.added"
    ]
    function_argument_deltas = [
        payload
        for payload in payloads
        if payload["type"] == "response.function_call_arguments.delta"
    ]
    function_argument_done = next(
        payload
        for payload in payloads
        if payload["type"] == "response.function_call_arguments.done"
    )
    function_item_done = next(
        payload
        for payload in payloads
        if payload["type"] == "response.output_item.done"
    )
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert not any(
        payload["type"] == "response.output_text.delta" for payload in payloads
    )
    assert [item["type"] for item in output_items] == ["function_call"]
    assert output_items[0]["name"] == "ticket_search"
    assert output_items[0]["status"] == "in_progress"
    assert output_items[0]["arguments"] == ""
    assert [event["delta"] for event in function_argument_deltas] == ['{"query":"P0"}']
    assert function_argument_done["arguments"] == '{"query":"P0"}'
    assert function_item_done["item"]["arguments"] == '{"query":"P0"}'
    assert function_argument_done["response_id"] == completed["id"]
    assert function_item_done["response_id"] == completed["id"]
    assert completed["output_text"] == ""
    assert completed["output"][0]["type"] == "function_call"
    assert response.closed is True


def test_openai_compat_responses_stream_keeps_native_function_call_out_of_text(
    test_app, monkeypatch
):
    native_call_id = "call_native_ops_health"
    native_item_id = "fc_native_ops_health"
    native_arguments = "{}"
    native_name = "mcp__ops_openbrand.system_health"
    response = _MockNativeStreamResponse(
        [
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": '{"arguments":"{}",',
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": f'"call_id":"{native_call_id}",',
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": (
                        f'"id":"{native_item_id}",'
                        f'"name":"{native_name}","type":"function_call"}}'
                    ),
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        ),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={
            "model": "norman-code",
            "input": "Check the internal system health.",
            "stream": True,
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__ops_openbrand",
                    "tools": [
                        {
                            "type": "function",
                            "name": "system_health",
                            "description": "Read the current system health.",
                            "parameters": {"type": "object"},
                        }
                    ],
                }
            ],
        },
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    function_item = next(
        payload["item"]
        for payload in payloads
        if payload["type"] == "response.output_item.added"
        and payload["item"]["type"] == "function_call"
    )
    function_argument_deltas = [
        payload
        for payload in payloads
        if payload["type"] == "response.function_call_arguments.delta"
    ]
    function_argument_done = next(
        payload
        for payload in payloads
        if payload["type"] == "response.function_call_arguments.done"
    )
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert not any(
        payload["type"] == "response.output_text.delta" for payload in payloads
    )
    assert function_item == {
        "type": "function_call",
        "id": native_item_id,
        "status": "in_progress",
        "call_id": native_call_id,
        "name": native_name,
        "arguments": "",
    }
    assert [event["delta"] for event in function_argument_deltas] == [native_arguments]
    assert function_argument_done["arguments"] == native_arguments
    assert completed["output_text"] == ""
    assert completed["output"] == [
        {
            "id": native_item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": native_call_id,
            "name": native_name,
            "arguments": native_arguments,
        }
    ]
    assert response.closed is True


def test_openai_compat_responses_stream_continues_native_tool_call(
    test_app, monkeypatch
):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    invocations = []
    first_upstream = _MockNativeStreamResponse(
        [
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": (
                        '{"tool_call":{"name":"tool_search",'
                        '"arguments":{"query":"Jira health"}}}'
                    ),
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )
    second_upstream = _MockNativeStreamResponse(
        [
            json.dumps({"model": "qwen3-coder:30b", "response": "Checks "}),
            json.dumps({"model": "qwen3-coder:30b", "response": "complete."}),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 7,
                    "eval_count": 2,
                }
            ),
        ]
    )
    upstreams = iter([first_upstream, second_upstream])

    def invoke_local_stream(**kwargs):
        invocations.append(kwargs)
        return norllama_gateway.NorllamaTextStream(
            next(upstreams),
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        invoke_local_stream,
    )
    headers = _proxy_headers(monkeypatch)
    tools = [
        {
            "type": "function",
            "name": "tool_search",
            "description": "Discover an available tool.",
            "parameters": {"type": "object"},
        }
    ]

    first_result = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "Check Jira health.",
            "stream": True,
            "tools": tools,
        },
    )

    assert first_result.status_code == 200
    first_events = _response_sse_events(first_result.text)
    first_payloads = [
        json.loads(data) for event, data in first_events if event and data != "[DONE]"
    ]
    first_types = [payload["type"] for payload in first_payloads]
    first_completed = next(
        payload["response"]
        for payload in first_payloads
        if payload["type"] == "response.completed"
    )
    first_call = next(
        payload["item"]
        for payload in first_payloads
        if payload["type"] == "response.output_item.added"
        and payload["item"]["type"] == "function_call"
    )

    assert "response.failed" not in first_types
    assert "response.output_text.delta" not in first_types
    assert first_call["name"] == "tool_search"
    assert first_call["arguments"] == ""
    assert first_completed["output_text"] == ""
    assert first_completed["output"][0]["type"] == "function_call"
    assert [payload["sequence_number"] for payload in first_payloads] == list(
        range(len(first_payloads))
    )

    tool_output = '  {"status":"ok"}\n'
    second_result = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "previous_response_id": first_completed["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": first_call["call_id"],
                    "output": tool_output,
                }
            ],
            "stream": True,
            "tools": tools,
        },
    )

    assert second_result.status_code == 200
    second_events = _response_sse_events(second_result.text)
    second_payloads = [
        json.loads(data) for event, data in second_events if event and data != "[DONE]"
    ]
    second_types = [payload["type"] for payload in second_payloads]
    second_completed = next(
        payload["response"]
        for payload in second_payloads
        if payload["type"] == "response.completed"
    )

    assert "response.failed" not in second_types
    assert second_completed["output_text"] == "Checks complete."
    assert (
        second_completed["norman"]["responses_compatibility"]["previous_response_id"]
        == first_completed["id"]
    )
    assert [payload["sequence_number"] for payload in second_payloads] == list(
        range(len(second_payloads))
    )
    assert len(invocations) == 2
    assert {
        "role": "tool",
        "type": "function_call_output",
        "call_id": first_call["call_id"],
        "output": tool_output,
    }.items() <= invocations[1]["messages"][-1].items()
    assert first_upstream.closed is True
    assert second_upstream.closed is True


def test_openai_compat_responses_stream_repairs_repeated_tool_call(
    test_app, monkeypatch
):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    stream_invocations = []
    repair_invocations = []
    tool_name = "tool_search"
    tool_arguments = {"query": "Jira health"}
    first_upstream = _MockNativeStreamResponse(
        [
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": json.dumps(
                        {
                            "tool_call": {
                                "name": tool_name,
                                "arguments": tool_arguments,
                            }
                        }
                    ),
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )
    repeated_upstream = _MockNativeStreamResponse(
        [
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": json.dumps(
                        {
                            "tool_call": {
                                "name": tool_name,
                                "arguments": tool_arguments,
                            }
                        }
                    ),
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 7,
                    "eval_count": 2,
                }
            ),
        ]
    )
    upstreams = iter([first_upstream, repeated_upstream])

    def invoke_local_stream(**kwargs):
        stream_invocations.append(kwargs)
        return norllama_gateway.NorllamaTextStream(
            next(upstreams),
            model=kwargs["model"],
        )

    def invoke_repair_chat(**kwargs):
        repair_invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [{"message": {"content": "Jira health checks are complete."}}]
        }

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        invoke_local_stream,
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        invoke_repair_chat,
    )
    headers = _proxy_headers(monkeypatch)
    tools = [
        {
            "type": "function",
            "name": tool_name,
            "description": "Discover an available tool.",
            "parameters": {"type": "object"},
        }
    ]

    first_result = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code-governed",
            "input": "Check Jira health.",
            "stream": True,
            "tools": tools,
        },
    )
    assert first_result.status_code == 200
    first_payloads = [
        json.loads(data)
        for event, data in _response_sse_events(first_result.text)
        if event and data != "[DONE]"
    ]
    first_completed = next(
        payload["response"]
        for payload in first_payloads
        if payload["type"] == "response.completed"
    )
    first_call = next(
        payload["item"]
        for payload in first_payloads
        if payload["type"] == "response.output_item.added"
        and payload["item"]["type"] == "function_call"
    )

    second_result = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code-governed",
            "previous_response_id": first_completed["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": first_call["call_id"],
                    "output": '{"status":"ok"}',
                }
            ],
            "stream": True,
            "tools": tools,
        },
    )

    assert second_result.status_code == 200
    second_payloads = [
        json.loads(data)
        for event, data in _response_sse_events(second_result.text)
        if event and data != "[DONE]"
    ]
    second_completed = next(
        payload["response"]
        for payload in second_payloads
        if payload["type"] == "response.completed"
    )

    assert second_completed["output_text"] == "Jira health checks are complete."
    assert all(
        not (
            payload["type"] == "response.output_item.added"
            and payload["item"]["type"] == "function_call"
        )
        for payload in second_payloads
    )
    assert second_completed["norman"]["responses_compatibility"]["tool_chain"][
        "watchdog"
    ] == {"state": "repaired", "attempts": 1}
    assert len(stream_invocations) == 2
    assert len(repair_invocations) == 1
    assert repair_invocations[0]["messages"][-1] == {
        "role": "system",
        "content": facade._TOOL_CONTINUATION_REPAIR_MESSAGE,
    }
    assert first_upstream.closed is True
    assert repeated_upstream.closed is True


def test_openai_compat_responses_stream_converts_implicit_tool_envelopes(
    test_app, monkeypatch
):
    response = _MockNativeStreamResponse(
        [
            json.dumps({"model": "qwen3-coder:30b", "response": "{"}),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": (
                        '"tool_call":{"name":"exec_command",'
                        '"arguments":{"cmd":"git status --short"}}}'
                    ),
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        ),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={
            "model": "norman-code",
            "input": "Check the working tree.",
            "stream": True,
        },
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    output_items = [
        payload["item"]
        for payload in payloads
        if payload["type"] == "response.output_item.added"
    ]
    function_argument_deltas = [
        payload
        for payload in payloads
        if payload["type"] == "response.function_call_arguments.delta"
    ]
    function_argument_done = next(
        payload
        for payload in payloads
        if payload["type"] == "response.function_call_arguments.done"
    )
    function_item_done = next(
        payload
        for payload in payloads
        if payload["type"] == "response.output_item.done"
    )
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert not any(
        payload["type"] == "response.output_text.delta" for payload in payloads
    )
    assert [item["type"] for item in output_items] == ["function_call"]
    assert output_items[0]["name"] == "exec_command"
    assert output_items[0]["status"] == "in_progress"
    assert output_items[0]["arguments"] == ""
    assert [event["delta"] for event in function_argument_deltas] == [
        '{"cmd":"git status --short"}'
    ]
    assert function_argument_done["arguments"] == '{"cmd":"git status --short"}'
    assert function_item_done["item"]["arguments"] == '{"cmd":"git status --short"}'
    assert function_argument_done["response_id"] == completed["id"]
    assert function_item_done["response_id"] == completed["id"]
    assert completed["output_text"] == ""
    assert (
        completed["norman"]["responses_compatibility"]["tool_call_mode"]
        == "adapter_json_envelope"
    )
    assert response.closed is True


def test_openai_compat_responses_streams_normal_json_text_with_tools_declared(
    test_app, monkeypatch
):
    response = _MockNativeStreamResponse(
        [
            json.dumps({"model": "qwen3-coder:30b", "response": '{"status":'}),
            json.dumps({"model": "qwen3-coder:30b", "response": '"ready"}'}),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        ),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={
            "model": "norman-code",
            "input": "Return the current status.",
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "name": "ticket_search",
                    "description": "Search Jira tickets.",
                    "parameters": {"type": "object"},
                }
            ],
        },
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    deltas = [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.output_text.delta"
    ]
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert "".join(deltas) == '{"status":"ready"}'
    assert completed["output_text"] == '{"status":"ready"}'
    assert completed["output"][0]["type"] == "message"
    assert response.closed is True


def test_openai_compat_responses_stream_preserves_action_prose_as_text(
    test_app, monkeypatch
):
    invocations = []
    response = _MockNativeStreamResponse(
        [
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": "A Jira health review would be the next step.",
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )

    def fake_stream(**kwargs):
        invocations.append(kwargs)
        return norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        )

    monkeypatch.setattr(norllama_gateway, "invoke_text_chat_stream", fake_stream)

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={
            "model": "norman-code",
            "input": "Describe the next step for Jira and our data.",
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "name": "tool_search",
                    "description": "Discover a connected tool.",
                    "parameters": {"type": "object"},
                }
            ],
        },
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    deltas = [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.output_text.delta"
    ]
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert len(invocations) == 1
    assert "".join(deltas) == "A Jira health review would be the next step."
    assert completed["output_text"] == "A Jira health review would be the next step."
    assert completed["output"][0]["type"] == "message"
    assert completed["norman"]["responses_compatibility"]["tool_calls_returned"] == 0
    assert response.closed is True


def test_openai_compat_responses_streams_queue_progress_without_output_text(
    test_app, monkeypatch
):
    response = _MockNativeStreamResponse(
        [
            (
                '{"norllama":{"schema":"norllama.stream-admission.v1",'
                '"event":"queued","admission":"queued","queue_wait_ms":0,'
                '"queue_depth":1,"queue_limit":1,"active":1,'
                '"active_limit":1,"retry_after_seconds":10}}'
            ),
            (
                '{"norllama":{"schema":"norllama.stream-admission.v1",'
                '"event":"admitted","admission":"queued","queue_wait_ms":31,'
                '"queue_depth":0,"queue_limit":1,"active":1,'
                '"active_limit":1,"retry_after_seconds":10}}'
            ),
            '{"model":"qwen3-coder:30b","response":"ready"}',
            (
                '{"model":"qwen3-coder:30b","done":true,'
                '"prompt_eval_count":4,"eval_count":1}'
            ),
        ],
        headers={
            "X-Norllama-Admission": "queued",
            "X-Norllama-Queue-Wait-Ms": "0",
            "X-Norllama-Queue-Depth": "1",
            "X-Norllama-Queue-Limit": "1",
            "X-Norllama-Active": "1",
            "X-Norllama-Active-Limit": "1",
        },
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        ),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={"model": "norman-code", "input": "say ready", "stream": True},
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    progress = [
        payload["response"]["norman"]["stream_admission"]
        for payload in payloads
        if payload["type"] == "response.in_progress"
        and payload["response"].get("norman", {}).get("stream_admission")
    ]
    deltas = [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.output_text.delta"
    ]
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert [item["state"] for item in progress] == [
        "queued",
        "queued",
        "admitted",
    ]
    assert progress[-1] == {
        "schema": "norman.stream-admission.v1",
        "state": "admitted",
        "queue_wait_ms": 31,
        "queue_depth": 0,
        "queue_limit": 1,
        "active": 1,
        "active_limit": 1,
        "retry_after_seconds": 10,
    }
    assert deltas == ["ready"]
    assert completed["norman"]["stream_admission"]["state"] == "admitted"
    assert response.closed is True


def test_openai_compat_responses_stream_falls_back_after_queued_capacity_expiry(
    test_app, monkeypatch
):
    response = _MockNativeStreamResponse(
        [
            (
                '{"norllama":{"schema":"norllama.stream-admission.v1",'
                '"event":"queued","admission":"queued","queue_wait_ms":0,'
                '"queue_depth":1,"queue_limit":1,"active":1,'
                '"active_limit":1,"retry_after_seconds":10}}'
            ),
            (
                '{"error":"local_capacity_exhausted","done":true,'
                '"norllama":{"schema":"norllama.capacity.v1","active":1,'
                '"active_limit":1,"queue_depth":0,"queue_limit":1,'
                '"retry_after_seconds":10}}'
            ),
        ],
        headers={"X-Norllama-Admission": "queued"},
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        ),
    )
    bedrock_calls = _install_bedrock_stub(
        monkeypatch,
        result=_mock_bedrock_result("cloud ready"),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={"model": "norman-code", "input": "say ready", "stream": True},
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    progress = [
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.in_progress"
    ]
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert not any(payload["type"] == "response.failed" for payload in payloads)
    assert any(
        snapshot.get("norman", {}).get("cloud_fallback", {}).get("state") == "started"
        for snapshot in progress
    )
    assert [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.output_text.delta"
    ] == ["cloud ready"]
    assert completed["model"] == "openai.gpt-5.6-terra"
    assert completed["norman"]["cloud_fallback"]["state"] == "completed"
    assert completed["norman"]["cloud_fallback"]["local_failure_code"] == (
        "local_capacity_exhausted"
    )
    assert len(bedrock_calls) == 1
    fallback_request = bedrock_calls[0]
    assert fallback_request.model == "openai.gpt-5.6-terra"
    assert fallback_request.metadata["execution_mode"] == (
        "prompt_intermediary_openai_facade_cloud_fallback"
    )
    assert fallback_request.metadata["route_policy"]["allow_cloud_proxy"] is False
    assert fallback_request.metadata["route_policy"]["aws_region"] == "us-east-2"
    assert (
        fallback_request.metadata["route_policy"]["aws_credentials_secret"]
        == "test/bedrock-fallback"
    )
    assert fallback_request.metadata["norllama_route"]["provider"] == "aws-bedrock"
    assert events[-1] == ("", "[DONE]")
    assert response.closed is True


def test_openai_compat_responses_stream_falls_back_when_local_stream_cannot_open(
    test_app, monkeypatch
):
    def exhausted_local_stream(**_kwargs):
        raise norllama_gateway.NorllamaGatewayError(
            429,
            {
                "error": "local_capacity_exhausted",
                "norllama": {
                    "schema": "norllama.capacity.v1",
                    "active": 1,
                    "active_limit": 1,
                    "queue_depth": 1,
                    "queue_limit": 1,
                    "retry_after_seconds": 12,
                },
            },
            headers={"Retry-After": "12"},
        )

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        exhausted_local_stream,
    )
    bedrock_calls = _install_bedrock_stub(
        monkeypatch,
        result=_mock_bedrock_result("cloud hello"),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={"model": "norman-code", "input": "say hello", "stream": True},
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    progress = [
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.in_progress"
    ]
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )

    assert any(
        snapshot.get("norman", {}).get("cloud_fallback", {}).get("local_failure_code")
        == "local_capacity_exhausted"
        for snapshot in progress
    )
    assert any(
        payload["type"] == "response.output_text.delta"
        and payload["delta"] == "cloud hello"
        for payload in payloads
    )
    assert completed["norman"]["cloud_fallback"]["state"] == "completed"
    assert len(bedrock_calls) == 1


def test_openai_compat_responses_stream_keeps_slow_cloud_fallback_live(
    test_app, monkeypatch
):
    from app.services import prompt_provider_facade

    def exhausted_local_stream(**_kwargs):
        raise norllama_gateway.NorllamaGatewayError(
            429,
            {"error": "local_capacity_exhausted"},
        )

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        exhausted_local_stream,
    )
    monkeypatch.setattr(
        prompt_provider_facade,
        "CLOUD_STREAM_HEARTBEAT_INTERVAL_SECONDS",
        0.005,
    )
    bedrock_calls = _install_bedrock_stub(
        monkeypatch,
        result=_mock_bedrock_result("cloud remains live"),
        delay_seconds=0.04,
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={"model": "norman-code", "input": "say hello", "stream": True},
    )

    assert result.status_code == 200
    payloads = [
        json.loads(data)
        for event, data in _response_sse_events(result.text)
        if event and data != "[DONE]"
    ]
    heartbeats = [
        payload["response"]["norman"]["cloud_fallback"]
        for payload in payloads
        if payload["type"] == "response.in_progress"
        and payload["response"]
        .get("norman", {})
        .get("cloud_fallback", {})
        .get("heartbeat")
    ]

    assert len(heartbeats) >= 3
    assert {heartbeat["state"] for heartbeat in heartbeats} == {"in_progress"}
    elapsed = [heartbeat["elapsed_ms"] for heartbeat in heartbeats]
    assert elapsed == sorted(elapsed)
    assert elapsed[-1] >= 15
    assert [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.output_text.delta"
    ] == ["cloud remains live"]
    assert len(bedrock_calls) == 1


def test_openai_compat_responses_stream_keeps_slow_local_open_live(
    test_app, monkeypatch
):
    from app.services import prompt_provider_facade

    response = _MockNativeStreamResponse(
        [
            '{"model":"qwen3-coder:30b","response":"local stream is ready"}',
            '{"model":"qwen3-coder:30b","done":true}',
        ],
    )

    def slow_local_stream(**kwargs):
        time.sleep(0.04)
        return norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        slow_local_stream,
    )
    monkeypatch.setattr(
        prompt_provider_facade,
        "LOCAL_STREAM_OPEN_HEARTBEAT_INTERVAL_SECONDS",
        0.005,
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={"model": "norman-code", "input": "say hello", "stream": True},
    )

    assert result.status_code == 200
    payloads = [
        json.loads(data)
        for event, data in _response_sse_events(result.text)
        if event and data != "[DONE]"
    ]
    local_open_progress = [
        payload["response"]["norman"]["local_stream_open"]
        for payload in payloads
        if payload["type"] == "response.in_progress"
        and payload["response"]
        .get("norman", {})
        .get("local_stream_open", {})
        .get("heartbeat")
    ]
    created_index = next(
        index
        for index, payload in enumerate(payloads)
        if payload["type"] == "response.created"
    )
    first_progress_index = next(
        index
        for index, payload in enumerate(payloads)
        if payload["type"] == "response.in_progress"
        and payload["response"].get("norman", {}).get("local_stream_open")
    )
    first_delta_index = next(
        index
        for index, payload in enumerate(payloads)
        if payload["type"] == "response.output_text.delta"
    )

    assert len(local_open_progress) >= 3
    assert {progress["state"] for progress in local_open_progress} == {"in_progress"}
    elapsed = [progress["elapsed_ms"] for progress in local_open_progress]
    assert elapsed == sorted(elapsed)
    assert elapsed[-1] >= 15
    assert created_index < first_progress_index < first_delta_index
    assert [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "response.output_text.delta"
    ] == ["local stream is ready"]
    assert response.closed is True


def test_openai_compat_responses_stream_reports_midstream_failure(
    test_app, monkeypatch
):
    bedrock_calls = _install_bedrock_stub(monkeypatch)
    response = _MockNativeStreamResponse(
        [
            '{"model":"qwen3-coder:30b","response":"partial "}',
            "not-json",
        ]
    )

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            response,
            model=kwargs["model"],
        ),
    )

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={"model": "norman-code", "input": "say hello", "stream": True},
    )

    assert result.status_code == 200
    events = _response_sse_events(result.text)
    payloads = [
        json.loads(data) for event, data in events if event and data != "[DONE]"
    ]
    failed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.failed"
    )

    assert any(
        payload["type"] == "response.output_text.delta"
        and payload["delta"] == "partial "
        for payload in payloads
    )
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "local_gateway_bad_response"
    assert bedrock_calls == []
    assert events[-1] == ("", "[DONE]")
    assert response.closed is True


@pytest.mark.parametrize(
    ("path", "payload", "facade_name", "facade_response"),
    [
        (
            "/v1/chat/completions",
            {
                "model": "norman-code",
                "messages": [{"role": "user", "content": "status?"}],
            },
            "execute_openai_chat_facade",
            {"object": "chat.completion"},
        ),
        (
            "/v1/responses",
            {"model": "norman-code", "input": "status?"},
            "execute_openai_responses_facade",
            {"object": "response"},
        ),
    ],
)
def test_openai_compat_facade_wait_does_not_block_models_endpoint(
    test_app,
    monkeypatch,
    path,
    payload,
    facade_name,
    facade_response,
):
    from app.api import openai_compat

    headers = _proxy_headers(monkeypatch)
    facade_started = threading.Event()
    release_facade = threading.Event()

    def blocking_facade(*args, **kwargs):
        facade_started.set()
        assert release_facade.wait(timeout=2)
        return facade_response

    monkeypatch.setattr(openai_compat, facade_name, blocking_facade)

    async def assert_models_remain_available():
        transport = httpx.ASGITransport(app=test_app.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            facade_task = asyncio.create_task(
                client.post(path, headers=headers, json=payload)
            )
            try:
                assert await asyncio.to_thread(facade_started.wait, 0.5)
                assert not facade_task.done()
                models = await asyncio.wait_for(
                    client.get("/v1/models", headers=headers),
                    timeout=0.5,
                )
            finally:
                release_facade.set()

            assert models.status_code == 200
            facade_response = await asyncio.wait_for(facade_task, timeout=0.5)
            assert facade_response.status_code == 200

    asyncio.run(assert_models_remain_available())


def test_openai_compat_responses_returns_gateway_failure(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch, route="gold-book")
    upstream_response = requests.Response()
    upstream_response.status_code = 502

    def unavailable_local_model(**kwargs):
        raise requests.HTTPError(response=upstream_response)

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        unavailable_local_model,
    )

    response = test_app.post(
        "/v1/responses",
        headers={**headers, "X-Request-Id": "gateway-unavailable-test"},
        json={"model": "norman-code", "input": "status?"},
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["message"] == "Local model gateway is unavailable"
    assert error["type"] == "server_error"
    assert error["param"] is None
    assert error["code"] == "local_gateway_unavailable"
    assert error["norman"] == {
        "schema": "norman.local-gateway-error.v1",
        "request_id": "gateway-unavailable-test",
        "requested_model": "norman-code",
        "selected_model": resident_model(),
        "retryable": True,
        "cloud_fallback": False,
        "eligible_workers": [
            {"id": worker_id, "role": "production"}
            for worker_id in sorted(ROUTE_POLICY_PLACEMENT["resident_runtime_workers"])
        ],
        "ineligible_workers": [
            {
                "id": "mac-mini-133",
                "reason": "ineligible_for_heavy_coding",
            }
        ],
    }


def test_openai_compat_responses_records_unexpected_gateway_failure(
    test_app, monkeypatch
):
    from app.api import openai_compat
    from app.services.proxy_observability import reset_proxy_events

    reset_proxy_events()
    headers = {
        **_proxy_headers(monkeypatch, route="gold-book"),
        "X-Request-Id": "unexpected-response-test",
    }

    def unexpected_failure(*args, **kwargs):
        raise RuntimeError("do not expose this implementation detail")

    monkeypatch.setattr(
        openai_compat, "execute_openai_responses_facade", unexpected_failure
    )

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "norman-code", "input": "status?"},
    )

    assert response.status_code == 500
    assert response.json()["error"] == {
        "message": "Local Responses gateway encountered an unexpected error",
        "type": "server_error",
        "param": None,
        "code": "internal_error",
    }
    assert "implementation detail" not in response.text

    events = test_app.get("/v1/norman/proxy/events", headers=headers).json()["events"]
    assert len(events) == 1
    assert events[0]["endpoint"] == "/v1/responses"
    assert events[0]["request_id"] == "unexpected-response-test"
    assert events[0]["gateway_route"] == "gold-book"
    assert events[0]["status"] == "error"
    assert events[0]["http_status"] == 500
    assert events[0]["error"] == response.json()["error"]


def test_openai_compat_responses_preserves_missing_local_model(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch, route="gold-book")

    def missing_local_model(**kwargs):
        raise norllama_gateway.NorllamaGatewayError(
            422,
            {"error": "local_model_not_installed"},
        )

    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        missing_local_model,
    )

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "norman-code", "input": "status?"},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["message"] == "Requested local model is not installed"
    assert error["type"] == "invalid_request_error"
    assert error["param"] is None
    assert error["code"] == "local_model_not_installed"
    assert error["norman"]["cloud_fallback"] is False
    assert error["norman"]["retryable"] is False


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code", "retryable", "retry_after"),
    (
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                429,
                {"error": "capacity"},
                {"Retry-After": "9"},
            ),
            503,
            "local_capacity_exhausted",
            True,
            "9",
        ),
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                429,
                {"error": "capacity"},
                {"Retry-After": "not-a-number"},
            ),
            503,
            "local_capacity_exhausted",
            True,
            "5",
        ),
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                503,
                {"error": "workers unavailable"},
            ),
            503,
            "local_capacity_unavailable",
            True,
            "",
        ),
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                504,
                {"error": "worker timeout"},
            ),
            504,
            "local_model_timeout",
            True,
            "60",
        ),
        (
            lambda: requests.Timeout("gateway timeout"),
            504,
            "local_model_timeout",
            True,
            "60",
        ),
        (
            lambda: TimeoutError("gateway timeout"),
            504,
            "local_model_timeout",
            True,
            "60",
        ),
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                401,
                {"error": "expired gateway credential"},
            ),
            503,
            "local_gateway_auth_failed",
            False,
            "",
        ),
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                403,
                {"error": "gateway route denied"},
            ),
            503,
            "local_gateway_auth_failed",
            False,
            "",
        ),
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                502,
                {"error": "bad upstream response"},
            ),
            503,
            "local_gateway_unavailable",
            True,
            "",
        ),
        (
            lambda: norllama_gateway.NorllamaGatewayError(
                502,
                {"error": "ollama_model_unavailable"},
            ),
            503,
            "local_model_unavailable",
            True,
            "",
        ),
        (
            lambda: requests.ConnectionError("front door refused connection"),
            503,
            "local_gateway_unreachable",
            True,
            "",
        ),
        (
            lambda: RuntimeError("malformed local response"),
            502,
            "local_gateway_bad_response",
            True,
            "",
        ),
    ),
)
def test_openai_compat_responses_classifies_local_gateway_failures(
    test_app,
    monkeypatch,
    failure,
    expected_status,
    expected_code,
    retryable,
    retry_after,
):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch, route="gold-book")
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: (_ for _ in ()).throw(failure()),
    )

    response = test_app.post(
        "/v1/responses",
        headers={**headers, "X-Request-Id": f"failure-{expected_code}"},
        json={"model": "norman-fast", "input": "status?"},
    )

    assert response.status_code == expected_status
    error = response.json()["error"]
    assert error["code"] == expected_code
    assert error["type"] == "server_error"
    assert error["norman"]["cloud_fallback"] is False
    assert error["norman"]["retryable"] is retryable
    if retry_after:
        assert response.headers["Retry-After"] == retry_after
    else:
        assert "Retry-After" not in response.headers


def test_openai_compat_responses_reports_empty_local_response(test_app, monkeypatch):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch, route="gold-book")
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: {
            "model": "qwen3-coder:30b-a3b-q4_K_M",
            "choices": [{"message": {"content": ""}}],
            "usage": {},
            "headers": {},
        },
    )

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "norman-fast", "input": "status?"},
    )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "empty_local_response"
    assert error["norman"]["cloud_fallback"] is False
    assert error["norman"]["retryable"] is True


def test_openai_compat_responses_retries_retryable_norman_code_failure_in_bedrock(
    test_app, monkeypatch
):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch, route="gold-book")
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: (_ for _ in ()).throw(
            norllama_gateway.NorllamaGatewayError(
                503,
                {"error": "workers unavailable"},
            )
        ),
    )
    bedrock_calls = _install_bedrock_stub(
        monkeypatch,
        result=_mock_bedrock_result(
            "cloud result",
            metadata={
                "norllama_receipt": {
                    "route_receipt": {
                        "provider": "aws-bedrock",
                        "credentials": "must-not-leak",
                    },
                    "authorization": "must-not-leak",
                }
            },
        ),
    )

    response = test_app.post(
        "/v1/responses",
        headers={**headers, "X-Request-Id": "fallback-response-test"},
        json={"model": "norman-code", "input": "status?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_text"] == "cloud result"
    assert payload["model"] == "openai.gpt-5.6-terra"
    assert payload["norman"]["local_execution"] is False
    assert payload["norman"]["cloud_forwarding"] is True
    assert payload["norman"]["cloud_fallback"] == {
        "schema": "norman.cloud-fallback.v1",
        "state": "completed",
        "fallback_attempted": True,
        "local_failure_code": "local_capacity_unavailable",
        "fallback_provider": "aws-bedrock",
        "fallback_model": "openai.gpt-5.6-terra",
        "request_id": "fallback-response-test",
    }
    assert "must-not-leak" not in response.text
    assert len(bedrock_calls) == 1


def test_openai_compat_responses_does_not_fallback_for_nonretryable_failure(
    test_app, monkeypatch
):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: (_ for _ in ()).throw(
            norllama_gateway.NorllamaGatewayError(
                401,
                {"error": "expired gateway credential"},
            )
        ),
    )
    bedrock_calls = _install_bedrock_stub(monkeypatch)

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "norman-code", "input": "status?"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_gateway_auth_failed"
    assert bedrock_calls == []


def test_openai_compat_responses_sanitizes_bedrock_fallback_failures(
    test_app, monkeypatch, caplog
):
    from app.services import prompt_provider_facade
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: (_ for _ in ()).throw(
            norllama_gateway.NorllamaGatewayError(
                429,
                {"error": "local_capacity_exhausted"},
            )
        ),
    )
    _install_bedrock_stub(
        monkeypatch,
        error=RuntimeError("bedrock token=must-not-leak"),
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_credentials_secret",
        "credentials-alias-must-not-leak",
        raising=False,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="app.services.prompt_provider_facade",
    ):
        response = test_app.post(
            "/v1/responses",
            headers=headers,
            json={"model": "norman-code", "input": "status?"},
        )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "cloud_fallback_failed"
    assert error["norman"]["cloud_fallback"]["state"] == "failed"
    assert "must-not-leak" not in response.text
    assert "credentials-alias-must-not-leak" not in response.text
    assert "must-not-leak" not in caplog.text
    assert "credentials-alias-must-not-leak" not in caplog.text
    assert "category=invoke_failed" in caplog.text
    assert "exception_class=RuntimeError" in caplog.text


def test_openai_compat_responses_does_not_attempt_unconfigured_cloud_fallback(
    test_app, monkeypatch
):
    from app.services import prompt_provider_facade
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_enabled",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_aws_region",
        "",
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_credentials_secret",
        "",
        raising=False,
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: (_ for _ in ()).throw(
            norllama_gateway.NorllamaGatewayError(
                503,
                {"error": "workers unavailable"},
            )
        ),
    )
    bedrock_calls = []

    class StubBedrockModelAdapter:
        def invoke(self, request):
            bedrock_calls.append(request)
            return _mock_bedrock_result()

    monkeypatch.setattr(
        prompt_provider_facade,
        "BedrockModelAdapter",
        StubBedrockModelAdapter,
    )

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "norman-code", "input": "status?"},
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "local_capacity_unavailable"
    assert error["norman"]["cloud_fallback"] is False
    assert bedrock_calls == []


def test_openai_compat_capacity_requires_gateway_authentication(test_app, monkeypatch):
    headers = _proxy_headers(monkeypatch)
    headers["Authorization"] = "Bearer invalid-token"

    response = test_app.get(
        "/v1/norman/capacity?model=norman-code",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


@pytest.mark.parametrize(
    ("mesh", "expected_available", "expected_reason"),
    (
        (_capacity_mesh(), True, "available"),
        (
            _capacity_mesh(
                spark_150_reachable=False,
                spark_151_reachable=False,
            ),
            False,
            "no_eligible_worker_reachable",
        ),
        (
            _capacity_mesh(cache_status="stale_error"),
            False,
            "mesh_probe_stale",
        ),
    ),
)
def test_openai_compat_capacity_reports_live_worker_state_without_invoking_a_model(
    test_app,
    monkeypatch,
    mesh,
    expected_available,
    expected_reason,
):
    from app.api import openai_compat
    from app.services.prompt_provider_facade import norllama_gateway
    from app.services.proxy_observability import reset_proxy_events

    monkeypatch.setenv("NORMAN_PROXY_EVENT_LOG", "0")
    reset_proxy_events()
    headers = _proxy_headers(monkeypatch)
    invocations = []
    monkeypatch.setattr(
        openai_compat.norllama_mesh_cache,
        "get_mesh_overview",
        lambda **_kwargs: mesh,
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: invocations.append(_kwargs),
    )

    response = test_app.get(
        "/v1/norman/capacity?model=norman-code",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is expected_available
    assert payload["reason"] == expected_reason
    assert payload["cloud_fallback"] is False
    assert payload["gateway"]["gateway_route"] == "norman"
    assert invocations == []


def test_openai_compat_capacity_reports_probe_failure_without_invoking_a_model(
    test_app,
    monkeypatch,
):
    from app.api import openai_compat
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    invocations = []

    def failed_probe(**_kwargs):
        raise RuntimeError("mesh connection failed")

    monkeypatch.setattr(
        openai_compat.norllama_mesh_cache,
        "get_mesh_overview",
        failed_probe,
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: invocations.append(_kwargs),
    )

    response = test_app.get(
        "/v1/norman/capacity?model=norman-code",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["reason"] == "mesh_probe_failed"
    assert payload["cloud_fallback"] is False
    assert invocations == []


def test_openai_compat_capacity_times_out_blocked_mesh_probe_without_invoking_a_model(
    test_app,
    monkeypatch,
):
    from app.api import openai_compat
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch)
    invocations = []
    probe_started = threading.Event()
    release_probe = threading.Event()

    def blocked_probe(**_kwargs):
        probe_started.set()
        release_probe.wait(timeout=1)
        return _capacity_mesh()

    monkeypatch.setattr(
        openai_compat.norllama_mesh_cache,
        "get_mesh_overview",
        blocked_probe,
    )
    monkeypatch.setattr(
        openai_compat,
        "CAPACITY_MESH_PROBE_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: invocations.append(_kwargs),
    )

    def release_after_deadline():
        probe_started.wait(timeout=1)
        time.sleep(0.05)
        release_probe.set()

    releaser = threading.Thread(target=release_after_deadline, daemon=True)
    releaser.start()
    started_at = time.monotonic()
    try:
        response = test_app.get(
            "/v1/norman/capacity?model=norman-code",
            headers=headers,
        )
    finally:
        release_probe.set()
        releaser.join(timeout=1)
    elapsed_seconds = time.monotonic() - started_at

    assert probe_started.is_set()
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["reason"] == "mesh_probe_timeout"
    assert elapsed_seconds < 0.5
    assert invocations == []


def test_openai_compat_capacity_reports_executable_cloud_fallback(
    test_app,
    monkeypatch,
):
    from app.api import openai_compat
    from app.services import prompt_provider_facade

    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_enabled",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_aws_region",
        "us-east-2",
        raising=False,
    )
    monkeypatch.setattr(
        prompt_provider_facade.settings,
        "prompt_facade_cloud_fallback_credentials_secret",
        "test/bedrock-fallback",
        raising=False,
    )
    monkeypatch.setattr(
        openai_compat.norllama_mesh_cache,
        "get_mesh_overview",
        lambda **_kwargs: _capacity_mesh(
            spark_150_reachable=False,
            spark_151_reachable=False,
        ),
    )

    response = test_app.get(
        "/v1/norman/capacity?model=norman-code",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["cloud_fallback"] is True


def test_openai_compat_capacity_blocks_recent_local_model_timeout(
    test_app,
    monkeypatch,
):
    from app.api import openai_compat
    from app.services.prompt_provider_facade import norllama_gateway
    from app.services.proxy_observability import record_proxy_event, reset_proxy_events

    monkeypatch.setenv("NORMAN_PROXY_EVENT_LOG", "0")
    reset_proxy_events()
    headers = _proxy_headers(monkeypatch)
    invocations = []
    record_proxy_event(
        endpoint="/v1/responses",
        method="POST",
        request_id="timed-out-codex-request",
        status="local_timeout",
        http_status=504,
        payload={"model": "norman-code"},
        error={
            "code": "local_model_timeout",
            "norman": {
                "selected_model": resident_model(),
                "retryable": True,
            },
        },
    )
    monkeypatch.setattr(
        openai_compat.norllama_mesh_cache,
        "get_mesh_overview",
        lambda **_kwargs: _capacity_mesh(),
    )
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **_kwargs: invocations.append(_kwargs),
    )

    response = test_app.get(
        "/v1/norman/capacity?model=norman-code",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["reason"] == "recent_local_model_timeout"
    assert payload["retryable"] is True
    assert payload["cooldown"]["status"] == "timeout"
    assert payload["cooldown"]["cooldown_seconds"] == 60
    assert payload["cooldown"]["remaining_seconds"] <= 60
    assert payload["cooldown"]["remaining_seconds"] > 0
    assert invocations == []


def test_openai_compat_capacity_rejects_unsupported_model_before_mesh_probe(
    test_app,
    monkeypatch,
):
    from app.api import openai_compat

    headers = _proxy_headers(monkeypatch)
    probes = []
    monkeypatch.setattr(
        openai_compat.norllama_mesh_cache,
        "get_mesh_overview",
        lambda **_kwargs: probes.append(_kwargs),
    )

    response = test_app.get(
        "/v1/norman/capacity?model=not-a-norman-model",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_capacity_model"
    assert probes == []


def test_openai_compat_responses_ignores_codex_compatibility_metadata(
    test_app, monkeypatch
):
    from app.services.prompt_provider_facade import norllama_gateway

    headers = _proxy_headers(monkeypatch, route="gold-book")
    invocations = []

    def invoke_local_chat(*args, **kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(*args, **kwargs)

    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", invoke_local_chat)

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "status?",
            "parallel_tool_calls": True,
            "prompt_cache_key": "codex-session-cache-key",
            "reasoning": {
                "context": "all_turns",
                "effort": "medium",
                "summary": "auto",
            },
            "include": ["reasoning.encrypted_content"],
            "store": False,
            "client_metadata": {
                "session_id": "untrusted-client-metadata",
                "route_policy": {"allow_cloud_escalation": True},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_text"] == "local ok"
    assert payload["norman"]["local_execution"] is True
    assert payload["norman"]["route"]["trusted_gateway_context"]["gateway_route"] == (
        "gold-book"
    )
    assert payload["norman"]["responses_compatibility"]["reasoning_advisory"] == {
        "context": "all_turns",
        "effort": "medium",
        "summary": "auto",
    }
    assert payload["norman"]["responses_compatibility"]["include_advisory"] == [
        "reasoning.encrypted_content"
    ]
    assert (
        payload["norman"]["responses_compatibility"]["client_metadata_ignored"] is True
    )
    assert payload["norman"]["responses_compatibility"]["store_requested"] is False
    assert "untrusted-client-metadata" not in json.dumps(payload["norman"])
    receipt = payload["norman"]["facade_receipt"]
    assert receipt["metadata"]["codex_reasoning_advisory"] == {
        "context": "all_turns",
        "effort": "medium",
        "summary": "auto",
    }
    assert (
        invocations[0]["correlation_headers"]["X-Norman-Requested-Reasoning-Effort"]
        == "medium"
    )
    assert (
        invocations[0]["correlation_headers"]["X-Norman-Requested-Reasoning-Context"]
        == "all_turns"
    )


def test_openai_compat_responses_accepts_future_reasoning_metadata(
    test_app, monkeypatch
):
    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: _mock_local_chat(kwargs["messages"], kwargs["model"]),
    )

    invalid_shape = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "norman-code", "input": "status?", "reasoning": "high"},
    )
    assert invalid_shape.status_code == 400
    assert invalid_shape.json()["error"]["code"] == "invalid_reasoning"

    future_effort = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "status?",
            "reasoning": {"effort": "turbo"},
        },
    )
    assert future_effort.status_code == 200
    assert (
        future_effort.json()["norman"]["responses_compatibility"]["reasoning_advisory"]
        == {}
    )

    future_summary = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "status?",
            "reasoning": {"summary": "full"},
        },
    )
    assert future_summary.status_code == 200
    assert (
        future_summary.json()["norman"]["responses_compatibility"]["reasoning_advisory"]
        == {}
    )

    future_context = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "status?",
            "reasoning": {"context": "forever"},
        },
    )
    assert future_context.status_code == 200
    assert (
        future_context.json()["norman"]["responses_compatibility"]["reasoning_advisory"]
        == {}
    )

    future_option = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "status?",
            "reasoning": {"effort": "medium", "token_budget": 100},
        },
    )
    assert future_option.status_code == 200
    assert future_option.json()["norman"]["responses_compatibility"][
        "reasoning_advisory"
    ] == {"effort": "medium"}


def test_openai_compat_responses_accepts_future_include_values(test_app, monkeypatch):
    headers = _proxy_headers(monkeypatch)
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: _mock_local_chat(kwargs["messages"], kwargs["model"]),
    )

    invalid_shape = test_app.post(
        "/v1/responses",
        headers=headers,
        json={"model": "norman-code", "input": "status?", "include": "reasoning"},
    )
    assert invalid_shape.status_code == 400
    assert invalid_shape.json()["error"]["code"] == "invalid_include"

    future_value = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "status?",
            "include": ["reasoning.encrypted_content", "message.output_text.logprobs"],
        },
    )
    assert future_value.status_code == 200
    assert future_value.json()["norman"]["responses_compatibility"][
        "include_advisory"
    ] == ["reasoning.encrypted_content", "message.output_text.logprobs"]


def test_openai_compat_responses_preserves_future_root_metadata(monkeypatch):
    import app.services.prompt_provider_facade as facade

    decisions = []
    monkeypatch.setattr(
        facade,
        "provider_adapter_decision",
        lambda **kwargs: decisions.append(kwargs) or _local_route_envelope(),
    )
    monkeypatch.setattr(
        facade.norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: _mock_local_chat(kwargs["messages"], kwargs["model"]),
    )

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "status?",
            "reasoning": {
                "effort": "high",
                "future_reasoning_mode": "adaptive",
            },
            "include": [
                "reasoning.encrypted_content",
                "future.include.path",
                "reasoning.encrypted_content",
            ],
            "future_client_metadata": {
                "schema_version": "2026-08",
                "capability": "tool_state_v2",
            },
        }
    )

    assert response["output_text"] == "local ok"
    assert decisions[0]["payload"]["reasoning"] == {
        "effort": "high",
        "future_reasoning_mode": "adaptive",
    }
    assert decisions[0]["payload"]["include"] == [
        "reasoning.encrypted_content",
        "future.include.path",
        "reasoning.encrypted_content",
    ]
    assert decisions[0]["payload"]["future_client_metadata"] == {
        "schema_version": "2026-08",
        "capability": "tool_state_v2",
    }


def test_openai_compat_responses_rejects_invalid_client_metadata(test_app, monkeypatch):
    headers = _proxy_headers(monkeypatch)

    response = test_app.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "norman-code",
            "input": "status?",
            "client_metadata": ["not", "an", "object"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_client_metadata"
    assert response.json()["error"]["param"] == "client_metadata"


def test_openai_compat_responses_rejects_invalid_store(test_app, monkeypatch):
    headers = _proxy_headers(monkeypatch)

    for store in ("false", 0, None):
        response = test_app.post(
            "/v1/responses",
            headers=headers,
            json={"model": "norman-code", "input": "status?", "store": store},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_store"
        assert response.json()["error"]["param"] == "store"


def test_openai_compat_models_requires_proxy_token_when_configured(
    test_app,
    monkeypatch,
):
    headers = _proxy_headers(monkeypatch)

    denied = test_app.get("/v1/models")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "gateway_route_required"

    denied = test_app.get("/v1/models", headers=_gateway_headers())
    assert denied.status_code == 401
    assert denied.json()["error"]["type"] == "authentication_error"

    allowed = test_app.get(
        "/v1/models",
        headers=headers,
    )
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["object"] == "list"
    assert {item["id"] for item in payload["data"]} >= {
        "norman-code",
        "norman-code-governed",
        "norman-local",
    }
    assert payload["norman"]["base_url"] == "/v1"
    assert payload["norman"]["gateway"]["gateway_route"] == "norman"


def test_openai_compat_models_advertises_codex_catalog(test_app, monkeypatch):
    headers = _proxy_headers(monkeypatch)

    response = test_app.get("/v1/models", headers=headers)

    assert response.status_code == 200
    models = response.json()["models"]
    assert [model["slug"] for model in models] == [
        "norman-code",
        "norman-code-governed",
        "norman-local",
    ]
    models_by_slug = {model["slug"]: model for model in models}
    assert models_by_slug["norman-code"]["apply_patch_tool_type"] == "freeform"
    assert models_by_slug["norman-code"]["supports_parallel_tool_calls"] is True
    assert models_by_slug["norman-code"]["default_reasoning_level"] == "high"
    assert models_by_slug["norman-code-governed"]["apply_patch_tool_type"] == "freeform"
    assert (
        models_by_slug["norman-code-governed"]["supports_parallel_tool_calls"] is True
    )
    assert models_by_slug["norman-local"]["apply_patch_tool_type"] is None
    assert models_by_slug["norman-local"]["supports_parallel_tool_calls"] is False
    for model in models:
        assert model["display_name"]
        assert model["supported_in_api"] is True
        assert model["priority"] > 0
        assert model["supports_image_detail_original"] is False
        assert model["context_window"] == 128000
        assert model["truncation_policy"] == {"mode": "bytes", "limit": 128000}


def test_openai_compat_auth_fails_closed_without_facade_token(test_app, monkeypatch):
    monkeypatch.delenv("NORMAN_PROMPT_PROXY_TOKEN", raising=False)
    headers = _gateway_headers()

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
        response = (
            request(path, headers=headers, json=body)
            if body is not None
            else request(path, headers=headers)
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "proxy_token_not_configured"


def test_openai_compat_rejects_unknown_gateway_route(test_app, monkeypatch):
    monkeypatch.setenv("NORMAN_PROMPT_PROXY_TOKEN", "proxy-token")

    response = test_app.get(
        "/v1/models",
        headers={
            "Authorization": "Bearer proxy-token",
            "X-Norman-Gateway-Route": "forged-route",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "gateway_route_invalid"


def test_openai_compat_rejects_gateway_identity_from_non_loopback(
    test_app,
    monkeypatch,
):
    monkeypatch.setenv("NORMAN_PROMPT_PROXY_TOKEN", "proxy-token")

    async def request_from_lan():
        transport = httpx.ASGITransport(
            app=test_app.app,
            client=("192.168.2.99", 18900),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(
                "/v1/models",
                headers={
                    "Authorization": "Bearer proxy-token",
                    "X-Norman-Gateway-Route": "gold-book",
                },
            )

    response = asyncio.run(request_from_lan())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "gateway_route_untrusted"


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


def test_openai_compat_responses_uses_requires_approval_as_local_advisory(
    test_app, monkeypatch
):
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

    response = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={
            "model": "norman-code",
            "input": "restart the service after approval",
            "reasoning": {"context": "all_turns", "effort": "medium"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_text"] == "local ok"
    assert payload["norman"]["local_execution"] is True
    assert payload["norman"]["cloud_forwarding"] is False
    assert payload["norman"]["authorization"]["execution_advisory"] == {
        "execution_allowed": False,
        "requires_approval": True,
    }
    assert payload["norman"]["responses_compatibility"]["reasoning_advisory"] == {
        "context": "all_turns",
        "effort": "medium",
    }
    assert len(calls) == 1
    assert calls[0]["model"] == "qwen3.6:35b-a3b-q4_K_M"


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
                    "model": "norman-code",
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
            "model": "norman-code",
            "instructions": "Answer briefly.",
            "store": False,
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
    assert "store" not in decisions[0]["payload"]
    assert response["norman"]["responses_compatibility"]["store_requested"] is False
    assert invocations[0]["messages"] == [
        {"role": "system", "content": "Answer briefly."},
        {"role": "developer", "content": "Preserve this role."},
        {"role": "user", "content": "status?"},
    ]


def test_openai_compat_responses_extracts_inline_images_locally(monkeypatch):
    import app.services.prompt_provider_facade as facade

    decisions = []
    invocations = []
    ocr_calls = []

    def fake_decision(**kwargs):
        decisions.append(kwargs)
        return _local_route_envelope(selected_model="qwen3.6:27b")

    def fake_ocr(**kwargs):
        ocr_calls.append(kwargs)
        return {"text": "Gmail match portal error for Andrew"}

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"])

    monkeypatch.setattr(facade, "provider_adapter_decision", fake_decision)
    monkeypatch.setattr(facade.norllama_gateway, "ocr_document", fake_ocr)
    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "What failed?"},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,aW1hZ2U=",
                        },
                    ],
                }
            ],
        }
    )

    assert response["object"] == "response"
    assert len(ocr_calls) == 1
    assert ocr_calls[0]["content"] == b"image"
    assert ocr_calls[0]["media_type"] == "image/png"
    assert ocr_calls[0]["filename"].endswith(".png")
    expected_content = (
        "What failed?\n[Attached image, locally extracted]\n"
        "Gmail match portal error for Andrew"
    )
    assert invocations[0]["messages"] == [{"role": "user", "content": expected_content}]
    assert decisions[0]["payload"]["input"] == invocations[0]["messages"]


def test_openai_compat_responses_uses_tesseract_when_vision_lane_is_blocked(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    invocations = []
    tesseract_calls = []

    monkeypatch.setattr(
        facade,
        "provider_adapter_decision",
        lambda **kwargs: _local_route_envelope(selected_model="qwen3.6:27b"),
    )
    monkeypatch.setattr(
        facade.norllama_gateway,
        "ocr_document",
        lambda **kwargs: (_ for _ in ()).throw(requests.HTTPError("policy_expired")),
    )

    def fake_tesseract(command, **kwargs):
        tesseract_calls.append((command, kwargs))
        return facade.subprocess.CompletedProcess(
            command,
            0,
            stdout=b"Fallback screenshot text",
            stderr=b"",
        )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"])

    monkeypatch.setattr(facade.subprocess, "run", fake_tesseract)
    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)

    execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,aW1hZ2U=",
                        }
                    ],
                }
            ],
        }
    )

    assert tesseract_calls[0][0] == ["tesseract", "stdin", "stdout"]
    assert tesseract_calls[0][1]["input"] == b"image"
    assert tesseract_calls[0][1]["timeout"] == 30
    assert invocations[0]["messages"] == [
        {
            "role": "user",
            "content": (
                "[Attached image, locally extracted]\nFallback screenshot text"
            ),
        }
    ]


def test_openai_compat_responses_rejects_remote_image_fetches():
    with pytest.raises(FacadeError) as error:
        execute_openai_responses_facade(
            {
                "model": "norman-code",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": "https://example.com/private.png",
                            }
                        ],
                    }
                ],
            }
        )

    assert error.value.status_code == 501
    assert error.value.code == "unsupported_input_image_reference"


def test_openai_compat_responses_accepts_benign_codex_context(monkeypatch):
    import app.services.prompt_provider_facade as facade

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
                        "content": "route-ok",
                    }
                }
            ]
        },
    )

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": [
                {
                    "role": "developer",
                    "content": "Do not stop at analysis; restart only when asked.",
                },
                {
                    "role": "user",
                    "content": "Repository instruction: deploy after release review.",
                },
                {"role": "user", "content": "Reply with exactly: route-ok"},
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "description": (
                        "Run a local shell command that can restart a service or "
                        "delete temporary files."
                    ),
                    "parameters": {"type": "object"},
                }
            ],
        },
        trusted_context={
            "gateway_route": "gold-book",
            "source_tui": "gold-book",
        },
    )

    assert response["output_text"] == "route-ok"
    route = response["norman"]["route"]
    assert route["normalized_prompt"] == "Reply with exactly: route-ok"
    assert route["caller_request"]["policy_prompt_source"] == "latest_user_turn"
    assert route["norman_route"]["recommendation"]["execution_allowed"] is True


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
            "model": "norman-code",
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


def test_openai_compat_responses_recovers_mixed_standalone_tool_envelopes(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    model_text = "\n".join(
        [
            "I’m checking the queue health now.",
            json.dumps(
                {
                    "tool_call": {
                        "name": "exec_command",
                        "arguments": {"cmd": "pwd"},
                    }
                }
            ),
            json.dumps(
                {
                    "tool_call": {
                        "name": "mcp__ops_openbrand.session_start",
                        "arguments": {
                            "user_email": "kris@openbrand.com",
                            "client_name": "Codex",
                        },
                    }
                }
            ),
            "The authenticated session will provide the queue status.",
        ]
    )
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )
    monkeypatch.setattr(
        facade.norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: _mock_local_chat(kwargs["messages"], kwargs["model"])
        | {"choices": [{"message": {"content": model_text}}]},
    )

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "How are the queues?",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__ops_openbrand",
                    "tools": [
                        {
                            "type": "function",
                            "name": "session_start",
                            "description": "Start an Ops Portal session.",
                            "parameters": {"type": "object"},
                        }
                    ],
                }
            ],
        },
        trusted_context={"source_tui": "codex-work"},
    )

    assert "tool_call" not in response["output_text"]
    assert response["output_text"] == (
        "I’m checking the queue health now.\n\n\n"
        "The authenticated session will provide the queue status."
    )
    function_calls = [
        item["name"] for item in response["output"] if item["type"] == "function_call"
    ]
    assert function_calls == [
        "exec_command",
        "mcp__ops_openbrand.session_start",
    ]


def test_responses_stream_normalizer_contains_mixed_tool_envelopes():
    import app.services.prompt_provider_facade as facade

    normalizer = facade.ResponsesStreamNormalizer()
    assert normalizer.feed("I’m checking now.\n") == ["I’m checking now.\n"]
    assert (
        normalizer.feed(
            '{"tool_call":{"name":"exec_command","arguments":{"cmd":"pwd"}}}'
        )
        == []
    )
    assert normalizer.feed("\n") == []
    assert (
        normalizer.feed(
            '{"tool_call":{"name":"mcp__ops_openbrand.session_start",'
            '"arguments":{"user_email":"kris@openbrand.com"}}}'
        )
        == []
    )
    assert normalizer.feed("\nSession started.") == []

    normalized = normalizer.finalize()

    assert normalized.visible_text == "I’m checking now.\n\n\nSession started."
    assert [call["name"] for call in normalized.raw_tool_calls] == [
        "exec_command",
        "mcp__ops_openbrand.session_start",
    ]
    assert "tool_call" not in normalized.visible_text


def test_openai_compat_responses_stream_repairs_tool_intention_without_call(
    test_app,
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    upstream = _MockNativeStreamResponse(
        [
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": "I'll run `pwd` once to get the directory.",
                }
            ),
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "done": True,
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                }
            ),
        ]
    )
    repair_invocations = []
    monkeypatch.setattr(
        norllama_gateway,
        "invoke_text_chat_stream",
        lambda **kwargs: norllama_gateway.NorllamaTextStream(
            upstream,
            model=kwargs["model"],
        ),
    )

    def repair_chat(**kwargs):
        repair_invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"exec_command",'
                            '"arguments":{"cmd":"pwd"}}}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", repair_chat)

    result = test_app.post(
        "/v1/responses",
        headers=_proxy_headers(monkeypatch),
        json={
            "model": "norman-code",
            "input": "Use exec_command to run pwd exactly once.",
            "stream": True,
        },
    )

    assert result.status_code == 200
    payloads = [
        json.loads(data)
        for event, data in _response_sse_events(result.text)
        if event and data != "[DONE]"
    ]
    assert not any(
        payload["type"] == "response.output_text.delta" for payload in payloads
    )
    function_call = next(
        payload["item"]
        for payload in payloads
        if payload["type"] == "response.output_item.done"
        and payload["item"]["type"] == "function_call"
    )
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )
    assert function_call["name"] == "exec_command"
    assert function_call["arguments"] == '{"cmd":"pwd"}'
    assert completed["output_text"] == ""
    assert completed["norman"]["responses_compatibility"]["tool_chain"]["watchdog"] == {
        "state": "repaired",
        "attempts": 1,
    }
    assert len(repair_invocations) == 1
    assert repair_invocations[0]["messages"][-1] == {
        "role": "system",
        "content": facade._TOOL_PROTOCOL_REPAIR_MESSAGE,
    }


def test_openai_compat_responses_can_return_native_function_call(monkeypatch):
    import app.services.prompt_provider_facade as facade

    native_call_id = "call_native_shell"
    native_item_id = "fc_native_shell"
    native_arguments = '{"cmd":"pwd"}'
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
                        "content": json.dumps(
                            {
                                "arguments": native_arguments,
                                "call_id": native_call_id,
                                "id": native_item_id,
                                "name": "shell",
                                "type": "function_call",
                            }
                        )
                    }
                }
            ]
        },
    )

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
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
    assert response["output"] == [
        {
            "id": native_item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": native_call_id,
            "name": "shell",
            "arguments": native_arguments,
        }
    ]


def test_openai_compat_responses_can_return_declared_mcp_namespace_function_call(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    native_call_id = "call_ops_health"
    native_item_id = "fc_ops_health"
    native_arguments = "{}"
    native_name = "mcp__ops_openbrand.system_health"
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
                        "content": json.dumps(
                            {
                                "arguments": native_arguments,
                                "call_id": native_call_id,
                                "id": native_item_id,
                                "name": native_name,
                                "type": "function_call",
                            }
                        )
                    }
                }
            ]
        },
    )

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Check the internal system health.",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__ops_openbrand",
                    "tools": [
                        {
                            "type": "function",
                            "name": "system_health",
                            "description": "Read the current system health.",
                            "parameters": {"type": "object"},
                        }
                    ],
                }
            ],
        }
    )

    assert response["output_text"] == ""
    assert response["output"] == [
        {
            "id": native_item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": native_call_id,
            "name": native_name,
            "arguments": native_arguments,
        }
    ]


def test_openai_compat_responses_flattens_namespace_tool_contract():
    import app.services.prompt_provider_facade as facade

    contract = facade._tool_contract_message(
        {
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__ops_openbrand",
                    "tools": [
                        {
                            "type": "function",
                            "name": "system_health",
                            "description": "Read the current system health.",
                            "parameters": {"type": "object"},
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "mcp__ops_openbrand.data_status_get",
                                "description": "Check source freshness.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"source": {"type": "string"}},
                                },
                            },
                        },
                        {
                            "type": "web_search_preview",
                            "name": "unsupported_member",
                        },
                    ],
                }
            ]
        }
    )

    assert len(contract) == 1
    tools = contract[0][facade.TOOL_CONTRACT_CONTEXT_MARKER]["tools"]
    assert tools == [
        {
            "name": "mcp__ops_openbrand.system_health",
            "type": "function",
            "description": "Read the current system health.",
            "parameters": {"type": "object"},
        },
        {
            "name": "mcp__ops_openbrand.data_status_get",
            "type": "function",
            "description": "Check source freshness.",
            "parameters": {
                "type": "object",
                "properties": {"source": {"type": "string"}},
            },
        },
    ]
    assert "mcp__ops_openbrand" not in {tool["name"] for tool in tools}


def test_openai_compat_responses_keeps_undeclared_mcp_namespace_call_as_text(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    model_text = json.dumps(
        {
            "arguments": "{}",
            "call_id": "call_undeclared_ops",
            "id": "fc_undeclared_ops",
            "name": "mcp__ops_openbrand.write_system_state",
            "type": "function_call",
        }
    )
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
        | {"choices": [{"message": {"content": model_text}}]},
    )

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Check the internal system health.",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__ops_openbrand",
                    "tools": [
                        {
                            "type": "function",
                            "name": "system_health",
                            "description": "Read the current system health.",
                            "parameters": {"type": "object"},
                        }
                    ],
                }
            ],
        }
    )

    assert response["output_text"] == model_text
    assert [item["type"] for item in response["output"]] == ["message"]
    assert response["output"][0]["content"][0]["text"] == model_text


def test_openai_compat_responses_preserves_declared_codex_apps_tool_call(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    invocations = []
    tool_name = "mcp__codex_apps__atlassian_rovo.search_company_knowledge"
    tool_arguments = {"query": "highest priority jira ticket"}
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "tool_call": {
                                    "name": tool_name,
                                    "arguments": tool_arguments,
                                }
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Tell me the highest priority Jira ticket right now.",
            "tools": [
                {
                    "type": "function",
                    "name": tool_name,
                    "description": "Search company knowledge.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ],
        }
    )

    assert len(invocations) == 1
    assert response["output_text"] == ""
    assert [item["name"] for item in response["output"]] == [tool_name]
    assert json.loads(response["output"][0]["arguments"]) == tool_arguments
    assert "tool_search" not in json.dumps(response["output"])


def test_openai_compat_responses_keeps_undeclared_tool_envelope_as_text(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    invocations = []
    undeclared_tool_name = "mcp__codex_apps__atlassian_rovo.search_company_knowledge"
    model_text = json.dumps(
        {
            "tool_call": {
                "name": undeclared_tool_name,
                "arguments": {"query": "highest priority jira ticket"},
            }
        }
    )
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [{"message": {"content": model_text}}]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Tell me the highest priority Jira ticket right now.",
            "tools": [
                {
                    "type": "function",
                    "name": "ticket_search",
                    "description": "Search Jira tickets.",
                    "parameters": {"type": "object"},
                }
            ],
        }
    )

    assert len(invocations) == 1
    assert response["output_text"] == model_text
    assert response["output"] == [
        {
            "id": response["output"][0]["id"],
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": model_text,
                    "annotations": [],
                }
            ],
        }
    ]
    assert "tool_search" not in json.dumps(response["output"])


def test_openai_compat_responses_keeps_undeclared_native_function_call_as_text(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    model_text = json.dumps(
        {
            "arguments": '{"query":"highest priority jira ticket"}',
            "call_id": "call_undeclared",
            "id": "fc_undeclared",
            "name": "mcp__codex_apps__atlassian_rovo.search_company_knowledge",
            "type": "function_call",
        }
    )
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
        | {"choices": [{"message": {"content": model_text}}]},
    )

    response = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Tell me the highest priority Jira ticket right now.",
            "tools": [
                {
                    "type": "function",
                    "name": "ticket_search",
                    "description": "Search Jira tickets.",
                    "parameters": {"type": "object"},
                }
            ],
        }
    )

    assert response["output_text"] == model_text
    assert [item["type"] for item in response["output"]] == ["message"]
    assert response["output"][0]["content"][0]["text"] == model_text


def test_openai_compat_responses_repairs_repeated_declared_tool_call(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    invocations = []
    tool_name = "tool_search"
    tool_arguments = {"query": "Jira data checks"}
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        content = (
            "Jira data checks are complete."
            if len(invocations) == 3
            else json.dumps(
                {
                    "tool_call": {
                        "name": tool_name,
                        "arguments": tool_arguments,
                    }
                }
            )
        )
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [{"message": {"content": content}}]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    tools = [
        {
            "type": "function",
            "name": tool_name,
            "description": "Discover a connected tool.",
            "parameters": {"type": "object"},
        }
    ]

    first = execute_openai_responses_facade(
        {
            "model": "norman-code-governed",
            "input": "Run checks on Jira and our data.",
            "tools": tools,
        }
    )
    function_call = first["output"][0]
    second = execute_openai_responses_facade(
        {
            "model": "norman-code-governed",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": function_call["call_id"],
                    "output": '{"tools":[{"name":"ticket_search"}]}',
                }
            ],
            "tools": tools,
        }
    )

    assert len(invocations) == 3
    assert second["output_text"] == "Jira data checks are complete."
    assert [item["type"] for item in second["output"]] == ["message"]
    assert second["norman"]["responses_compatibility"]["tool_chain"]["watchdog"] == {
        "state": "repaired",
        "attempts": 1,
    }
    assert invocations[-1]["messages"][-1] == {
        "role": "system",
        "content": facade._TOOL_CONTINUATION_REPAIR_MESSAGE,
    }


def test_openai_compat_responses_remaps_reused_call_id_after_protocol_repair(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    invocations = []
    reused_call_id = "call_reused_by_repair"
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        if len(invocations) == 1:
            content = json.dumps(
                {
                    "tool_call": {
                        "call_id": reused_call_id,
                        "id": "fc_reused_by_repair",
                        "name": "shell",
                        "arguments": {"cmd": "cat SKILL.md"},
                    }
                }
            )
        elif len(invocations) == 2:
            content = "I need to read the portal contract before connecting."
        elif len(invocations) == 3:
            content = json.dumps(
                {
                    "tool_call": {
                        "call_id": reused_call_id,
                        "id": "fc_reused_by_repair",
                        "name": "shell",
                        "arguments": {"cmd": "cat portal-contract.md"},
                    }
                }
            )
        else:
            content = "Queue health is normal."
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [{"message": {"content": content}}]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    tools = [
        {
            "type": "function",
            "name": "shell",
            "description": "Run a shell command.",
            "parameters": {"type": "object"},
        }
    ]

    first = execute_openai_responses_facade(
        {"model": "norman-code", "input": "Check the queues.", "tools": tools}
    )
    first_call = first["output"][0]
    assert first_call["call_id"] == reused_call_id

    second = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": first_call["call_id"],
                    "output": "skill contents",
                }
            ],
            "tools": tools,
        }
    )
    second_call = second["output"][0]

    assert second_call["call_id"] != reused_call_id
    assert second_call["id"] != "fc_reused_by_repair"
    assert json.loads(second_call["arguments"]) == {"cmd": "cat portal-contract.md"}
    assert second["norman"]["responses_compatibility"]["tool_chain"]["watchdog"] == {
        "state": "repaired",
        "attempts": 1,
    }

    third = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": second["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": second_call["call_id"],
                    "output": "portal contract contents",
                }
            ],
            "tools": tools,
        }
    )

    assert third["output_text"] == "Queue health is normal."
    assert len(invocations) == 4


def test_openai_compat_responses_rejects_repeated_tool_call_after_repair(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    invocations = []
    tool_name = "tool_search"
    tool_arguments = {"query": "Jira data checks"}
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "tool_call": {
                                    "name": tool_name,
                                    "arguments": tool_arguments,
                                }
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    tools = [
        {
            "type": "function",
            "name": tool_name,
            "description": "Discover a connected tool.",
            "parameters": {"type": "object"},
        }
    ]

    first = execute_openai_responses_facade(
        {
            "model": "norman-code-governed",
            "input": "Run checks on Jira and our data.",
            "tools": tools,
        }
    )
    function_call = first["output"][0]

    with pytest.raises(FacadeError) as captured:
        execute_openai_responses_facade(
            {
                "model": "norman-code-governed",
                "previous_response_id": first["id"],
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": function_call["call_id"],
                        "output": '{"tools":[{"name":"ticket_search"}]}',
                    }
                ],
                "tools": tools,
            }
        )

    assert len(invocations) == 3
    error = captured.value
    assert error.status_code == 502
    assert error.code == "tool_continuation_exhausted"
    assert error.norman["responses_compatibility"]["tool_chain"]["watchdog"] == {
        "state": "exhausted",
        "attempts": 1,
    }


def test_openai_compat_responses_transparent_mode_preserves_repeated_tool_call(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    invocations = []
    tool_name = "tool_search"
    tool_arguments = {"query": "Jira data checks"}
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "tool_call": {
                                    "name": tool_name,
                                    "arguments": tool_arguments,
                                }
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    tools = [
        {
            "type": "function",
            "name": tool_name,
            "description": "Discover a connected tool.",
            "parameters": {"type": "object"},
        }
    ]

    first = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Run checks on Jira and our data.",
            "tools": tools,
        }
    )
    function_call = first["output"][0]
    second = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": function_call["call_id"],
                    "output": '{"tools":[{"name":"ticket_search"}]}',
                }
            ],
            "tools": tools,
        }
    )

    assert len(invocations) == 2
    assert [item["type"] for item in second["output"]] == ["function_call"]
    assert second["output"][0]["name"] == tool_name
    compatibility = second["norman"]["responses_compatibility"]
    assert compatibility["tool_bridge_mode"] == "transparent"
    assert compatibility["tool_chain"]["watchdog"] == {
        "state": "passthrough",
        "attempts": 0,
    }


def test_openai_compat_responses_keeps_saved_call_metadata_server_side(
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
        response = _mock_local_chat(kwargs["messages"], kwargs["model"])
        if not any(message["role"] == "tool" for message in kwargs["messages"]):
            response["choices"] = [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"shell","arguments":{"cmd":"pwd"}}}'
                        )
                    }
                }
            ]
        return response

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)

    first = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "check the repo",
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "description": "Run a shell command.",
                    "parameters": {"type": "object"},
                }
            ],
        }
    )
    function_call = first["output"][0]
    second = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": function_call["call_id"],
                    "output": "/home/kristopher/code/norman",
                }
            ],
        }
    )

    assert second["output_text"] == "local ok"
    assert second["norman"]["responses_compatibility"]["tool_chain"] == {
        "schema": "norman.responses-tool-chain.v1",
        "turn_type": "after_tool_result",
        "chain_depth": 1,
        "tool_results_supplied": 1,
        "tool_results_matched": 1,
        "successful_tool_results": 1,
        "tool_calls_returned": 0,
        "outcome": "final_after_tool",
        "watchdog": {
            "state": "normal",
            "attempts": 0,
        },
    }
    assert len(invocations) == 2
    replayed = invocations[-1]["messages"]
    assert {
        "role": "tool",
        "type": "function_call_output",
        "call_id": function_call["call_id"],
        "output": "/home/kristopher/code/norman",
        "content": json.dumps(
            {
                "type": "function_call_output",
                "call_id": function_call["call_id"],
                "output": "/home/kristopher/code/norman",
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    } in replayed
    assert {
        "role": "assistant",
        "type": "function_call",
        "call_id": function_call["call_id"],
        "name": "shell",
        "arguments": function_call["arguments"],
        "content": json.dumps(
            {
                "type": "function_call",
                "call_id": function_call["call_id"],
                "name": "shell",
                "arguments": function_call["arguments"],
                "id": function_call["id"],
                "status": function_call["status"],
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        "id": function_call["id"],
        "status": function_call["status"],
    } in replayed


def test_openai_compat_responses_replays_text_and_tool_output_with_call_arguments(
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
        {"model": "norman-code", "input": "remember alpha"}
    )
    second = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call",
                    "call_id": "call_shell",
                    "name": "shell",
                    "arguments": '{"cmd":"pwd"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_shell",
                    "output": "tool says beta",
                },
                {"role": "user", "content": "continue"},
            ],
        }
    )

    compatibility = second["norman"]["responses_compatibility"]
    assert compatibility["history_replayed"] is True
    assert compatibility["history_state"] == "replayed"
    replayed = invocations[-1]["messages"]
    assert {"role": "assistant", "content": "local ok"} in replayed
    assert {
        "role": "tool",
        "type": "function_call_output",
        "call_id": "call_shell",
        "output": "tool says beta",
        "content": (
            '{"call_id":"call_shell","output":"tool says beta",'
            '"type":"function_call_output"}'
        ),
    } in replayed
    assert {"role": "user", "content": "continue"} in replayed
    assert {
        "role": "assistant",
        "type": "function_call",
        "call_id": "call_shell",
        "name": "shell",
        "arguments": '{"cmd":"pwd"}',
        "content": (
            '{"arguments":"{\\"cmd\\":\\"pwd\\"}","call_id":"call_shell",'
            '"name":"shell","type":"function_call"}'
        ),
    } in replayed


def test_openai_compat_responses_store_false_preserves_ephemeral_context(monkeypatch):
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

    response = execute_openai_responses_facade(
        {"model": "norman-code", "input": "do not retain", "store": False}
    )

    continued = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": response["id"],
            "input": [
                {
                    "type": "function_call",
                    "call_id": "call_shell",
                    "name": "shell",
                    "arguments": '{"cmd":"git status"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_shell",
                    "output": "working tree clean",
                },
                {"role": "user", "content": "continue"},
            ],
        }
    )

    compatibility = continued["norman"]["responses_compatibility"]
    assert compatibility["history_replayed"] is True
    assert compatibility["history_state"] == "replayed"
    assert (
        response["norman"]["responses_compatibility"]["state_retention"] == "ephemeral"
    )
    replayed = invocations[-1]["messages"]
    assert {"role": "assistant", "content": "local ok"} in replayed
    assert {
        "role": "tool",
        "type": "function_call_output",
        "call_id": "call_shell",
        "output": "working tree clean",
        "content": (
            '{"call_id":"call_shell","output":"working tree clean",'
            '"type":"function_call_output"}'
        ),
    } in replayed
    assert {"role": "user", "content": "continue"} in replayed
    assert {
        "role": "assistant",
        "type": "function_call",
        "call_id": "call_shell",
        "name": "shell",
        "arguments": '{"cmd":"git status"}',
        "content": (
            '{"arguments":"{\\"cmd\\":\\"git status\\"}","call_id":"call_shell",'
            '"name":"shell","type":"function_call"}'
        ),
    } in replayed


def test_openai_compat_responses_replays_tool_output_bytes_without_trimming(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    invocations = []
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        return _mock_local_chat(kwargs["messages"], kwargs["model"])

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    output = "  first line\nsecond line  \n"

    execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "  preserve input bytes\n"}
                    ],
                },
                {
                    "type": "function_call",
                    "call_id": "call_exact_output",
                    "name": "shell",
                    "arguments": '{"cmd":"pwd"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_exact_output",
                    "output": output,
                },
            ],
        }
    )

    replayed = invocations[0]["messages"]
    tool_message = next(
        message for message in replayed if message.get("type") == "function_call_output"
    )
    assert tool_message["output"] == output
    assert json.loads(tool_message["content"])["output"] == output
    assert replayed[0]["content"] == "  preserve input bytes\n"
    prompt = norllama_gateway.messages_to_prompt(replayed)
    assert f"TOOL:\n{tool_message['content']}" in prompt
    assert "USER:\n  preserve input bytes\n" in prompt


def test_openai_compat_responses_rejects_changed_or_unknown_call_before_invocation(
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
        return _mock_local_chat(kwargs["messages"], kwargs["model"]) | {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"shell","arguments":{"cmd":"pwd"}}}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    first = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "check the repo",
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "parameters": {"type": "object"},
                }
            ],
        }
    )
    function_call = first["output"][0]

    with pytest.raises(FacadeError) as mismatch:
        execute_openai_responses_facade(
            {
                "model": "norman-code",
                "previous_response_id": first["id"],
                "input": [
                    {
                        "type": "function_call",
                        "call_id": function_call["call_id"],
                        "name": "shell",
                        "arguments": '{"cmd":"git status"}',
                    }
                ],
            }
        )
    assert mismatch.value.code == "function_call_mismatch"

    with pytest.raises(FacadeError) as unknown:
        execute_openai_responses_facade(
            {
                "model": "norman-code",
                "previous_response_id": first["id"],
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": "call_not_returned_by_the_model",
                        "output": "ignored",
                    }
                ],
            }
        )
    assert unknown.value.code == "unknown_function_call_id"
    assert len(invocations) == 1


def test_openai_compat_responses_rejects_changed_historical_tool_output(
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
        response = _mock_local_chat(kwargs["messages"], kwargs["model"])
        if not any(message["role"] == "tool" for message in kwargs["messages"]):
            response["choices"] = [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"shell","arguments":{"cmd":"pwd"}}}'
                        )
                    }
                }
            ]
        return response

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    first = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "check the repo",
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "parameters": {"type": "object"},
                }
            ],
        }
    )
    function_call = first["output"][0]
    second = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": function_call["call_id"],
                    "output": "first result",
                }
            ],
        }
    )

    with pytest.raises(FacadeError) as mismatch:
        execute_openai_responses_facade(
            {
                "model": "norman-code",
                "previous_response_id": second["id"],
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": function_call["call_id"],
                        "output": "changed result",
                    }
                ],
            }
        )
    assert mismatch.value.code == "function_call_output_mismatch"
    assert len(invocations) == 2


def test_openai_compat_responses_ignores_generated_reasoning_in_continuation(
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
        response = _mock_local_chat(kwargs["messages"], kwargs["model"])
        if not any(message["role"] == "tool" for message in kwargs["messages"]):
            response["choices"] = [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"shell","arguments":{"cmd":"pwd"}}}'
                        )
                    }
                }
            ]
        return response

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    first = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "check the repo",
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "parameters": {"type": "object"},
                }
            ],
        }
    )
    function_call = first["output"][0]
    second = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "opaque"}],
                },
                {
                    "type": "function_call_output",
                    "call_id": function_call["call_id"],
                    "output": "working tree clean",
                },
            ],
        }
    )

    assert second["output_text"] == "local ok"
    assert len(invocations) == 2
    assert not any(
        message.get("content") == "opaque" for message in invocations[-1]["messages"]
    )


def test_openai_compat_responses_preserves_historical_tool_contracts():
    import app.services.prompt_provider_facade as facade

    first_tools = [
        {
            "type": "function",
            "name": "first_tool",
            "parameters": {"type": "object"},
        }
    ]
    second_tools = [
        {
            "type": "function",
            "name": "second_tool",
            "parameters": {"type": "object"},
        }
    ]
    old_contract = facade._tool_contract_message({"tools": first_tools})[0]
    messages = [
        {"role": "user", "content": "before contract"},
        old_contract,
        {"role": "assistant", "content": "after contract"},
        dict(old_contract),
        {"role": "user", "content": "after duplicate"},
    ]

    updated, extras = facade._messages_with_current_tool_contract(
        messages,
        {"tools": second_tools},
    )

    contracts = [
        message for message in updated if facade._is_tool_contract_message(message)
    ]
    assert len(contracts) == 2
    assert updated == messages
    assert len(extras) == 1
    assert extras[0][facade.TOOL_CONTRACT_CONTEXT_MARKER]["tools"][0]["name"] == (
        "second_tool"
    )
    assert [message["content"] for message in updated if message["role"] == "user"] == [
        "before contract",
        "after duplicate",
    ]


def test_openai_compat_responses_adds_codex_tool_contract_when_omitted(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    prepared = facade._prepare_responses_execution(
        {"model": "norman-code", "input": "Inspect the working tree."},
        trusted_context={"gateway_route": "cloudagent", "source_tui": "cloudagent"},
    )

    contract = next(
        message
        for message in prepared.messages
        if facade._is_tool_contract_message(message)
    )
    tools = contract[facade.TOOL_CONTRACT_CONTEXT_MARKER]["tools"]

    assert [tool["name"] for tool in tools] == ["exec_command", "apply_patch"]
    assert "emit that call now" in contract["content"]


def test_openai_compat_responses_does_not_inject_codex_tools_for_ordinary_calls():
    import app.services.prompt_provider_facade as facade

    assert (
        facade._implicit_codex_tui_tools_required(
            {"model": "norman-code", "input": "hello"},
            {},
        )
        is False
    )
    assert (
        facade._implicit_codex_tui_tools_required(
            {"model": "norman-code", "input": "hello", "tools": []},
            {"source_tui": "cloudagent"},
        )
        is True
    )


def test_openai_compat_responses_supplements_tui_mcp_tools_with_shell_contract(
    monkeypatch,
):
    import app.services.prompt_provider_facade as facade

    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )
    prepared = facade._prepare_responses_execution(
        {
            "model": "norman-code",
            "input": "Inspect the working tree.",
            "tools": [
                {
                    "type": "function",
                    "name": "openaiDeveloperDocs.search",
                    "description": "Search documentation.",
                    "parameters": {"type": "object"},
                }
            ],
        },
        trusted_context={"gateway_route": "cloudagent", "source_tui": "cloudagent"},
    )

    contract = next(
        message
        for message in prepared.messages
        if facade._is_tool_contract_message(message)
    )
    assert [
        tool["name"] for tool in contract[facade.TOOL_CONTRACT_CONTEXT_MARKER]["tools"]
    ] == ["openaiDeveloperDocs.search", "exec_command", "apply_patch"]


def test_openai_compat_responses_converts_tui_shell_call_with_mcp_tools(monkeypatch):
    import app.services.prompt_provider_facade as facade

    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )
    monkeypatch.setattr(
        facade.norllama_gateway,
        "invoke_text_chat",
        lambda **kwargs: _mock_local_chat(kwargs["messages"], kwargs["model"])
        | {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"exec_command",'
                            '"arguments":{"cmd":"git rev-parse HEAD"}}}'
                        )
                    }
                }
            ]
        },
    )

    response = facade.execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Inspect the working tree.",
            "tools": [
                {
                    "type": "function",
                    "name": "openaiDeveloperDocs.search",
                    "parameters": {"type": "object"},
                }
            ],
        },
        trusted_context={"gateway_route": "cloudagent", "source_tui": "cloudagent"},
    )

    assert response["output_text"] == ""
    assert response["output"][0]["type"] == "function_call"
    assert response["output"][0]["name"] == "exec_command"
    assert response["output"][0]["arguments"] == ('{"cmd":"git rev-parse HEAD"}')


def test_openai_compat_responses_replays_typed_message_after_tool_output(monkeypatch):
    import app.services.prompt_provider_facade as facade

    facade.reset_facade_response_state()
    invocations = []
    monkeypatch.setattr(
        facade, "provider_adapter_decision", lambda **kwargs: _local_route_envelope()
    )

    def fake_chat(**kwargs):
        invocations.append(kwargs)
        response = _mock_local_chat(kwargs["messages"], kwargs["model"])
        if len(invocations) == 1:
            response["choices"] = [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"tool_search",'
                            '"arguments":{"query":"synthetic health"}}}'
                        )
                    }
                }
            ]
        elif len(invocations) == 2:
            response["choices"] = [
                {
                    "message": {
                        "content": (
                            '{"tool_call":{"name":"synthetic.status_lookup",'
                            '"arguments":{}}}'
                        )
                    }
                }
            ]
        else:
            assert kwargs["messages"][-1] == {
                "role": "user",
                "content": "Return a concise final health result now.",
            }
        return response

    monkeypatch.setattr(facade.norllama_gateway, "invoke_text_chat", fake_chat)
    discovery_tools = [
        {
            "type": "function",
            "name": "tool_search",
            "parameters": {"type": "object"},
        }
    ]
    status_tools = [
        {
            "type": "function",
            "name": "synthetic.status_lookup",
            "parameters": {"type": "object"},
        }
    ]

    first = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "input": "Run the synthetic health check.",
            "tools": discovery_tools,
        }
    )
    second = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": first["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": first["output"][0]["call_id"],
                    "output": '{"tools":["synthetic.status_lookup"]}',
                }
            ],
            "tools": status_tools,
        }
    )
    final = execute_openai_responses_facade(
        {
            "model": "norman-code",
            "previous_response_id": second["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": second["output"][0]["call_id"],
                    "output": '{"status":"ok"}',
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": "Return a concise final health result now.",
                },
            ],
            "tools": status_tools,
        }
    )

    assert final["output_text"] == "local ok"
    assert len(invocations) == 3
    third_messages = invocations[2]["messages"]
    tool_contracts = [
        message
        for message in third_messages
        if facade._is_tool_contract_message(message)
    ]
    assert [
        message[facade.TOOL_CONTRACT_CONTEXT_MARKER]["tools"][0]["name"]
        for message in tool_contracts
    ] == ["tool_search", "synthetic.status_lookup"]
    assert third_messages[-2]["type"] == "function_call_output"


def test_openai_compat_proxy_observability_records_success_without_prompt_leak(
    test_app,
    monkeypatch,
):
    from app.services.prompt_provider_facade import norllama_gateway
    from app.services.proxy_observability import reset_proxy_events

    reset_proxy_events()
    headers = {
        **_proxy_headers(monkeypatch, route="gold-book"),
        "X-Norman-Client": "codex-work",
        "X-Norman-Team": "platform",
    }
    monkeypatch.setattr(norllama_gateway, "invoke_text_chat", _mock_local_chat)

    response = test_app.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "norman-code",
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
    assert events[0]["gateway_route"] == "gold-book"
    assert events[0]["source_tui"] == "gold-book"
    assert events[0]["policy_scope"] == "tui:gold-book"
    assert "secret-value" not in str(events[0])


def test_openai_compat_proxy_observability_reports_auth_and_unsupported_alerts(
    test_app,
    monkeypatch,
):
    from app.services.proxy_observability import reset_proxy_events

    reset_proxy_events()
    headers = _proxy_headers(monkeypatch)

    denied = test_app.get("/v1/models", headers=_gateway_headers())
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
