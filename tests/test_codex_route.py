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


def write_skill(root, name, contents="---\nname: test\n---\n"):
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(contents, encoding="utf-8")
    return skill


def tool_capable_catalog(module):
    return {
        "object": "list",
        "models": [
            {
                "slug": module.DEFAULT_ROUTER_MODEL,
                **module.REQUIRED_CODEX_MODEL_CAPABILITIES,
            }
        ],
    }


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


def test_route_environment_hides_raw_secret_configuration_from_every_tui(
    route_module, monkeypatch
):
    for name in route_module.MODEL_HIDDEN_SECRET_ENVIRONMENT_KEYS:
        monkeypatch.setenv(name, f"configured-{name.lower()}")

    environment = route_module.route_environment(
        route_by_key(route_module, "networking")
    )

    assert not (route_module.MODEL_HIDDEN_SECRET_ENVIRONMENT_KEYS & environment.keys())


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
    ("arguments", "expected"),
    (
        (
            ["--model", "gpt-5.6-terra"],
            "only supports Norman's Qwen Local, Luna, Terra, or Sol coding models",
        ),
        (
            ["--model=gpt-5.6-terra"],
            "only supports Norman's Qwen Local, Luna, Terra, or Sol coding models",
        ),
        (
            ["-mgpt-5.6-terra"],
            "only supports Norman's Qwen Local, Luna, Terra, or Sol coding models",
        ),
        (["--config", 'model="gpt-5.6-terra"'], "does not allow --config"),
        (
            ["--config", 'model_catalog_json="/tmp/other.json"'],
            "does not allow --config",
        ),
    ),
)
def test_mapped_checkout_rejects_model_or_catalog_overrides(
    route_module, arguments, expected
):
    route = route_by_key(route_module, "norman")

    message = route_module.route_arguments_error(route, arguments)

    assert expected in message


@pytest.mark.parametrize(
    "model_name",
    (
        "norman-code-qwen-local",
        "norman-code-luna",
        "norman-code-terra",
        "norman-code-sol",
        "norman-code",
        "norman-code-governed",
    ),
)
def test_mapped_checkout_allows_the_managed_models(route_module, model_name):
    route = route_by_key(route_module, "norman")

    assert route_module.route_arguments_error(route, ["--model", model_name]) == ""


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
    catalog_path = tmp_path / "codex" / "router-model-catalog.json"

    assert f'base_url = "{route.endpoint}"' in contents
    assert "stream_idle_timeout_ms = 1200000" in contents
    assert 'args = ["--secret", "norman/prompt-proxy-token"]' in contents
    assert "developer_instructions" not in contents
    assert f'model_catalog_json = "{catalog_path}"' in contents
    assert "[features]" not in contents
    assert "hooks = true" not in contents
    assert "PreToolUse" not in contents
    assert "Bearer " not in contents
    assert "token-real-value" not in contents
    assert profile_path.stat().st_mode & 0o777 == 0o600
    assert agents_path.stat().st_mode & 0o777 == 0o600
    assert "BEGIN NORMAN TUI SECRET POLICY" in agents_path.read_text(encoding="utf-8")
    assert "Never create or migrate a vault" in agents_path.read_text(encoding="utf-8")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog_path.stat().st_mode & 0o777 == 0o600
    assert [model["slug"] for model in catalog["models"]] == [
        "norman-code-qwen-local",
        "norman-code-luna",
        "norman-code-terra",
        "norman-code-sol",
    ]
    assert catalog["models"][0]["apply_patch_tool_type"] == "freeform"
    assert catalog["models"][0]["supports_parallel_tool_calls"] is True
    assert catalog["models"][0]["default_reasoning_level"] == "high"
    assert catalog["models"][0]["base_instructions"] == ""
    assert catalog["models"][0]["input_modalities"] == ["text"]
    assert catalog["models"][0]["include_skills_usage_instructions"] is False
    assert catalog["models"][0]["include_plugin_usage_instructions"] is False
    assert catalog["models"][2]["include_skills_usage_instructions"] is True
    assert catalog["models"][2]["include_plugin_usage_instructions"] is True
    assert not (profile_path.parent / "config.toml").exists()


def test_generic_work_fallback_refreshes_tiered_model_contract(route_module, tmp_path):
    profile = tmp_path / "work.config.toml"
    profile.write_text(
        "\n".join(
            (
                'model_provider = "norman"',
                'model = "norman-code"',
                'model_catalog_json = "/tmp/stale-catalog.json"',
                "",
                "[model_providers.norman]",
                'base_url = "https://norman.home.arpa/v1"',
                "",
            )
        ),
        encoding="utf-8",
    )

    catalog_path = route_module.write_work_fallback_model_contract(tmp_path)

    contents = profile.read_text(encoding="utf-8")
    assert f'model = "{route_module.LUNA_ROUTER_MODEL}"' in contents
    assert f'model_catalog_json = "{catalog_path}"' in contents
    assert profile.stat().st_mode & 0o777 == 0o600
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert [model["slug"] for model in catalog["models"]] == [
        route_module.QWEN_LOCAL_ROUTER_MODEL,
        route_module.LUNA_ROUTER_MODEL,
        route_module.TERRA_ROUTER_MODEL,
        route_module.SOL_ROUTER_MODEL,
    ]


