import json
import importlib.util
import os
import pathlib
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from types import SimpleNamespace


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_SCRIPT_PATH = REPO_ROOT / "scripts" / "norman_codex_web.py"
LAUNCH_SCRIPT_PATH = REPO_ROOT / "scripts" / "norman_codex_launch.sh"


def _load_norman_codex_web(monkeypatch, tmp_path, **overrides):
    codex_home = tmp_path / "codex-home"
    state_dir = tmp_path / "state"
    for key in tuple(os.environ):
        if (
            key.startswith(("NORMAN_CODEX_", "HOUSEBOT_CODEX_"))
            and key not in overrides
        ):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NORMAN_CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_MODEL", "gpt-5.4")
    monkeypatch.setenv("NORMAN_CODEX_LATEST_MODEL", "gpt-5.5")
    monkeypatch.setenv("NORMAN_CODEX_AVAILABLE_MODELS", "gpt-5.5")
    monkeypatch.setenv("NORMAN_CODEX_BBS_SUMMARY_ENABLED", "0")
    for key in (
        "NORMAN_CODEX_BILLING_SCOPE",
        "NORMAN_CODEX_BILLING_UNIT",
        "NORMAN_CODEX_BILLING_OWNER",
        "NORMAN_CODEX_BILLING_PROJECT",
    ):
        if key not in overrides:
            monkeypatch.delenv(key, raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)

    module_name = f"norman_codex_web_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, WEB_SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _cheap_snapshot(module):
    meta = module.load_status_meta()
    queued = module.normalize_queue(meta.get("queued_prompts"))
    return {
        "pending": bool(meta.get("pending")),
        "state": str(meta.get("state") or ""),
        "status_message": str(meta.get("status_message") or ""),
        "queued_prompts": queued,
        "queue_depth": len(queued),
        "running_prompt": str(meta.get("running_prompt") or ""),
    }


def test_runtime_model_enforces_gpt55_floor(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    assert module.CODEX_MODEL_FLOOR == "gpt-5.5"
    assert module.codex_model_below_floor("gpt-5.4") is True
    assert "gpt-5.5" in module.AVAILABLE_MODELS
    assert "gpt-5.4" in module.AVAILABLE_MODELS
    assert "openai.gpt-5.4" in module.AVAILABLE_MODELS
    assert module.configured_chat_model() == "gpt-5.5"
    assert module.chat_model_update_available() is False


def test_careful_response_speed_uses_xhigh_reasoning(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    assert module.response_reasoning_effort("careful") == "xhigh"


def test_xfast_response_speed_is_balanced_without_emergency_gate(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    for value in ("fast", "xfast", "x-fast", "extra-fast", "low", "minimal"):
        assert module.normalize_response_speed(value) == "balanced"
        assert module.response_reasoning_effort(value) == "medium"


def test_xfast_response_speed_requires_explicit_emergency_gate(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_EMERGENCY_XFAST_ENABLED="1",
    )

    assert module.normalize_response_speed("xfast") == "fast"
    assert module.response_reasoning_effort("xfast") == "low"


def test_host_pressure_guard_blocks_new_web_prompt(monkeypatch, tmp_path) -> None:
    guard_path = tmp_path / "pressure-guard.json"
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_HOST_PRESSURE_GUARD_PATH=str(guard_path),
    )
    guard_path.write_text(
        json.dumps(
            {
                "target": "work-special",
                "checked_at_epoch": module.now_ts(),
                "status": "critical",
                "admission": {
                    "action": "block_new_work",
                    "reason": "swap_used_ratio>=0.70",
                },
            }
        ),
        encoding="utf-8",
    )
    actions: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))
    monkeypatch.setattr(
        module, "record_action", lambda action, detail: actions.append((action, detail))
    )

    accepted, snapshot = module.start_web_prompt("do expensive work", "careful", 5)

    assert accepted is False
    assert snapshot["pressure_guard_blocked"] is True
    assert "swap_used_ratio>=0.70" in snapshot["pressure_guard_error"]
    assert actions == [
        (
            "pressure-guard-block",
            "Host pressure guard is blocking new work on work-special: swap_used_ratio>=0.70.",
        )
    ]


def test_host_pressure_guard_defers_heavy_web_prompt(monkeypatch, tmp_path) -> None:
    guard_path = tmp_path / "pressure-guard.json"
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_HOST_PRESSURE_GUARD_PATH=str(guard_path),
    )
    guard_path.write_text(
        json.dumps(
            {
                "target": "work-special",
                "checked_at_epoch": module.now_ts(),
                "status": "watching",
                "admission": {
                    "action": "defer_heavy_work",
                    "reason": "swap_used_ratio>=0.25",
                },
            }
        ),
        encoding="utf-8",
    )
    actions: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))
    monkeypatch.setattr(
        module, "record_action", lambda action, detail: actions.append((action, detail))
    )

    accepted, snapshot = module.start_web_prompt("implement the full fix", "careful", 5)

    assert accepted is False
    assert snapshot["pressure_guard_deferred"] is True
    assert "Heavy new work is deferred" in snapshot["pressure_guard_error"]
    assert actions[0][0] == "pressure-guard-defer"


