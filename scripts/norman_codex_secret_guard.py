#!/usr/bin/env python3
"""Block model-directed direct access to the local cred vault from Codex."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib


DENY_REASON = (
    "Direct local secret access is disabled for Norman TUIs. Use the approved "
    "Norman Keys path when credentialed work is necessary, or report the "
    "action blocked. Never initialize a vault or request a vault passphrase."
)
SHELL_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "(", ")"})
CONTROL_WORDS = frozenset(
    {
        "!",
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "function",
        "if",
        "in",
        "select",
        "then",
        "time",
        "until",
        "while",
        "{",
        "}",
    }
)
SHELL_COMMANDS = frozenset({"bash", "dash", "fish", "ksh", "sh", "zsh"})
DIRECT_CRED_BASENAMES = frozenset({"cred", "cred_vault.py", "cred-vault"})
DIRECT_SECRET_RESOLVER_BASENAMES = frozenset({"secret_resolver.py", "secret_get.sh"})
PROTECTED_SECRET_BASENAMES = DIRECT_CRED_BASENAMES | DIRECT_SECRET_RESOLVER_BASENAMES
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIRECTION_RE = re.compile(r"^(?:\d+)?(?:>>?|<<?|<>|>&|<&).*$")
DEFAULT_REQUIREMENTS_PATH = Path("/etc/codex/requirements.toml")
DEFAULT_MANAGED_HOOKS_DIR = Path("/usr/local/lib/norman-codex-route")
MANAGED_GUARD_FILENAME = "norman_codex_secret_guard.py"
MANAGED_HOOK_STATUS_MESSAGE = "Checking Norman credential policy"
MANAGED_HOOKS_ONLY_KEY = "allow_managed_hooks_only"
MANAGED_DIRECT_VAULT_RULE = {
    "pattern": [{"any_of": ["cred", "cred-vault"]}],
    "decision": "forbidden",
    "justification": DENY_REASON,
}


def _tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        # A malformed shell command cannot execute as intended. Do not emit the
        # command or parsing details because hook output can reach the model.
        return []


def _is_redirection(token: str) -> bool:
    return token in {">", ">>", "<", "<<", "<>", ">&", "<&"} or bool(
        REDIRECTION_RE.match(token)
    )


def _is_protected_secret_target(token: str) -> bool:
    return os.path.basename(token) in PROTECTED_SECRET_BASENAMES


def _contains_protected_python_code(code: str) -> bool:
    # Python snippets can dispatch the vault CLI without exposing it as the
    # shell command. Match the protected executable/module names, not generic
    # prose such as "credentials".
    return bool(
        re.search(
            r"(?<![a-z0-9_])(?:cred(?:[_-]vault)?|secret_resolver|secret_get)"
            r"(?:\.py)?(?![a-z0-9_])",
            code.lower(),
        )
    )


def _command_segments(tokens: Sequence[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SHELL_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _skip_sudo_options(tokens: Sequence[str], index: int) -> int:
    options_with_values = {
        "-C",
        "-g",
        "-h",
        "-p",
        "-r",
        "-t",
        "-u",
        "--chdir",
        "--close-from",
        "--group",
        "--host",
        "--prompt",
        "--role",
        "--type",
        "--user",
    }
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if not token.startswith("-"):
            return index
        index += 1
        if token in options_with_values and index < len(tokens):
            index += 1
    return index


def _skip_env_options(tokens: Sequence[str], index: int) -> int:
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in {"-C", "-S", "-u", "--chdir", "--split-string", "--unset"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if ASSIGNMENT_RE.match(token):
            index += 1
            continue
        return index
    return index


def _skip_simple_wrapper_options(tokens: Sequence[str], index: int) -> int:
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token.startswith("-"):
            index += 1
            continue
        return index
    return index


def _skip_nice_options(tokens: Sequence[str], index: int) -> int:
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in {"-n", "--adjustment"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return index
    return index


def _skip_timeout_options(tokens: Sequence[str], index: int) -> int:
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in {"-k", "-s", "--kill-after", "--signal"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        # The first non-option is the timeout duration.
        return min(index + 1, len(tokens))
    return index


def _skip_xargs_options(tokens: Sequence[str], index: int) -> int:
    options_with_values = {
        "-d",
        "-E",
        "-I",
        "-L",
        "-n",
        "-P",
        "-s",
        "--delimiter",
        "--eof",
        "--max-args",
        "--max-chars",
        "--max-lines",
        "--max-procs",
        "--replace",
    }
    short_options_with_attached_values = ("-d", "-E", "-I", "-L", "-n", "-P", "-s")
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in options_with_values:
            index += 2
            continue
        if any(
            token.startswith(option) and len(token) > len(option)
            for option in short_options_with_attached_values
        ):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return index
    return index


def _python_uses_protected_secret_target(tokens: Sequence[str], index: int) -> bool:
    for nested_index, token in enumerate(tokens[index:], index):
        if _is_protected_secret_target(token):
            return True
        if token == "-c" and nested_index + 1 < len(tokens):
            return _contains_protected_python_code(tokens[nested_index + 1])
    return False


def _shell_uses_protected_secret_target(tokens: Sequence[str], index: int) -> bool:
    for nested_index, token in enumerate(tokens[index:], index):
        if token == "-c" and nested_index + 1 < len(tokens):
            return command_uses_direct_cred(tokens[nested_index + 1])
        if _is_protected_secret_target(token):
            return True
    return False


def _segment_uses_direct_cred(tokens: Sequence[str]) -> bool:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if ASSIGNMENT_RE.match(token) or _is_redirection(token):
            index += 1
            continue
        if token in CONTROL_WORDS:
            index += 1
            continue

        command = os.path.basename(token)
        if _is_protected_secret_target(token):
            return True
        if command in SHELL_COMMANDS:
            return _shell_uses_protected_secret_target(tokens, index + 1)
        if command.startswith("python"):
            return _python_uses_protected_secret_target(tokens, index + 1)
        if command == "env":
            index = _skip_env_options(tokens, index + 1)
            continue
        if command == "sudo":
            index = _skip_sudo_options(tokens, index + 1)
            continue
        if command in {"builtin", "command", "exec", "nohup", "setsid"}:
            index = _skip_simple_wrapper_options(tokens, index + 1)
            continue
        if command == "nice":
            index = _skip_nice_options(tokens, index + 1)
            continue
        if command == "timeout":
            index = _skip_timeout_options(tokens, index + 1)
            continue
        if command == "eval":
            return command_uses_direct_cred(" ".join(tokens[index + 1 :]))
        if command in {".", "source"}:
            return any(
                _is_protected_secret_target(nested_token)
                for nested_token in tokens[index + 1 :]
            )
        if command == "find":
            for nested_index, nested_token in enumerate(tokens[index + 1 :], index + 1):
                if nested_token in {"-exec", "-execdir"} and nested_index + 1 < len(
                    tokens
                ):
                    return _segment_uses_direct_cred(tokens[nested_index + 1 :])
            return False
        if command == "xargs":
            nested_index = _skip_xargs_options(tokens, index + 1)
            return nested_index < len(tokens) and _segment_uses_direct_cred(
                tokens[nested_index:]
            )
        return False
    return False


def command_uses_direct_cred(command: str) -> bool:
    """Return whether a shell command directly executes the local vault CLI."""
    return any(
        _segment_uses_direct_cred(segment)
        for segment in _command_segments(_tokens(command))
    )


def pre_tool_response(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command_uses_direct_cred(command):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_REASON,
        }
    }


def install_pre_tool_hook(codex_home: Path, guard_path: Path) -> Path:
    """Install an optional user-level defense without replacing other hooks."""
    if not guard_path.is_file():
        raise ValueError(f"secret guard is unavailable: {guard_path}")

    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    hooks_path = codex_home / "hooks.json"
    if hooks_path.exists() and hooks_path.is_symlink():
        raise ValueError(
            f"refusing to replace symlinked hook configuration: {hooks_path}"
        )

    if hooks_path.exists():
        with hooks_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("hooks.json must contain a JSON object")

    hooks_by_event = payload.setdefault("hooks", {})
    if not isinstance(hooks_by_event, dict):
        raise ValueError("hooks.json field 'hooks' must contain a JSON object")

    pre_tool_use = hooks_by_event.setdefault("PreToolUse", [])
    if not isinstance(pre_tool_use, list):
        raise ValueError(
            "hooks.json field 'hooks.PreToolUse' must contain a JSON array"
        )

    command = shlex.join((sys.executable, str(guard_path)))
    managed_handler = {
        "type": "command",
        "command": command,
        "timeout": 10,
        "statusMessage": MANAGED_HOOK_STATUS_MESSAGE,
    }
    for group in pre_tool_use:
        if not isinstance(group, dict) or group.get("matcher") != "^Bash$":
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            continue
        for handler in handlers:
            if isinstance(handler, dict) and handler.get("command") == command:
                handler.update(managed_handler)
                break
        else:
            continue
        break
    else:
        pre_tool_use.append({"matcher": "^Bash$", "hooks": [managed_handler]})

    payload.setdefault("description", "Norman TUI lifecycle hooks.")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=hooks_path.parent,
        prefix=f".{hooks_path.name}.",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, hooks_path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return hooks_path


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.is_symlink():
        raise ValueError(f"refusing to use symlinked managed policy: {path}")
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("requirements.toml must contain a TOML table")
    return payload


def _managed_hooks_dir(
    requirements_path: Path, *, default_dir: Path = DEFAULT_MANAGED_HOOKS_DIR
) -> Path:
    payload = _load_toml(requirements_path)
    hooks = payload.get("hooks")
    configured = hooks.get("managed_dir") if isinstance(hooks, dict) else ""
    if configured in (None, ""):
        return default_dir
    if not isinstance(configured, str):
        raise ValueError("requirements hooks.managed_dir must be a string")
    result = Path(configured).expanduser()
    if not result.is_absolute():
        raise ValueError("requirements hooks.managed_dir must be an absolute path")
    return result


def _table_bounds(lines: list[str], table: str) -> tuple[int, int] | None:
    header = f"[{table}]"
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == header),
        None,
    )
    if start is None:
        return None
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("[")
        ),
        len(lines),
    )
    return start, end


def _upsert_table_key(text: str, *, table: str, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    bounds = _table_bounds(lines, table)
    assignment = f"{key} = {value}\n"
    assignment_re = re.compile(rf"^(\s*){re.escape(key)}\s*=")
    if bounds is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend((f"[{table}]\n", assignment))
        return "".join(lines)

    _start, end = bounds
    for index in range(_start + 1, end):
        if assignment_re.match(lines[index]):
            indentation = assignment_re.match(lines[index]).group(1)
            lines[index] = f"{indentation}{assignment}"
            return "".join(lines)
    lines.insert(end, assignment)
    return "".join(lines)


def _upsert_top_level_key(text: str, *, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    assignment = f"{key} = {value}\n"
    assignment_re = re.compile(rf"^(\s*){re.escape(key)}\s*=")
    first_table = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith("[")),
        len(lines),
    )
    for index in range(first_table):
        match = assignment_re.match(lines[index])
        if match:
            lines[index] = f"{match.group(1)}{assignment}"
            return "".join(lines)
    lines.insert(first_table, assignment)
    return "".join(lines)


def _toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return json.dumps(key)


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value).lower()
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{_toml_key(str(key))} = {_toml_literal(item)}"
                for key, item in value.items()
            )
            + "}"
        )
    raise ValueError(f"unsupported TOML rule value type: {type(value).__name__}")


def _managed_prefix_rules_value(prefix_rules: Sequence[dict[str, Any]]) -> str:
    return "[\n" + "".join(f"  {_toml_literal(rule)},\n" for rule in prefix_rules) + "]"


def _array_value_bounds(
    lines: Sequence[str], *, start: int, assignment: str
) -> tuple[int, int]:
    """Return the line range containing a TOML array assignment."""
    opened = False
    square_depth = 0
    curly_depth = 0
    in_basic_string = False
    in_literal_string = False
    escaped = False

    for line_index in range(start, len(lines)):
        line = lines[line_index]
        value = line.split("=", 1)[1] if line_index == start else line
        for character in value:
            if in_basic_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_basic_string = False
                continue
            if in_literal_string:
                if character == "'":
                    in_literal_string = False
                continue
            if character == "#":
                break
            if character == '"':
                in_basic_string = True
                continue
            if character == "'":
                in_literal_string = True
                continue
            if character == "[":
                opened = True
                square_depth += 1
            elif character == "]":
                square_depth -= 1
            elif character == "{":
                curly_depth += 1
            elif character == "}":
                curly_depth -= 1

            if opened and square_depth == 0 and curly_depth == 0:
                return start, line_index

    raise ValueError(f"unable to parse [rules].{assignment} array assignment")


def _prefix_rules_assignment_bounds(text: str) -> tuple[int, int] | None:
    lines = text.splitlines(keepends=True)
    bounds = _table_bounds(lines, "rules")
    if bounds is None:
        return None
    start, end = bounds
    assignment_re = re.compile(r"^\s*prefix_rules\s*=")
    for index in range(start + 1, end):
        if assignment_re.match(lines[index]):
            return _array_value_bounds(lines, start=index, assignment="prefix_rules")
    return None


def _has_managed_direct_vault_rule(payload: dict[str, Any]) -> bool:
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        return False
    prefix_rules = rules.get("prefix_rules")
    if not isinstance(prefix_rules, list):
        return False
    return any(
        rule == MANAGED_DIRECT_VAULT_RULE
        for rule in prefix_rules
        if isinstance(rule, dict)
    )


def _install_managed_direct_vault_rule(content: str, payload: dict[str, Any]) -> str:
    rules = payload.get("rules")
    existing_rules = rules.get("prefix_rules") if isinstance(rules, dict) else []
    if existing_rules is None:
        existing_rules = []
    if not isinstance(existing_rules, list) or not all(
        isinstance(rule, dict) for rule in existing_rules
    ):
        raise ValueError("requirements rules.prefix_rules must be an array of tables")

    prefix_rules = [*existing_rules, MANAGED_DIRECT_VAULT_RULE]
    value = _managed_prefix_rules_value(prefix_rules)
    bounds = _prefix_rules_assignment_bounds(content)
    if bounds is None:
        return _upsert_table_key(
            content,
            table="rules",
            key="prefix_rules",
            value=value,
        )

    lines = content.splitlines(keepends=True)
    start, end = bounds
    lines[start : end + 1] = [f"prefix_rules = {value}\n"]
    return "".join(lines)


def _has_managed_pre_tool_handler(payload: dict[str, Any], *, guard_path: Path) -> bool:
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return False
    pre_tool_use = hooks.get("PreToolUse")
    if not isinstance(pre_tool_use, list):
        return False
    for group in pre_tool_use:
        if not isinstance(group, dict) or group.get("matcher") != "^Bash$":
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            continue
        for handler in handlers:
            if not isinstance(handler, dict):
                continue
            command = handler.get("command")
            if (
                handler.get("type") == "command"
                and isinstance(command, str)
                and str(guard_path) in command
            ):
                return True
    return False


def _managed_pre_tool_handler_toml(guard_path: Path) -> str:
    command = json.dumps(f"python3 {guard_path}")
    status_message = json.dumps(MANAGED_HOOK_STATUS_MESSAGE)
    return (
        "\n[[hooks.PreToolUse]]\n"
        'matcher = "^Bash$"\n'
        "\n[[hooks.PreToolUse.hooks]]\n"
        'type = "command"\n'
        f"command = {command}\n"
        "timeout = 10\n"
        f"statusMessage = {status_message}\n"
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        if path.exists():
            os.chmod(temporary_name, path.stat().st_mode & 0o777)
        else:
            os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def install_managed_policy(requirements_path: Path, guard_path: Path) -> Path:
    """Install the enforced hook while preserving unrelated requirements."""
    if not guard_path.is_file():
        raise ValueError(f"managed secret guard is unavailable: {guard_path}")
    if not guard_path.is_absolute():
        raise ValueError("managed secret guard path must be absolute")

    payload = _load_toml(requirements_path)
    hooks = payload.get("hooks")
    configured_dir = hooks.get("managed_dir") if isinstance(hooks, dict) else None
    if configured_dir not in (None, ""):
        if not isinstance(configured_dir, str):
            raise ValueError("requirements hooks.managed_dir must be a string")
        if Path(configured_dir).expanduser() != guard_path.parent:
            raise ValueError(
                "managed secret guard must be installed in the existing "
                "requirements hooks.managed_dir"
            )

    content = (
        requirements_path.read_text(encoding="utf-8")
        if requirements_path.exists()
        else ""
    )
    content = _upsert_table_key(
        content,
        table="features",
        key="hooks",
        value="true",
    )
    content = _upsert_top_level_key(
        content,
        key=MANAGED_HOOKS_ONLY_KEY,
        value="true",
    )
    if configured_dir in (None, ""):
        content = _upsert_table_key(
            content,
            table="hooks",
            key="managed_dir",
            value=json.dumps(str(guard_path.parent)),
        )

    candidate = tomllib.loads(content)
    if not _has_managed_pre_tool_handler(candidate, guard_path=guard_path):
        content += _managed_pre_tool_handler_toml(guard_path)

    candidate = tomllib.loads(content)
    if not _has_managed_direct_vault_rule(candidate):
        content = _install_managed_direct_vault_rule(content, candidate)

    # Parse before replacing the current policy so an unsupported shape never
    # leaves a broken system requirements file behind.
    tomllib.loads(content)
    _atomic_write(requirements_path, content)
    return requirements_path


def verify_managed_policy(requirements_path: Path, guard_path: Path) -> None:
    """Raise ValueError unless the system policy enforces this guard."""
    if not requirements_path.is_file() or requirements_path.is_symlink():
        raise ValueError("managed Codex requirements policy is not installed")
    if not guard_path.is_file() or guard_path.is_symlink():
        raise ValueError("managed Norman TUI secret guard is not installed")

    payload = _load_toml(requirements_path)
    if payload.get(MANAGED_HOOKS_ONLY_KEY) is not True:
        raise ValueError(
            "managed Codex policy does not restrict hooks to managed hooks"
        )

    features = payload.get("features")
    if not isinstance(features, dict) or features.get("hooks") is not True:
        raise ValueError("managed Codex policy does not require hooks")

    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        raise ValueError("managed Codex policy does not configure hooks")
    if Path(str(hooks.get("managed_dir") or "")).expanduser() != guard_path.parent:
        raise ValueError("managed Codex hook directory does not contain the guard")
    if not _has_managed_pre_tool_handler(payload, guard_path=guard_path):
        raise ValueError("managed Codex policy does not run the Norman secret guard")
    if not _has_managed_direct_vault_rule(payload):
        raise ValueError("managed Codex policy does not forbid direct vault commands")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or run the Norman Codex credential guard."
    )
    parser.add_argument(
        "--install-hooks",
        metavar="CODEX_HOME",
        type=Path,
        help="install the managed PreToolUse guard in this Codex home",
    )
    parser.add_argument(
        "--install-managed-policy",
        action="store_true",
        help="install the managed system requirements policy for this guard",
    )
    parser.add_argument(
        "--verify-managed-policy",
        action="store_true",
        help="verify the managed system requirements policy for this guard",
    )
    parser.add_argument(
        "--requirements-path",
        type=Path,
        default=DEFAULT_REQUIREMENTS_PATH,
        help="managed Codex requirements.toml path",
    )
    parser.add_argument(
        "--managed-guard-path",
        type=Path,
        default=DEFAULT_MANAGED_HOOKS_DIR / MANAGED_GUARD_FILENAME,
        help="installed managed secret guard path",
    )
    parser.add_argument(
        "--print-managed-hooks-dir",
        action="store_true",
        help="print the managed hook directory configured by requirements",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.install_hooks:
        try:
            install_pre_tool_hook(
                args.install_hooks.expanduser(), Path(__file__).resolve()
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Unable to install Norman TUI secret guard: {exc}", file=sys.stderr)
            return 1
        return 0
    requirements_path = args.requirements_path.expanduser()
    managed_guard_path = args.managed_guard_path.expanduser()
    if args.print_managed_hooks_dir:
        try:
            print(_managed_hooks_dir(requirements_path))
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            print(f"Unable to read managed Codex policy: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.install_managed_policy:
        try:
            install_managed_policy(requirements_path, managed_guard_path)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            print(f"Unable to install managed Codex policy: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.verify_managed_policy:
        try:
            verify_managed_policy(requirements_path, managed_guard_path)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            print(f"Norman TUI secret guard is not enforced: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    response = pre_tool_response(payload)
    if response is not None:
        print(json.dumps(response, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