def test_work_profile_registers_ops_mcp_without_forcing_workflow(
    route_module, monkeypatch, tmp_path
):
    route = route_by_key(route_module, "control-plane")
    helper = tmp_path / "gateway-token"
    helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.chmod(0o700)
    monkeypatch.setattr(route_module, "GATEWAY_TOKEN_HELPER", helper)
    monkeypatch.setattr(route_module, "route_home", lambda _route: tmp_path / "codex")

    profile_path = route_module.write_gateway_profile(route)
    profile = route_module.tomllib.loads(profile_path.read_text(encoding="utf-8"))
    config = route_module.tomllib.loads(
        (profile_path.parent / "config.toml").read_text(encoding="utf-8")
    )

    assert "developer_instructions" not in profile
    assert config["mcp_servers"]["ops_openbrand"] == {
        "url": "https://ops.openbrand.com/mcp",
        "bearer_token_env_var": "OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY",
        "startup_timeout_sec": 20,
        "tool_timeout_sec": 60,
        "default_tools_approval_mode": "approve",
    }


@pytest.mark.parametrize(
    "route_key",
    (
        "compere",
        "control-plane",
        "earlybird",
        "gold-book",
        "infra",
        "market-sizing",
        "tmi-dashboards",
    ),
)
def test_work_routes_link_every_canonical_work_skill(
    route_module, monkeypatch, tmp_path, route_key
):
    work_root = tmp_path / "work-skills"
    personal_root = tmp_path / "personal-skills"
    work_skills = (
        write_skill(work_root, "work-one"),
        write_skill(work_root, "work-two"),
    )
    write_skill(personal_root, "personal-only")
    route = route_by_key(route_module, route_key)
    home = tmp_path / route.key
    built_in = home / "skills" / ".system"
    built_in.mkdir(parents=True)
    monkeypatch.setattr(route_module, "WORK_SKILLS_SOURCE_ROOT", work_root)
    monkeypatch.setattr(route_module, "PERSONAL_SKILLS_SOURCE_ROOT", personal_root)
    monkeypatch.setattr(route_module, "route_home", lambda _route: home)

    route_module.sync_scoped_skills(route)

    assert built_in.is_dir()
    for skill in work_skills:
        linked_skill = home / "skills" / skill.name
        assert linked_skill.is_symlink()
        assert linked_skill.resolve() == skill
    assert not (home / "skills" / "personal-only").exists()


@pytest.mark.parametrize(
    "route_key",
    ("autocamera", "glimpser", "housebot", "norman", "parkergale", "theseus"),
)
def test_personal_routes_link_only_canonical_personal_skills(
    route_module, monkeypatch, tmp_path, route_key
):
    work_root = tmp_path / "work-skills"
    personal_root = tmp_path / "personal-skills"
    write_skill(work_root, "work-only")
    personal_skill = write_skill(personal_root, "personal-one")
    route = route_by_key(route_module, route_key)
    home = tmp_path / route.key
    monkeypatch.setattr(route_module, "WORK_SKILLS_SOURCE_ROOT", work_root)
    monkeypatch.setattr(route_module, "PERSONAL_SKILLS_SOURCE_ROOT", personal_root)
    monkeypatch.setattr(route_module, "route_home", lambda _route: home)

    route_module.sync_scoped_skills(route)

    linked_skill = home / "skills" / personal_skill.name
    assert linked_skill.is_symlink()
    assert linked_skill.resolve() == personal_skill
    assert not (home / "skills" / "work-only").exists()


@pytest.mark.parametrize("route_key", ("cloudagent", "networking"))
def test_shared_routes_remove_stale_managed_skill_links_without_adding_skills(
    route_module, monkeypatch, tmp_path, route_key
):
    work_root = tmp_path / "work-skills"
    personal_root = tmp_path / "personal-skills"
    stale_skill = write_skill(work_root, "stale-work-skill")
    write_skill(personal_root, "personal-only")
    route = route_by_key(route_module, route_key)
    home = tmp_path / route.key
    skills_home = home / "skills"
    skills_home.mkdir(parents=True)
    (skills_home / stale_skill.name).symlink_to(stale_skill, target_is_directory=True)
    user_skill = write_skill(tmp_path / "user-skills", "user-owned")
    (skills_home / user_skill.name).symlink_to(user_skill, target_is_directory=True)
    monkeypatch.setattr(route_module, "WORK_SKILLS_SOURCE_ROOT", work_root)
    monkeypatch.setattr(route_module, "PERSONAL_SKILLS_SOURCE_ROOT", personal_root)
    monkeypatch.setattr(route_module, "route_home", lambda _route: home)

    route_module.sync_scoped_skills(route)

    assert not (skills_home / stale_skill.name).exists()
    assert (skills_home / user_skill.name).is_symlink()
    assert (skills_home / user_skill.name).resolve() == user_skill
    assert [entry.name for entry in skills_home.iterdir()] == [user_skill.name]


