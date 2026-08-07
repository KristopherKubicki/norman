import importlib.util
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "codex_route.py"


EXPECTED_ROUTES = {
    "autocamera": ("regular", "https://autocamera.home.arpa/v1"),
    "cloudagent": ("regular", "https://cloudagent.home.arpa/v1"),
    "compere": ("work", "https://keystone.kris.openbrand.com/v1"),
    "control-plane": ("work", "https://cp.kris.openbrand.com/v1"),
    "earlybird": ("work", "https://earlybird.kris.openbrand.com/v1"),
    "glimpser": ("regular", "https://eyebat.home.arpa/v1"),
    "gold-book": ("work", "https://goldbook.kris.openbrand.com/v1"),
    "housebot": ("regular", "https://housebot.home.arpa/v1"),
    "infra": ("work", "https://infra.kris.openbrand.com/v1"),
    "market-sizing": ("work", "https://market.kris.openbrand.com/v1"),
    "networking": ("regular", "https://networking.home.arpa/v1"),
    "norman": ("regular", "https://norman.home.arpa/v1"),
    "parkergale": ("regular", "https://pefb.home.arpa/v1"),
    "theseus": ("regular", "https://theseus.home.arpa/v1"),
    "tmi-dashboards": ("work", "https://dashboards.kris.openbrand.com/v1"),
}


@pytest.fixture
def route_module():
    module_name = f"codex_route_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(module_name, None)


def route_by_key(module, key):
    return next(route for route in module.ROUTES if route.key == key)


def test_route_table_assigns_each_checkout_to_its_expected_launcher(route_module):
    actual = {
        route.key: (route.launcher, route.endpoint) for route in route_module.ROUTES
    }

    assert actual == EXPECTED_ROUTES


def test_origin_takes_precedence_over_checkout_directory_name(
    route_module, monkeypatch
):
    monkeypatch.setattr(
        route_module,
        "checkout_identity",
        lambda _cwd: (Path("/tmp/not-gold-book"), "gold-book"),
    )

    assert route_module.resolve_route(Path("/tmp/not-gold-book")).key == "gold-book"


@pytest.mark.parametrize(
    ("nested_root", "expected_route"),
    (
        (Path("/home/kristopher/code/housebot/hubitat-tools"), "housebot"),
        (Path("/home/kristopher/code/networking/mothbox"), "networking"),
    ),
)
def test_parent_checkout_path_routes_nested_git_repositories(
    route_module, monkeypatch, nested_root, expected_route
):
    monkeypatch.setattr(
        route_module,
        "checkout_identity",
        lambda _cwd: (nested_root, nested_root.name),
    )

    assert route_module.resolve_route(nested_root).key == expected_route


def test_unmapped_checkout_has_the_expected_generic_fallback(route_module, monkeypatch):
    unknown_root = Path("/tmp/unmapped-checkout")
    monkeypatch.setattr(
        route_module,
        "checkout_identity",
        lambda _cwd: (unknown_root, "unmapped-checkout"),
    )

    assert route_module.resolve_route(unknown_root) is None
    assert route_module.route_payload(None, "regular", unknown_root)["fallback"] == (
        "regular-default"
    )
    assert route_module.route_payload(None, "work", unknown_root)["fallback"] == (
        "work-bedrock"
    )


@pytest.mark.parametrize("route_key", tuple(EXPECTED_ROUTES))
def test_mapped_checkout_rejects_the_wrong_launcher(
    route_module, monkeypatch, capsys, route_key
):
    route = route_by_key(route_module, route_key)
    wrong_launcher = "work" if route.launcher == "regular" else "regular"
    required_command = "codex" if route.launcher == "regular" else "codex-work"
    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)

    assert route_module.main(["--launcher", wrong_launcher, "--", "implement"]) == 2
    assert required_command in capsys.readouterr().err


