"""Adversarial owner/argument checks, optionally against an installed router."""

import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROUTER_PATH = Path(
    os.environ.get(
        "CODEX_AUDIT_ROUTER_PATH",
        Path(__file__).resolve().parents[1] / "scripts/codex_route.py",
    )
)


@pytest.fixture
def router(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "codex_boundary_audit_target", ROUTER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HOME", tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX_WORK_HOME", raising=False)
    monkeypatch.setattr(
        module,
        "ROUTES",
        tuple(
            replace(r, codex_home=str(tmp_path / (".codex-" + r.key)))
            for r in module.ROUTES
        ),
    )
    return module


@pytest.mark.parametrize("source_index", range(15))
@pytest.mark.parametrize("target_index", range(15))
def test_all_named_home_pairs(router, source_index, target_index):
    source, target = router.ROUTES[source_index], router.ROUTES[target_index]
    owner = "work" if source.launcher == "work" else "personal"
    path = Path(target.codex_home)
    if source.launcher != target.launcher:
        with pytest.raises(RuntimeError, match="opposite-owner"):
            router.validate_codex_home_owner(path, owner)
    else:
        assert router.validate_codex_home_owner(path, owner) == path
    assert not path.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["-C", "/work/repo"],
        ["--cd", "/work/repo"],
        ["--cd=/work/repo"],
        ["-C/work/repo"],
        ["-C=/work/repo"],
        ["exec", "-C/work/repo", "check"],
    ],
)
def test_cd_option_spellings_select_same_checkout(router, args):
    assert router.codex_cwd(args) == Path("/work/repo")


@pytest.mark.parametrize(
    "args",
    [
        ["exec", "--", "--cd", "/work/repo"],
        ["--", "--cd=/work/repo"],
        ["-m", "--cd=/work/repo"],
    ],
)
def test_prompt_or_option_value_cannot_select_checkout(router, args):
    assert router.codex_cwd(args) == Path.cwd()


@pytest.mark.parametrize(
    "args",
    [
        ["--", "login"],
        ["exec", "--", "--help"],
        ["--", "--version"],
        ["-m", "--help", "exec", "check"],
    ],
)
def test_literal_prompt_or_option_value_does_not_skip_session_guards(router, args):
    assert router.starts_session(args)


@pytest.mark.parametrize("args", [["-C", "/a", "--cd=/b"], ["-C"], ["--cd="]])
def test_ambiguous_or_missing_directory_is_rejected_before_routing(router, args):
    with pytest.raises(RuntimeError):
        router.codex_cwd(args)


@pytest.mark.parametrize("owner", ["work", "personal"])
@pytest.mark.parametrize(
    "kind", ["absent", "same_owner_link", "opposite_owner_link", "loop"]
)
def test_home_alias_matrix(router, tmp_path, owner, kind):
    own = tmp_path / (".codex-work" if owner == "work" else ".codex")
    other = tmp_path / (".codex" if owner == "work" else ".codex-work")
    candidate = tmp_path / "candidate"
    if kind == "same_owner_link":
        candidate.symlink_to(own, target_is_directory=True)
    elif kind == "opposite_owner_link":
        candidate.symlink_to(other, target_is_directory=True)
    elif kind == "loop":
        candidate.symlink_to(candidate)
    if kind in {"opposite_owner_link", "loop"}:
        with pytest.raises(RuntimeError):
            router.validate_codex_home_owner(candidate, owner)
    else:
        assert router.validate_codex_home_owner(candidate, owner) == candidate


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"[]",
        b"null",
        b"\xff",
        b" " * 4097,
        b'{"schema_version":1,"google":{"work":"w@example.com","personal":"p@gmail.com"},"credential":"synthetic"}',
    ],
)
def test_policy_failure_never_produces_authentication_claim(router, tmp_path, raw):
    policy = tmp_path / ".config/norman/codex-connector-accounts.json"
    policy.parent.mkdir(parents=True)
    policy.write_bytes(raw)
    result = router.connector_account_policy()
    assert result["status"] == "invalid"
    assert result["google"] == {}
    assert result["authenticated_identity_verified"] is False
    assert "synthetic" not in json.dumps(result)