def test_skill_sync_preserves_conflicting_unmanaged_entries(
    route_module, monkeypatch, tmp_path, capsys
):
    work_root = tmp_path / "work-skills"
    managed_skill = write_skill(work_root, "same-name", "managed\n")
    route = route_by_key(route_module, "control-plane")
    home = tmp_path / route.key
    conflicting_skill = write_skill(home / "skills", managed_skill.name, "user-owned\n")
    monkeypatch.setattr(route_module, "WORK_SKILLS_SOURCE_ROOT", work_root)
    monkeypatch.setattr(
        route_module, "PERSONAL_SKILLS_SOURCE_ROOT", tmp_path / "personal"
    )
    monkeypatch.setattr(route_module, "route_home", lambda _route: home)

    route_module.sync_scoped_skills(route)

    assert conflicting_skill.is_dir()
    assert not conflicting_skill.is_symlink()
    assert conflicting_skill.joinpath("SKILL.md").read_text(encoding="utf-8") == (
        "user-owned\n"
    )
    assert "skill conflict for control-plane" in capsys.readouterr().err


@pytest.mark.parametrize(
    "route_key",
    (
        "compere",
        "control-plane",
        "earlybird",
        "gold-book",
        "infra",
        "market-sizing",
        "tmi-dashboards",
    ),
)
def test_work_route_profile_installs_managed_ops_mcp_in_its_own_codex_home(
    route_module, monkeypatch, tmp_path, route_key
):
    route = route_by_key(route_module, route_key)
    helper = tmp_path / "gateway-token"
    helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.chmod(0o700)
    home = tmp_path / route.key
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text(
        (
            'personality = "pragmatic"\n\n'
            "[mcp_servers.ops_openbrand]\n"
            'url = "https://stale.example.test/mcp"\n'
            'bearer_token_env_var = "STALE_TOKEN"\n'
            "startup_timeout_sec = 60\n"
            "tool_timeout_sec = 10\n\n"
            '[projects."/workspace"]\n'
            'trust_level = "trusted"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(route_module, "GATEWAY_TOKEN_HELPER", helper)
    monkeypatch.setattr(route_module, "route_home", lambda _route: home)

    route_module.write_gateway_profile(route)
    route_module.write_gateway_profile(route)

    contents = config_path.read_text(encoding="utf-8")
    parsed = route_module.tomllib.loads(contents)
    assert parsed["personality"] == "pragmatic"
    assert parsed["projects"]["/workspace"]["trust_level"] == "trusted"
    assert parsed["mcp_servers"]["ops_openbrand"] == {
        "url": "https://ops.openbrand.com/mcp",
        "bearer_token_env_var": "OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY",
        "startup_timeout_sec": 20,
        "tool_timeout_sec": 60,
        "default_tools_approval_mode": "approve",
    }
    assert contents.count("[mcp_servers.ops_openbrand]") == 1
    assert "BEGIN NORMAN OPS OPENBRAND MCP" in contents
    assert "END NORMAN OPS OPENBRAND MCP" in contents
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_generated_profile_restores_managed_model_and_refreshes_stale_catalog_cache(
    route_module, monkeypatch, tmp_path
):
    route = route_by_key(route_module, "control-plane")
    helper = tmp_path / "gateway-token"
    helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.chmod(0o700)
    home = tmp_path / "codex"
    home.mkdir()
    profile = home / f"{route.profile}.config.toml"
    profile.write_text(
        'model_provider = "router_control_plane"\nmodel = "gpt-5.6-terra"\n',
        encoding="utf-8",
    )
    cache = home / "models_cache.json"
    cache.write_text('{"models":[{"slug":"norman-code"}]}\n', encoding="utf-8")
    monkeypatch.setattr(route_module, "GATEWAY_TOKEN_HELPER", helper)
    monkeypatch.setattr(route_module, "route_home", lambda _route: home)

    route_module.write_gateway_profile(route)

    contents = profile.read_text(encoding="utf-8")
    assert f'model = "{route_module.DEFAULT_ROUTER_MODEL}"' in contents
    assert "gpt-5.6-terra" not in contents
    assert not cache.exists()
    backups = list(home.glob("models_cache.json.stale-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == (
        '{"models":[{"slug":"norman-code"}]}\n'
    )
    assert route_module.model_catalog_contract_stamp_path(route).read_text(
        encoding="utf-8"
    ).strip() == route_module._model_catalog_contract_stamp(route)

    route_module.write_gateway_profile(route)

    assert list(home.glob("models_cache.json.stale-*")) == backups


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
            return 200, tool_capable_catalog(route_module), ""
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
            f"norman/capacity?model={route_module.QWEN_LOCAL_ROUTER_MODEL}",
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
            return 200, tool_capable_catalog(route_module), ""
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
            f"norman/capacity?model={route_module.QWEN_LOCAL_ROUTER_MODEL}",
            "short-lived-token",
        ),
    ]


def test_route_verify_rejects_model_catalog_without_coding_tools(
    route_module, monkeypatch
):
    route = route_by_key(route_module, "networking")
    monkeypatch.setattr(
        route_module, "brokered_gateway_token", lambda _route: ("short-lived-token", "")
    )
    monkeypatch.setattr(
        route_module,
        "gateway_get_json",
        lambda *_args, **_kwargs: (
            200,
            {
                "object": "list",
                "models": [
                    {
                        "slug": route_module.DEFAULT_ROUTER_MODEL,
                        "shell_type": "shell_command",
                        "apply_patch_tool_type": None,
                        "supports_parallel_tool_calls": False,
                    }
                ],
            },
            "",
        ),
    )

    assert route_module.verify_route(route) == (
        False,
        "gateway model catalog is incompatible with local coding tools: "
        f"'{route_module.DEFAULT_ROUTER_MODEL}' advertises "
        "apply_patch_tool_type=None, expected "
        "'freeform'; deploy the catalog fix and start a new chat",
    )


def test_startup_model_contract_uses_the_managed_local_catalog(
    route_module, monkeypatch
):
    route = route_by_key(route_module, "networking")

    monkeypatch.setattr(
        route_module,
        "brokered_gateway_token",
        lambda _route: pytest.fail("startup model contract must not use the broker"),
    )

    assert route_module.verify_route_model_contract(route) == (
        True,
        "managed tool-capable Codex model catalog verified",
    )


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
                "condition": "recent_local_failure",
                "local_lane": {
                    "eligible_worker_count": 2,
                    "model_ready_worker_count": 1,
                    "redundancy": "single_worker",
                },
                "retryable": True,
            },
            "",
        ),
    )

    assert route_module.verify_norman_capacity(route, token="short-lived-token") == (
        False,
        "the local lane was paused after a recent failed request "
        "(recent_local_model_request_failed); 1/2 model-ready worker(s), "
        "single worker; approved Bedrock fallback is ready and will run before "
        "any local output; retry later",
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
        "verify_route_model_contract",
        lambda _route: (True, "tool-capable gateway model catalog verified"),
    )
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
    assert "Starting Codex normally" in captured.err
    assert "subscription: Short window 68% left" in captured.err
    assert "metered (Aug 01 to Sep 01): ~$1.25" in captured.err