def test_explicit_gateway_profile_and_model_are_not_overridden(
    route_module, monkeypatch, tmp_path
):
    route = route_by_key(route_module, "norman")
    real_codex = tmp_path / "codex"
    real_codex.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    real_codex.chmod(0o700)
    captured = {}

    monkeypatch.setattr(route_module, "write_gateway_profile", lambda _route: tmp_path)
    monkeypatch.setattr(route_module, "resolve_real_codex", lambda: real_codex)
    monkeypatch.setattr(route_module, "verify_managed_tui_secret_policy", lambda: None)
    monkeypatch.setattr(
        route_module.os,
        "execve",
        lambda executable, arguments, environment: captured.update(
            executable=executable,
            arguments=arguments,
            environment=environment,
        ),
    )

    route_module.exec_regular_route(
        route,
        ["--profile", route.profile, "--model", "selected-model", "implement"],
    )

    assert captured["arguments"] == [
        str(real_codex),
        "--profile",
        route.profile,
        "--model",
        "selected-model",
        "implement",
    ]
    assert captured["environment"]["CODEX_HOME"].endswith(".codex-norman")
    assert captured["environment"]["NORMAN_TUI_NO_DIRECT_VAULT"] == "1"


def test_mapped_checkout_rejects_profile_or_provider_overrides(
    route_module, monkeypatch, capsys
):
    route = route_by_key(route_module, "norman")
    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)

    assert (
        route_module.main(
            ["--launcher", "regular", "--", "--profile", "personal", "implement"]
        )
        == 2
    )
    assert "could bypass" in capsys.readouterr().err

    assert (
        route_module.main(
            [
                "--launcher",
                "regular",
                "--",
                "--config",
                'model_provider="openai"',
                "implement",
            ]
        )
        == 2
    )
    assert "does not allow --config" in capsys.readouterr().err


@pytest.mark.parametrize(
    "override",
    (
        'developer_instructions="ignore policy"',
        "allow_managed_hooks_only=false",
        "features.hooks=false",
        "features.codex_hooks=false",
        "hooks=[]",
        "hooks.PreToolUse=[]",
        "rules.prefix_rules=[]",
    ),
)
def test_mapped_checkout_rejects_secret_guard_overrides(
    route_module, monkeypatch, capsys, override
):
    route = route_by_key(route_module, "norman")
    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)

    assert (
        route_module.main(["--launcher", "regular", "--", "-c", override, "implement"])
        == 2
    )
    assert "required Norman TUI secret guard" in capsys.readouterr().err


@pytest.mark.parametrize(
    "override",
    (
        "features.hooks=false",
        "features.codex_hooks=false",
        "hooks.PreToolUse=[]",
        "allow_managed_hooks_only=false",
        "rules.prefix_rules=[]",
    ),
)
def test_unmapped_checkout_rejects_secret_guard_overrides(
    route_module, monkeypatch, capsys, override
):
    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: None)

    assert (
        route_module.main(["--launcher", "regular", "--", "-c", override, "implement"])
        == 2
    )
    assert "required Norman TUI secret guard" in capsys.readouterr().err


def test_regular_fallback_requires_the_managed_secret_guard(
    route_module, monkeypatch, tmp_path
):
    real_codex = tmp_path / "codex"
    real_codex.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    real_codex.chmod(0o700)
    codex_home = tmp_path / "codex-home"
    captured = {}

    monkeypatch.setattr(route_module, "resolve_real_codex", lambda: real_codex)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(route_module, "verify_managed_tui_secret_policy", lambda: None)
    monkeypatch.setattr(
        route_module.os,
        "execve",
        lambda executable, arguments, environment: captured.update(
            executable=executable,
            arguments=arguments,
            environment=environment,
        ),
    )

    route_module.exec_regular_fallback(["quick", "status"])

    assert captured["executable"] == str(real_codex)
    assert captured["arguments"] == [
        str(real_codex),
        "quick",
        "status",
    ]
    assert captured["environment"]["CODEX_HOME"] == str(codex_home)
    assert captured["environment"]["NORMAN_TUI_NO_DIRECT_VAULT"] == "1"


def test_generated_profile_uses_brokered_auth_without_storing_a_token(
    route_module, monkeypatch, tmp_path
):
    route = route_by_key(route_module, "norman")
    helper = tmp_path / "gateway-token"
    helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.chmod(0o700)
    monkeypatch.setattr(route_module, "GATEWAY_TOKEN_HELPER", helper)
    monkeypatch.setattr(route_module, "route_home", lambda _route: tmp_path / "codex")

    profile_path = route_module.write_gateway_profile(route)
    contents = profile_path.read_text(encoding="utf-8")
    agents_path = profile_path.parent / "AGENTS.md"

    assert f'base_url = "{route.endpoint}"' in contents
    assert 'args = ["--secret", "norman/prompt-proxy-token"]' in contents
    assert "developer_instructions" in contents
    assert "[features]" not in contents
    assert "hooks = true" not in contents
    assert "PreToolUse" not in contents
    assert "Bearer " not in contents
    assert "token-real-value" not in contents
    assert profile_path.stat().st_mode & 0o777 == 0o600
    assert agents_path.stat().st_mode & 0o777 == 0o600
    assert "BEGIN NORMAN TUI SECRET POLICY" in agents_path.read_text(encoding="utf-8")
    assert "Never create or migrate a vault" in agents_path.read_text(encoding="utf-8")