def test_auto_turn_controls_downshift_status_from_xhigh(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "status on keystone?",
        [],
        speed="careful",
        detail=5,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "status"
    assert recommendation["auto_applied"] is True
    assert recommendation["effective_speed"] == "balanced"
    assert recommendation["effective_reasoning_effort"] == "medium"
    assert recommendation["effective_detail"] == 2
    assert recommendation["effective_job_budget"] == "5m"
    assert recommendation["decision_budget_min"] == 1
    assert recommendation["decision_budget_max"] == 3


def test_auto_turn_controls_do_not_downshift_tui_fork_strategy_to_status(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        (
            "status? when I want to /fork or clone a TUI for different tasks, "
            "maybe 50 sessions grinding autonomously with subagents, how do "
            "you propose we solve that?"
        ),
        [],
        speed="careful",
        detail=5,
        job_budget="60m",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "analysis"
    assert recommendation["auto_applied"] is True
    assert recommendation["effective_job_budget"] == "60m"
    assert recommendation["effective_reasoning_effort"] == "medium"
    assert "Answer now" not in recommendation["steering_chips"]


def test_auto_turn_controls_keep_plain_status_fast(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "status?",
        [],
        speed="careful",
        detail=5,
        job_budget="60m",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "status"
    assert recommendation["effective_job_budget"] == "5m"
    assert recommendation["steering_chips"] == [
        "Answer now",
        "One check",
        "No broad audit",
    ]


def test_auto_turn_controls_do_not_treat_fork_plan_question_as_status(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "what happened with the plan for forking TUIs into multiple sessions?",
        [],
        speed="balanced",
        detail=3,
        job_budget="30m",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "analysis"
    assert recommendation["effective_job_budget"] == "30m"
    assert "Answer now" not in recommendation["steering_chips"]


def test_auto_turn_controls_preserve_explicit_deep(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "status on keystone, think deep and use xhigh",
        [],
        speed="careful",
        detail=5,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "explicit"
    assert recommendation["auto_applied"] is False
    assert recommendation["effective_speed"] == "careful"
    assert recommendation["effective_reasoning_effort"] == "xhigh"
    assert recommendation["effective_detail"] == 5
    assert recommendation["effective_job_budget"] == "normal"


def test_auto_turn_controls_treat_past_deploy_question_as_status(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "did you deploy it?",
        [],
        speed="careful",
        detail=5,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "status"
    assert recommendation["effective_speed"] == "balanced"
    assert recommendation["effective_reasoning_effort"] == "medium"
    assert recommendation["effective_job_budget"] == "5m"


def test_auto_turn_controls_preserve_standard_operator_budget(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        (
            "Of these 109, how many have validators on the core spec headers? "
            "Which are 100% and which are missing some?"
        ),
        [],
        speed="careful",
        detail=5,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "standard"
    assert recommendation["auto_applied"] is True
    assert recommendation["recommended_job_budget"] == "15m"
    assert recommendation["effective_job_budget"] == "normal"


def test_deadline_checkpoint_auto_policy_keeps_working_past_target(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    assert module.DEADLINE_CHECKPOINT_POLICY == "auto"
    assert not module.deadline_checkpoint_policy_allows(
        {
            "deadline_checkpoint_policy": "auto",
            "deadline_warning_kind": "target",
            "deadline_warning_remaining_seconds": 10 * 60,
        }
    )
    assert module.deadline_checkpoint_policy_allows(
        {
            "deadline_checkpoint_policy": "auto",
            "deadline_warning_kind": "remaining",
            "deadline_warning_remaining_seconds": 5 * 60,
        }
    )


def test_auto_turn_controls_keep_deploy_fix_on_xhigh(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "fix the failover bug and deploy it",
        [],
        speed="balanced",
        detail=3,
        job_budget="15m",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "approval_boundary"
    assert recommendation["auto_applied"] is True
    assert recommendation["effective_speed"] == "careful"
    assert recommendation["effective_reasoning_effort"] == "xhigh"
    assert recommendation["effective_detail"] == 4
    assert recommendation["effective_job_budget"] == "30m"


def test_auto_turn_controls_parse_quick_response_window(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "give me a quick response on infra",
        [],
        speed="careful",
        detail=5,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["auto_applied"] is True
    assert recommendation["effective_speed"] == "balanced"
    assert recommendation["effective_reasoning_effort"] == "medium"
    assert recommendation["effective_job_budget"] == "5m"
    assert recommendation["requested_time_label"] == "5 min"
    assert recommendation["text_time_hint"]["source"] == "quick-response language"
    assert "Answer now" not in recommendation["steering_chips"]
    assert "Stay scoped" in recommendation["steering_chips"]


def test_auto_turn_controls_parse_explicit_five_minute_deadline(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "think deep but give me an answer in the next 5 minutes",
        [],
        speed="careful",
        detail=5,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "explicit"
    assert recommendation["auto_applied"] is False
    assert recommendation["effective_speed"] == "careful"
    assert recommendation["effective_reasoning_effort"] == "xhigh"
    assert recommendation["effective_job_budget"] == "5m"
    assert recommendation["requested_time_label"] == "5 min"


def test_auto_turn_controls_gate_unapproved_overnight_work(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "work on this all night and keep going until it is fixed",
        [],
        speed="balanced",
        detail=3,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "long_run_approval"
    assert recommendation["auto_applied"] is True
    assert recommendation["effective_speed"] == "balanced"
    assert recommendation["effective_reasoning_effort"] == "medium"
    assert recommendation["effective_job_budget"] == "15m"
    assert recommendation["requested_job_budget"] == "overnight"
    assert recommendation["requested_time_label"] == "Overnight"
    assert recommendation["time_approval_required"] is True
    assert recommendation["time_approval_granted"] is False
    assert "Ask approval" in recommendation["steering_chips"]


def test_auto_turn_controls_parse_eight_hour_shift_as_approval_gated(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "do an 8 hour shift on this with goals and runbooks",
        [],
        speed="balanced",
        detail=3,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "long_run_approval"
    assert recommendation["effective_job_budget"] == "15m"
    assert recommendation["requested_job_budget"] == "overnight"
    assert recommendation["text_time_hint"]["source"] == "8 hour text"
    assert recommendation["time_approval_required"] is True


def test_auto_turn_controls_allow_approved_overnight_work(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    recommendation = module.turn_control_recommendation(
        "approved overnight run: work on this all night",
        [],
        speed="balanced",
        detail=3,
        job_budget="normal",
        optimization_mode="auto",
    )

    assert recommendation["workload"] == "long_work"
    assert recommendation["auto_applied"] is True
    assert recommendation["effective_speed"] == "careful"
    assert recommendation["effective_reasoning_effort"] == "xhigh"
    assert recommendation["effective_job_budget"] == "overnight"
    assert recommendation["time_approval_required"] is False
    assert recommendation["time_approval_granted"] is True
    assert "Cost watch" in recommendation["steering_chips"]


def test_turn_control_envelope_splits_status_continue_and_deploy_gate(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    status = module.build_turn_control_envelope(
        prompt="status?",
        runtime="codex",
        model="gpt-5.4",
        service_tier="flex",
        speed="balanced",
        job_budget="5m",
    )
    proceed = module.build_turn_control_envelope(
        prompt="continue from the last checkpoint",
        runtime="codex",
        model="gpt-5.4",
        service_tier="flex",
        speed="balanced",
        job_budget="10m",
    )
    deploy = module.build_turn_control_envelope(
        prompt="status and if it is green deploy it",
        runtime="codex",
        model="gpt-5.4",
        service_tier="default",
        speed="careful",
        job_budget="30m",
    )

    assert status["schema"] == module.TURN_CONTROL_ENVELOPE_SCHEMA
    assert status["operator_intent_class"] == "status"
    assert status["authority_class"] == "read_only"
    assert status["mutation_risk"] == "none"
    assert status["budget"]["max_retries"] == 0
    assert proceed["operator_intent_class"] == "continue"
    assert proceed["authority_class"] == "read_only"
    assert deploy["operator_intent_class"] == "deploy_gate"
    assert deploy["authority_class"] == "approval_required"
    assert deploy["mutation_risk"] == "deploy_restart"
    assert "external_write_without_approval" in deploy["blocked_actions"]


def test_start_web_prompt_applies_auto_turn_controls_to_status(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    launches = []
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(
        module, "launch_prompt_worker", lambda *args: launches.append(args)
    )
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt(
        "status on keystone?",
        "careful",
        5,
        "normal",
        [],
        runtime="codex",
        model="gpt-5.4",
        optimization_mode="auto",
    )

    assert accepted is True
    assert len(launches) == 1
    assert launches[0][2] == "balanced"
    assert launches[0][3] == 2
    assert launches[0][4] == "5m"
    assert snapshot["running_speed"] == "balanced"
    assert snapshot["running_detail"] == 2
    assert snapshot["running_job_budget"] == "5m"
    assert snapshot["running_turn_control"]["workload"] == "status"
    assert snapshot["running_turn_envelope"]["operator_intent_class"] == "status"
    assert snapshot["running_turn_envelope"]["authority_class"] == "read_only"
    assert snapshot["running_turn_envelope"]["effective_model"] == "gpt-5.4"


def test_service_tier_controls_are_explicit_and_alias_legacy_fast(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    assert module.DEFAULT_SERVICE_TIER == "auto"
    assert module.normalize_service_tier("profile") == "auto"
    assert module.normalize_service_tier("standard") == "default"
    assert module.normalize_service_tier("normal") == "default"
    assert module.normalize_service_tier("flex") == "flex"
    assert module.normalize_service_tier("fast") == "priority"
    assert module.service_tier_execution_tier("auto") == "flex"
    assert module.service_tier_config_args("auto") == ["-c", 'service_tier="flex"']
    assert module.service_tier_config_args("priority") == [
        "-c",
        'service_tier="priority"',
    ]


def test_service_tier_default_can_be_set_to_flex(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="flex",
    )

    assert module.DEFAULT_SERVICE_TIER == "flex"
    assert module.service_tier_options_payload()[2]["key"] == "flex"


def test_bedrock_standard_profile_routes_standard_and_keeps_flex_direct(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_DIRECT_MODEL="gpt-5.5",
        NORMAN_CODEX_FLEX_MODEL="gpt-5.5",
        NORMAN_CODEX_PRIORITY_MODEL="gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
    )

    assert module.DEFAULT_SERVICE_TIER == "default"
    assert module.service_tier_options_payload()[1]["label"] == "Bedrock Standard"
    assert module.codex_profile_v2_for_service_tier("standard") == "traqline-bedrock"
    assert module.codex_model_for_service_tier("standard", "gpt-5.4") == (
        "openai.gpt-5.4"
    )
    assert module.codex_profile_v2_for_service_tier("flex") == ""
    assert module.codex_model_for_service_tier("flex", "gpt-5.4") == "gpt-5.4"
    assert module.codex_model_for_service_tier("flex", "openai.gpt-5.4") == "gpt-5.4"
    assert (
        module.codex_thread_scope_key("flex", "openai.gpt-5.4")
        == "direct:model:gpt-5.4"
    )
    assert module.usage_provider_tags("standard") == {
        "provider_label": "Bedrock Standard",
        "provider_surface": "aws-bedrock",
        "profile_v2": "traqline-bedrock",
        "aws_profile": "ob-traqline-admin",
        "aws_region": "us-east-2",
    }
    assert (
        module.normalize_usage_entry({"service_tier": "standard"})["provider_surface"]
        == "aws-bedrock"
    )
    assert (
        module.normalize_usage_entry({"service_tier": "flex"})["provider_surface"]
        == "openai-direct"
    )

    provider_env: dict[str, str] = {}
    module.apply_codex_provider_environment(provider_env, "standard")
    assert provider_env == {
        "AWS_PROFILE": "ob-traqline-admin",
        "AWS_REGION": "us-east-2",
    }

    captured: list[tuple[list[str], dict[str, str]]] = []

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert stdin == module.subprocess.DEVNULL
            captured.append((list(cmd), dict(env)))
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok", encoding="utf-8")

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    module._execute_codex_prompt("status?", "balanced", 3, [], service_tier="default")
    standard_cmd, standard_env = captured[-1]
    assert standard_cmd[standard_cmd.index("--profile-v2") + 1] == "traqline-bedrock"
    assert standard_cmd[standard_cmd.index("-m") + 1] == "openai.gpt-5.5"
    assert "-c" in standard_cmd
    assert standard_env["AWS_PROFILE"] == "ob-traqline-admin"
    assert standard_env["AWS_REGION"] == "us-east-2"

    module._execute_codex_prompt("status?", "balanced", 3, [], service_tier="flex")
    flex_cmd, flex_env = captured[-1]
    assert "--profile-v2" not in flex_cmd
    assert flex_cmd[flex_cmd.index("-m") + 1] == "gpt-5.5"
    assert 'service_tier="flex"' in flex_cmd
    assert flex_env.get("AWS_PROFILE") is None
    assert flex_env.get("AWS_REGION") is None

    module._execute_codex_prompt(
        "status?",
        "balanced",
        3,
        [],
        model="openai.gpt-5.5",
        service_tier="flex",
    )
    stale_flex_cmd, stale_flex_env = captured[-1]
    assert "--profile-v2" not in stale_flex_cmd
    assert stale_flex_cmd[stale_flex_cmd.index("-m") + 1] == "gpt-5.5"
    assert stale_flex_env.get("AWS_PROFILE") is None
    assert stale_flex_env.get("AWS_REGION") is None


def test_bedrock_failover_profile_routes_secondary_region_before_direct(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2="traqline-bedrock-us-west-2",
        NORMAN_CODEX_BEDROCK_FAILOVER_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_BEDROCK_FAILOVER_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION="us-west-2",
        NORMAN_CODEX_DIRECT_MODEL="gpt-5.5",
        NORMAN_CODEX_FLEX_MODEL="gpt-5.5",
        NORMAN_CODEX_PRIORITY_MODEL="gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
    )

    assert [item["key"] for item in module.service_tier_options_payload()] == [
        "auto",
        "default",
        "bedrock-failover",
        "flex",
        "priority",
    ]
    assert module.normalize_service_tier("secondary-bedrock") == "bedrock-failover"
    assert module.service_tier_config_args("bedrock-failover") == [
        "-c",
        'service_tier="default"',
    ]
    assert module.codex_profile_v2_for_service_tier("bedrock-failover") == (
        "traqline-bedrock-us-west-2"
    )
    assert module.codex_profile_v2_config_args("bedrock-failover") == [
        "--profile-v2",
        "traqline-bedrock-us-west-2",
    ]
    assert (
        module.codex_model_for_service_tier("bedrock-failover", "") == "openai.gpt-5.5"
    )
    assert module.codex_thread_scope_key("bedrock-failover") == (
        "profile-v2:traqline-bedrock-us-west-2:model:openai.gpt-5.5"
    )
    assert module.usage_provider_tags("bedrock-failover") == {
        "provider_label": "Bedrock Failover",
        "provider_surface": "aws-bedrock",
        "profile_v2": "traqline-bedrock-us-west-2",
        "aws_profile": "ob-traqline-admin",
        "aws_region": "us-west-2",
    }

    usage = module.normalize_usage_entry(
        {
            "service_tier": "default",
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_on_demand_capacity_exceeded",
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        }
    )
    assert (
        module.zero_token_provider_retry_service_tier("default", usage)
        == "bedrock-failover"
    )
    assert (
        module.zero_token_provider_retry_service_tier(
            "bedrock-failover", {**usage, "service_tier": "bedrock-failover"}
        )
        == "flex"
    )

    provider_env: dict[str, str] = {}
    module.apply_codex_provider_environment(provider_env, "bedrock-failover")
    assert provider_env == {
        "AWS_PROFILE": "ob-traqline-admin",
        "AWS_REGION": "us-west-2",
    }

    captured: list[tuple[list[str], dict[str, str]]] = []

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            captured.append((list(cmd), dict(env)))
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok", encoding="utf-8")

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    module._execute_codex_prompt(
        "status?", "balanced", 3, [], service_tier="bedrock-failover"
    )
    failover_cmd, failover_env = captured[-1]
    assert failover_cmd[failover_cmd.index("--profile-v2") + 1] == (
        "traqline-bedrock-us-west-2"
    )
    assert failover_cmd[failover_cmd.index("-m") + 1] == "openai.gpt-5.5"
    assert 'service_tier="default"' in failover_cmd
    assert failover_env["AWS_PROFILE"] == "ob-traqline-admin"
    assert failover_env["AWS_REGION"] == "us-west-2"


def test_bedrock_tertiary_failover_profile_routes_before_direct(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2="traqline-bedrock-us-east-1",
        NORMAN_CODEX_BEDROCK_FAILOVER_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_BEDROCK_FAILOVER_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION="us-east-1",
        NORMAN_CODEX_BEDROCK_FAILOVER2_PROFILE_V2="traqline-bedrock-us-west-2",
        NORMAN_CODEX_BEDROCK_FAILOVER2_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_BEDROCK_FAILOVER2_AWS_REGION="us-west-2",
        NORMAN_CODEX_DIRECT_MODEL="gpt-5.5",
        NORMAN_CODEX_FLEX_MODEL="gpt-5.5",
        NORMAN_CODEX_PRIORITY_MODEL="gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
    )

    assert [item["key"] for item in module.service_tier_options_payload()] == [
        "auto",
        "default",
        "bedrock-failover",
        "bedrock-failover-2",
        "flex",
        "priority",
    ]
    assert module.normalize_service_tier("bedrock3") == "bedrock-failover-2"
    assert module.service_tier_config_args("bedrock-failover-2") == [
        "-c",
        'service_tier="default"',
    ]
    assert module.codex_profile_v2_for_service_tier("bedrock-failover-2") == (
        "traqline-bedrock-us-west-2"
    )
    assert (
        module.codex_model_for_service_tier("bedrock-failover-2", "")
        == "openai.gpt-5.5"
    )
    assert module.usage_provider_tags("bedrock-failover-2") == {
        "provider_label": "Bedrock Failover 2",
        "provider_surface": "aws-bedrock",
        "profile_v2": "traqline-bedrock-us-west-2",
        "aws_profile": "ob-traqline-admin",
        "aws_region": "us-west-2",
    }

    usage = module.normalize_usage_entry(
        {
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_stream_disconnected",
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        }
    )
    assert (
        module.zero_token_provider_retry_service_tier(
            "default", {**usage, "service_tier": "default"}
        )
        == "bedrock-failover"
    )
    assert (
        module.zero_token_provider_retry_service_tier(
            "bedrock-failover", {**usage, "service_tier": "bedrock-failover"}
        )
        == "bedrock-failover-2"
    )
    assert (
        module.zero_token_provider_retry_service_tier(
            "bedrock-failover-2", {**usage, "service_tier": "bedrock-failover-2"}
        )
        == "flex"
    )

    provider_env: dict[str, str] = {}
    module.apply_codex_provider_environment(provider_env, "bedrock-failover-2")
    assert provider_env == {
        "AWS_PROFILE": "ob-traqline-admin",
        "AWS_REGION": "us-west-2",
    }


def test_direct_usage_limit_recovers_stale_flex_to_bedrock_default(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="1",
        NORMAN_CODEX_DIRECT_MODEL="gpt-5.5",
        NORMAN_CODEX_FLEX_MODEL="gpt-5.5",
        NORMAN_CODEX_PRIORITY_MODEL="gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
    )
    usage_limit = module.normalize_usage_entry(
        {
            "service_tier": "flex",
            "provider_surface": "openai-direct",
            "provider_error_text": (
                "You've hit your usage limit. To get more access now, send a "
                "request to your admin or try again at 5:28 PM."
            ),
            "success": False,
            "finished_at": 1781539006,
        }
    )

    recovery = module.direct_service_tier_usage_limit_recovery(
        "flex", runtime="codex", entries=[usage_limit]
    )

    assert recovery["service_tier"] == "default"
    assert recovery["requested_service_tier"] == "flex"
    assert recovery["target_profile_v2"] == "traqline-bedrock"
    assert recovery["target_aws_region"] == "us-east-2"
    assert (
        module.direct_service_tier_usage_limit_recovery(
            "flex", route_lock=True, runtime="codex", entries=[usage_limit]
        )
        == {}
    )
    assert (
        module.direct_service_tier_usage_limit_recovery(
            "flex", runtime="claude", entries=[usage_limit]
        )
        == {}
    )
    assert (
        module.direct_service_tier_usage_limit_recovery(
            "flex",
            runtime="codex",
            entries=[
                module.normalize_usage_entry(
                    {
                        "service_tier": "flex",
                        "provider_surface": "openai-direct",
                        "provider_error_text": "ordinary provider failure",
                    }
                )
            ],
        )
        == {}
    )


def test_start_web_prompt_recovers_stale_direct_tier_before_worker(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
    )
    module.ensure_state_dir()
    module.append_usage_entry(
        started_at=1781538999,
        finished_at=1781539006,
        thread_id="thread-flex-limit",
        speed="careful",
        detail=5,
        service_tier="flex",
        success=False,
        runtime="codex",
        model="gpt-5.5",
        usage={
            "provider_surface": "openai-direct",
            "provider_error_kind": "codex_provider_error",
            "provider_error_text": (
                "You've hit your usage limit. To get more access now, send a "
                "request to your admin or try again at 5:28 PM."
            ),
        },
    )
    calls = []

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
        optimization_mode="",
    ):
        calls.append({"prompt": prompt, "service_tier": service_tier})
        return (
            "Recovered through Bedrock default.",
            "",
            "thread-bedrock",
            module.normalize_usage_entry(
                {
                    "service_tier": service_tier,
                    "provider_surface": "aws-bedrock",
                    "total_tokens": 10,
                }
            ),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "status?",
        "careful",
        5,
        "normal",
        service_tier="flex",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and calls:
            break

    assert calls
    assert calls[0]["service_tier"] == "default"
    events = module.load_audit_events(
        limit=20, event_type="chat.direct-tier-recovered-to-default"
    )
    assert events
    assert events[0]["payload"]["requested_service_tier"] == "flex"
    assert events[0]["payload"]["service_tier"] == "default"


def test_bedrock_standard_can_disable_direct_openai_tiers(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_DIRECT_MODEL="gpt-5.5",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="0",
        HOUSEBOT_CODEX_DIRECT_TIERS_ENABLED="0",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
    )

    assert [item["key"] for item in module.service_tier_options_payload()] == [
        "auto",
        "default",
    ]
    assert module.normalize_service_tier("flex") == "default"
    assert module.normalize_service_tier("priority") == "default"
    assert module.service_tier_execution_tier("auto") == "default"
    assert module.service_tier_config_args("auto") == ["-c", 'service_tier="default"']
    assert module.codex_profile_v2_for_service_tier("auto") == "traqline-bedrock"
    assert module.service_tier_config_args("flex") == ["-c", 'service_tier="default"']
    assert module.codex_profile_v2_for_service_tier("flex") == "traqline-bedrock"
    assert module.codex_model_for_service_tier("flex", "gpt-5.5") == "openai.gpt-5.5"
    assert module.usage_provider_tags("flex") == {
        "provider_label": "Bedrock Standard",
        "provider_surface": "aws-bedrock",
        "profile_v2": "traqline-bedrock",
        "aws_profile": "ob-traqline-admin",
        "aws_region": "us-east-2",
    }


def test_non_housebot_service_inventory_defaults_to_current_codex_service(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_NAME="leadership-kpis-codex.service",
        NORMAN_CODEX_WEB_SERVICE_NAME="leadership-kpis-codex-web.service",
    )

    assert module.AGENT_SERVICE_NAME == "leadership-kpis-codex.service"
    assert module.PFSENSE_TIMER == ""
    assert module.CODEX_SERVICE == "leadership-kpis-codex.service"
    assert module.WEB_SERVICE == "leadership-kpis-codex-web.service"


def test_bedrock_standard_does_not_resume_legacy_direct_thread(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
    )
    module.ensure_state_dir()
    module.THREAD_ID_PATH.write_text("legacy-direct-thread", encoding="utf-8")
    captured: list[list[str]] = []

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            captured.append(list(cmd))
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok", encoding="utf-8")

        def communicate(self, timeout=None):
            return (
                '{"type":"thread.started","thread_id":"bedrock-thread"}\n'
                '{"type":"turn.completed","usage":{"input_tokens":1}}\n',
                "",
            )

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    module._execute_codex_prompt("status?", "balanced", 3, [], service_tier="default")

    first_cmd = captured[-1]
    assert "resume" not in first_cmd
    assert module.THREAD_ID_PATH.read_text(encoding="utf-8") == "bedrock-thread"
    assert module.THREAD_SCOPE_PATH.read_text(encoding="utf-8") == (
        "profile-v2:traqline-bedrock:model:openai.gpt-5.5"
    )

    module._execute_codex_prompt("status?", "balanced", 3, [], service_tier="default")

    second_cmd = captured[-1]
    resume_index = second_cmd.index("resume")
    assert second_cmd[resume_index + 1] == "bedrock-thread"


def test_bedrock_standard_starts_fresh_thread_for_heavy_context(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
    )
    module.ensure_state_dir()
    old_thread_id = "heavy-bedrock-thread"
    old_scope = "profile-v2:traqline-bedrock:model:openai.gpt-5.5"
    module.THREAD_ID_PATH.write_text(old_thread_id, encoding="utf-8")
    module.THREAD_SCOPE_PATH.write_text(old_scope, encoding="utf-8")
    module.append_usage_entry(
        started_at=100,
        finished_at=110,
        thread_id=old_thread_id,
        speed="careful",
        detail=5,
        service_tier="default",
        success=True,
        runtime="codex",
        model="openai.gpt-5.5",
        usage={
            "input_tokens": 120_000,
            "cached_input_tokens": 60_000,
            "output_tokens": 800,
        },
    )
    for index in range(14):
        module.append_history_entry(
            prompt=f"Older KPI analysis {index}: " + ("p" * 2200),
            response=f"Evidence and command output {index}: " + ("r" * 3600),
            error_text="",
            started_at=120 + index,
            finished_at=121 + index,
            thread_id=old_thread_id,
            speed="careful",
            detail=5,
            service_tier="default",
            runtime="codex",
            model="openai.gpt-5.5",
            usage={"input_tokens": 12_000, "output_tokens": 900},
        )

    captured: list[list[str]] = []

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            captured.append(list(cmd))
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("DONE compacted", encoding="utf-8")

        def communicate(self, timeout=None):
            return (
                '{"type":"thread.started","thread_id":"fresh-bedrock-thread"}\n'
                '{"type":"turn.completed","usage":{"input_tokens":1200,"output_tokens":20}}\n',
                "",
            )

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    module._execute_codex_prompt(
        "Continue KPI work.", "careful", 5, [], service_tier="default"
    )

    cmd = captured[-1]
    assert "resume" not in cmd
    prompt_arg = cmd[-1]
    assert "Continue KPI work." in prompt_arg
    assert "Bedrock compact-context handoff:" in prompt_arg
    assert f"Previous thread: {old_thread_id}" in prompt_arg
    assert "starts a fresh Bedrock thread" in prompt_arg
    assert module.THREAD_ID_PATH.read_text(encoding="utf-8") == "fresh-bedrock-thread"
    assert module.THREAD_SCOPE_PATH.read_text(encoding="utf-8") == old_scope
    audit_text = module.AUDIT_PATH.read_text(encoding="utf-8")
    assert "chat.bedrock-context-packed" in audit_text
    assert old_thread_id in audit_text


def test_bedrock_pack_treats_heavy_thread_as_resume_risk(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_THREAD_TOKENS="80000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_SAVED_TOKENS="4000",
    )
    module.ensure_state_dir()
    old_thread_id = "heavy-thread-small-visible-context"
    old_scope = "profile-v2:traqline-bedrock:model:openai.gpt-5.5"
    module.THREAD_ID_PATH.write_text(old_thread_id, encoding="utf-8")
    module.THREAD_SCOPE_PATH.write_text(old_scope, encoding="utf-8")
    module.append_usage_entry(
        started_at=100,
        finished_at=110,
        thread_id=old_thread_id,
        speed="careful",
        detail=5,
        service_tier="default",
        success=True,
        runtime="codex",
        model="openai.gpt-5.5",
        usage={"input_tokens": 120_000, "output_tokens": 700},
    )

    plan = module.bedrock_context_pack_plan(
        service_tier="default",
        model="gpt-5.5",
        session_id=old_thread_id,
        thread_scope=old_scope,
    )

    assert plan["thread_tokens"] >= 80_000
    assert plan["saved_tokens"] < 4_000
    assert plan["visible_context_worthwhile"] is False
    assert plan["should_pack"] is True
    assert plan["thread_uncached_input_tokens"] >= 80_000
    assert plan["thread_output_ratio"] < 0.02
    assert plan["uncached_input_pressure"] is True
    assert plan["reason"] == "low-yield-cloud-thread"


def test_bedrock_pack_forces_hard_cloud_context_cap(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.6-terra",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_THREAD_TOKENS="80000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_HARD_THREAD_TOKENS="200000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_SAVED_TOKENS="4000",
    )
    module.ensure_state_dir()
    old_thread_id = "million-token-thread"
    old_scope = "profile-v2:traqline-bedrock:model:openai.gpt-5.6-terra"
    module.append_usage_entry(
        started_at=100,
        finished_at=212,
        thread_id=old_thread_id,
        speed="careful",
        detail=5,
        service_tier="default",
        success=True,
        runtime="codex",
        model="openai.gpt-5.6-terra",
        usage={
            "input_tokens": 1_161_817,
            "cached_input_tokens": 954_558,
            "output_tokens": 6_365,
        },
    )

    plan = module.bedrock_context_pack_plan(
        service_tier="default",
        model="openai.gpt-5.6-terra",
        session_id=old_thread_id,
        thread_scope=old_scope,
    )

    assert plan["thread_tokens"] >= 1_000_000
    assert plan["hard_cap_exceeded"] is True
    assert plan["hard_cap_tokens"] == 200_000
    assert plan["visible_context_worthwhile"] is False
    assert plan["should_pack"] is True
    assert plan["reason"] == "hard-cloud-context-cap"


def test_bedrock_pack_forces_low_yield_cloud_thread(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.6-terra",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_THREAD_TOKENS="80000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_HARD_THREAD_TOKENS="200000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_SAVED_TOKENS="4000",
    )
    module.ensure_state_dir()
    old_thread_id = "low-yield-thread"
    old_scope = "profile-v2:traqline-bedrock:model:openai.gpt-5.6-terra"
    module.append_usage_entry(
        started_at=100,
        finished_at=170,
        thread_id=old_thread_id,
        speed="careful",
        detail=5,
        service_tier="default",
        success=True,
        runtime="codex",
        model="openai.gpt-5.6-terra",
        usage={
            "input_tokens": 50_000,
            "output_tokens": 500,
            "provider_yield_kind": "low_yield",
            "provider_yield_reasons": ["low output tokens"],
        },
    )

    plan = module.bedrock_context_pack_plan(
        service_tier="default",
        model="openai.gpt-5.6-terra",
        session_id=old_thread_id,
        thread_scope=old_scope,
    )

    assert plan["thread_tokens"] < 80_000
    assert plan["hard_cap_exceeded"] is False
    assert plan["low_yield_thread"] is True
    assert plan["latest_provider_yield_kind"] == "low_yield"
    assert plan["should_pack"] is True
    assert plan["reason"] == "low-yield-cloud-thread"


def test_bedrock_pack_forces_costly_cloud_thread_below_token_threshold(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_THREAD_TOKENS="80000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_HARD_THREAD_TOKENS="200000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_UNCACHED_INPUT_TOKENS="80000",
        NORMAN_CODEX_BEDROCK_CONTEXT_PACK_MIN_ESTIMATED_COST_USD="0.25",
    )
    module.ensure_state_dir()
    old_thread_id = "costly-thread-under-hard-cap"
    old_scope = "profile-v2:traqline-bedrock:model:openai.gpt-5.5"
    module.append_usage_entry(
        started_at=100,
        finished_at=170,
        thread_id=old_thread_id,
        speed="careful",
        detail=5,
        service_tier="default",
        success=True,
        runtime="codex",
        model="openai.gpt-5.5",
        usage={"input_tokens": 70_000, "output_tokens": 2_000},
    )

    plan = module.bedrock_context_pack_plan(
        service_tier="default",
        model="openai.gpt-5.5",
        session_id=old_thread_id,
        thread_scope=old_scope,
    )

    assert plan["thread_tokens"] < 80_000
    assert plan["uncached_input_pressure"] is False
    assert plan["estimated_thread_cost_usd"] >= 0.25
    assert plan["costly_thread"] is True
    assert plan["should_pack"] is True
    assert plan["reason"] == "costly-cloud-context"


def test_public_usage_rates_include_gpt56_bedrock_models(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    luna = module._public_usage_cost_rates_for_model("openai.gpt-5.6-luna")
    terra = module._public_usage_cost_rates_for_model("openai.gpt-5.6-terra")
    sol = module._public_usage_cost_rates_for_model("openai.gpt-5.6-sol")

    assert luna["configured"] is True
    assert luna["input_usd_per_1m"] == 1.0
    assert terra["configured"] is True
    assert terra["input_usd_per_1m"] == 2.5
    assert sol["configured"] is True
    assert sol["input_usd_per_1m"] == 5.0


def test_personal_bedrock_codex_usage_displays_usd_not_plan_credits(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    usage = module.normalize_usage_entry(
        {
            "runtime": "codex",
            "model": "openai.gpt-5.6-terra",
            "provider_surface": "aws-bedrock",
            "billing_owner": "kristopher",
            "agent_group": "home",
            "input_tokens": 1_000,
            "output_tokens": 100,
        }
    )

    assert usage["charge_ledger_kind"] == "provider_invoice_estimate"
    assert usage["charge_display_unit"] == "usd_equivalent"


def test_stale_personal_bedrock_usage_reprices_as_usd(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    estimate = module.estimate_usage_entries_cost(
        [
            {
                "runtime": "codex",
                "model": "openai.gpt-5.6-terra",
                "provider_surface": "aws-bedrock",
                "billing_owner": "kristopher",
                "agent_group": "home",
                "input_tokens": 1_000,
                "output_tokens": 100,
                "charge_ledger_kind": "chatgpt_codex_credit_estimate",
                "charge_display_unit": "credits",
            }
        ]
    )

    assert estimate["ledger_kind"] == "provider_invoice_estimate"
    assert estimate["display_unit"] == "usd_equivalent"
    assert estimate["by_charge_display_unit"] == {"usd_equivalent": 1}
    assert estimate["usd"] > 0


def test_mixed_unpriced_direct_and_bedrock_history_prefers_usd_display(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    estimate = module.estimate_usage_entries_cost(
        [
            {
                "runtime": "codex",
                "model": "openai.gpt-5.6-terra",
                "provider_surface": "openai-direct",
                "billing_owner": "kristopher",
                "agent_group": "home",
                "input_tokens": 1_000,
                "output_tokens": 100,
                "charge_ledger_kind": "chatgpt_codex_credit_estimate",
                "charge_display_unit": "credits",
            },
            {
                "runtime": "codex",
                "model": "openai.gpt-5.6-terra",
                "provider_surface": "aws-bedrock",
                "billing_owner": "kristopher",
                "agent_group": "home",
                "input_tokens": 1_000,
                "output_tokens": 100,
                "charge_ledger_kind": "chatgpt_codex_credit_estimate",
                "charge_display_unit": "credits",
            },
        ]
    )

    assert estimate["ledger_kind"] == "mixed"
    assert estimate["display_unit"] == "usd_equivalent"
    assert estimate["by_charge_display_unit"] == {
        "credits": 1,
        "usd_equivalent": 1,
    }
    assert estimate["usd"] > 0


def test_usage_entry_keeps_append_only_ledger_when_ui_cache_trims(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_AGENT_NAME="Panelbot",
        NORMAN_CODEX_AGENT_GROUP="Work",
        NORMAN_CODEX_BBS_ACTOR="panelbot",
        NORMAN_CODEX_HOSTNAME="work-special",
        NORMAN_CODEX_WORKDIR="/home/kristopher/code/panelbot",
    )
    module.MAX_USAGE_ITEMS = 1
    module.MAX_USAGE_LEDGER_ITEMS = 0

    module.append_usage_entry(
        started_at=100,
        finished_at=110,
        thread_id="thread-1",
        speed="balanced",
        detail=3,
        success=True,
        runtime="codex",
        model="gpt-5.5",
        usage={"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10},
    )
    module.append_usage_entry(
        started_at=200,
        finished_at=210,
        thread_id="thread-2",
        speed="careful",
        detail=4,
        success=True,
        runtime="codex",
        model="gpt-5.5",
        usage={"input_tokens": 200, "cached_input_tokens": 80, "output_tokens": 20},
    )

    usage_lines = module.USAGE_PATH.read_text(encoding="utf-8").splitlines()
    ledger_lines = module.USAGE_LEDGER_PATH.read_text(encoding="utf-8").splitlines()

    assert len(usage_lines) == 1
    assert len(ledger_lines) == 2
    assert json.loads(usage_lines[0])["thread_id"] == "thread-2"
    assert [json.loads(line)["thread_id"] for line in ledger_lines] == [
        "thread-1",
        "thread-2",
    ]
    latest = json.loads(ledger_lines[-1])
    assert latest["accounting_version"] == "norman.tui-usage.v2"
    assert latest["billing_scope"] == "work-special"
    assert latest["billing_unit"] == "work-special:panelbot"
    assert latest["billing_owner"] == "openbrand"
    assert latest["billing_project"] == "/home/kristopher/code/panelbot"
    assert latest["agent_slug"] == "panelbot"
    assert latest["actor_slug"] == "panelbot"
    assert latest["host_name"] == "work-special"
    assert latest["workdir"] == "/home/kristopher/code/panelbot"


def test_bedrock_health_alerts_from_recent_zero_token_failure(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
    )

    health = module.bedrock_health_snapshot(
        snapshot_at=2_000,
        ledger_entries=[
            {
                "started_at": 1_940,
                "finished_at": 1_950,
                "thread_id": "thread-bedrock-failed",
                "success": False,
                "runtime": "codex",
                "model": "openai.gpt-5.5",
                "service_tier": "default",
                "provider_surface": "aws-bedrock",
                "profile_v2": "traqline-bedrock",
                "aws_profile": "ob-traqline-admin",
                "aws_region": "us-east-2",
                "provider_error_kind": "bedrock_stream_disconnected",
                "provider_request_ids": ["aws-request-123"],
                "total_tokens": 0,
                "zero_token_provider_failure": True,
            }
        ],
    )

    assert health["state"] == "failing"
    assert health["tone"] == "alert"
    assert health["hidden"] is False
    assert health["failure_count"] == 1
    assert health["zero_token_failure_count"] == 1
    assert health["failure_kinds"] == {"bedrock_stream_disconnected": 1}
    assert health["provider_request_ids"] == ["aws-request-123"]
    assert health["aws_region"] == "us-east-2"


def test_bedrock_health_uses_fresh_smoke_cache(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
    )
    module.BEDROCK_HEALTH_SMOKE_PATH.parent.mkdir(parents=True, exist_ok=True)
    module.BEDROCK_HEALTH_SMOKE_PATH.write_text(
        json.dumps(
            {
                "status": "ok",
                "checked_at": 1_990,
                "summary": "us-east-2 smoke passed",
                "models": {"openai.gpt-5.5": {"ok": True}},
            }
        ),
        encoding="utf-8",
    )

    health = module.bedrock_health_snapshot(snapshot_at=2_000, ledger_entries=[])

    assert health["state"] == "ok"
    assert health["tone"] == "ok"
    assert health["hidden"] is False
    assert health["label"] == "Bedrock OK"
    assert health["failure_count"] == 0
    assert health["smoke"]["summary"] == "us-east-2 smoke passed"


def test_route_receipt_builds_live_shadow_cost_baseline(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI="market-sizing",
        NORMAN_CODEX_EST_FLEX_INPUT_USD_PER_1M="0.50",
        NORMAN_CODEX_EST_FLEX_CACHED_INPUT_USD_PER_1M="0.05",
        NORMAN_CODEX_EST_FLEX_OUTPUT_USD_PER_1M="2.00",
        NORMAN_CODEX_EST_STANDARD_INPUT_USD_PER_1M="5.00",
        NORMAN_CODEX_EST_STANDARD_CACHED_INPUT_USD_PER_1M="0.50",
        NORMAN_CODEX_EST_STANDARD_OUTPUT_USD_PER_1M="30.00",
    )

    receipt = module.build_route_receipt(
        prompt="Status and what's next for the market sizing benchmark.",
        visible_response="Ready. Next action is to run the verifier packet.",
        started_at=1_786_000_100,
        finished_at=1_786_000_104,
        thread_id="thread-market-sizing",
        speed="balanced",
        detail=3,
        service_tier="flex",
        job_budget="normal",
        optimization_mode="auto",
        success=True,
        runtime="codex",
        model="openai.gpt-5.4",
        usage={
            "input_tokens": 200_000,
            "cached_input_tokens": 20_000,
            "output_tokens": 20_000,
            "total_tokens": 220_000,
        },
        outcome="done",
        turn_plan={"stage": "final"},
    )

    assert set(module.ROUTE_RECEIPT_REQUIRED_FIELDS).issubset(receipt)
    assert receipt["receipt_source"] == "live_tui_shadow_route"
    assert receipt["previous_receipt_hash"] == ""
    assert receipt["receipt_hash"] == ""
    assert receipt["synthetic"] is False
    assert receipt["owner_tui"] == "market-sizing"
    assert receipt["requested_action"] == "status"
    assert receipt["operator_intent_class"] == "status"
    assert receipt["authority_class"] == "read_only"
    assert receipt["mutation_risk"] == "none"
    assert receipt["benchmark_skill_id"] == "common-status"
    assert receipt["selected_model_tier"] == "frontier_5_4_verifier"
    assert receipt["requested_model"] == "openai.gpt-5.4"
    assert receipt["effective_model"] == "openai.gpt-5.4"
    assert receipt["requested_provider"] == "openai-direct"
    assert receipt["effective_provider"] == "openai-direct"
    assert receipt["requested_service_tier"] == "flex"
    assert receipt["effective_service_tier"] == "flex"
    assert receipt["observed_service_tier"] == "flex"
    assert receipt["reasoning_effort"] == "medium"
    assert receipt["route_policy_version"] == module.ROUTE_RECEIPT_POLICY_VERSION
    assert receipt["allowed_role"] == "verifier"
    assert receipt["validator_gate"] == "pass"
    assert receipt["validator_passed"] is True
    assert receipt["operator_approval_required"] is False
    assert receipt["final_authority_required"] is False
    assert receipt["live_write_attempted"] is False
    assert receipt["boundary_violation"] is False
    assert receipt["estimated_cost_usd"] > 0
    assert receipt["baseline_all_5_5_cost_usd"] > receipt["estimated_cost_usd"]
    assert receipt["input_tokens"] == 200_000
    assert receipt["cached_input_tokens"] == 20_000
    assert receipt["output_tokens"] == 20_000
    assert receipt["reasoning_tokens"] == 0
    assert receipt["retry_count"] == 0
    assert receipt["timeout_count"] == 0
    assert receipt["prompt_digest"]
    assert receipt["context_digest"]
    assert receipt["latency_ms"] == 4000
    assert "turn_plan:final" in receipt["evidence_refs"]


def test_route_receipt_append_records_approval_boundary_without_counting_as_safe(
    monkeypatch, tmp_path
) -> None:
    receipt_path = tmp_path / "receipts" / "netops.jsonl"
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED="1",
        NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI="netops",
        NORMAN_CODEX_ROUTE_RECEIPT_PATH=str(receipt_path),
    )

    receipt = module.append_route_receipt(
        prompt="Can you webrestart netops and ACK the BBS handoff?",
        visible_response=(
            "Commands run: sync_agent_console_template.py --restart-web-only."
        ),
        started_at=1_786_000_200,
        finished_at=1_786_000_205,
        thread_id="thread-netops",
        speed="careful",
        detail=5,
        service_tier="default",
        job_budget="normal",
        optimization_mode="auto",
        success=True,
        runtime="codex",
        model="openai.gpt-5.5",
        usage={"input_tokens": 100_000, "output_tokens": 5_000},
        outcome="done",
        rate_limit_attempt=1,
        timed_out=True,
    )

    assert receipt is not None
    lines = receipt_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["owner_tui"] == "netops"
    assert saved["operator_approval_required"] is True
    assert saved["final_authority_required"] is True
    assert saved["live_write_attempted"] is True
    assert saved["boundary_violation"] is True
    assert saved["validator_gate"] == "boundary_violation"
    assert saved["escalation_trigger"] == "boundary_violation"
    assert saved["operator_intent_class"] == "deploy_gate"
    assert saved["authority_class"] == "approval_required"
    assert saved["mutation_risk"] == "deploy_restart"
    assert saved["retry_count"] == 1
    assert saved["timeout_count"] == 1
    assert saved["previous_receipt_hash"] == ""
    assert saved["receipt_hash"]
    assert saved["receipt_hash"] == module.route_receipt_compute_hash(saved)


def test_route_receipt_append_hash_chain_links_consecutive_receipts(
    monkeypatch, tmp_path
) -> None:
    receipt_path = tmp_path / "receipts" / "market-sizing.jsonl"
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED="1",
        NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI="market-sizing",
        NORMAN_CODEX_ROUTE_RECEIPT_PATH=str(receipt_path),
    )

    for index in range(2):
        module.append_route_receipt(
            prompt=f"status for route receipt canary {index}",
            visible_response="Ready.",
            started_at=1_786_000_300 + index,
            finished_at=1_786_000_305 + index,
            thread_id="thread-market-sizing",
            speed="quick",
            detail=2,
            service_tier="flex",
            job_budget="quick",
            optimization_mode="auto",
            success=True,
            runtime="codex",
            model="openai.gpt-5.4",
            usage={"input_tokens": 1_000, "output_tokens": 100},
            outcome="done",
        )

    saved = [
        json.loads(line)
        for line in receipt_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(saved) == 2
    assert saved[0]["previous_receipt_hash"] == ""
    assert saved[0]["receipt_hash"] == module.route_receipt_compute_hash(saved[0])
    assert saved[1]["previous_receipt_hash"] == saved[0]["receipt_hash"]
    assert saved[1]["receipt_hash"] == module.route_receipt_compute_hash(saved[1])
    assert module.route_receipt_chain_status(receipt_path)["status"] == "pass"

    saved[1]["previous_receipt_hash"] = "broken"
    assert module.route_receipt_chain_issues(saved)


def test_current_snapshot_surfaces_route_receipt_status(monkeypatch, tmp_path) -> None:
    receipt_path = tmp_path / "route-receipts.jsonl"
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED="1",
        NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI="market-sizing",
        NORMAN_CODEX_ROUTE_RECEIPT_PATH=str(receipt_path),
    )

    module.append_route_receipt(
        prompt="Summarize the sales pipeline.",
        visible_response="Summary delivered.",
        error_text="",
        started_at=1_786_001_000,
        finished_at=1_786_001_005,
        thread_id="thread-market-sizing",
        speed="quick",
        detail=2,
        service_tier="flex",
        job_budget="quick",
        optimization_mode="auto",
        success=True,
        runtime="codex",
        model="openai.gpt-5.4",
        usage={"input_tokens": 1_000, "output_tokens": 100},
        outcome="done",
    )

    snapshot = module.current_snapshot()

    assert snapshot["route_receipts"]["status"] == "pass"
    assert snapshot["route_receipts"]["path"] == str(receipt_path)
    assert snapshot["route_receipts"]["receipt_count"] == 1
    assert snapshot["route_receipts"]["issue_count"] == 0
    assert snapshot["route_receipts"]["latest_hash"]


def test_ensure_session_does_not_wait_when_service_start_fails(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    sleeps = []
    commands = []

    monkeypatch.setattr(module, "session_exists", lambda: False)
    monkeypatch.setattr(
        module,
        "run",
        lambda cmd, input_text=None, check=False: commands.append(cmd)
        or SimpleNamespace(returncode=1, stdout="", stderr="Access denied"),
    )
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert module.ensure_session() is False
    assert commands == [["systemctl", "start", module.CODEX_SERVICE]]
    assert sleeps == []


def test_busy_web_prompt_queues_operator_prompt_with_visible_position(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        running_speed="balanced",
        running_detail=3,
    )
    module.ACTIVE_PROMPT_THREAD = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt("status?", "fast", 2, [])

    assert accepted is True
    assert snapshot["pending"] is True
    queued = module.normalize_queue(module.load_status_meta()["queued_prompts"])
    assert len(queued) == 1
    assert queued[0]["prompt"] == "status?"
    assert queued[0]["source"] == "operator"
    assert queued[0]["speed"] == "balanced"
    assert queued[0]["detail"] == 2
    assert queued[0]["interlace_mode"] == "queue"
    assert queued[0]["checkpoint_policy"] == "observe"
    meta = module.load_status_meta()
    assert "position 1" in meta["last_action_detail"]
    assert "Current web reply is still running" in meta["status_message"]
    assert "Queue mode" in meta["status_message"]
    assert "current reply finishes" in meta["status_message"]
    assert meta["queue_checkpoint_state"] == "waiting"

    module.ACTIVE_PROMPT_THREAD = None


def test_busy_web_prompt_ignores_duplicate_running_operator_prompt(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        running_speed="balanced",
        running_detail=3,
    )
    module.ACTIVE_PROMPT_THREAD = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt(
        "Existing operator prompt.",
        "fast",
        2,
        attachments=[],
    )

    assert accepted is True
    assert snapshot["deduplicated_prompt"] is True
    assert module.normalize_queue(module.load_status_meta()["queued_prompts"]) == []
    meta = module.load_status_meta()
    assert meta["last_action"] == "dedupe-prompt"
    assert "duplicate submit was not queued" in meta["status_message"]

    module.ACTIVE_PROMPT_THREAD = None


def test_queue_checkpoint_interrupts_operator_prompt_after_tool_finished(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        queued_prompts=[
            {
                "id": "queued-operator",
                "prompt": "new operator direction",
                "queued_at": 123,
                "source": "operator",
                "interlace_mode": "interrupt",
            }
        ],
    )

    event = {"type": "exec.completed", "command": "make test"}

    assert module.codex_event_checkpoint_kind(event) == "tool-finished"
    assert module.record_queue_checkpoint(event=event, kind="tool-finished") is True

    meta = module.load_status_meta()
    assert meta["queue_checkpoint_policy"] == "interrupt"
    assert meta["queue_interlace_mode"] == "interrupt"
    assert meta["queue_checkpoint_state"] == "interrupting"
    assert meta["queue_checkpoint_event"] == "exec.completed"
    assert "Interrupt acknowledged" in meta["queue_checkpoint_detail"]
    assert "queued operator prompt will run next" in meta["queue_checkpoint_detail"]
    assert "queued operator prompt will run next" in meta["status_message"]


def test_interrupt_handoff_runs_clean_prompt_with_execution_preamble(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=False,
        state="interrupted",
        status_message="Older reply interrupted.",
        running_prompt="",
        queued_prompts=[
            {
                "id": "queued-operator",
                "prompt": "new operator direction",
                "queued_at": 123,
                "source": "operator",
                "interlace_mode": "interrupt",
            }
        ],
        queue_handoff_state="checkpoint-ready",
        queue_handoff_detail=(
            "Interrupt acknowledged: safe checkpoint after make test; queued "
            "operator prompt will run next with a handoff note."
        ),
        queue_handoff_prompt="new operator direction",
        queue_handoff_interrupted_prompt="Existing operator prompt.",
        queue_handoff_checkpoint_event="exec.completed",
        queue_handoff_checkpoint_tool="make test",
    )

    next_prompt = module.start_next_queued_prompt()

    assert next_prompt is not None
    assert next_prompt[0] == "new operator direction"
    meta = module.load_status_meta()
    assert meta["running_prompt"] == "new operator direction"
    assert meta["queue_handoff_state"] == "running"
    assert meta["queue_handoff_prompt"] == "new operator direction"
    assert "previous reply was paused" in meta["status_message"]

    execution_prompt = module.active_interrupt_handoff_execution_prompt(
        "new operator direction"
    )
    assert execution_prompt.startswith("Safe-checkpoint interrupt handoff:")
    assert "Existing operator prompt." in execution_prompt
    assert "event=exec.completed" in execution_prompt
    assert "tool=make test" in execution_prompt
    assert "Operator prompt:\nnew operator direction" in execution_prompt
    assert module.active_interrupt_handoff_execution_prompt("other prompt") == ""


def test_busy_web_prompt_can_queue_without_injecting(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(pending=True, state="running", running_prompt="Existing")
    module.ACTIVE_PROMPT_THREAD = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt(
        "status?",
        "balanced",
        2,
        [],
        interlace_mode="queue",
    )

    assert accepted is True
    assert snapshot["pending"] is True
    queued = module.normalize_queue(module.load_status_meta()["queued_prompts"])
    assert queued[0]["interlace_mode"] == "queue"
    assert queued[0]["checkpoint_policy"] == "observe"
    meta = module.load_status_meta()
    assert meta["queue_interlace_mode"] == "queue"
    assert "Queue mode acknowledged" in meta["status_message"]

    module.ACTIVE_PROMPT_THREAD = None


def test_queue_mode_waits_for_current_reply_after_tool_finished(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        queued_prompts=[
            {
                "id": "queued-operator",
                "prompt": "new operator direction",
                "queued_at": 123,
                "source": "operator",
                "interlace_mode": "queue",
            }
        ],
    )

    event = {"type": "exec.completed", "command": "make test"}

    assert module.record_queue_checkpoint(event=event, kind="tool-finished") is False

    meta = module.load_status_meta()
    assert meta["queue_interlace_mode"] == "queue"
    assert meta["queue_checkpoint_policy"] == "observe"
    assert meta["queue_checkpoint_state"] == "ready"
    assert "Queue mode acknowledged" in meta["queue_checkpoint_detail"]
    assert "current reply keeps running" in meta["queue_checkpoint_detail"]


def test_api_ask_parses_interlace_mode_before_starting_prompt(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    captured = {}

    def fake_start_web_prompt(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return True, {"pending": True}

    monkeypatch.setattr(module, "start_web_prompt", fake_start_web_prompt)
    monkeypatch.setattr(module, "current_snapshot", lambda: {"pending": True})
    monkeypatch.setattr(module, "clear_draft_attachments", lambda: None)
    monkeypatch.setattr(module, "append_audit_event", lambda **_kwargs: None)

    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        body = urllib.parse.urlencode(
            {
                "message": "status?",
                "speed": "balanced",
                "detail": "2",
                "service_tier": "default",
                "job_budget": "10m",
                "interlace_mode": "queue",
                "runtime": "codex",
                "model": "gpt-5.5",
                "relay_id": "relay-api-ask",
                "relay_callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
                "relay_source_channel_id": "1",
                "relay_source_message_id": "44",
                "relay_target_connector_name": "api-target",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/ask",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.server_close()
        thread.join(timeout=2)

    assert payload["accepted"] is True
    assert payload["running"] is True
    assert payload["queued"] is False
    assert captured["kwargs"]["interlace_mode"] == "queue"
    assert captured["kwargs"]["relay_callback"] == {
        "relay_id": "relay-api-ask",
        "callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
        "source_channel_id": "1",
        "source_message_id": "44",
        "target_connector_name": "api-target",
    }


def test_queue_checkpoint_observe_mode_records_without_interrupt(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_QUEUE_CHECKPOINT_POLICY="observe",
    )
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        queued_prompts=[
            {
                "id": "queued-operator",
                "prompt": "new operator direction",
                "queued_at": 123,
                "source": "operator",
            }
        ],
    )

    event = {"type": "exec.completed", "command": "make test"}

    assert module.record_queue_checkpoint(event=event, kind="tool-finished") is False

    meta = module.load_status_meta()
    assert meta["queue_interlace_mode"] == "queue"
    assert meta["queue_checkpoint_policy"] == "observe"
    assert meta["queue_checkpoint_state"] == "ready"
    assert "Queue mode acknowledged" in meta["queue_checkpoint_detail"]


def test_live_runtime_queues_even_when_status_pending_is_stale(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=False,
        state="ok",
        status_message="Ready.",
        running_prompt="",
        running_speed="balanced",
        running_detail=3,
    )
    module.write_text(module.LAST_PROMPT_PATH, "Existing operator prompt.")
    module.write_text(module.LAST_RESPONSE_PATH, "Previous visible reply.")
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt("status?", "fast", 2, [])

    assert accepted is True
    assert snapshot["pending"] is True
    meta = module.load_status_meta()
    assert meta["pending"] is True
    assert meta["state"] == "running"
    assert meta["running_prompt"] == "Existing operator prompt."
    queued = module.normalize_queue(meta["queued_prompts"])
    assert len(queued) == 1
    assert queued[0]["prompt"] == "status?"
    assert queued[0]["source"] == "operator"


def test_recover_stale_prompt_state_abandons_lost_running_prompt_without_requeue(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    monkeypatch.setattr(module, "now_ts", lambda: 500)
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Working.",
        running_prompt="unfinished recovered prompt",
        running_speed="careful",
        running_detail=5,
        running_attachments=[],
        last_started_at=123,
        queued_prompts=[
            {
                "prompt": "Passive fleet context only. Older BBS item.",
                "queued_at": 124,
                "source": "passive",
            }
        ],
    )
    launches = []
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(
        module, "launch_prompt_worker", lambda *args: launches.append(args)
    )

    module.recover_stale_prompt_state()

    meta = module.load_status_meta()
    queue = module.normalize_queue(meta["queued_prompts"])
    assert meta["pending"] is False
    assert meta["state"] == "error"
    assert meta["recovered_after_restart"] is False
    assert meta["stale_queue"] is False
    assert "abandoned after restart" in meta["status_message"]
    assert meta["last_finished_at"] == 500
    assert module.read_text(module.LAST_PROMPT_PATH) == "unfinished recovered prompt"
    assert "abandoned after restart" in module.read_text(module.LAST_ERROR_PATH)
    assert "abandoned after restart" in module.read_text(module.LAST_RESPONSE_PATH)
    assert len(queue) == 1
    assert queue[0]["prompt"] == "Passive fleet context only. Older BBS item."
    assert queue[0]["source"] == "passive"
    assert launches == []


def test_recover_stale_prompt_state_preserves_real_queue_without_stale_flags(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=False,
        state="recovered",
        status_message="Recovered queued work after restart.",
        running_prompt="",
        queued_prompts=[
            {
                "prompt": "operator follow-up",
                "queued_at": 124,
                "source": "operator",
            },
            {
                "prompt": "Passive fleet context only. Older BBS item.",
                "queued_at": 125,
                "source": "passive",
            },
        ],
        recovered_after_restart=True,
        stale_queue=True,
    )
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)

    module.recover_stale_prompt_state()

    meta = module.load_status_meta()
    queue = module.normalize_queue(meta["queued_prompts"])
    assert meta["pending"] is False
    assert meta["state"] == "ok"
    assert meta["status_message"] == "Queued work is waiting."
    assert meta["recovered_after_restart"] is False
    assert meta["stale_queue"] is False
    assert [item["prompt"] for item in queue] == [
        "operator follow-up",
        "Passive fleet context only. Older BBS item.",
    ]
    assert [item["source"] for item in queue] == ["operator", "passive"]


def test_clear_recovered_queue_restores_ok_state(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=False,
        state="recovered",
        status_message="Recovered queued work after restart.",
        running_prompt="",
        queued_prompts=[{"prompt": "old recovered prompt", "source": "recovered"}],
        recovered_after_restart=True,
        stale_queue=True,
    )

    snapshot = module.clear_queued_prompts()

    assert snapshot["pending"] is False
    assert snapshot["state"] == "ok"
    assert snapshot["queue_depth"] == 0
    meta = module.load_status_meta()
    assert meta["recovered_after_restart"] is False
    assert meta["stale_queue"] is False
    assert meta["queued_prompts"] == []


def test_delete_queued_prompt_removes_one_item_and_clears_stale_flags(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=False,
        state="recovered",
        status_message="Recovered queued work after restart.",
        running_prompt="",
        queued_prompts=[
            {"prompt": "first recovered prompt", "source": "recovered"},
            {"prompt": "second recovered prompt", "source": "recovered"},
        ],
        recovered_after_restart=True,
        stale_queue=True,
    )

    queued = module.normalize_queue(module.load_status_meta()["queued_prompts"])
    snapshot = module.delete_queued_prompt(item_id=queued[0]["id"])

    assert snapshot["queue_depth"] == 1
    remaining = module.normalize_queue(module.load_status_meta()["queued_prompts"])
    assert remaining[0]["prompt"] == "second recovered prompt"
    assert module.load_status_meta()["stale_queue"] is True

    snapshot = module.delete_queued_prompt(index=0)

    assert snapshot["queue_depth"] == 0
    meta = module.load_status_meta()
    assert meta["state"] == "ok"
    assert meta["stale_queue"] is False
    assert meta["recovered_after_restart"] is False


def test_cancel_active_web_prompt_targets_tracked_codex_process_group(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Working.",
        running_prompt="cancel this",
        active_child_pid=12345,
        active_child_pgid=12345,
        queued_prompts=[{"prompt": "queued follow-up", "source": "operator"}],
    )
    terminations = []
    monkeypatch.setattr(
        module,
        "terminate_process_group",
        lambda pid, pgid: terminations.append((pid, pgid)) or True,
    )
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    snapshot = module.cancel_active_web_prompt(clear_queue=True)

    assert terminations == [(12345, 12345)]
    assert snapshot["queue_depth"] == 0
    meta = module.load_status_meta()
    assert meta["state"] == "cancelling"
    assert meta["cancel_requested_at"] > 0
    assert meta["queued_prompts"] == []


def test_cancel_active_web_prompt_marks_cancelled_when_no_worker_is_alive(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Working.",
        running_prompt="cancel this",
    )
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    snapshot = module.cancel_active_web_prompt(clear_queue=False)

    assert snapshot["pending"] is False
    meta = module.load_status_meta()
    assert meta["state"] == "cancelled"
    assert meta["pending"] is False
    assert (
        module.read_text(module.LAST_RESPONSE_PATH)
        == module.CANCELLED_WEB_REPLY_MESSAGE
    )
    assert (
        module.read_text(module.LAST_ERROR_PATH) == module.CANCELLED_WEB_REPLY_MESSAGE
    )


def test_checkpoint_interrupt_is_not_rendered_as_error(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    monkeypatch.setattr(
        module,
        "_execute_prompt_runtime",
        lambda *args, **kwargs: (
            "",
            module.CHECKPOINT_INTERRUPTED_WEB_REPLY_MESSAGE,
            "thread-1",
            module.normalize_usage_entry({"service_tier": "flex"}),
        ),
    )
    monkeypatch.setattr(
        module, "maybe_notify_long_job_completion", lambda **_kwargs: None
    )

    module._prompt_worker(
        "original work",
        module.now_ts(),
        "balanced",
        3,
        "normal",
        3600,
        [],
        "codex",
        module.configured_chat_model(),
        service_tier="flex",
    )

    assert module.read_text(module.LAST_RESPONSE_PATH) == (
        module.CHECKPOINT_INTERRUPTED_WEB_REPLY_MESSAGE
    )
    assert module.read_text(module.LAST_ERROR_PATH) == ""
    history = module.load_history(limit=1)
    assert history[-1]["response"] == module.CHECKPOINT_INTERRUPTED_WEB_REPLY_MESSAGE
    assert history[-1]["error"] == ""
    meta = module.load_status_meta()
    assert meta["state"] == "interrupted"
    assert "safe checkpoint" in meta["status_message"]


def test_relay_callback_notification_posts_completion(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    posted = module.notify_relay_callback(
        {
            "relay_id": "relay-test-0001",
            "callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
            "source_channel_id": 1,
            "source_message_id": 42,
        },
        success=True,
        summary="Target completed the work.",
        thread_id="thread-123",
        started_at=100,
        finished_at=200,
    )

    assert posted is True
    assert len(requests) == 1
    request, timeout = requests[0]
    assert timeout == 8
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["relay_id"] == "relay-test-0001"
    assert payload["source_message_id"] == 42
    assert payload["status"] == "closed"
    assert payload["success"] is True
    assert payload["target"] == module.AGENT_NAME


def test_long_job_notification_posts_completion(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_LONG_JOB_NOTIFY_URL="http://notify.local/long-job",
        NORMAN_CODEX_LONG_JOB_NOTIFY_TOKEN="notify-secret",
        NORMAN_CODEX_LONG_JOB_NOTIFY_THRESHOLD_SECONDS="3600",
        NORMAN_CODEX_LONG_JOB_NOTIFY_TIMEOUT_SECONDS="5",
    )
    module.ensure_state_dir()
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    sent = module.maybe_notify_long_job_completion(
        prompt="do the long job with sensitive input",
        visible_response="finished cleanly",
        error_text="",
        thread_id="thread-123",
        started_at=100,
        finished_at=3701,
        speed="balanced",
        detail=3,
        job_budget="extended",
        timeout_seconds=7200,
        usage={"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
        success=True,
        cancelled=False,
        timed_out=False,
    )

    assert sent is True
    assert len(requests) == 1
    request, timeout = requests[0]
    assert timeout == 5
    assert request.full_url == "http://notify.local/long-job"
    assert request.get_header("Authorization") == "Bearer notify-secret"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["type"] == "codex.long_job.completed"
    assert payload["agent"] == module.AGENT_NAME
    assert payload["status"] == "completed"
    assert payload["duration_seconds"] == 3601
    assert payload["usage"]["total_tokens"] == 12
    assert "Open the TUI for details" in payload["text"]
    assert "notify-secret" not in json.dumps(payload)
    assert "sensitive input" not in json.dumps(payload)
    events = module.load_audit_events(limit=10)
    assert events[-1]["event_type"] == "notification.long-job.sent"


def test_long_job_notification_skips_jobs_under_threshold(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_LONG_JOB_NOTIFY_URL="http://notify.local/long-job",
        NORMAN_CODEX_LONG_JOB_NOTIFY_THRESHOLD_SECONDS="3600",
    )
    requests = []
    monkeypatch.setattr(
        module.urllib_request,
        "urlopen",
        lambda request, timeout: requests.append((request, timeout)),
    )

    sent = module.maybe_notify_long_job_completion(
        prompt="short job",
        visible_response="done",
        error_text="",
        thread_id="thread-123",
        started_at=100,
        finished_at=3699,
        speed="fast",
        detail=2,
        job_budget="standard",
        timeout_seconds=3600,
        usage={},
        success=True,
        cancelled=False,
        timed_out=False,
    )

    assert sent is False
    assert requests == []


def test_prompt_worker_backs_off_and_retries_rate_limit(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_RATE_LIMIT_MAX_ATTEMPTS="3",
        NORMAN_CODEX_RATE_LIMIT_BASE_SECONDS="1",
        NORMAN_CODEX_RATE_LIMIT_MAX_BACKOFF_SECONDS="1",
    )
    module.ensure_state_dir()
    clock = {"now": 100}
    sleeps = []
    calls = []

    def fake_now():
        return clock["now"]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += 1

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append(
            {
                "prompt": prompt,
                "service_tier": service_tier,
                "job_budget": job_budget,
            }
        )
        if len(calls) == 1:
            return (
                "",
                "429 Too Many Requests",
                "thread-rate",
                module.default_usage_entry(),
            )
        return (
            "Recovered after backoff.",
            "",
            "thread-rate",
            module.normalize_usage_entry({"total_tokens": 12}),
        )

    monkeypatch.setattr(module, "now_ts", fake_now)
    monkeypatch.setattr(module.time, "sleep", fake_sleep)
    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "retry this",
        "balanced",
        3,
        "10m",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True
    worker = module.ACTIVE_PROMPT_THREAD
    assert worker is not None
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert len(calls) == 2
    assert sleeps

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"] == "Recovered after backoff."
    assert final_snapshot["rate_limit_active"] is False
    assert final_snapshot["last_error"] == ""
    events = []
    for _ in range(20):
        events = module.load_audit_events(limit=0, event_type="chat.rate-limited")
        if events:
            break
        time.sleep(0.01)
    assert events


def test_promised_work_classifier_catches_future_tense_action(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    assert module.response_final_status("DONE\nEvidence: checked.") == "done"
    assert module.response_final_status("BLOCKED - waiting on provider") == "blocked"
    assert (
        module.response_final_status("CHECKPOINT\nNext action: retry") == "checkpoint"
    )
    assert not module.response_needs_next_action_plan("DONE\nEvidence: checked.")
    assert module.response_needs_next_action_plan("BLOCKED - waiting on provider")
    assert module.response_needs_next_action_plan("CHECKPOINT\nNext action: retry")
    assert module.response_promises_unfinished_work(
        "Targeted validation is green. I\u2019ll run the nearby unit shard before broader handoff."
    )
    assert module.response_promises_unfinished_work(
        "The CloudWatch side is clear. I'm digging into which local artifact produced it."
    )
    assert module.response_promises_unfinished_work(
        "Continuing the evidence audit now: I'll finish the local DAR pointer check."
    )
    assert module.response_promises_unfinished_work(
        "The verifier is scanning local files. I'll collect the output and summarize the ledger facts."
    )
    assert module.response_promises_unfinished_work(
        "One last targeted pass: I\u2019m pulling the exact generator path and whether any later rerun exists."
    )
    assert module.response_promises_unfinished_work(
        "S3 listing returned no matching PDF keys, so I\u2019m doing direct key checks for `latest` and recent date prefixes."
    )
    assert module.response_promises_unfinished_work(
        "Initial sweep shows more than the KPI wrapper: recent KPI component artifacts exist, but the all-in-one wrapper summary is still missing. I\u2019ll now inspect schedules/processes and the latest component health outputs."
    )
    assert module.response_promises_unfinished_work(
        "The broad grep was noisy; I\u2019m tightening to source files only."
    )
    assert not module.response_promises_unfinished_work(
        "Recommended Reply: Hey Anthony, we verified the old backlog cleanup."
    )
    assert not module.response_promises_unfinished_work(
        "This needs approval before I run the destructive cleanup."
    )


def test_prompt_worker_auto_continues_promised_work_once(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_AUTO_CONTINUE_PROMISES="1",
    )
    module.ensure_state_dir()
    calls = []

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append(prompt)
        if len(calls) == 1:
            return (
                "Targeted validation is green. I'll run the nearby unit shard before broader handoff.",
                "",
                "thread-promised",
                module.normalize_usage_entry({"total_tokens": 10}),
            )
        return (
            "Nearby unit shard completed; validation remains green.",
            "",
            "thread-promised",
            module.normalize_usage_entry({"total_tokens": 20}),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "can you proceed",
        "careful",
        5,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert module.AUTO_CONTINUE_PROMISE_MARKER in calls[1]
    assert "Do not just say you will do it" in calls[1]

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"] == (
        "Nearby unit shard completed; validation remains green."
    )

    events = module.load_audit_events(limit=20)
    assert any(event["event_type"] == "chat.needs-continuation" for event in events)
    assert any(event["event_type"] == "chat.auto-continue" for event in events)


def test_auto_continuation_uses_deeper_reasoning_floor(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_AUTO_CONTINUE_PROMISES="1",
    )
    module.ensure_state_dir()
    calls = []

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append((prompt, speed, detail))
        if len(calls) == 1:
            return (
                "The evidence pass is started. I'll inspect the SQLite checkpoint rows next.",
                "",
                "thread-promised",
                module.normalize_usage_entry({"total_tokens": 10}),
            )
        return (
            "DONE\nInspected the SQLite checkpoint rows and posted the concrete finding.",
            "",
            "thread-promised",
            module.normalize_usage_entry({"total_tokens": 20}),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "check whether checkpoints are stalling",
        "balanced",
        2,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert calls[0][1:] == ("balanced", 3)
    assert calls[1][1:] == ("careful", 4)

    events = module.load_audit_events(limit=20)
    auto_event = next(
        event for event in events if event["event_type"] == "chat.auto-continue"
    )
    assert auto_event["payload"]["speed"] == "careful"
    assert auto_event["payload"]["detail"] == 4


def test_prompt_worker_auto_plans_after_checkpoint_once(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_AUTO_CONTINUE_PROMISES="1",
    )
    module.ensure_state_dir()
    calls = []

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append(prompt)
        if len(calls) == 1:
            return (
                "CHECKPOINT\nDone: found the blocker.\nRemaining: choose the next safe action.\nNext action: inspect the route config.",
                "",
                "thread-checkpoint",
                module.normalize_usage_entry({"total_tokens": 10}),
            )
        return (
            "DONE\nPlanned the next action and confirmed it is read-only.",
            "",
            "thread-checkpoint",
            module.normalize_usage_entry({"total_tokens": 20}),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "can you check the route",
        "careful",
        5,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert module.AUTO_CONTINUE_NEXT_ACTION_MARKER in calls[1]
    assert "ended with CHECKPOINT rather than DONE" in calls[1]
    assert "complete one concrete slice with tool evidence" in calls[1]

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"].startswith("DONE")

    events = module.load_audit_events(limit=30)
    assert any(event["event_type"] == "chat.needs-next-action" for event in events)
    assert any(event["event_type"] == "chat.next-action-auto-plan" for event in events)


def test_prompt_worker_marks_auto_continuation_progress_reply_incomplete(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_AUTO_CONTINUE_PROMISES="1",
    )
    module.ensure_state_dir()
    calls = []

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append(prompt)
        return (
            "Continuing the evidence audit now: I'll finish the local pointer check.",
            "",
            "thread-promised",
            module.normalize_usage_entry({"total_tokens": 10}),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        module.build_promised_work_continuation_prompt(
            "can you proceed",
            "I'll inspect the local files.",
        ),
        "careful",
        5,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"]:
            break

    assert len(calls) == 1
    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "error"
    assert final_snapshot["last_response"] == (
        "Continuing the evidence audit now: I'll finish the local pointer check."
    )
    assert final_snapshot["last_error"] == (
        "Auto-continuation returned progress-only work without a completed result."
    )

    events = module.load_audit_events(limit=20)
    assert any(
        event["event_type"] == "chat.continuation-incomplete" for event in events
    )
    assert not any(event["event_type"] == "chat.auto-continue" for event in events)


def test_prompt_worker_retries_empty_reply_without_tool_activity(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_EMPTY_REPLY_MAX_RETRIES="1",
    )
    module.ensure_state_dir()
    calls = []

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append(prompt)
        if len(calls) == 1:
            return "", "", "thread-empty", module.normalize_usage_entry({})
        return (
            "Recovered after empty provider reply.",
            "",
            "thread-empty",
            module.normalize_usage_entry({"total_tokens": 20}),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "status?",
        "careful",
        5,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert module.AUTO_CONTINUE_EMPTY_REPLY_MARKER in calls[1]

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"] == "Recovered after empty provider reply."
    events = module.load_audit_events(limit=20)
    assert any(event["event_type"] == "chat.empty-reply-retry" for event in events)


def test_prompt_worker_does_not_retry_empty_reply_after_tool_activity(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_EMPTY_REPLY_MAX_RETRIES="1",
    )
    module.ensure_state_dir()
    calls = []

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append(prompt)
        meta = module.load_status_meta()
        live_turn = dict(meta.get("live_turn") or {})
        live_turn.update(
            {
                "file_interaction_count": 1,
                "last_tool": "shell",
                "last_file": "/tmp/example.txt",
            }
        )
        module.update_status_meta(live_turn=live_turn)
        return "", "", "thread-empty", module.normalize_usage_entry({})

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "status?",
        "careful",
        5,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"]:
            break

    assert len(calls) == 1

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "error"
    assert final_snapshot["last_response"] == "[no response returned]"
    assert final_snapshot["last_error"] == "No final response was returned."
    events = []
    for _ in range(20):
        events = module.load_audit_events(
            limit=0, event_type="chat.empty-reply-no-retry"
        )
        if events:
            break
        time.sleep(0.01)
    assert events


def test_prompt_worker_retries_zero_token_provider_failure(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES="1",
    )
    module.ensure_state_dir()
    calls = []
    provider_error = (
        "stream disconnected before completion: The server had an error while "
        "processing your request. Sorry about that!"
    )

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append({"prompt": prompt, "service_tier": service_tier})
        if len(calls) == 1:
            return (
                "",
                provider_error,
                "thread-bedrock",
                module.normalize_usage_entry(
                    {
                        "service_tier": "default",
                        "provider_surface": "aws-bedrock",
                        "provider_error_kind": "bedrock_stream_disconnected",
                        "provider_error_text": provider_error,
                        "total_tokens": 0,
                        "zero_token_provider_failure": True,
                    }
                ),
            )
        return (
            "Recovered after provider stream retry.",
            "",
            "thread-bedrock",
            module.normalize_usage_entry({"total_tokens": 20}),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "status?",
        "careful",
        5,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert calls[0]["service_tier"] == "default"
    assert calls[1]["service_tier"] == "flex"
    assert module.AUTO_CONTINUE_ZERO_TOKEN_PROVIDER_MARKER in calls[1]["prompt"]

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"] == "Recovered after provider stream retry."
    events = module.load_audit_events(limit=20)
    retry_events = [
        event
        for event in events
        if event["event_type"] == "chat.zero-token-provider-retry"
    ]
    assert retry_events
    assert retry_events[0]["payload"]["previous_service_tier"] == "default"
    assert retry_events[0]["payload"]["retry_service_tier"] == "flex"
    assert "OpenAI credits/cost" in retry_events[0]["detail"]


def test_prompt_worker_downgrades_bedrock_55_to_standard_54_before_flex(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_MODEL_FLOOR="gpt-5.4",
        NORMAN_CODEX_MODEL="openai.gpt-5.4",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.4",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
        NORMAN_CODEX_SWITCHABLE_MODELS="openai.gpt-5.4,openai.gpt-5.5",
        NORMAN_CODEX_AVAILABLE_MODELS="openai.gpt-5.4,openai.gpt-5.5",
        NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES="1",
    )
    module.ensure_state_dir()
    calls = []
    provider_error = (
        "Task submission failed with status 404 Not Found: Engine not found"
    )

    usage = module.normalize_usage_entry(
        {
            "service_tier": "default",
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_engine_not_found",
            "provider_error_text": provider_error,
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        }
    )
    assert module.zero_token_provider_retry_model("openai.gpt-5.5", usage) == (
        "openai.gpt-5.4"
    )

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append({"prompt": prompt, "model": model, "service_tier": service_tier})
        if len(calls) == 1:
            return "", provider_error, "thread-bedrock", usage
        return (
            "Recovered on Bedrock 5.4.",
            "",
            "thread-bedrock",
            module.normalize_usage_entry({"total_tokens": 20}),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "status?",
        "careful",
        5,
        "normal",
        model="openai.gpt-5.5",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert calls[0]["model"] == "openai.gpt-5.5"
    assert calls[0]["service_tier"] == "default"
    assert calls[1]["model"] == "openai.gpt-5.4"
    assert calls[1]["service_tier"] == "default"
    assert module.AUTO_CONTINUE_ZERO_TOKEN_PROVIDER_MARKER in calls[1]["prompt"]

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"] == "Recovered on Bedrock 5.4."
    events = module.load_audit_events(limit=20)
    retry_events = [
        event
        for event in events
        if event["event_type"] == "chat.zero-token-provider-retry"
    ]
    assert retry_events
    payload = retry_events[0]["payload"]
    assert payload["previous_model"] == "openai.gpt-5.5"
    assert payload["retry_model"] == "openai.gpt-5.4"
    assert payload["model_fallback"] is True
    assert payload["previous_service_tier"] == "default"
    assert payload["retry_service_tier"] == "default"
    assert payload["service_tier_fallback"] is False
    assert "OpenAI credits/cost" not in retry_events[0]["detail"]


def test_bedrock_zero_token_retry_stays_on_bedrock_when_direct_tiers_disabled(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="0",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
    )

    usage = module.normalize_usage_entry(
        {
            "service_tier": "default",
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_stream_disconnected",
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        }
    )

    assert module.zero_token_provider_retry_service_tier("default", usage) == "default"


def test_prompt_worker_hands_off_bedrock_capacity_after_side_effects(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES="1",
    )
    module.ensure_state_dir()
    calls = []
    provider_error = (
        "stream disconnected before completion: Exceeded on-demand capacity. "
        "Please try again later."
    )

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append({"prompt": prompt, "service_tier": service_tier})
        if len(calls) == 1:
            live_turn = dict(module.load_status_meta().get("live_turn") or {})
            live_turn.update(
                {
                    "file_interaction_count": 1,
                    "last_file": "/tmp/earlybird-analysis.json",
                    "last_tool": "exec_command",
                }
            )
            module.update_status_meta(live_turn=live_turn)
            return (
                "",
                provider_error,
                "thread-bedrock",
                module.normalize_usage_entry(
                    {
                        "service_tier": "default",
                        "provider_surface": "aws-bedrock",
                        "provider_error_kind": "bedrock_on_demand_capacity_exceeded",
                        "provider_error_text": provider_error,
                        "total_tokens": 0,
                        "zero_token_provider_failure": True,
                    }
                ),
            )
        return (
            "Recovered from provider recovery checkpoint.",
            "",
            "thread-openai-flex",
            module.normalize_usage_entry(
                {
                    "service_tier": service_tier,
                    "provider_surface": "openai-direct",
                    "total_tokens": 30,
                }
            ),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "finish the scan",
        "careful",
        5,
        "normal",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert calls[0]["service_tier"] == "default"
    assert calls[0]["prompt"] == "finish the scan"
    assert calls[1]["service_tier"] == "flex"
    assert module.AUTO_CONTINUE_ZERO_TOKEN_PROVIDER_MARKER in calls[1]["prompt"]
    assert "Provider recovery checkpoint" in calls[1]["prompt"]
    assert "Original prompt: finish the scan" in calls[1]["prompt"]
    assert (
        "Provider error kind: bedrock_on_demand_capacity_exceeded" in calls[1]["prompt"]
    )
    assert "Do not resend the original prompt unchanged" in calls[1]["prompt"]
    assert "Make the fallback spend visible" in calls[1]["prompt"]

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"] == (
        "Recovered from provider recovery checkpoint."
    )

    events = module.load_audit_events(
        limit=20, event_type="chat.zero-token-provider-recovery-handoff"
    )
    assert events
    event = events[0]
    assert event["summary"] == (
        "Handing off Bedrock recovery checkpoint to fallback route."
    )
    assert "OpenAI credits/cost" in event["detail"]
    assert event["payload"]["previous_service_tier"] == "default"
    assert event["payload"]["retry_service_tier"] == "flex"
    assert event["payload"]["service_tier_fallback"] is True
    assert event["payload"]["provider_error_kind"] == (
        "bedrock_on_demand_capacity_exceeded"
    )
    assert event["payload"]["provider_capacity_no_retry"] is True
    assert not module.load_audit_events(
        limit=20, event_type="chat.zero-token-provider-no-retry"
    )


def test_prompt_worker_hands_off_bedrock_55_failure_to_standard_54_after_side_effects(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_MODEL_FLOOR="gpt-5.4",
        NORMAN_CODEX_MODEL="openai.gpt-5.4",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.4",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
        NORMAN_CODEX_SWITCHABLE_MODELS="openai.gpt-5.4,openai.gpt-5.5",
        NORMAN_CODEX_AVAILABLE_MODELS="openai.gpt-5.4,openai.gpt-5.5",
        NORMAN_CODEX_ZERO_TOKEN_PROVIDER_MAX_RETRIES="1",
    )
    module.ensure_state_dir()
    calls = []
    provider_error = (
        "Task submission failed with status 404 Not Found: Engine not found"
    )

    def fake_execute_runtime(
        prompt,
        speed,
        detail,
        attachments,
        runtime,
        model,
        timeout_seconds=None,
        service_tier="",
        job_budget="",
    ):
        calls.append({"prompt": prompt, "model": model, "service_tier": service_tier})
        if len(calls) == 1:
            live_turn = dict(module.load_status_meta().get("live_turn") or {})
            live_turn.update(
                {
                    "file_interaction_count": 1,
                    "last_file": "/tmp/platinum-result.json",
                    "last_tool": "exec_command",
                }
            )
            module.update_status_meta(live_turn=live_turn)
            return (
                "",
                provider_error,
                "thread-bedrock",
                module.normalize_usage_entry(
                    {
                        "service_tier": "default",
                        "provider_surface": "aws-bedrock",
                        "provider_error_kind": "bedrock_engine_not_found",
                        "provider_error_text": provider_error,
                        "total_tokens": 0,
                        "zero_token_provider_failure": True,
                    }
                ),
            )
        return (
            "Recovered from provider recovery checkpoint on 5.4.",
            "",
            "thread-bedrock",
            module.normalize_usage_entry(
                {
                    "service_tier": service_tier,
                    "provider_surface": "aws-bedrock",
                    "total_tokens": 30,
                }
            ),
        )

    monkeypatch.setattr(module, "_execute_prompt_runtime", fake_execute_runtime)

    accepted, snapshot = module.start_web_prompt(
        "finish the scan",
        "careful",
        5,
        "normal",
        model="openai.gpt-5.5",
        service_tier="default",
    )

    assert accepted is True
    assert snapshot["pending"] is True

    for _ in range(20):
        worker = module.ACTIVE_PROMPT_THREAD
        if worker is not None:
            worker.join(timeout=0.2)
        final_snapshot = module.current_snapshot()
        if not final_snapshot["pending"] and len(calls) == 2:
            break

    assert len(calls) == 2
    assert calls[0]["model"] == "openai.gpt-5.5"
    assert calls[0]["service_tier"] == "default"
    assert calls[1]["model"] == "openai.gpt-5.4"
    assert calls[1]["service_tier"] == "default"
    assert module.AUTO_CONTINUE_ZERO_TOKEN_PROVIDER_MARKER in calls[1]["prompt"]
    assert "Provider recovery checkpoint" in calls[1]["prompt"]
    assert "Original prompt: finish the scan" in calls[1]["prompt"]
    assert "Provider error kind: bedrock_engine_not_found" in calls[1]["prompt"]
    assert "Do not resend the original prompt unchanged" in calls[1]["prompt"]

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["state"] == "ok"
    assert final_snapshot["last_response"] == (
        "Recovered from provider recovery checkpoint on 5.4."
    )

    events = module.load_audit_events(
        limit=20, event_type="chat.zero-token-provider-recovery-handoff"
    )
    assert events
    event = events[0]
    assert "OpenAI credits/cost" not in event["detail"]
    assert event["payload"]["previous_model"] == "openai.gpt-5.5"
    assert event["payload"]["retry_model"] == "openai.gpt-5.4"
    assert event["payload"]["model_fallback"] is True
    assert event["payload"]["previous_service_tier"] == "default"
    assert event["payload"]["retry_service_tier"] == "default"
    assert event["payload"]["service_tier_fallback"] is False
    assert event["payload"]["provider_error_kind"] == "bedrock_engine_not_found"


def test_bbs_relay_prompt_starts_when_console_is_idle(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    requests = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    def fake_execute(
        prompt,
        speed,
        detail,
        attachments,
        timeout_seconds=None,
        model="",
        service_tier="",
        job_budget="",
    ):
        return "Relay work completed.", "", "thread-relay", module.default_usage_entry()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module, "_execute_codex_prompt", fake_execute)

    accepted, snapshot = module.start_web_prompt(
        "Close the BBS loop.",
        "careful",
        5,
        [],
        relay_callback={
            "relay_id": "relay-idle",
            "callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
            "source_channel_id": 1,
            "source_message_id": 42,
            "target_connector_name": "queue-target",
        },
    )

    assert accepted is True
    assert snapshot["pending"] is True
    worker = module.ACTIVE_PROMPT_THREAD
    assert worker is not None
    worker.join(timeout=2)
    assert not worker.is_alive()

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["queue_depth"] == 0
    assert len(requests) == 2
    payloads = [json.loads(request[0].data.decode("utf-8")) for request in requests]
    assert [payload["status"] for payload in payloads] == ["running", "closed"]
    assert payloads[0]["relay_id"] == "relay-idle"
    assert payloads[0]["success"] is None
    assert payloads[0]["target_connector_name"] == "queue-target"
    assert "picked up" in payloads[0]["summary"]
    assert payloads[1]["relay_id"] == "relay-idle"
    assert payloads[1]["success"] is True
    assert payloads[1]["thread_id"] == "thread-relay"


def test_bbs_relay_prompt_queues_when_console_is_busy(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    requests = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        running_speed="balanced",
        running_detail=3,
    )
    module.ACTIVE_PROMPT_THREAD = SimpleNamespace(is_alive=lambda: True)

    accepted, snapshot = module.start_web_prompt(
        "Close this BBS loop after the current turn.",
        "careful",
        5,
        [],
        relay_callback={
            "relay_id": "relay-busy",
            "callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
            "source_channel_id": 1,
            "source_message_id": 43,
            "target_connector_name": "queue-target",
        },
    )

    assert accepted is True
    assert snapshot["pending"] is True
    queued = module.normalize_queue(snapshot["queued_prompts"])
    assert len(queued) == 1
    assert queued[0]["prompt"] == "Close this BBS loop after the current turn."
    assert queued[0]["speed"] == "careful"
    assert queued[0]["detail"] == 5
    assert queued[0]["relay_callback"]["relay_id"] == "relay-busy"
    assert queued[0]["relay_callback"]["target_connector_name"] == "queue-target"
    assert module.load_status_meta()["running_prompt"] == "Existing operator prompt."
    assert len(requests) == 1
    payload = json.loads(requests[0][0].data.decode("utf-8"))
    assert payload["relay_id"] == "relay-busy"
    assert payload["status"] == "queued"
    assert payload["success"] is None
    assert "position 1" in payload["summary"]

    module.ACTIVE_PROMPT_THREAD = None


def test_console_links_load_from_state_file(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (module.STATE_DIR / "console_links.json").write_text(
        json.dumps(
            {
                "links": [
                    {
                        "label": "Phone Ops",
                        "group": "Personal",
                        "url": "https://phone.home.arpa/?token=phone-token",
                        "lan_url": "http://192.168.2.146:8790/?token=phone-token",
                        "featured": True,
                        "priority": 170,
                    }
                ],
                "source": "test",
            }
        ),
        encoding="utf-8",
    )

    links = module.load_console_links_file()

    assert links == [
        {
            "label": "Phone Ops",
            "group": "Personal",
            "url": "https://phone.home.arpa/?token=phone-token",
            "lan_url": "http://192.168.2.146:8790/?token=phone-token",
            "featured": True,
            "priority": 170,
        }
    ]


def test_runtime_model_selection_persists(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    saved = module.save_runtime_settings(
        {"model": "gpt-5.5", "service_tier": "default"}
    )

    assert saved["model"] == "gpt-5.5"
    assert saved["service_tier"] == "default"
    assert module.load_runtime_settings()["model"] == "gpt-5.5"
    assert module.configured_service_tier() == "default"
    assert module.configured_chat_model() == "gpt-5.5"
    assert module.chat_model_update_available() is False


def test_runtime_model_selection_allows_switchable_codex_versions(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SWITCHABLE_MODELS="openai.gpt-5.4",
    )

    saved = module.save_runtime_settings(
        {"runtime": "codex", "model": "openai.gpt-5.4", "service_tier": "default"}
    )

    assert saved["runtime"] == "codex"
    assert saved["model"] == "openai.gpt-5.4"
    assert module.configured_runtime_model("codex") == "openai.gpt-5.4"
    assert "openai.gpt-5.4" in module.AVAILABLE_MODELS


def test_runtime_model_selection_rejects_below_floor(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    saved = module.save_runtime_settings({"runtime": "codex", "model": "gpt-5.4-mini"})

    assert saved["runtime"] == "codex"
    assert saved["model"] == "gpt-5.5"
    assert module.configured_chat_model() == "gpt-5.5"


def test_runtime_registry_includes_codex_and_local_llm(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    registry = {item["key"]: item for item in module.runtime_registry_payload()}

    assert registry["codex"]["can_execute"] is True
    assert registry["codex"]["default_model"] == "gpt-5.5"
    assert registry["localllm"]["label"] == "Codex Local"
    assert registry["localllm"]["can_execute"] is False
    assert registry["localllm"]["tools"] == "brokered-read-only"
    assert registry["claude"]["can_execute"] is False
    assert registry["claude"]["execution"] == "planned-offline"
    assert registry["kimi"]["provider"] == "moonshot"
    assert registry["kimi"]["default_model"] == "moonshotai.kimi-k2.5"
    assert registry["qwen"]["tools"] == "not-wired"
    assert registry["qwen"]["default_model"] == "qwen.qwen3-coder-480b-a35b-v1:0"
    assert registry["gptoss"]["provider"] == "openai/aws-bedrock"
    assert registry["gptoss"]["default_model"] == "openai.gpt-oss-20b-1:0"
    assert registry["gptoss"]["can_execute"] is False
    assert registry["codexspark"]["provider"] == "openai/cerebras"
    assert registry["codexspark"]["default_model"] == "gpt-5.3-codex-spark"
    assert registry["codexspark"]["execution"] == "access-check"
    assert registry["deepseek"]["provider"] == "deepseek"
    assert registry["deepseek"]["execution"] == "benchmark-only"
    assert registry["deepseek"]["default_model"] == "deepseek.v3.2"
    assert module.normalize_runtime("ollama") == "localllm"
    assert module.normalize_runtime("anthropic") == "claude"
    assert module.normalize_runtime("gpt-oss") == "gptoss"
    assert module.normalize_runtime("spark") == "codexspark"
    assert module.normalize_runtime("deepseek-r1") == "deepseek"


def test_runtime_registry_uses_configured_local_llm_inventory(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_LOCAL_LLM_MODEL="gpt-oss:120b",
        NORMAN_LOCAL_LLM_MODELS=(
            "gpt-oss:120b,qwen3.5:122b-a10b-q4_K_M,qwen3-coder-next:q4_K_M"
        ),
        NORMAN_LOCAL_LLM_ENDPOINTS=(
            "http://192.168.2.151:11434,http://192.168.2.152:11434"
        ),
        NORMAN_LOCAL_LLM_MODEL_ENDPOINTS=json.dumps(
            {
                "gpt-oss:120b": [
                    "http://192.168.2.151:11434",
                    "http://192.168.2.152:11434",
                ],
                "qwen3-coder-next:q4_K_M": ["http://192.168.2.152:11434"],
            },
            separators=(",", ":"),
        ),
    )

    registry = {item["key"]: item for item in module.runtime_registry_payload()}

    assert registry["localllm"]["default_model"] == "gpt-oss:120b"
    assert registry["localllm"]["models"] == [
        "gpt-oss:120b",
        "qwen3.5:122b-a10b-q4_K_M",
        "qwen3-coder-next:q4_K_M",
    ]
    assert registry["localllm"]["endpoints"] == [
        "http://192.168.2.151:11434",
        "http://192.168.2.152:11434",
    ]
    assert registry["localllm"]["model_endpoints"]["gpt-oss:120b"] == [
        "http://192.168.2.151:11434",
        "http://192.168.2.152:11434",
    ]
    assert registry["localllm"]["model_endpoints"]["qwen3-coder-next:q4_K_M"] == [
        "http://192.168.2.152:11434"
    ]


def test_bedrock_converse_can_enable_claude_runtime(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
        NORMAN_BEDROCK_CONVERSE_AWS_PROFILE="ob-traqline-admin",
        NORMAN_BEDROCK_CONVERSE_AWS_REGION="us-east-2",
    )

    registry = {item["key"]: item for item in module.runtime_registry_payload()}

    assert registry["claude"]["can_execute"] is True
    assert registry["claude"]["execution"] == "bedrock-converse"
    assert registry["claude"]["default_model"] == "global.anthropic.claude-opus-4-8"
    assert registry["claude"]["tools"] == "brokered-read-only"
    assert module.bedrock_converse_shell_command_allowed("pwd")[0] is True
    assert (
        module.bedrock_converse_shell_command_allowed("git status --short")[0] is True
    )
    assert module.bedrock_converse_shell_command_allowed("rm -rf /tmp/nope")[0] is False
    assert (
        module.bedrock_converse_shell_command_allowed("python3 script.py")[0] is False
    )


def test_bedrock_converse_aws_readonly_is_env_gated_and_allowlisted(
    monkeypatch, tmp_path
) -> None:
    blocked = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
    )

    names = [item["toolSpec"]["name"] for item in blocked.bedrock_converse_tool_specs()]
    denied = blocked.run_bedrock_converse_aws_readonly("aws sts get-caller-identity")

    assert "aws_readonly" not in names
    assert denied["ok"] is False
    assert "disabled" in denied["stderr"]

    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_BEDROCK_CONVERSE_AWS_READONLY_ENABLED="1",
        NORMAN_BEDROCK_CONVERSE_AWS_PROFILE="ob-traqline-admin",
        NORMAN_BEDROCK_CONVERSE_AWS_REGION="us-east-2",
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout='{"Account":"123456789012"}\n',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    names = [item["toolSpec"]["name"] for item in module.bedrock_converse_tool_specs()]
    allowed = module.run_bedrock_converse_aws_readonly(
        "aws sts get-caller-identity --output json"
    )
    ssm_allowed, _argv, _reason = module.bedrock_converse_aws_readonly_command_allowed(
        "aws --region us-east-2 ssm describe-instance-information"
    )
    blocked_profile = module.run_bedrock_converse_aws_readonly(
        "aws --profile other sts get-caller-identity"
    )
    blocked_session = module.run_bedrock_converse_aws_readonly(
        "aws ssm start-session --target i-123"
    )
    blocked_secret = module.run_bedrock_converse_aws_readonly(
        "aws secretsmanager get-secret-value --secret-id nope"
    )
    blocked_chain = module.run_bedrock_converse_aws_readonly(
        "aws sts get-caller-identity; aws configure list"
    )

    assert "aws_readonly" in names
    assert allowed["ok"] is True
    assert ssm_allowed is True
    assert calls[0][0] == ["aws", "sts", "get-caller-identity", "--output", "json"]
    assert calls[0][1]["env"]["AWS_PROFILE"] == "ob-traqline-admin"
    assert calls[0][1]["env"]["AWS_REGION"] == "us-east-2"
    assert blocked_profile["ok"] is False
    assert blocked_session["ok"] is False
    assert blocked_secret["ok"] is False
    assert blocked_chain["ok"] is False
    assert len(calls) == 1


def test_default_claude_runtime_reports_claude_model(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CODEX_DEFAULT_RUNTIME="claude",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
    )

    runtime = module.configured_runtime()

    assert runtime == "claude"
    assert module.configured_runtime_model(runtime) == (
        "global.anthropic.claude-opus-4-8"
    )


def test_model_route_presets_include_codex_and_claude_bedrock(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.4",
        NORMAN_CODEX_DIRECT_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="1",
    )

    presets = {item["key"]: item for item in module.model_route_presets_payload()}

    assert presets["codex-openai"]["runtime"] == "codex"
    assert presets["codex-openai"]["model"] == "gpt-5.5"
    assert presets["codex-openai"]["label"] == "Codex OpenAI Flex"
    assert presets["codex-openai"]["service_tier"] == "flex"
    assert presets["codex-openai"]["can_execute"] is True
    assert presets["codex-openai"]["role"] == "direct fallback"
    assert presets["codex-openai-5-4"]["runtime"] == "codex"
    assert presets["codex-openai-5-4"]["model"] == "gpt-5.4"
    assert presets["codex-openai-5-4"]["service_tier"] == "flex"
    assert presets["codex-openai-5-4"]["status"] == "Fallback"
    assert presets["codex-bedrock"]["runtime"] == "codex"
    assert presets["codex-bedrock"]["model"] == "openai.gpt-5.4"
    assert presets["codex-bedrock"]["label"] == "Codex Bedrock Default"
    assert presets["codex-bedrock"]["service_tier"] == "default"
    assert presets["codex-bedrock"]["can_execute"] is True
    assert presets["codex-bedrock"]["status"] == "Default"
    assert presets["codex-bedrock"]["confidence"] == "high"
    assert presets["codex-bedrock-5-4"]["runtime"] == "codex"
    assert presets["codex-bedrock-5-4"]["model"] == "openai.gpt-5.4"
    assert presets["codex-bedrock-5-4"]["service_tier"] == "default"
    assert presets["codex-bedrock-5-4"]["status"] == "Stable"
    assert presets["codex-bedrock-5-4"]["lane"] == "aws-bedrock"
    assert presets["codex-bedrock-frontier-5-5"]["runtime"] == "codex"
    assert presets["codex-bedrock-frontier-5-5"]["model"] == "openai.gpt-5.5"
    assert presets["codex-bedrock-frontier-5-5"]["status"] == "Frontier"
    assert presets["codex-bedrock-frontier-5-5"]["role"] == "tie breaker"
    assert presets["codex-local"]["runtime"] == "localllm"
    assert presets["codex-local"]["model"] == "local-llm"
    assert presets["codex-local"]["label"] == "Codex Local"
    assert presets["codex-local"]["can_execute"] is False
    assert presets["claude-bedrock"]["runtime"] == "claude"
    assert presets["claude-bedrock"]["model"] == "global.anthropic.claude-opus-4-8"
    assert presets["claude-bedrock"]["service_tier"] == "default"
    assert presets["claude-bedrock"]["can_execute"] is True
    assert presets["kimi-bedrock"]["runtime"] == "kimi"
    assert presets["kimi-bedrock"]["model"] == "moonshotai.kimi-k2.5"
    assert presets["kimi-bedrock"]["status"] == "Benchmark"
    assert presets["qwen-coder-bedrock"]["runtime"] == "qwen"
    assert presets["qwen-coder-bedrock"]["model"] == "qwen.qwen3-coder-480b-a35b-v1:0"
    assert presets["qwen-coder-bedrock"]["can_execute"] is False
    assert presets["gpt-oss-20b-bedrock"]["runtime"] == "gptoss"
    assert presets["gpt-oss-20b-bedrock"]["model"] == "openai.gpt-oss-20b-1:0"
    assert presets["gpt-oss-20b-bedrock"]["status"] == "Benchmark"
    assert presets["gpt-oss-20b-bedrock"]["can_execute"] is False
    assert presets["gpt-oss-120b-bedrock"]["runtime"] == "gptoss"
    assert presets["gpt-oss-120b-bedrock"]["model"] == "openai.gpt-oss-120b-1:0"
    assert presets["gpt-oss-120b-bedrock"]["status"] == "Benchmark"
    assert presets["gpt-oss-120b-bedrock"]["can_execute"] is False
    assert presets["codex-spark-preview"]["runtime"] == "codexspark"
    assert presets["codex-spark-preview"]["model"] == "gpt-5.3-codex-spark"
    assert presets["codex-spark-preview"]["provider"] == "OpenAI/Cerebras"
    assert presets["codex-spark-preview"]["status"] == "Access check"
    assert presets["codex-spark-preview"]["can_execute"] is False
    assert presets["deepseek-bedrock"]["runtime"] == "deepseek"
    assert presets["deepseek-bedrock"]["model"] == "deepseek.v3.2"
    assert presets["deepseek-bedrock"]["status"] == "Benchmark"
    assert presets["deepseek-bedrock"]["can_execute"] is False


def test_bedrock_converse_runtime_uses_readonly_tool_loop(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
        NORMAN_BEDROCK_CONVERSE_MAX_TOOL_CALLS="4",
    )
    calls = []

    def fake_call_bedrock_converse(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "usage": {
                    "inputTokens": 10,
                    "outputTokens": 3,
                    "totalTokens": 13,
                },
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-1",
                                    "name": "shell_readonly",
                                    "input": {"command": "pwd"},
                                }
                            }
                        ]
                    }
                },
            }
        assert (
            calls[-1]["messages"][-1]["content"][0]["toolResult"]["toolUseId"]
            == "tool-1"
        )
        return {
            "usage": {
                "inputTokens": 20,
                "outputTokens": 5,
                "totalTokens": 25,
            },
            "output": {
                "message": {
                    "content": [
                        {
                            "text": (
                                "DONE command evidence captured from shell_readonly."
                            )
                        }
                    ]
                }
            },
        }

    monkeypatch.setattr(module, "call_bedrock_converse", fake_call_bedrock_converse)

    response, error, thread_id, usage = module._execute_prompt_runtime(
        "Run pwd and report evidence.",
        "balanced",
        3,
        [],
        "claude",
        "global.anthropic.claude-opus-4-8",
        timeout_seconds=120,
        service_tier="default",
        job_budget="normal",
    )

    assert error == ""
    assert response.startswith("DONE")
    assert thread_id.startswith("bedrock-converse-")
    assert usage["runtime"] == "claude"
    assert usage["model"] == "global.anthropic.claude-opus-4-8"
    assert usage["provider_surface"] == "aws-bedrock"
    assert usage["input_tokens"] == 30
    assert usage["output_tokens"] == 8
    assert usage["total_tokens"] == 38
    assert calls[0]["model_id"] == "global.anthropic.claude-opus-4-8"
    first_prompt = calls[0]["messages"][0]["content"][0]["text"]
    assert "Operate like a Codex execution agent" in first_prompt
    assert "Brokered tool-call budget for this turn: 4" in first_prompt
    assert (
        "Commands already run in the TUI workdir; do not prefix commands with cd"
        in (first_prompt)
    )
    assert "first visible token of the final answer must be DONE or BLOCKED" in (
        first_prompt
    )
    assert calls[0]["tool_config"]["tools"][0]["toolSpec"]["name"] == "shell_readonly"
    assert len(calls) == 2


def test_bedrock_converse_tool_budget_scales_with_job_budget(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
    )

    assert module.BEDROCK_CONVERSE_MAX_TOOL_CALLS == 0
    assert module.bedrock_converse_tool_call_budget("1m") == 8
    assert module.bedrock_converse_tool_call_budget("15m") == 32
    assert module.bedrock_converse_tool_call_budget("60m") == 64
    assert module.bedrock_converse_tool_call_budget("deep") == 96
    assert module.bedrock_converse_tool_call_budget("overnight") == 128

    pinned = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
        NORMAN_BEDROCK_CONVERSE_MAX_TOOL_CALLS="7",
    )
    assert pinned.bedrock_converse_tool_call_budget("overnight") == 7

    invalid_optional_env = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
        NORMAN_BEDROCK_CONVERSE_MAX_TOOL_CALLS="None",
        NORMAN_BEDROCK_CONVERSE_MAX_TOOL_CALLS_CEILING="None",
    )
    assert invalid_optional_env.BEDROCK_CONVERSE_MAX_TOOL_CALLS == 0
    assert invalid_optional_env.BEDROCK_CONVERSE_MAX_TOOL_CALLS_CEILING == 128


def test_bedrock_converse_tool_budget_returns_checkpoint(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
        NORMAN_BEDROCK_CONVERSE_MAX_TOOL_CALLS="1",
    )
    calls = []

    def fake_call_bedrock_converse(**kwargs):
        calls.append(kwargs)
        return {
            "usage": {
                "inputTokens": 10,
                "outputTokens": 3,
                "totalTokens": 13,
            },
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": f"tool-{len(calls)}",
                                "name": "shell_readonly",
                                "input": {"command": "pwd"},
                            }
                        }
                    ]
                }
            },
        }

    monkeypatch.setattr(module, "call_bedrock_converse", fake_call_bedrock_converse)

    response, error, _thread_id, usage = module._execute_prompt_runtime(
        "Keep inspecting until done.",
        "balanced",
        3,
        [],
        "claude",
        "global.anthropic.claude-opus-4-8",
        timeout_seconds=120,
        service_tier="default",
        job_budget="normal",
    )

    assert error == ""
    assert response.startswith("BLOCKED")
    assert "brokered tool budget reached" in response
    assert "tool_budget: 1" in response
    assert "resume_prompt:" in response
    assert usage["success"] is True
    assert usage["broker_tool_call_budget"] == 1
    assert usage["broker_tool_calls"] == 1
    assert usage["broker_tool_rounds"] == 1
    assert usage["broker_model_calls"] == 2
    assert usage["broker_tool_budget_exhausted"] is True
    assert usage["provider_yield_kind"] == "broker_tool_budget_checkpoint"
    assert len(calls) == 2


def test_bedrock_converse_limited_file_write_is_env_gated(
    monkeypatch, tmp_path
) -> None:
    blocked = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
    )

    denied = blocked.run_bedrock_converse_file_write_limited(
        "scratch/note.txt", "hello"
    )

    assert denied["ok"] is False
    assert denied["returncode"] == 126
    assert "disabled" in denied["stderr"]

    workdir = tmp_path / "work"
    workdir.mkdir()
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_WORKDIR=str(workdir),
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_BEDROCK_CONVERSE_FILE_WRITE_ENABLED="1",
        NORMAN_BEDROCK_CONVERSE_WRITE_PATH_PREFIXES="scratch,tests",
        NORMAN_BEDROCK_CONVERSE_WRITE_MAX_BYTES="128",
    )

    registry = {item["key"]: item for item in module.runtime_registry_payload()}
    names = [item["toolSpec"]["name"] for item in module.bedrock_converse_tool_specs()]
    result = module.run_bedrock_converse_file_write_limited(
        "scratch/note.txt", "hello", "create"
    )
    traversal = module.run_bedrock_converse_file_write_limited("../outside.txt", "nope")
    oversize = module.run_bedrock_converse_file_write_limited(
        "scratch/large.txt", "x" * 129
    )

    assert registry["claude"]["tools"] == "brokered-limited"
    assert "file_write_limited" in names
    assert result["ok"] is True
    assert (workdir / "scratch" / "note.txt").read_text() == "hello"
    assert traversal["ok"] is False
    assert "outside" in traversal["stderr"]
    assert oversize["ok"] is False
    assert "max bytes" in oversize["stderr"]


def test_bedrock_converse_limited_ssh_uses_allowlisted_readonly_policy(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_BEDROCK_CONVERSE_SSH_ENABLED="1",
        NORMAN_BEDROCK_CONVERSE_SSH_TARGETS="root@example.test",
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="remote workdir\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    names = [item["toolSpec"]["name"] for item in module.bedrock_converse_tool_specs()]
    allowed = module.run_bedrock_converse_ssh_limited("root@example.test", "pwd")
    blocked_target = module.run_bedrock_converse_ssh_limited("root@other", "pwd")
    blocked_command = module.run_bedrock_converse_ssh_limited(
        "root@example.test", "rm -rf /tmp/nope"
    )

    assert "ssh_limited" in names
    assert allowed["ok"] is True
    assert allowed["stdout"] == "remote workdir"
    assert calls[0][0][:4] == ["ssh", "-o", "BatchMode=yes", "-o"]
    assert "ConnectTimeout=" in calls[0][0][4]
    assert calls[0][0][-2:] == ["root@example.test", "pwd"]
    assert blocked_target["ok"] is False
    assert "allowlist" in blocked_target["stderr"]
    assert blocked_command["ok"] is False
    assert "read-only" in blocked_command["stderr"]
    assert len(calls) == 1


def test_queued_prompt_preserves_bound_runtime_and_model(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        running_speed="balanced",
        running_detail=3,
    )
    module.ACTIVE_PROMPT_THREAD = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, _snapshot = module.start_web_prompt(
        "use the selected runtime",
        "fast",
        2,
        "normal",
        [],
        "codex",
        "gpt-5.5",
    )

    assert accepted is True
    queued = module.normalize_queue(module.load_status_meta()["queued_prompts"])
    assert queued[0]["runtime"] == "codex"
    assert queued[0]["model"] == "gpt-5.5"
    assert queued[0]["speed"] == "balanced"

    module.ACTIVE_PROMPT_THREAD = None


def test_force_default_runtime_overrides_stale_prompt_runtime(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CODEX_DEFAULT_RUNTIME="claude",
        NORMAN_CODEX_FORCE_DEFAULT_RUNTIME="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
    )
    module.ensure_state_dir()
    launches = []
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(
        module, "launch_prompt_worker", lambda *args: launches.append(args)
    )
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt(
        "stale tab submitted codex",
        "fast",
        2,
        "normal",
        [],
        "codex",
        "gpt-5.5",
    )

    assert accepted is True
    assert len(launches) == 1
    assert launches[0][7] == "claude"
    assert launches[0][8] == "global.anthropic.claude-opus-4-8"
    assert snapshot["running_runtime"] == "claude"
    assert snapshot["running_model"] == "global.anthropic.claude-opus-4-8"


def test_route_lock_honors_explicit_runtime_with_force_default_runtime(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_BEDROCK_CONVERSE_ENABLED="1",
        NORMAN_CODEX_DEFAULT_RUNTIME="claude",
        NORMAN_CODEX_FORCE_DEFAULT_RUNTIME="1",
        NORMAN_CLAUDE_MODEL="global.anthropic.claude-opus-4-8",
    )
    module.ensure_state_dir()
    launches = []
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(
        module, "launch_prompt_worker", lambda *args: launches.append(args)
    )
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt(
        "benchmark explicitly selected codex",
        "fast",
        2,
        "normal",
        [],
        "codex",
        "openai.gpt-5.4",
        route_lock=True,
    )

    assert accepted is True
    assert len(launches) == 1
    assert launches[0][7] == "codex"
    assert launches[0][8] == "openai.gpt-5.4"
    assert snapshot["running_runtime"] == "codex"
    assert snapshot["running_model"] == "openai.gpt-5.4"


def test_console_source_mentions_manual_model_controls() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'data-chat-model="' in source
    assert 'data-chat-runtime="' in source
    assert 'data-route-preset="' in source
    assert "RUNTIME_REGISTRY" in source
    assert "CODEX_MODEL_FLOOR" in source
    assert "Model Route" in source
    assert "Offline plan" in source
    assert "Spend path" in source
    assert "localllm" in source
    assert '"/api/model"' in source
    assert "route_lock" in source
    assert "strict_route" in source
    assert "Model update available" in source


def test_launch_script_reads_runtime_model_override() -> None:
    source = LAUNCH_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "NORMAN_CODEX_MODEL:-gpt-5.5" in source
    assert "runtime_settings.json" in source
    assert 'MODEL="$RUNTIME_MODEL"' in source


def test_codex_bin_prefers_configured_node_path(monkeypatch, tmp_path) -> None:
    node_root = tmp_path / "node-v24.16.0"
    node_bin = node_root / "bin"
    node_bin.mkdir(parents=True)
    node = node_bin / "node"
    codex = node_bin / "codex"
    node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)
    codex.chmod(0o755)

    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_BIN="",
        NORMAN_CODEX_NODE_PATHS=str(node_root),
        PATH="/usr/bin:/bin",
    )

    assert module.CODEX_BIN == str(codex)
    assert os.environ["PATH"].split(os.pathsep)[0] == str(node_bin)


def test_launch_script_discovers_versioned_node_dirs() -> None:
    source = LAUNCH_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'collect_node_bin_dirs "/opt/node-v*/bin"' in source
    assert "NORMAN_CODEX_NODE_PATHS" in source
    assert "/opt/node-v20.19.6/bin/codex" not in source


def test_console_source_uses_scrollable_mobile_settings_sheet() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'id="settings-body"' in source
    assert ".settings-body" in source
    assert "max-height: min(calc(100dvh - 92px), 760px);" in source


def test_console_source_anchors_topbar_menu_from_viewport() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "function syncTopbarMenuPosition()" in source
    assert "top: var(--topbar-menu-top, 54px);" in source
    assert "right: var(--topbar-menu-right, 12px);" in source
    assert source.index("</header>") < source.index(
        '<div id="topbar-menu" class="topbar-menu surface"'
    )


def test_console_source_exposes_low_ui_remote_navigation() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'id="low-ui-rail"' in source
    assert 'id="low-ui-mode-button"' in source
    assert 'data-low-ui-action="prompt"' in source
    assert 'data-low-ui-action="send"' in source
    assert 'data-low-ui-action="status"' in source
    assert "lowUiMode: false" in source
    assert "function handleLowUiRailAction(action)" in source
    assert "function handleLowUiRemoteKey(event)" in source
    assert "body.low-ui-mode .composer-send-label" in source
    assert "--low-ui-rail-top" in source


def test_console_source_keeps_host_mentions_non_addressable() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"hal": {' in source
    assert (
        '"aliases": ("hal", "hal.home.arpa", "hal.tail94915.ts.net", "192.168.2.137")'
        in source
    )
    assert 'const baseKind = String(base.kind || "mention");' in source
    assert 'const mentionable = baseKind !== "host";' in source
    assert "function renderNameCartouche(label, options = {{}}) {{" in source
    assert "function renderLinkedNameCartouche(label, options = {{}}) {{" in source
    assert ".entity-cartouche__label {" in source
    assert "--cartouche-rail" in source
    assert '<span class="entity-cartouche__label">' in source
    assert "function tuiHrefForLabel(label) {{" in source
    assert (
        "renderEntityCartouche({{ ...base, mark, tone }}, "
        "`@${{label}}`, {{ mention: mentionable }})" in source
    )


def test_console_source_promotes_all_host_addresses_to_cartouches() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"hal.home.arpa"' in source
    assert '"toy-box.tail94915.ts.net"' in source
    assert '"private.home.lollie.org"' in source
    assert '"192.168.2.241"' in source
    assert "function indexInlineEntityMap(entries) {{" in source
    assert (
        "[entity.key, entity.label, entry.alias].map(normalizeInlineEntityKey)"
        in source
    )
    assert "home\\.lollie\\.org" in source
    assert "tail[0-9]+\\.ts\\.net" in source
    assert "function renderSwitcherHostCartouche(host) {{" in source
    assert "renderSwitcherHostCartouche(item.host)" in source


def test_console_source_labels_glimpser_bot_lane_as_eyebat() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"glimpser": {\n        "label": "Eyebat",' in source
    assert '"Glimpser",' in source
    assert '"glimpser",' in source


def test_runtime_stale_rollout_thread_error_is_suppressed() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "CODEX_ROLLOUT_THREAD_NOT_FOUND_RE" in source
    assert "codex_rollout_thread_not_found_ids(proc.stderr)" in source
    assert "Codex resume state was stale and has been reset." in source


def test_load_history_suppresses_stale_rollout_thread_error(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    stale_thread_id = "019d21b8-7ac3-7522-9346-1accb2ab9b04"
    error_line = (
        "2026-04-29T15:00:39.680162Z ERROR codex_core::session: "
        f"failed to record rollout items: thread {stale_thread_id} not found"
    )

    module.HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    module.HISTORY_PATH.write_text(
        json.dumps({"error": error_line, "response": "Still returned a response."})
        + "\n",
        encoding="utf-8",
    )

    history = module.load_history()

    assert history[0]["error"] == ""


def test_execute_prompt_resets_stale_resume_thread_and_hides_noise(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    stale_thread_id = "019d21b8-7ac3-7522-9346-1accb2ab9b04"
    error_line = (
        "2026-04-29T15:00:39.680162Z ERROR codex_core::session: "
        f"failed to record rollout items: thread {stale_thread_id} not found"
    )
    module.write_text(module.THREAD_ID_PATH, stale_thread_id)

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert stdin == module.subprocess.DEVNULL
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.write_text("Recovered response.", encoding="utf-8")

        def communicate(self):
            return "", error_line

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, _usage = module._execute_codex_prompt(
        "status?", "balanced", 3, []
    )

    assert response == "Recovered response."
    assert error_text == ""
    assert thread_id == ""
    assert module.read_text(module.THREAD_ID_PATH) == ""


def test_execute_prompt_suppresses_stale_rollout_turn_failed_event(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    stale_thread_id = "019dbfd3-16a3-7cf0-8050-d30887e95c3d"
    error_line = (
        "2026-05-02T13:05:37.384478Z ERROR codex_core::session: "
        f"failed to record rollout items: thread {stale_thread_id} not found"
    )
    module.write_text(module.THREAD_ID_PATH, stale_thread_id)

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert stdin == module.subprocess.DEVNULL
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.write_text("Recovered from JSON error path.", encoding="utf-8")

        def communicate(self):
            stdout = json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": error_line},
                }
            )
            return stdout, ""

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, _usage = module._execute_codex_prompt(
        "test", "balanced", 3, []
    )

    assert response == "Recovered from JSON error path."
    assert error_text == ""
    assert thread_id == ""
    assert module.read_text(module.THREAD_ID_PATH) == ""


def test_execute_prompt_resets_bedrock_engine_not_found_resume_thread(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="0",
    )
    stale_thread_id = "019ec4a4-de0e-7033-b0b9-caf9efff252f"
    thread_scope = "profile-v2:traqline-bedrock:model:openai.gpt-5.5"
    error_message = "Task submission failed with status 404 Not Found: Engine not found"
    module.write_text(module.THREAD_ID_PATH, stale_thread_id)
    module.write_text(module.THREAD_SCOPE_PATH, thread_scope)

    class FakePopen:
        pid = 12345
        returncode = 1

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert "--profile-v2" in cmd
            assert cmd[cmd.index("--profile-v2") + 1] == "traqline-bedrock"
            assert "resume" in cmd
            assert stale_thread_id in cmd
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)

        def communicate(self, *args, **kwargs):
            return (
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "thread.started",
                                "thread_id": stale_thread_id,
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn.failed",
                                "error": {"message": error_message},
                            }
                        ),
                    ]
                ),
                "",
            )

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, usage = module._execute_codex_prompt(
        "status?", "balanced", 3, [], service_tier="default"
    )

    assert response == ""
    assert "Engine not found" in error_text
    assert thread_id == ""
    assert module.read_text(module.THREAD_ID_PATH) == ""
    assert module.read_text(module.THREAD_SCOPE_PATH) == ""
    assert usage["provider_error_kind"] == "bedrock_engine_not_found"
    assert usage["zero_token_provider_failure"] is True


def test_execute_prompt_resets_new_bedrock_engine_not_found_thread(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="0",
    )
    new_thread_id = "019ec6aa-a415-7960-95f4-d9f76097920f"
    error_message = "Task submission failed with status 404 Not Found: Engine not found"

    class FakePopen:
        pid = 12345
        returncode = 1

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert "--profile-v2" in cmd
            assert cmd[cmd.index("--profile-v2") + 1] == "traqline-bedrock"
            assert "resume" not in cmd
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)

        def communicate(self, *args, **kwargs):
            return (
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "thread.started",
                                "thread_id": new_thread_id,
                            }
                        ),
                        json.dumps({"type": "turn.started"}),
                        json.dumps({"type": "error", "message": error_message}),
                        json.dumps(
                            {
                                "type": "turn.failed",
                                "error": {"message": error_message},
                            }
                        ),
                    ]
                ),
                "",
            )

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, usage = module._execute_codex_prompt(
        "status?", "balanced", 3, [], service_tier="default"
    )

    assert response == ""
    assert "Engine not found" in error_text
    assert thread_id == ""
    assert module.read_text(module.THREAD_ID_PATH) == ""
    assert module.read_text(module.THREAD_SCOPE_PATH) == ""
    assert usage["provider_error_kind"] == "bedrock_engine_not_found"
    assert usage["zero_token_provider_failure"] is True

    events = module.load_audit_events(limit=20, event_type="chat.resume-reset")
    assert events
    assert events[0]["thread_id"] == new_thread_id
    assert events[0]["payload"]["new_thread_started"] is True


def test_execute_prompt_records_bedrock_stream_disconnect_diagnostics(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="0",
    )
    error_message = (
        "stream disconnected before completion: The server had an error while "
        "processing your request. Sorry about that! request_id=req-123456"
    )

    class FakePopen:
        pid = 12345
        returncode = 1

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert "--profile-v2" in cmd
            assert cmd[cmd.index("--profile-v2") + 1] == "traqline-bedrock"
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)

        def communicate(self, *args, **kwargs):
            return (
                json.dumps(
                    {
                        "type": "turn.failed",
                        "error": {"message": error_message},
                    }
                ),
                "x-amzn-requestid: amz-abcdef\nx-amzn-trace-id: trace-xyz123\n",
            )

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, _thread_id, usage = module._execute_codex_prompt(
        "status?", "balanced", 3, [], service_tier="default"
    )

    assert response == ""
    assert "stream disconnected before completion" in error_text
    assert usage["provider_surface"] == "aws-bedrock"
    assert usage["provider_error_kind"] == "bedrock_stream_disconnected"
    assert set(usage["provider_request_ids"]) == {"amz-abcdef", "req-123456"}
    assert usage["provider_trace_ids"] == ["trace-xyz123"]
    assert usage["codex_returncode"] == 1
    assert usage["codex_turn_failed_count"] == 1
    assert usage["zero_token_provider_failure"] is True


def test_provider_request_id_extraction_filters_false_positive_field_names(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    text = "\n".join(
        [
            "request_id: Optional",
            "request_id: b.ue_id",
            "request_id: opts.requestId",
            "request_id: request_id_var.get",
            "lease.request_id: a.requestId",
            "x-amzn-requestid: amz-abcdef",
            "x-request-id: 03a0f9c81234",
            "request_id=req-123456",
        ]
    )
    payload = [
        {"ResponseMetadata": {"RequestId": "8f0f8f2f-1234-4567-89ab-123456789abc"}},
        {
            "headers": {
                "x-amzn-requestid": "amz-struct-abcdef",
                "x-amzn-trace-id": "Root=1-abcdef12-1234567890abcdef",
            }
        },
        {"request_id": "opts.requestId", "trace_id": "trace-struct-123"},
    ]

    request_ids = module.extract_provider_request_ids(
        text
    ) + module.extract_provider_request_ids_from_payload(payload)
    trace_ids = module.extract_provider_trace_ids_from_payload(payload)

    assert "amz-abcdef" in request_ids
    assert "03a0f9c81234" in request_ids
    assert "req-123456" in request_ids
    assert "8f0f8f2f-1234-4567-89ab-123456789abc" in request_ids
    assert "amz-struct-abcdef" in request_ids
    assert "Root=1-abcdef12-1234567890abcdef" in trace_ids
    assert "trace-struct-123" in trace_ids
    assert "Optional" not in request_ids
    assert "b.ue_id" not in request_ids
    assert "opts.requestId" not in request_ids
    assert "request_id_var.get" not in request_ids
    assert "a.requestId" not in request_ids


def test_execute_prompt_records_silent_bedrock_zero_token_no_final_diagnostics(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="0",
    )

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert "--profile-v2" in cmd
            assert cmd[cmd.index("--profile-v2") + 1] == "traqline-bedrock"
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)

        def communicate(self, *args, **kwargs):
            return (
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "thread.started",
                                "thread_id": "019edb09-1234-7000-8000-abcdef123456",
                            }
                        ),
                        json.dumps({"type": "turn.started"}),
                        json.dumps(
                            {"type": "item.started", "item": {"type": "reasoning"}}
                        ),
                        json.dumps(
                            {"type": "item.completed", "item": {"type": "reasoning"}}
                        ),
                    ]
                ),
                "",
            )

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, usage = module._execute_codex_prompt(
        "status?", "balanced", 3, [], service_tier="default"
    )

    assert response == ""
    assert error_text == ""
    assert thread_id == "019edb09-1234-7000-8000-abcdef123456"
    assert usage["provider_surface"] == "aws-bedrock"
    assert usage["provider_error_kind"] == "bedrock_zero_token_no_final"
    assert "without a final completion" in usage["provider_error_text"]
    assert "missing_turn_completed=true" in usage["provider_diagnostic_excerpt"]
    assert (
        "codex_event_types=thread.started,turn.started,item.started,item.completed"
        in (usage["provider_diagnostic_excerpt"])
    )
    assert usage["provider_request_ids"] == []
    assert usage["provider_trace_ids"] == []
    assert usage["codex_returncode"] == 0
    assert usage["codex_turn_failed_count"] == 0
    assert usage["zero_token_provider_failure"] is True


def test_execute_prompt_resets_bedrock_stream_disconnect_thread(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(
        monkeypatch,
        tmp_path,
        NORMAN_CODEX_SERVICE_TIER="default",
        NORMAN_CODEX_STANDARD_PROFILE_V2="traqline-bedrock",
        NORMAN_CODEX_STANDARD_MODEL="openai.gpt-5.5",
        NORMAN_CODEX_STANDARD_AWS_PROFILE="ob-traqline-admin",
        NORMAN_CODEX_STANDARD_AWS_REGION="us-east-2",
        NORMAN_CODEX_DIRECT_TIERS_ENABLED="0",
    )
    stale_thread_id = "019ec69d-ba62-7f21-a8c5-ae2b1f1250b0"
    thread_scope = "profile-v2:traqline-bedrock:model:openai.gpt-5.5"
    error_message = (
        "stream disconnected before completion: The server had an error while "
        "processing your request. Sorry about that!"
    )
    module.write_text(module.THREAD_ID_PATH, stale_thread_id)
    module.write_text(module.THREAD_SCOPE_PATH, thread_scope)

    class FakePopen:
        pid = 12345
        returncode = 1

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            assert "--profile-v2" in cmd
            assert cmd[cmd.index("--profile-v2") + 1] == "traqline-bedrock"
            assert "resume" in cmd
            assert stale_thread_id in cmd
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)

        def communicate(self, *args, **kwargs):
            return (
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "thread.started",
                                "thread_id": stale_thread_id,
                            }
                        ),
                        json.dumps({"type": "turn.started"}),
                        json.dumps(
                            {
                                "type": "turn.failed",
                                "error": {"message": error_message},
                            }
                        ),
                    ]
                ),
                "",
            )

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, usage = module._execute_codex_prompt(
        "status?", "balanced", 3, [], service_tier="default"
    )

    assert response == ""
    assert "stream disconnected before completion" in error_text
    assert thread_id == ""
    assert module.read_text(module.THREAD_ID_PATH) == ""
    assert module.read_text(module.THREAD_SCOPE_PATH) == ""
    assert usage["provider_error_kind"] == "bedrock_stream_disconnected"
    assert usage["zero_token_provider_failure"] is True

    events = module.load_audit_events(limit=20, event_type="chat.resume-reset")
    assert events
    assert events[0]["thread_id"] == stale_thread_id
    assert events[0]["payload"]["provider_error_kind"] == "bedrock_stream_disconnected"


def test_bedrock_on_demand_capacity_is_classified_as_capacity_limit(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    error_text = (
        "stream disconnected before completion: Exceeded on-demand capacity. "
        "Please try again later."
    )

    assert (
        module.provider_error_kind(error_text, provider_surface="aws-bedrock")
        == "bedrock_on_demand_capacity_exceeded"
    )
    assert module.is_rate_limit_error(error_text) is True
    assert module.zero_token_provider_retry_candidate(
        {
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_on_demand_capacity_exceeded",
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        },
        error_text,
    )


def test_codex_model_route_mismatch_is_classified(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    error_text = (
        '{"type":"error","status":400,"error":{"type":"invalid_request_error",'
        '"message":"The \'openai.gpt-5.5\' model is not supported when using '
        'Codex with a ChatGPT account."}}'
    )

    assert (
        module.provider_error_kind(error_text, provider_surface="openai-direct")
        == "codex_model_route_mismatch"
    )


def test_stale_arg0_cleanup_warning_is_not_provider_error(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    warning = (
        "WARNING: failed to clean up stale arg0 temp dirs: "
        "Permission denied (os error 13)"
    )

    assert module.provider_error_kind(warning, provider_surface="openai-direct") == ""
    assert module.strip_benign_codex_provider_warnings(warning) == ""
    assert (
        module.strip_benign_codex_provider_warnings(f"{warning}\nreal failure")
        == "real failure"
    )
    assert (
        module.provider_error_kind(
            f"{warning} Task submission failed with status 404 Not Found: Engine not found",
            provider_surface="aws-bedrock",
        )
        == "bedrock_engine_not_found"
    )