def test_invalid_managed_catalog_blocks_routed_session_before_capacity_preflight(
    route_module, monkeypatch, capsys
):
    route = route_by_key(route_module, "control-plane")
    preflight_calls = []
    executed = []

    monkeypatch.setenv("CODEX_WORK_OPS_BINDING_LOADED", "1")
    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)
    monkeypatch.setattr(
        route_module,
        "routed_model_catalog",
        lambda: {"models": [{"slug": route_module.DEFAULT_ROUTER_MODEL}]},
    )
    monkeypatch.setattr(
        route_module,
        "preflight_route_capacity",
        lambda _route: preflight_calls.append(_route.key) or (True, ""),
    )
    monkeypatch.setattr(
        route_module, "exec_work_route", lambda *_args: executed.append("route")
    )

    assert route_module.main(["--launcher", "work", "--", "resume"]) == 1
    assert preflight_calls == []
    assert executed == []
    assert "startup blocked" in capsys.readouterr().err


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


def test_mapped_work_mcp_command_uses_the_resolved_route(route_module, monkeypatch):
    route = route_by_key(route_module, "control-plane")
    executed = []

    monkeypatch.setattr(route_module, "resolve_route", lambda _cwd: route)
    monkeypatch.setattr(
        route_module,
        "exec_work_route",
        lambda configured_route, arguments: executed.append(
            (configured_route.key, arguments)
        ),
    )

    assert route_module.main(["--launcher", "work", "--", "mcp", "list", "--json"]) == 0
    assert executed == [("control-plane", ["mcp", "list", "--json"])]


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