def test_generated_policy_preserves_route_local_instructions(route_module, tmp_path):
    home = tmp_path / "codex"
    home.mkdir()
    agents_path = home / "AGENTS.md"
    agents_path.write_text("Keep this local instruction.\n", encoding="utf-8")

    route_module.write_routed_tui_secret_policy(home)

    contents = agents_path.read_text(encoding="utf-8")
    assert "Keep this local instruction." in contents
    assert "BEGIN NORMAN TUI SECRET POLICY" in contents
    assert "END NORMAN TUI SECRET POLICY" in contents
    assert agents_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("route_key", "expected_launcher", "expected_endpoint"),
    tuple((key, *route) for key, route in EXPECTED_ROUTES.items()),
)
def test_every_route_generates_an_isolated_brokered_gateway_profile(
    route_module, monkeypatch, tmp_path, route_key, expected_launcher, expected_endpoint
):
    route = route_by_key(route_module, route_key)
    helper = tmp_path / "gateway-token"
    helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.chmod(0o700)
    monkeypatch.setattr(route_module, "GATEWAY_TOKEN_HELPER", helper)
    monkeypatch.setattr(
        route_module,
        "route_home",
        lambda configured_route: tmp_path / configured_route.key,
    )

    profile_path = route_module.write_gateway_profile(route)
    contents = profile_path.read_text(encoding="utf-8")

    assert route.launcher == expected_launcher
    assert f'model_provider = "{route.provider}"' in contents
    assert f'base_url = "{expected_endpoint}"' in contents
    assert 'wire_api = "responses"' in contents
    assert f'args = ["--secret", "{route.resolved_token_secret}"]' in contents
    assert "PreToolUse" not in contents
    assert str(helper) in contents
    assert "Bearer " not in contents
    assert profile_path.stat().st_mode & 0o777 == 0o600


def test_regular_and_work_fallbacks_execute_the_expected_targets(
    route_module, monkeypatch, tmp_path
):
    real_codex = tmp_path / "real-codex"
    reentry = tmp_path / "codex-work"
    for path in (real_codex, reentry):
        path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        path.chmod(0o700)
    captured = []

    monkeypatch.setattr(route_module, "resolve_real_codex", lambda: real_codex)
    monkeypatch.setattr(
        route_module.os,
        "execve",
        lambda executable, arguments, environment: captured.append(
            (executable, arguments, environment)
        ),
    )

    route_module.exec_regular_fallback(["--version"])
    route_module.exec_work_fallback(str(reentry), ["--version"])

    assert captured[0][0] == str(real_codex)
    assert captured[0][1] == [str(real_codex), "--version"]
    assert captured[1][0] == str(reentry)
    assert captured[1][1] == [str(reentry), "--version"]
    assert captured[1][2]["CODEX_ROUTER_RESOLVED"] == "1"
    assert captured[1][2]["CODEX_REAL_BIN"] == str(real_codex)


def test_mapped_route_verify_checks_models_then_local_capacity_once(
    route_module, monkeypatch
):
    route = route_by_key(route_module, "networking")
    calls = []

    monkeypatch.setattr(
        route_module, "brokered_gateway_token", lambda _route: ("short-lived-token", "")
    )

    def fake_gateway_get(endpoint, path, *, token):
        calls.append((endpoint, path, token))
        if path == "models":
            return 200, {"object": "list"}, ""
        return 200, {"available": True, "cloud_fallback": False}, ""

    monkeypatch.setattr(route_module, "gateway_get_json", fake_gateway_get)

    assert route_module.verify_route(route) == (
        True,
        "authenticated Responses gateway and local coding capacity verified",
    )
    assert calls == [
        (route.endpoint, "models", "short-lived-token"),
        (
            route.endpoint,
            "norman/capacity?model=norman-code",
            "short-lived-token",
        ),
    ]