@pytest.mark.parametrize(
    "args,expected,choice",
    [
        (["--work-apps", "exec", "check"], ["exec", "check"], True),
        (["--work-apps", "--work-no-apps", "exec", "check"], ["exec", "check"], False),
        (["exec", "--", "--work-apps"], ["exec", "--", "--work-apps"], None),
        (
            ["-m", "--work-apps", "exec", "check"],
            ["-m", "--work-apps", "exec", "check"],
            None,
        ),
        (
            ["--work-apps", "exec", "--", "--work-no-apps"],
            ["exec", "--", "--work-no-apps"],
            True,
        ),
    ],
)
def test_work_switches_cannot_eat_prompt_or_option_values(
    router, args, expected, choice
):
    assert router.work_app_arguments(args) == (expected, choice)


@pytest.mark.parametrize(
    "option",
    [
        "-m",
        "--model",
        "-i",
        "--image",
        "-s",
        "--sandbox",
        "-a",
        "--ask-for-approval",
        "--remote",
        "--remote-auth-token-env",
        "--output-last-message",
        "--output-schema",
        "--local-provider",
    ],
)
def test_value_options_cannot_impersonate_help_or_management(router, option):
    assert router.starts_session([option, "--help", "exec", "check"])
    assert router.command_name([option, "login", "exec", "check"]) == "exec"


@pytest.mark.parametrize(
    "tail",
    [
        ["exec", "--", "--work-apps"],
        ["exec", "--", "--work-no-apps"],
        ["-m", "--work-apps", "exec", "check"],
        ["--image", "--work-no-apps", "exec", "check"],
    ],
)
def test_real_work_wrapper_preserves_literal_arguments(tmp_path, tail):
    import subprocess

    wrapper = Path(
        os.environ.get(
            "CODEX_AUDIT_WORK_WRAPPER",
            Path(__file__).resolve().parents[1] / "scripts/codex_work_wrapper.sh",
        )
    )
    capture = tmp_path / "router.py"
    capture.write_text("import json,sys\nprint(json.dumps(sys.argv[1:]))\n")
    environment = dict(os.environ, HOME=str(tmp_path), CODEX_ROUTER_SCRIPT=str(capture))
    result = subprocess.run(
        [str(wrapper), "--print-route", *tail],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "--launcher",
        "work",
        "--print-route",
        "--",
        *tail,
    ]


@pytest.mark.parametrize("origin_index", range(15))
@pytest.mark.parametrize("directory_index", range(15))
def test_recognized_origin_always_wins_over_conflicting_directory(
    router, monkeypatch, tmp_path, origin_index, directory_index
):
    origin_route = router.ROUTES[origin_index]
    directory_route = router.ROUTES[directory_index]
    root = tmp_path / directory_route.repo_names[0]
    monkeypatch.setattr(
        router, "checkout_identity", lambda _: (root, origin_route.repo_names[0])
    )
    assert router.resolve_route(root).key == origin_route.key


@pytest.mark.parametrize(
    "reader,flag,value",
    [
        ("explicit_profiles", "--profile", "personal"),
        ("explicit_models", "--model", "other"),
        ("explicit_feature_toggles", "--enable", "apps"),
        ("config_overrides", "-c", 'model_provider="other"'),
    ],
)
def test_literal_prompt_does_not_override_model_or_app_configuration(
    router, reader, flag, value
):
    assert not getattr(router, reader)(["exec", "--", flag, value])
    if reader != "explicit_models":
        assert not getattr(router, reader)(["-m", flag, "exec", "check"])


@pytest.mark.parametrize(
    "directory,origin,expected",
    [
        ("autocamera", "tmi_dashboards", "tmi-dashboards"),
        ("tmi_dashboards", "autocamera", "autocamera"),
    ],
)
def test_real_git_origin_and_attached_cd_block_wrong_launcher_before_credentials(
    router, tmp_path, monkeypatch, directory, origin, expected
):
    import subprocess

    root = tmp_path / directory
    subprocess.run(
        ["git", "init", "--quiet", str(root)],
        check=True,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "remote",
            "add",
            "origin",
            f"https://example.invalid/test/{origin}.git",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    route = router.resolve_route(root)
    assert route.key == expected
    wrong = "regular" if route.launcher == "work" else "work"
    monkeypatch.setattr(
        router.os, "execve", lambda *args: pytest.fail("wrong-owner client launched")
    )
    monkeypatch.setattr(
        router,
        "brokered_gateway_token",
        lambda *args: pytest.fail("credential lookup before owner rejection"),
    )
    assert (
        router.main(
            ["--launcher", wrong, "--", "-C" + str(root), "exec", "--", "--help"]
        )
        == 2
    )
    assert not (tmp_path / ".codex").exists()
    assert not (tmp_path / ".codex-work").exists()
