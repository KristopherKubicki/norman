import importlib.util
import os
import sys
import uuid
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

    assert f'base_url = "{route.endpoint}"' in contents
    assert 'args = ["--secret", "norman/prompt-proxy-token"]' in contents
    assert "Bearer " not in contents
    assert "token-real-value" not in contents
    assert profile_path.stat().st_mode & 0o777 == 0o600


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
