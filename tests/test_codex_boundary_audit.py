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


@pytest.mark.parametrize(
    "args",
    [["--help"], ["-h"], ["--version"], ["-V"], ["help", "exec"], ["exec", "--help"]],
)
@pytest.mark.parametrize("launcher", ["work", "regular"])
def test_local_cli_information_never_enters_session_setup(
    router, monkeypatch, tmp_path, args, launcher
):
    monkeypatch.setattr(router, "resolve_route", lambda cwd: None)
    monkeypatch.setattr(router, "resolve_real_codex", lambda: Path("/fake/codex"))

    def forbidden(*args, **kwargs):
        pytest.fail("Local CLI information entered session/credential setup")

    for name in (
        "exec_work_fallback",
        "exec_regular_fallback",
        "verify_managed_tui_secret_policy",
        "write_routed_tui_secret_policy",
    ):
        monkeypatch.setattr(router, name, forbidden)
    calls = []
    monkeypatch.setattr(router.os, "execve", lambda *call: calls.append(call))
    monkeypatch.setenv("OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY", "synthetic-test-value")
    assert router.main(["--launcher", launcher, "--", *args]) == 0
    executable, command, environment = calls.pop()
    assert executable == "/fake/codex"
    assert command == ["/fake/codex", *args]
    assert environment["CODEX_HOME"] == str(
        tmp_path / (".codex-work" if launcher == "work" else ".codex")
    )
    assert "OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY" not in environment
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "args",
    [
        ["--", "--help"],
        ["-m", "--help"],
        ["exec", "--", "help"],
        ["--help=false"],
        ["--version=false"],
    ],
)
def test_local_information_classifier_preserves_literals(router, args):
    assert not router.local_cli_information(args)


@pytest.mark.parametrize("launcher", ["work", "regular"])
def test_local_information_still_rejects_opposite_owner_home(
    router, monkeypatch, tmp_path, launcher
):
    monkeypatch.setattr(router, "resolve_route", lambda cwd: None)
    monkeypatch.setenv(
        "CODEX_WORK_HOME" if launcher == "work" else "CODEX_HOME",
        str(tmp_path / (".codex" if launcher == "work" else ".codex-work")),
    )
    with pytest.raises(RuntimeError, match="opposite-owner"):
        router.main(["--launcher", launcher, "--", "--version"])


