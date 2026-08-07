from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import sys
import uuid
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = REPO_ROOT / "scripts" / "norman_codex_secret_guard.py"


@pytest.fixture
def guard_module():
    module_name = f"norman_codex_secret_guard_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.parametrize(
    "command",
    (
        "cred init",
        "/usr/local/bin/cred get networking/firewall",
        "env NORMAN_TEST=1 cred get networking/firewall",
        "sudo -n cred init",
        "python3 /opt/norman/cred_vault.py migrate",
        "python3 scripts/secret_resolver.py networking/firewall",
        "bash scripts/secret_get.sh networking/firewall",
        "python3 -c \"import subprocess; subprocess.run(['cred', 'get', 'networking/firewall'])\"",
        "bash -c 'cred init'",
        "eval 'cred init'",
        r"find . -type f -exec cred get {} \;",
        "printf 'networking/firewall\\n' | xargs cred get",
        "printf 'networking/firewall\\n' | xargs -I{} cred get {}",
    ),
)
def test_guard_denies_direct_vault_execution(guard_module, command: str) -> None:
    assert guard_module.command_uses_direct_cred(command) is True
    assert guard_module.pre_tool_response(
        {"tool_name": "Bash", "tool_input": {"command": command}}
    ) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": guard_module.DENY_REASON,
        }
    }


@pytest.mark.parametrize(
    "command",
    (
        "git status --short",
        "rg -n 'cred init' docs",
        "printf 'cred init\\n'",
        "find . -name cred",
        "python3 -m pytest tests/test_norman_codex_secret_guard.py",
    ),
)
def test_guard_allows_nonexecuting_references_and_ordinary_commands(
    guard_module, command: str
) -> None:
    assert guard_module.command_uses_direct_cred(command) is False
    assert (
        guard_module.pre_tool_response(
            {"tool_name": "Bash", "tool_input": {"command": command}}
        )
        is None
    )


def test_guard_ignores_non_bash_tool_calls(guard_module) -> None:
    assert (
        guard_module.pre_tool_response(
            {"tool_name": "apply_patch", "tool_input": {"command": "cred init"}}
        )
        is None
    )


def test_guard_installs_private_hook_without_replacing_existing_handlers(
    guard_module, tmp_path: Path
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    hooks_path = codex_home / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/keep-existing-hook",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert guard_module.install_pre_tool_hook(codex_home, GUARD_PATH) == hooks_path

    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"] == (
        "/usr/local/bin/keep-existing-hook"
    )
    assert hooks["hooks"]["PreToolUse"][0]["hooks"] == [
        {
            "command": f"{sys.executable} {GUARD_PATH}",
            "statusMessage": "Checking Norman credential policy",
            "timeout": 10,
            "type": "command",
        }
    ]
    assert stat.S_IMODE(hooks_path.stat().st_mode) == 0o600


def test_guard_installs_and_verifies_an_idempotent_managed_policy(
    guard_module, tmp_path: Path
) -> None:
    requirements_path = tmp_path / "requirements.toml"
    requirements_path.write_text(
        '[model_providers.existing]\nname = "Existing provider"\n',
        encoding="utf-8",
    )
    managed_guard_path = tmp_path / "managed" / "norman_codex_secret_guard.py"
    managed_guard_path.parent.mkdir()
    shutil.copy2(GUARD_PATH, managed_guard_path)
    managed_guard_path.chmod(0o755)

    assert (
        guard_module.install_managed_policy(requirements_path, managed_guard_path)
        == requirements_path
    )
    first_install = requirements_path.read_text(encoding="utf-8")
    assert (
        guard_module.install_managed_policy(requirements_path, managed_guard_path)
        == requirements_path
    )
    assert requirements_path.read_text(encoding="utf-8") == first_install

    policy = tomllib.loads(first_install)
    assert policy["model_providers"]["existing"]["name"] == "Existing provider"
    assert policy["allow_managed_hooks_only"] is True
    assert policy["features"]["hooks"] is True
    assert policy["hooks"]["managed_dir"] == str(managed_guard_path.parent)
    assert policy["hooks"]["PreToolUse"][0]["matcher"] == "^Bash$"
    assert (
        policy["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        == f"python3 {managed_guard_path}"
    )
    assert policy["rules"]["prefix_rules"] == [guard_module.MANAGED_DIRECT_VAULT_RULE]
    guard_module.verify_managed_policy(requirements_path, managed_guard_path)


def test_guard_preserves_existing_managed_prefix_rules(
    guard_module, tmp_path: Path
) -> None:
    requirements_path = tmp_path / "requirements.toml"
    requirements_path.write_text(
        """
[rules]
prefix_rules = [
  { pattern = [{ token = "git" }, { token = "push" }], decision = "prompt", justification = "Review publishes." },
]
""".lstrip(),
        encoding="utf-8",
    )
    managed_guard_path = tmp_path / "managed" / "norman_codex_secret_guard.py"
    managed_guard_path.parent.mkdir()
    shutil.copy2(GUARD_PATH, managed_guard_path)
    managed_guard_path.chmod(0o755)

    guard_module.install_managed_policy(requirements_path, managed_guard_path)

    policy = tomllib.loads(requirements_path.read_text(encoding="utf-8"))
    assert policy["rules"]["prefix_rules"] == [
        {
            "pattern": [{"token": "git"}, {"token": "push"}],
            "decision": "prompt",
            "justification": "Review publishes.",
        },
        guard_module.MANAGED_DIRECT_VAULT_RULE,
    ]
    guard_module.verify_managed_policy(requirements_path, managed_guard_path)


def test_guard_rejects_policy_without_managed_hooks_only(
    guard_module, tmp_path: Path
) -> None:
    requirements_path = tmp_path / "requirements.toml"
    managed_guard_path = tmp_path / "managed" / "norman_codex_secret_guard.py"
    managed_guard_path.parent.mkdir()
    shutil.copy2(GUARD_PATH, managed_guard_path)
    managed_guard_path.chmod(0o755)
    guard_module.install_managed_policy(requirements_path, managed_guard_path)

    requirements_path.write_text(
        requirements_path.read_text(encoding="utf-8").replace(
            "allow_managed_hooks_only = true",
            "allow_managed_hooks_only = false",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="restrict hooks"):
        guard_module.verify_managed_policy(requirements_path, managed_guard_path)
