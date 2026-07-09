from __future__ import annotations

import ipaddress
import os
from typing import Any, Mapping
from urllib.parse import urlparse

from app.services.console_runtime.types import RouteDecision, RuntimeModeState


CLOUD_LLM_PROVIDERS = {
    "anthropic",
    "aws-bedrock",
    "aws_bedrock",
    "bedrock",
    "codex",
    "openai",
    "openai-compatible",
    "openai_compatible",
    "openai-direct",
    "openai_direct",
}
OPENAI_COMPATIBLE_PROVIDERS = {"openai-compatible", "openai_compatible"}
LOCAL_PROVIDERS = {
    "fake",
    "local",
    "local_ollama",
    "local-ollama",
    "norllama",
    "ollama",
    "runtime-dry-run",
    "shell",
}
TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "force"}
FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
LOCAL_MODEL_SELECTION_VALUES = {
    "benchmark",
    "benchmark_catalog",
    "benchmark_policy",
    "benchmark_warm_policy",
    "capability_catalog",
    "catalog",
    "warm",
    "warm_policy",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, dict) else {}


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    clean = _lower(value)
    if not clean:
        return default
    if clean in TRUE_VALUES:
        return True
    if clean in FALSE_VALUES:
        return False
    return default


def _env_flag(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    return _flag(env.get(name), default)


def _policy_flag(
    policy: Mapping[str, Any],
    env: Mapping[str, str],
    policy_key: str,
    env_name: str,
    default: bool = False,
) -> bool:
    if policy_key in policy:
        return _flag(policy.get(policy_key), default)
    return _env_flag(env, env_name, default)


def _policy_value(
    policy: Mapping[str, Any], env: Mapping[str, str], policy_key: str, env_name: str
) -> str:
    return _clean(policy.get(policy_key)) or _clean(env.get(env_name))


def _host_is_lan(host: str) -> bool:
    clean = host.strip("[]").lower()
    if not clean:
        return False
    if clean in {"localhost", "llm.home.arpa"} or clean.endswith(".home.arpa"):
        return True
    try:
        address = ipaddress.ip_address(clean)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _host_is_local(host: str) -> bool:
    clean = host.strip("[]").lower()
    if clean in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(clean).is_loopback
    except ValueError:
        return False


def provider_is_cloud_llm(provider: str, runner: str = "") -> bool:
    provider_key = _lower(provider).replace("_", "-")
    runner_key = _lower(runner).replace("_", "-")
    return provider_key in CLOUD_LLM_PROVIDERS or runner_key in CLOUD_LLM_PROVIDERS


def _route_policy_has_runner(policy: Mapping[str, Any]) -> bool:
    return any(
        _clean(policy.get(key))
        for key in (
            "provider",
            "preferred_provider",
            "provider_surface",
            "runtime",
            "model_proxy",
        )
    )


def _route_policy_provider(policy: Mapping[str, Any]) -> str:
    return (
        _clean(policy.get("provider"))
        or _clean(policy.get("preferred_provider"))
        or _clean(policy.get("provider_surface"))
        or _clean(policy.get("model_proxy"))
        or _clean(policy.get("runtime"))
    )


def route_policy_is_catalog_candidate(policy: Mapping[str, Any]) -> bool:
    """Return true when a route policy should use Norllama capability selection."""

    provider = _lower(_route_policy_provider(policy)).replace("_", "-")
    if not provider:
        return True
    return provider in LOCAL_PROVIDERS or provider in {"norllama", "kernel-shadow"}


def with_local_first_catalog_defaults(
    route_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply Norman's TUI/kernel default: local Norllama before cloud.

    Explicit provider/model choices remain intact. The catalog default only fills in
    missing local route intent so planner/TUI calls select capability-specific local
    models before any cloud escalation path is considered.
    """

    policy = dict(route_policy or {})
    policy.setdefault("local_first", True)
    policy.setdefault("allow_cloud_proxy", False)
    policy.setdefault("allow_cloud_tool_proxy", False)
    policy.setdefault("escalation_policy", "explicit_cloud_only")
    policy.setdefault("cost_posture", "local_token_first")
    policy.setdefault("planner", "norllama")
    policy.setdefault("model_proxy", "norllama")
    if not _route_policy_has_runner(policy):
        policy["provider"] = "norllama"
    if route_policy_is_catalog_candidate(policy):
        policy.setdefault("provider", "norllama")
        policy.setdefault("preferred_provider", "norllama")
        policy.setdefault("use_capability_catalog", True)
        selection = _lower(policy.get("model_selection"))
        if not selection:
            policy["model_selection"] = "warm_policy"
        elif selection not in LOCAL_MODEL_SELECTION_VALUES:
            policy.setdefault("fallback_model_selection", selection)
    return policy


def _target_host(target: str) -> str:
    clean = _clean(target)
    if not clean:
        return ""
    parsed = urlparse(clean if "://" in clean else f"//{clean}")
    return parsed.hostname or clean.split("/", 1)[0].split(":", 1)[0]


def _openai_compatible_key(provider: str, runner: str = "") -> bool:
    provider_key = _lower(provider).replace("_", "-")
    runner_key = _lower(runner).replace("_", "-")
    return (
        provider_key in OPENAI_COMPATIBLE_PROVIDERS
        or runner_key in OPENAI_COMPATIBLE_PROVIDERS
    )


def _openai_compatible_lan_target(
    target: str = "", *, provider: str = "", runner: str = ""
) -> bool:
    if not _openai_compatible_key(provider, runner):
        return False
    host = _target_host(target)
    return bool(host and (_host_is_local(host) or _host_is_lan(host)))


def classify_egress(target: str = "", *, provider: str = "", runner: str = "") -> str:
    """Classify an outbound target for mode/egress policy.

    The class is intentionally coarse. It is used to decide whether the kernel
    may attempt a route; provider-specific auth and capability checks happen
    later in the adapter.
    """

    provider_key = _lower(provider).replace("_", "-")
    runner_key = _lower(runner).replace("_", "-")
    if _openai_compatible_lan_target(target, provider=provider, runner=runner):
        host = _target_host(target)
        return "local" if _host_is_local(host) else "lan"
    if provider_is_cloud_llm(provider, runner):
        return "cloud_llm"
    if provider_key in LOCAL_PROVIDERS or runner_key in LOCAL_PROVIDERS:
        if provider_key == "shell" or runner_key == "shell":
            return "local"
        return "lan"
    clean = _clean(target)
    if not clean:
        return "unknown_external"
    if clean.startswith("unix:") or clean.startswith("file:"):
        return "local"
    parsed = urlparse(clean if "://" in clean else f"//{clean}")
    host = parsed.hostname or clean.split("/", 1)[0].split(":", 1)[0]
    if _host_is_local(host):
        return "local"
    if _host_is_lan(host):
        return "lan"
    return "web_research"


def resolve_runtime_mode(
    route_policy: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> RuntimeModeState:
    policy = _dict(route_policy)
    values = env or os.environ

    requested_mode = _lower(
        _policy_value(policy, values, "mode", "NORMAN_RUNTIME_MODE")
        or _policy_value(policy, values, "offline_mode", "NORMAN_OFFLINE_MODE")
    )
    network_mode = _lower(
        _policy_value(policy, values, "network_mode", "NORMAN_NETWORK_MODE")
    )
    if not network_mode:
        network_mode = "internet_ok"
    if network_mode == "web_only_no_cloud_llm":
        cloud_llm_disabled = True
    else:
        cloud_llm_disabled = _policy_flag(
            policy,
            values,
            "cloud_llm_disabled",
            "NORMAN_CLOUD_LLM_DISABLED",
            False,
        )
    codex_disabled = _policy_flag(
        policy, values, "codex_disabled", "NORMAN_CODEX_DISABLED", False
    )
    third_party_disabled = _policy_flag(
        policy,
        values,
        "third_party_egress_disabled",
        "NORMAN_THIRD_PARTY_EGRESS_DISABLED",
        False,
    )
    no_inference = _policy_flag(
        policy, values, "no_inference", "NORMAN_NO_INFERENCE", False
    )
    tui_backend = _lower(values.get("NORMAN_TUI_BACKEND"))
    if requested_mode in {"control", "control-only"}:
        requested_mode = "control_only"
    if requested_mode in {"offline", "cloud-offline", "cloud_llm_disabled"}:
        requested_mode = "cloud_llm_offline"
    if tui_backend == "control_only":
        requested_mode = "control_only"

    active_mode = requested_mode
    if not active_mode or active_mode == "auto":
        if no_inference:
            active_mode = "control_only"
        elif network_mode == "airgap":
            active_mode = "airgap_local"
        elif network_mode == "lan_only":
            active_mode = "lan_only"
        elif cloud_llm_disabled:
            active_mode = "cloud_llm_offline"
        elif codex_disabled:
            active_mode = "codex_quarantine"
        elif _flag(policy.get("local_first"), False):
            active_mode = "local_first_online"
        else:
            active_mode = "primary_online"

    notices: list[str] = []
    reasons: list[str] = []
    llm_plane = "cloud_ok"
    runner_plane = "kernel_shell"
    tool_plane = "full_tools"
    egress_policy = "normal"
    cloud_llm_allowed = not cloud_llm_disabled
    codex_allowed = not codex_disabled
    web_allowed = True
    lan_allowed = True
    shell_allowed = True

    if active_mode == "control_only":
        llm_plane = "no_inference"
        runner_plane = "control_only"
        tool_plane = "disabled"
        egress_policy = "deny_all"
        cloud_llm_allowed = False
        codex_allowed = False
        web_allowed = False
        shell_allowed = False
        notices.append("Control-only mode: inference and tool execution are disabled.")
        reasons.append("control-only mode selected")
    elif active_mode == "airgap_local":
        llm_plane = "lan_local_only"
        network_mode = "airgap"
        egress_policy = "deny_all"
        cloud_llm_allowed = False
        codex_allowed = False
        web_allowed = False
        notices.append("Airgap local mode: only local capabilities may be used.")
        reasons.append("airgap mode selected")
    elif active_mode == "lan_only":
        llm_plane = "lan_local_only"
        network_mode = "lan_only"
        egress_policy = "lan_only"
        cloud_llm_allowed = False
        codex_allowed = False
        web_allowed = False
        notices.append(
            "LAN-only mode: public internet and cloud LLM egress are blocked."
        )
        reasons.append("lan-only mode selected")
    elif active_mode == "cloud_llm_offline":
        llm_plane = "cloud_llm_offline"
        egress_policy = "cloud_llm_blocked"
        cloud_llm_allowed = False
        codex_allowed = False
        notices.append(
            "Cloud LLMs disabled: local models and allowed tools remain available."
        )
        reasons.append("cloud LLM egress disabled")
    elif active_mode == "codex_quarantine":
        runner_plane = "codex_quarantined"
        codex_allowed = False
        notices.append("Codex quarantined: kernel must use non-Codex runners.")
        reasons.append("Codex disabled by policy")
    elif active_mode == "local_first_online":
        notices.append("Local-first mode: use Norllama before cloud escalation.")
        reasons.append("local-first policy selected")

    if third_party_disabled:
        egress_policy = "third_party_blocked"
        web_allowed = False
        cloud_llm_allowed = False
        notices.append("Third-party egress disabled: LAN/local routes only.")
        reasons.append("third-party egress disabled")

    if cloud_llm_disabled and "cloud LLM egress disabled" not in reasons:
        cloud_llm_allowed = False
        notices.append("Cloud LLMs disabled by explicit flag.")
        reasons.append("cloud LLM egress disabled")
    if codex_disabled and "Codex disabled by policy" not in reasons:
        codex_allowed = False
        notices.append("Codex disabled by explicit flag.")
        reasons.append("Codex disabled by policy")

    degraded = (
        active_mode != "primary_online" or not cloud_llm_allowed or not codex_allowed
    )
    return RuntimeModeState(
        active_mode=active_mode,
        llm_plane=llm_plane,
        runner_plane=runner_plane,
        network_plane=network_mode,
        tool_plane=tool_plane,
        egress_policy=egress_policy,
        cloud_llm_allowed=cloud_llm_allowed,
        codex_allowed=codex_allowed,
        web_allowed=web_allowed,
        lan_allowed=lan_allowed,
        shell_allowed=shell_allowed,
        degraded=degraded,
        notices=notices,
        reasons=reasons,
        metadata={
            "requested_mode": requested_mode,
            "tui_backend": tui_backend,
        },
    )


def egress_allowed(egress_class: str, state: RuntimeModeState) -> bool:
    kind = _lower(egress_class)
    if state.egress_policy == "deny_all":
        return kind == "local" and state.network_plane == "airgap"
    if kind == "cloud_llm":
        return state.cloud_llm_allowed
    if kind == "web_research":
        return state.web_allowed and state.egress_policy not in {
            "lan_only",
            "third_party_blocked",
        }
    if kind == "lan":
        return state.lan_allowed
    if kind == "local":
        return True
    if state.egress_policy in {"lan_only", "third_party_blocked"}:
        return False
    return state.web_allowed


def route_decision(
    *,
    task_kind: str,
    route: Any,
    policy_state: RuntimeModeState,
    runner: str = "",
    capabilities: Mapping[str, Any] | None = None,
    fallback_order: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RouteDecision:
    route_dict = route.as_dict() if hasattr(route, "as_dict") else _dict(route)
    provider = _clean(route_dict.get("provider") or route_dict.get("provider_kind"))
    selected_runner = _clean(runner) or provider
    endpoint = _clean(route_dict.get("endpoint"))
    egress_class = classify_egress(endpoint, provider=provider, runner=selected_runner)
    blocked: list[str] = []
    if not egress_allowed(egress_class, policy_state):
        blocked.append(f"{egress_class} egress blocked by {policy_state.active_mode}")
    if (
        _lower(selected_runner).replace("_", "-") == "codex"
        and not policy_state.codex_allowed
    ):
        blocked.append("Codex runner blocked by policy")
    if (
        provider_is_cloud_llm(provider, selected_runner)
        and not _openai_compatible_lan_target(
            endpoint, provider=provider, runner=selected_runner
        )
        and not policy_state.cloud_llm_allowed
    ):
        blocked.append("cloud LLM provider blocked by policy")
    if _lower(selected_runner) == "shell" and not policy_state.shell_allowed:
        blocked.append("shell execution blocked by policy")
    if policy_state.llm_plane == "no_inference" and _lower(selected_runner) != "shell":
        blocked.append("inference disabled by control-only mode")

    local = bool(route_dict.get("local")) or egress_class in {"local", "lan"}
    cloud_proxy = bool(route_dict.get("cloud_proxy"))
    if policy_state.llm_plane == "no_inference":
        cost_basis = "control_only_queue"
    elif egress_class in {"local", "lan"}:
        cost_basis = (
            "local_token_estimate"
            if selected_runner != "shell"
            else "free_deterministic"
        )
    elif egress_class == "cloud_llm":
        cost_basis = "cloud_token_estimate"
    else:
        cost_basis = "external_egress"

    reasons = []
    if route_dict.get("reason"):
        reasons.append(_clean(route_dict.get("reason")))
    reasons.extend(policy_state.reasons)

    return RouteDecision(
        task_kind=task_kind,
        selected_lane=_clean(route_dict.get("lane") or route_dict.get("capability")),
        selected_provider=provider,
        selected_runner=selected_runner,
        selected_model=_clean(route_dict.get("model")),
        selected_endpoint=endpoint,
        local=local,
        cloud_proxy=cloud_proxy,
        egress_class=egress_class,
        cost_basis=cost_basis,
        allowed=not blocked,
        reasons=reasons,
        blocked_reasons=blocked,
        fallback_order=fallback_order or [],
        capability_snapshot=dict(capabilities or {}),
        policy_state=policy_state.as_dict(),
        metadata=dict(metadata or {}),
    )
