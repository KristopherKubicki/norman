from __future__ import annotations

import pytest

from app.services.console_runtime.policy import (
    classify_egress,
    egress_allowed,
    resolve_runtime_mode,
    route_decision,
)


def test_cloud_llm_offline_blocks_cloud_llm_but_allows_web_research():
    state = resolve_runtime_mode({"cloud_llm_disabled": True})

    assert state.active_mode == "cloud_llm_offline"
    assert state.cloud_llm_allowed is False
    assert state.codex_allowed is False
    assert egress_allowed("cloud_llm", state) is False
    assert egress_allowed("web_research", state) is True

    decision = route_decision(
        task_kind="plan",
        route={
            "provider": "bedrock",
            "lane": "cloud_planner",
            "model": "anthropic.claude",
            "endpoint": "https://bedrock.us-east-1.amazonaws.com",
        },
        policy_state=state,
        runner="bedrock",
    )

    assert decision.allowed is False
    assert decision.egress_class == "cloud_llm"
    assert "cloud LLM provider blocked by policy" in decision.blocked_reasons


@pytest.mark.parametrize(
    ("route_policy", "expected"),
    [
        (
            {"mode": "primary_online"},
            {
                "active_mode": "primary_online",
                "llm_plane": "cloud_ok",
                "cloud_llm_allowed": True,
                "codex_allowed": True,
                "web_allowed": True,
                "shell_allowed": True,
            },
        ),
        (
            {"local_first": True},
            {
                "active_mode": "local_first_online",
                "llm_plane": "cloud_ok",
                "cloud_llm_allowed": True,
                "codex_allowed": True,
                "web_allowed": True,
                "shell_allowed": True,
            },
        ),
        (
            {"network_mode": "web_only_no_cloud_llm"},
            {
                "active_mode": "cloud_llm_offline",
                "llm_plane": "cloud_llm_offline",
                "cloud_llm_allowed": False,
                "codex_allowed": False,
                "web_allowed": True,
                "shell_allowed": True,
            },
        ),
        (
            {"network_mode": "lan_only"},
            {
                "active_mode": "lan_only",
                "llm_plane": "lan_local_only",
                "cloud_llm_allowed": False,
                "codex_allowed": False,
                "web_allowed": False,
                "shell_allowed": True,
            },
        ),
        (
            {"network_mode": "airgap"},
            {
                "active_mode": "airgap_local",
                "llm_plane": "lan_local_only",
                "cloud_llm_allowed": False,
                "codex_allowed": False,
                "web_allowed": False,
                "shell_allowed": True,
            },
        ),
        (
            {"mode": "control-only"},
            {
                "active_mode": "control_only",
                "llm_plane": "no_inference",
                "cloud_llm_allowed": False,
                "codex_allowed": False,
                "web_allowed": False,
                "shell_allowed": False,
            },
        ),
    ],
)
def test_runtime_mode_tiers_are_explicit(route_policy, expected):
    state = resolve_runtime_mode(route_policy)

    for field, value in expected.items():
        assert getattr(state, field) == value


def test_web_only_no_cloud_llm_still_allows_web_research():
    state = resolve_runtime_mode({"network_mode": "web_only_no_cloud_llm"})

    assert classify_egress("https://search.example.com") == "web_research"
    assert egress_allowed("web_research", state) is True
    assert egress_allowed("cloud_llm", state) is False

    web_route = route_decision(
        task_kind="research",
        route={
            "provider": "web",
            "lane": "research",
            "endpoint": "https://search.example.com",
        },
        policy_state=state,
        runner="web",
    )
    cloud_route = route_decision(
        task_kind="plan",
        route={
            "provider": "openai",
            "lane": "cloud",
            "model": "gpt-next",
            "endpoint": "https://api.openai.com/v1/responses",
        },
        policy_state=state,
        runner="openai",
    )

    assert web_route.allowed is True
    assert cloud_route.allowed is False
    assert "cloud LLM provider blocked by policy" in cloud_route.blocked_reasons


@pytest.mark.parametrize(
    ("model", "model_family"),
    [
        ("qwen4-coder:72b-q4_K_M", "qwen"),
        ("gemma5:48b-it-q4_K_M", "gemma"),
        ("codex-next-local:30b", "codex"),
    ],
)
def test_local_route_decision_keeps_future_model_families_modular(model, model_family):
    state = resolve_runtime_mode({"cloud_llm_disabled": True})
    capabilities = {"models": [model], "provider": "norllama"}

    decision = route_decision(
        task_kind="plan",
        route={
            "provider": "norllama",
            "lane": "local_planner",
            "model": model,
            "endpoint": "https://llm.home.arpa/v1",
            "local": True,
        },
        policy_state=state,
        runner="norllama",
        capabilities=capabilities,
        metadata={"model_family": model_family},
    )

    assert decision.allowed is True
    assert decision.selected_model == model
    assert decision.selected_provider == "norllama"
    assert decision.capability_snapshot == capabilities
    assert decision.metadata["model_family"] == model_family


def test_lan_only_allows_home_arpa_and_blocks_public_web():
    state = resolve_runtime_mode({"network_mode": "lan_only"})

    assert state.active_mode == "lan_only"
    assert classify_egress("https://llm.home.arpa/v1") == "lan"
    assert classify_egress("https://example.com") == "web_research"
    assert egress_allowed("lan", state) is True
    assert egress_allowed("web_research", state) is False


def test_openai_compatible_home_arpa_is_lan_not_cloud_llm():
    state = resolve_runtime_mode({"cloud_llm_disabled": True})

    decision = route_decision(
        task_kind="plan",
        route={
            "provider": "openai_compatible",
            "lane": "local_planner",
            "model": "gemma4:26b-a4b-it-q4_K_M",
            "endpoint": "https://llm.home.arpa/v1",
            "local": True,
        },
        policy_state=state,
        runner="norllama",
    )

    assert (
        classify_egress("https://llm.home.arpa/v1", provider="openai_compatible")
        == "lan"
    )
    assert decision.allowed is True
    assert decision.egress_class == "lan"
    assert decision.cost_basis == "local_token_estimate"


def test_codex_quarantine_blocks_codex_runner_but_not_norllama():
    state = resolve_runtime_mode({"codex_disabled": True})

    codex = route_decision(
        task_kind="chat",
        route={"provider": "codex", "lane": "codex", "model": "gpt-5.5"},
        policy_state=state,
        runner="codex",
    )
    local = route_decision(
        task_kind="chat",
        route={
            "provider": "norllama",
            "lane": "local",
            "model": "gemma4:26b-a4b-it-q4_K_M",
            "endpoint": "https://llm.home.arpa/v1",
            "local": True,
        },
        policy_state=state,
        runner="norllama",
    )

    assert state.active_mode == "codex_quarantine"
    assert codex.allowed is False
    assert "Codex runner blocked by policy" in codex.blocked_reasons
    assert local.allowed is True
    assert local.metadata == {}


def test_control_only_blocks_inference_routes():
    state = resolve_runtime_mode({"mode": "control_only"})
    decision = route_decision(
        task_kind="summarize",
        route={
            "provider": "norllama",
            "lane": "local",
            "endpoint": "https://llm.home.arpa/v1",
            "local": True,
        },
        policy_state=state,
        runner="norllama",
    )

    assert state.llm_plane == "no_inference"
    assert decision.allowed is False
    assert "inference disabled by control-only mode" in decision.blocked_reasons