@pytest.mark.parametrize(
    "args", [["--help"], ["--version"], ["help", "exec"], ["exec", "--help"]]
)
def test_work_wrapper_local_information_with_unavailable_credentials(tmp_path, args):
    import subprocess

    wrapper = Path(
        os.environ.get(
            "CODEX_AUDIT_WORK_WRAPPER",
            Path(__file__).resolve().parents[1] / "scripts/codex_work_wrapper.sh",
        )
    )
    binary = tmp_path / ".local/lib/codex-work-0.158.0/node_modules/.bin/codex"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n"
    )
    binary.chmod(0o700)
    broker = tmp_path / "code/control_plane/scripts/with_ops_openbrand_mcp.sh"
    broker.parent.mkdir(parents=True)
    marker = tmp_path / "broker-called"
    broker.write_text('#!/bin/sh\ntouch "$HOME/broker-called"\nexit 97\n')
    broker.chmod(0o700)
    environment = dict(
        os.environ,
        HOME=str(tmp_path),
        CODEX_ROUTER_SCRIPT=str(ROUTER_PATH),
        CODEX_REAL_BIN=str(binary),
        CODEX_WORK_HOME=str(tmp_path / ".codex-work"),
    )
    for key in (
        "CODEX_ROUTER_RESOLVED",
        "CODEX_WORK_OPS_BINDING_LOADED",
        "OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY",
        "CODEX_HOME",
    ):
        environment.pop(key, None)
    result = subprocess.run(
        [str(wrapper), *args],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert not marker.exists(), "Local information attempted credential loading"
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == args
    assert not (tmp_path / ".codex-work").exists()


@pytest.mark.parametrize(
    "prefix",
    [
        ["resume", "session-id", "--"],
        ["resume", "--model"],
        ["resume", "--image"],
        ["resume", "-c"],
    ],
)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_shell_resume_guard_cannot_be_bypassed_by_literal_help(tmp_path, prefix, flag):
    import re
    import subprocess

    wrapper = Path(
        os.environ.get(
            "CODEX_AUDIT_WORK_WRAPPER",
            Path(__file__).resolve().parents[1] / "scripts/codex_work_wrapper.sh",
        )
    )
    source = wrapper.read_text()
    functions = "\n".join(
        re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.M | re.S).group()
        for name in ("resume_target", "is_help_request", "guard_resume")
    )
    pressure = tmp_path / "pressure.py"
    pressure.write_text("raise SystemExit(3)\n")
    environment = dict(
        os.environ,
        CODEX_HOME=str(tmp_path),
        CODEX_SESSION_PRESSURE_SCRIPT=str(pressure),
        CODEX_WORK_ALLOW_OVERSIZE_RESUME="0",
    )
    result = subprocess.run(
        ["bash", "-c", functions + '\nguard_resume "$@"', "test", *prefix, flag],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 3, result.stderr
    assert "session resume blocked" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["resume", "--help"],
        ["resume", "-h"],
        ["resume", "--image", "example.png", "--help"],
    ],
)
def test_shell_resume_help_still_skips_pressure_guard(tmp_path, args):
    import re
    import subprocess

    wrapper = Path(
        os.environ.get(
            "CODEX_AUDIT_WORK_WRAPPER",
            Path(__file__).resolve().parents[1] / "scripts/codex_work_wrapper.sh",
        )
    )
    source = wrapper.read_text()
    functions = "\n".join(
        re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.M | re.S).group()
        for name in ("resume_target", "is_help_request", "guard_resume")
    )
    result = subprocess.run(
        ["bash", "-uc", functions + '\nguard_resume "$@"', "test", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_shell_help_scanner_consumes_every_router_value_option(router):
    import re
    import subprocess

    wrapper = Path(
        os.environ.get(
            "CODEX_AUDIT_WORK_WRAPPER",
            Path(__file__).resolve().parents[1] / "scripts/codex_work_wrapper.sh",
        )
    )
    function = re.search(
        r"^is_help_request\(\) \{\n.*?^\}", wrapper.read_text(), re.M | re.S
    ).group()
    for option in router.OPTIONS_WITH_VALUE:
        result = subprocess.run(
            [
                "bash",
                "-c",
                function + '\nis_help_request "$@"',
                "test",
                "resume",
                option,
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1, option


def shell_wrapper_source():
    return Path(
        os.environ.get(
            "CODEX_AUDIT_WORK_WRAPPER",
            Path(__file__).resolve().parents[1] / "scripts/codex_work_wrapper.sh",
        )
    ).read_text()


@pytest.mark.parametrize(
    "args,expected",
    [
        (["exec", "--", "--profile", "other"], ""),
        (["--image", "--profile=other", "exec"], ""),
        (["-m", "-pother", "exec"], ""),
        (["--profile", "work", "exec", "--", "-pother"], "work"),
        (["-p=work", "exec"], "work"),
        (["--profile-v2=work"], "work"),
    ],
)
def test_shell_profile_selection_respects_values_and_literals(args, expected):
    import subprocess

    source = shell_wrapper_source()
    block = source[
        source.index('profile_name=""\n') : source.index("\nselected_profile=")
    ]
    result = subprocess.run(
        ["bash", "-uc", block + '\nprintf "%s" "$profile_name"', "test", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


def test_shell_resume_target_consumes_all_router_value_options(router):
    import re
    import subprocess

    function = re.search(
        r"^resume_target\(\) \{\n.*?^\}", shell_wrapper_source(), re.M | re.S
    ).group()
    for option in router.OPTIONS_WITH_VALUE:
        result = subprocess.run(
            [
                "bash",
                "-c",
                function + '\nresume_target "$@"',
                "test",
                "resume",
                option,
                "option-value",
                "session-id",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "session-id", option


@pytest.mark.parametrize(
    "args",
    [["--profile", ""], ["--profile="], ["-p="], ["--profile-v2="], ["--profile"]],
)
def test_shell_profile_rejects_empty_or_missing_name(args):
    import subprocess

    source = shell_wrapper_source()
    block = source[
        source.index('profile_name=""\n') : source.index("\nselected_profile=")
    ]
    result = subprocess.run(
        ["bash", "-uc", block, "test", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "requires a profile name" in result.stderr


@pytest.mark.parametrize(
    "prefix",
    [
        ["--profile", "work"],
        ["-pwork"],
        ["--cd", "/checkout"],
        ["-C/checkout"],
        ["--model", "resume"],
        ["--enable", "apps", "--profile=work"],
    ],
)
def test_shell_resume_guard_handles_global_options(tmp_path, prefix):
    import re
    import subprocess

    functions = "\n".join(
        re.search(
            rf"^{name}\(\) \{{\n.*?^\}}", shell_wrapper_source(), re.M | re.S
        ).group()
        for name in ("resume_target", "is_help_request", "guard_resume")
    )
    pressure = tmp_path / "pressure.py"
    pressure.write_text(
        'import sys\nassert sys.argv[sys.argv.index("--resume-target") + 1] == "session-id"\nraise SystemExit(3)\n'
    )
    environment = dict(
        os.environ,
        CODEX_HOME=str(tmp_path),
        CODEX_SESSION_PRESSURE_SCRIPT=str(pressure),
        CODEX_WORK_ALLOW_OVERSIZE_RESUME="0",
    )
    result = subprocess.run(
        [
            "bash",
            "-uc",
            functions + '\nguard_resume "$@"',
            "test",
            *prefix,
            "resume",
            "session-id",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 3, result.stderr
    assert "session resume blocked" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--", "resume", "session-id"],
        ["exec", "resume", "session-id"],
        ["--image", "resume", "prompt"],
        ["--profile", "resume"],
    ],
)
def test_shell_resume_guard_does_not_interpret_prompt_or_values_as_command(args):
    import re
    import subprocess

    function = re.search(
        r"^guard_resume\(\) \{\n.*?^\}", shell_wrapper_source(), re.M | re.S
    ).group()
    result = subprocess.run(
        ["bash", "-uc", function + '\nguard_resume "$@"', "test", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