def test_norman_route_verify_checks_models_then_local_capacity_once(
    route_module, monkeypatch
):
    route = route_by_key(route_module, "norman")
    broker_calls = []
    calls = []

    def fake_broker(configured_route):
        broker_calls.append(configured_route.key)
        return "short-lived-token", ""

    def fake_gateway_get(endpoint, path, *, token):
        calls.append((endpoint, path, token))
        if path == "models":
            return 200, {"object": "list"}, ""
        return 200, {"available": True, "cloud_fallback": False}, ""

    monkeypatch.setattr(route_module, "brokered_gateway_token", fake_broker)
    monkeypatch.setattr(route_module, "gateway_get_json", fake_gateway_get)

    assert route_module.verify_route(route) == (
        True,
        "authenticated Responses gateway and local coding capacity verified",
    )
    assert broker_calls == ["norman"]
    assert calls == [
        (route.endpoint, "models", "short-lived-token"),
        (
            route.endpoint,
            "norman/capacity?model=norman-code",
            "short-lived-token",
        ),
    ]


def test_gateway_json_probe_uses_bounded_gateway_timeout(route_module, monkeypatch):
    observed = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"object": "list"}'

    def fake_urlopen(request, *, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(route_module.urllib.request, "urlopen", fake_urlopen)

    assert route_module.gateway_get_json(
        "https://cp.kris.openbrand.com/v1", "models", token="short-lived-token"
    ) == (200, {"object": "list"}, "")
    assert observed == {
        "url": "https://cp.kris.openbrand.com/v1/models",
        "timeout": route_module.GATEWAY_REQUEST_TIMEOUT_SECONDS,
    }
    assert route_module.GATEWAY_REQUEST_TIMEOUT_SECONDS == 20


def test_unavailable_local_capacity_reports_approved_bedrock_fallback(
    route_module, monkeypatch
):
    route = route_by_key(route_module, "control-plane")

    monkeypatch.setattr(
        route_module,
        "gateway_get_json",
        lambda *_args, **_kwargs: (
            200,
            {
                "available": False,
                "cloud_fallback": True,
                "reason": "recent_local_model_request_failed",
                "retryable": True,
            },
            "",
        ),
    )

    assert route_module.verify_norman_capacity(route, token="short-lived-token") == (
        False,
        "local coding capacity is unavailable "
        "(recent_local_model_request_failed); approved Bedrock fallback will be "
        "attempted before any local output; retry later",
    )


def test_capacity_unavailable_warns_then_starts_routed_session(
    route_module, monkeypatch, capsys
):
    route = route_by_key(route_module, "control-plane")
    executed = []

    monkeypatch.setenv("CODEX_WORK_OPS_BINDING_LOADED", "1")
    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)
    monkeypatch.setattr(
        route_module,
        "preflight_route_capacity",
        lambda _route: (
            False,
            "local coding capacity is unavailable (mesh_probe_stale); retry later",
        ),
    )
    monkeypatch.setattr(
        route_module,
        "startup_usage_notices",
        lambda *_args: [
            "subscription: Short window 68% left",
            "metered (Aug 01 to Sep 01): ~$1.25 local estimate across 1 turn(s)",
        ],
    )
    monkeypatch.setattr(
        route_module, "exec_work_route", lambda *_args: executed.append("route")
    )

    assert route_module.main(["--launcher", "work", "--", "resume"]) == 0
    assert executed == ["route"]
    captured = capsys.readouterr()
    assert "control-plane local capacity warning" in captured.err
    assert "mesh_probe_stale" in captured.err
    assert "Starting Codex anyway; use /model" in captured.err
    assert "subscription: Short window 68% left" in captured.err
    assert "metered (Aug 01 to Sep 01): ~$1.25" in captured.err


def test_unbound_work_route_reenters_before_preflight(route_module, monkeypatch):
    route = route_by_key(route_module, "control-plane")
    executed = []
    preflight_calls = []

    monkeypatch.delenv("CODEX_WORK_OPS_BINDING_LOADED", raising=False)
    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)
    monkeypatch.setattr(
        route_module,
        "preflight_route_capacity",
        lambda _route: preflight_calls.append(_route.key) or (True, ""),
    )
    monkeypatch.setattr(
        route_module, "exec_work_route", lambda *_args: executed.append("reenter")
    )

    assert route_module.main(["--launcher", "work", "--", "resume"]) == 0
    assert executed == ["reenter"]
    assert preflight_calls == []


