"""Credential-free regression checks for work app switches and wrapper parity."""

import ast
import os
from pathlib import Path
import subprocess
from typing import Sequence

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROUTER = Path(os.environ.get("TEST_WORK_APP_ROUTER", ROOT / "scripts/codex_route.py"))
WRAPPER = Path(
    os.environ.get("TEST_WORK_APP_WRAPPER", ROOT / "scripts/codex_work_wrapper.sh")
)
CASES = [
    ([], [], None),
    (["resume"], ["resume"], None),
    (["--work-apps", "resume"], ["resume"], True),
    (["resume", "--work-no-apps"], ["resume"], False),
    (["exec", "--work-apps", "hello"], ["exec", "hello"], True),
    (["--work-no-apps", "--work-apps"], [], True),
    (["--work-apps", "--work-no-apps"], [], False),
    (["exec", "--", "--work-no-apps"], ["exec", "--", "--work-no-apps"], None),
    (
        ["--work-no-apps", "exec", "--", "--work-apps"],
        ["exec", "--", "--work-apps"],
        False,
    ),
    (["exec", "discuss --work-no-apps"], ["exec", "discuss --work-no-apps"], None),
    (["--model=--work-no-apps"], ["--model=--work-no-apps"], None),
    (["-m--work-no-apps"], ["-m--work-no-apps"], None),
    (["--model", "--work-no-apps", "--work-apps"], ["--model", "--work-no-apps"], True),
]


def router_parser():
    # Execute only the pure parser and constant, never credential setup.
    nodes = [
        node
        for node in ast.parse(ROUTER.read_text()).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "work_app_arguments"
        or isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "OPTIONS_WITH_VALUE"
            for t in node.targets
        )
    ]
    assert len(nodes) == 2
    namespace = {"Sequence": Sequence}
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTER), "exec"), namespace
    )
    return namespace["work_app_arguments"], namespace["OPTIONS_WITH_VALUE"]


def wrapper_parse(arguments):
    source = WRAPPER.read_text()
    start = source.index("disable_apps=")
    end = source.index('set -- "${filtered_args[@]}"', start)
    end += len('set -- "${filtered_args[@]}"')
    script = source[start:end] + '\nprintf "%s\\0" "$disable_apps" "$#" "$@"\n'
    result = subprocess.run(
        ["bash", "-c", script, "app-parser-test", *arguments],
        capture_output=True,
        check=True,
        timeout=5,
    )
    parts = result.stdout.split(b"\0")
    count = int(parts[1])
    return [p.decode() for p in parts[2 : 2 + count]], parts[0] == b"0"


@pytest.mark.parametrize("arguments,expected,choice", CASES)
def test_python_and_shell_app_switch_semantics(arguments, expected, choice):
    parser, _ = router_parser()
    assert parser(arguments) == (expected, choice)
    assert wrapper_parse(arguments) == (expected, choice is not False)


def test_option_values_are_not_app_switches():
    parser, options = router_parser()
    for option in sorted(options):
        for marker in ("--work-apps", "--work-no-apps"):
            arguments = [option, marker, "resume"]
            assert parser(arguments) == (arguments, None), (option, marker)
            assert wrapper_parse(arguments) == (arguments, True), (option, marker)


@pytest.mark.parametrize("disabled,expected", [(0, "--enable"), (1, "--disable")])
def test_final_wrapper_command_uses_exactly_one_app_toggle(
    tmp_path, disabled, expected
):
    source = WRAPPER.read_text()
    start = source.index("run_codex() {")
    end = source.index("\n}\n", start) + len("\n}")
    fake = tmp_path / "fake-codex"
    fake.write_text('#!/bin/sh\nprintf "%s\\0" "$@"\n')
    fake.chmod(0o700)
    script = "\n".join(
        [
            'CODEX_WORK_PINNED_BIN="$1"',
            'CODEX_REAL_BIN="$1"',
            'disable_apps="$2"',
            "ops_mcp_args=()",
            source[start:end],
            'run_codex -c "mcp_servers.example.enabled=false" resume "a prompt with spaces"',
        ]
    )
    result = subprocess.run(
        ["bash", "-c", script, "app-launch-test", str(fake), str(disabled)],
        capture_output=True,
        check=True,
        timeout=5,
    )
    arguments = [p.decode() for p in result.stdout.split(b"\0")[:-1]]
    assert arguments == [
        expected,
        "apps",
        "-c",
        "mcp_servers.example.enabled=false",
        "resume",
        "a prompt with spaces",
    ]


def test_management_dispatch_remains_before_router_reentry():
    source = WRAPPER.read_text()
    assert source.index("--print-route|--routes|--verify)") < source.index(
        'if [[ "${CODEX_ROUTER_RESOLVED:-}" != "1" ]]'
    )


@pytest.mark.parametrize(
    "flags,enabled",
    [
        (["--enable", "apps"], True),
        (["--disable", "apps"], False),
        (["--enable", "apps", "--disable", "apps"], False),
        (["--disable", "apps", "--enable", "apps"], False),
    ],
)
def test_pinned_cli_app_feature(tmp_path, flags, enabled):
    """Opt-in real CLI proof with an empty home and no connector authentication."""
    binary = os.environ.get("TEST_WORK_APP_CODEX")
    if not binary:
        pytest.skip("Set TEST_WORK_APP_CODEX for credential-free real CLI validation")
    environment = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "CODEX_HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
    }
    result = subprocess.run(
        [binary, *flags, "features", "list"],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    rows = [
        line.split()
        for line in result.stdout.splitlines()
        if line.split()[:1] == ["apps"]
    ]
    assert len(rows) == 1
    assert rows[0][-1] == str(enabled).lower()