def test_startup_usage_notices_report_fresh_capacity_and_metered_month(
    route_module, monkeypatch, tmp_path
):
    observed_at = int(datetime(2026, 8, 5, 12, tzinfo=timezone.utc).timestamp())
    capacity_path = tmp_path / "codex_account_capacity.json"
    ledger_path = tmp_path / "usage-ledger.jsonl"
    capacity_path.write_text(
        json.dumps(
            {
                "source": "interactive_usage",
                "state": "available",
                "observed_at": observed_at - 30,
                "windows": [
                    {
                        "label": "Short window",
                        "percent_left": 68,
                        "reset_hint": "in 2 hours",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ledger_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "finished_at": observed_at - 60,
                        "charge_ledger_kind": "chatgpt_codex_credit_estimate",
                        "estimated_credits": 100,
                    }
                ),
                json.dumps(
                    {
                        "finished_at": observed_at - 120,
                        "charge_ledger_kind": "api_rate_card_estimate",
                        "cost": {"estimated_usd": 1.25},
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(route_module, "CODEX_ACCOUNT_CAPACITY_PATH", capacity_path)
    monkeypatch.setattr(route_module, "USAGE_LEDGER_PATH", ledger_path)
    monkeypatch.setattr(route_module, "USAGE_HISTORY_PATH", tmp_path / "usage.jsonl")

    assert route_module.startup_usage_notices(observed_at=observed_at) == [
        "subscription: Short window 68% left (resets in 2 hours)",
        "metered (Aug 01 to Sep 01): ~$1.25 local estimate across 1 turn(s)",
    ]


def test_startup_usage_notices_explain_when_no_local_usage_is_available(
    route_module, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        route_module,
        "CODEX_ACCOUNT_CAPACITY_PATH",
        tmp_path / "codex_account_capacity.json",
    )
    monkeypatch.setattr(
        route_module, "USAGE_LEDGER_PATH", tmp_path / "usage-ledger.jsonl"
    )
    monkeypatch.setattr(route_module, "USAGE_HISTORY_PATH", tmp_path / "usage.jsonl")

    assert route_module.startup_usage_notices(observed_at=1_775_664_000) == [
        "no locally captured subscription or metered usage for this profile yet"
    ]


def test_startup_usage_notices_use_the_routed_profile_web_bridge(
    route_module, monkeypatch, tmp_path
):
    observed_at = int(datetime(2026, 8, 5, 12, tzinfo=timezone.utc).timestamp())
    route = route_by_key(route_module, "control-plane")
    state_dir = tmp_path / ".codex-cp" / "web-bridge"
    state_dir.mkdir(parents=True)
    (state_dir / "usage-ledger.jsonl").write_text(
        json.dumps(
            {
                "finished_at": observed_at - 60,
                "charge_ledger_kind": "provider_invoice_estimate",
                "estimated_usd": 3.5,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(route_module, "route_home", lambda _route: state_dir.parent)
    monkeypatch.setattr(route_module, "STATE_DIR", None)
    monkeypatch.setattr(route_module, "USAGE_LEDGER_PATH", None)
    monkeypatch.setattr(route_module, "USAGE_HISTORY_PATH", None)
    monkeypatch.setattr(route_module, "CODEX_ACCOUNT_CAPACITY_PATH", None)

    assert route_module.startup_usage_notices(route, observed_at=observed_at) == [
        "metered (Aug 01 to Sep 01): ~$3.50 local estimate across 1 turn(s)"
    ]


@pytest.mark.parametrize("arguments", (["login"], ["--version"], ["--help"]))
def test_norman_management_commands_skip_capacity_preflight(
    route_module, monkeypatch, arguments
):
    route = route_by_key(route_module, "norman")
    preflight_calls = []
    fallback_calls = []

    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)
    monkeypatch.setattr(
        route_module,
        "preflight_route_capacity",
        lambda _route: preflight_calls.append(_route.key) or (True, ""),
    )
    monkeypatch.setattr(
        route_module,
        "exec_regular_fallback",
        lambda codex_args: fallback_calls.append(codex_args),
    )

    assert route_module.main(["--launcher", "regular", "--", *arguments]) == 0
    assert preflight_calls == []
    assert fallback_calls == [arguments]
