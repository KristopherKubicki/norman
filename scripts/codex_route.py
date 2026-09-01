#!/usr/bin/env python3
"""Route local Codex sessions through the checkout's TUI Responses gateway."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib


HOME = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
GATEWAY_TOKEN_HELPER = SCRIPT_DIR / "norman_codex_gateway_token.py"
SECRET_GUARD = SCRIPT_DIR / "norman_codex_secret_guard.py"
MANAGED_CODEX_REQUIREMENTS = Path("/etc/codex/requirements.toml")
MANAGED_SECRET_GUARD = Path(
    "/usr/local/lib/norman-codex-route/norman_codex_secret_guard.py"
)
OPS_OPENBRAND_MCP_LAUNCHER = (
    HOME / "code" / "control_plane" / "scripts" / "with_ops_openbrand_mcp.sh"
)
OPS_OPENBRAND_MCP_CONFIG_BEGIN = "# BEGIN NORMAN OPS OPENBRAND MCP"
OPS_OPENBRAND_MCP_CONFIG_END = "# END NORMAN OPS OPENBRAND MCP"
OPS_OPENBRAND_MCP_URL = "https://ops.openbrand.com/mcp"
OPS_OPENBRAND_MCP_TOKEN_ENV = "OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY"
OPS_OPENBRAND_MCP_STARTUP_TIMEOUT_SECONDS = 20
OPS_OPENBRAND_MCP_TOOL_TIMEOUT_SECONDS = 60
WORK_SKILLS_SOURCE_ROOT = HOME / ".codex-work" / "skills"
PERSONAL_SKILLS_SOURCE_ROOT = HOME / ".codex-personal" / "skills"
ROUTE_SKILL_SCOPE_BY_GROUP = {
    "norman": "personal",
    "personal": "personal",
    "private": "personal",
    "work": "work",
}
LOCAL_BIN = HOME / ".local" / "bin"
LOCAL_CODEX_WRAPPER = LOCAL_BIN / "codex"
LOCAL_CODEX_WORK_WRAPPER = LOCAL_BIN / "codex-work"
ROUTER_PROFILE_PREFIX = "router-"
QWEN_LOCAL_ROUTER_MODEL = "norman-code-qwen-local"
LUNA_ROUTER_MODEL = "norman-code-luna"
TERRA_ROUTER_MODEL = "norman-code-terra"
SOL_ROUTER_MODEL = "norman-code-sol"
DEFAULT_ROUTER_MODEL = LUNA_ROUTER_MODEL
GOVERNED_ROUTER_MODEL = "norman-code-governed"
LEGACY_ROUTER_MODEL = "norman-code"
ROUTER_MODELS = frozenset(
    {
        QWEN_LOCAL_ROUTER_MODEL,
        LUNA_ROUTER_MODEL,
        TERRA_ROUTER_MODEL,
        SOL_ROUTER_MODEL,
        LEGACY_ROUTER_MODEL,
        GOVERNED_ROUTER_MODEL,
    }
)
MODEL_CATALOG_CONTRACT_VERSION = "2026-08-tiered-code-router-v1"
REQUIRED_CODEX_MODEL_CAPABILITIES = {
    "shell_type": "shell_command",
    "apply_patch_tool_type": "freeform",
    "supports_parallel_tool_calls": True,
}
STATE_DIR = (
    Path(value).expanduser()
    if (value := os.environ.get("NORMAN_CODEX_STATE_DIR", "").strip())
    else None
)
USAGE_HISTORY_PATH = (
    Path(value).expanduser()
    if (value := os.environ.get("NORMAN_CODEX_USAGE_PATH", "").strip())
    else None
)
USAGE_LEDGER_PATH = (
    Path(value).expanduser()
    if (value := os.environ.get("NORMAN_CODEX_USAGE_LEDGER_PATH", "").strip())
    else None
)
CODEX_ACCOUNT_CAPACITY_PATH = (
    Path(value).expanduser()
    if (value := os.environ.get("NORMAN_CODEX_ACCOUNT_CAPACITY_PATH", "").strip())
    else None
)
USAGE_STATE_READ_LIMIT_BYTES = 2 * 1024 * 1024
ACCOUNT_CAPACITY_FRESH_SECONDS = max(
    60,
    int(os.environ.get("NORMAN_CODEX_ACCOUNT_CAPACITY_FRESH_SECONDS", "1800")),
)
GATEWAY_REQUEST_TIMEOUT_SECONDS = 20
PLAN_LEDGER_KIND = "chatgpt_codex_credit_estimate"
METERED_LEDGER_KINDS = frozenset(
    {"api_rate_card_estimate", "provider_invoice_estimate"}
)
ROUTED_TUI_SECRET_POLICY = """# Norman TUI Secret Policy

- Treat read-only analysis, review, status checks, and recommendations as non-credentialed work. Do not access a secret unless a credentialed action is necessary.
- Do not inspect or probe `NORMAN_KEYS_URL`, `NORMAN_SECRET_CMD`, or any other secret configuration for read-only work, even when a document mentions protected systems or credentials.
- Raw secret retrieval is unavailable in an agent terminal. Never manually invoke a secret broker, capture its output, or pass a broker command through another shell or remote command.
- Before a credentialed action, explain the required capability and logical alias. Use only a task-specific approved executor or an injected tool; if neither is available, report the action blocked with the logical alias or capability needed.
- Do not directly invoke `cred`, even for reads. Never run `cred init`, bootstrap, migration, rotation, or put/set/remove/rm operations.
- Never create or migrate a vault, and never ask for, accept, or enter a vault passphrase.
"""
ROUTED_TUI_POLICY_BEGIN = "<!-- BEGIN NORMAN TUI SECRET POLICY -->"
ROUTED_TUI_POLICY_END = "<!-- END NORMAN TUI SECRET POLICY -->"
MODEL_HIDDEN_SECRET_ENVIRONMENT_KEYS = frozenset(
    {
        "CREDENTIALS_DIRECTORY",
        "NORMAN_CONFIG_SECRET_CMD",
        "NORMAN_CRED_BIN",
        "NORMAN_KEYS_API_BASE",
        "NORMAN_KEYS_API_TOKEN",
        "NORMAN_KEYS_TOKEN",
        "NORMAN_KEYS_URL",
        "NORMAN_NETWORKING_KEYS_URL",
        "NORMAN_NETWORKING_SECRET_BROKER_HOST",
        "NORMAN_SECRET_CMD",
    }
)
PROTECTED_HOOK_CONFIG_KEYS = frozenset(
    {
        "allow_managed_hooks_only",
        "features.hooks",
        "features.codex_hooks",
        "hooks",
        "rules",
    }
)


@dataclass(frozen=True)
class Route:
    key: str
    group: str
    launcher: str
    endpoint: str
    codex_home: str
    repo_names: tuple[str, ...]
    root_paths: tuple[str, ...] = ()
    token_secret: str = ""

    @property
    def profile(self) -> str:
        return f"{ROUTER_PROFILE_PREFIX}{self.key}"

    @property
    def provider(self) -> str:
        return f"router_{self.key.replace('-', '_')}"

    @property
    def resolved_token_secret(self) -> str:
        return self.token_secret or f"{self.key}/prompt-proxy-token"


ROUTES: tuple[Route, ...] = (
    Route(
        key="autocamera",
        group="personal",
        launcher="regular",
        endpoint="https://autocamera.home.arpa/v1",
        codex_home="~/.codex-autocamera",
        repo_names=("autocamera",),
    ),
    Route(
        key="cloudagent",
        group="shared",
        launcher="regular",
        endpoint="https://cloudagent.home.arpa/v1",
        codex_home="~/.codex-cloudagent",
        repo_names=("cloudagent",),
        root_paths=("/home/kristopher/code/cloudagent", "/data/code/cloudagent"),
    ),
    Route(
        key="compere",
        group="work",
        launcher="work",
        endpoint="https://keystone.kris.openbrand.com/v1",
        codex_home="~/.codex-compere",
        repo_names=("compere",),
    ),
    Route(
        key="control-plane",
        group="work",
        launcher="work",
        endpoint="https://cp.kris.openbrand.com/v1",
        codex_home="~/.codex-cp",
        repo_names=("control-plane", "control_plane"),
    ),
    Route(
        key="earlybird",
        group="work",
        launcher="work",
        endpoint="https://earlybird.kris.openbrand.com/v1",
        codex_home="~/.codex-earlybird",
        repo_names=("earlybird",),
    ),
    Route(
        key="glimpser",
        group="personal",
        launcher="regular",
        endpoint="https://eyebat.home.arpa/v1",
        codex_home="~/.codex-glimpser",
        repo_names=("glimpser",),
    ),
    Route(
        key="gold-book",
        group="work",
        launcher="work",
        endpoint="https://goldbook.kris.openbrand.com/v1",
        codex_home="~/.codex-gold-book",
        repo_names=("gold-book", "gold_book"),
        root_paths=("/home/kristopher/code/gold_book", "/data/code/gold_book"),
    ),
    Route(
        key="housebot",
        group="personal",
        launcher="regular",
        endpoint="https://housebot.home.arpa/v1",
        codex_home="~/.codex-housebot",
        repo_names=("housebot",),
        root_paths=("/home/kristopher/code/housebot",),
    ),
    Route(
        key="infra",
        group="work",
        launcher="work",
        endpoint="https://infra.kris.openbrand.com/v1",
        codex_home="~/.codex-infra",
        repo_names=("infra",),
    ),
    Route(
        key="market-sizing",
        group="work",
        launcher="work",
        endpoint="https://market.kris.openbrand.com/v1",
        codex_home="~/.codex-market-sizing",
        repo_names=("market-sizing", "market_sizing"),
    ),
    Route(
        key="networking",
        group="shared",
        launcher="regular",
        endpoint="https://networking.home.arpa/v1",
        codex_home="~/.codex-networking",
        repo_names=("networking",),
        root_paths=("/home/kristopher/code/networking",),
    ),
    Route(
        key="norman",
        group="norman",
        launcher="regular",
        endpoint="https://norman.home.arpa/v1",
        codex_home="~/.codex-norman",
        repo_names=("norman",),
        token_secret="norman/prompt-proxy-token",
    ),
    Route(
        key="parkergale",
        group="private",
        launcher="regular",
        endpoint="https://pefb.home.arpa/v1",
        codex_home="~/.codex-parkergale",
        repo_names=("parkergale", "pefb"),
    ),
    Route(
        key="theseus",
        group="personal",
        launcher="regular",
        endpoint="https://theseus.home.arpa/v1",
        codex_home="~/.codex-theseus",
        repo_names=("theseus",),
    ),
    Route(
        key="tmi-dashboards",
        group="work",
        launcher="work",
        endpoint="https://dashboards.kris.openbrand.com/v1",
        codex_home="~/.codex-tmi-dashboards",
        repo_names=("tmi-dashboards", "tmi_dashboards"),
    ),
)

MANAGEMENT_COMMANDS = frozenset(
    {
        "apply",
        "archive",
        "cloud",
        "completion",
        "config",
        "debug",
        "delete",
        "doctor",
        "exec-server",
        "features",
        "help",
        "login",
        "logout",
        "mcp",
        "mcp-server",
        "plugin",
        "remote-control",
        "sandbox",
        "unarchive",
        "update",
        "version",
    }
)
NON_SESSION_FLAGS = frozenset({"--help", "--version", "-V", "-h"})
OPTIONS_WITH_VALUE = frozenset(
    {
        "--add-dir",
        "--config",
        "--cd",
        "--color",
        "--model",
        "--profile",
        "--profile-v2",
        "-C",
        "-c",
        "-m",
        "-p",
    }
)


def normalize_name(value: str) -> str:
    clean = value.strip().lower().removesuffix(".git")
    clean = re.sub(r"[^a-z0-9]+", "-", clean)
    return clean.strip("-")


def _run_git(cwd: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def checkout_identity(cwd: Path) -> tuple[Path, str]:
    """Return the Git checkout root and canonical origin repository name."""
    requested_cwd = cwd.expanduser().resolve()
    root_value = _run_git(requested_cwd, "rev-parse", "--show-toplevel")
    root = Path(root_value).resolve() if root_value else requested_cwd
    origin = _run_git(root, "remote", "get-url", "origin")
    if not origin:
        return root, ""
    candidate = origin.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return root, normalize_name(candidate)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_route(cwd: Path) -> Route | None:
    """Resolve a route by Git origin first, then by canonical checkout path."""
    root, origin_name = checkout_identity(cwd)
    for route in ROUTES:
        names = {normalize_name(name) for name in route.repo_names}
        if origin_name and origin_name in names:
            return route
        if normalize_name(root.name) in names:
            return route
    for route in ROUTES:
        for configured_path in route.root_paths:
            if _is_within(root, Path(configured_path).expanduser().resolve()):
                return route
    return None


def _value_after(arguments: Sequence[str], index: int) -> str:
    return arguments[index + 1] if index + 1 < len(arguments) else ""


def has_explicit_profile(arguments: Sequence[str]) -> bool:
    return bool(explicit_profiles(arguments))


def explicit_profiles(arguments: Sequence[str]) -> list[str]:
    profiles: list[str] = []
    for index, argument in enumerate(arguments):
        if argument in {"--profile", "--profile-v2", "-p"}:
            value = _value_after(arguments, index)
            if value:
                profiles.append(value)
        elif argument.startswith(("--profile=", "--profile-v2=")):
            value = argument.split("=", 1)[1]
            if value:
                profiles.append(value)
        if argument.startswith("-p") and len(argument) > 2:
            profiles.append(argument[2:])
    return profiles


def explicit_models(arguments: Sequence[str]) -> list[str]:
    models: list[str] = []
    for index, argument in enumerate(arguments):
        if argument in {"--model", "-m"}:
            value = _value_after(arguments, index)
            if value:
                models.append(value)
        elif argument.startswith("--model="):
            value = argument.split("=", 1)[1]
            if value:
                models.append(value)
        elif argument.startswith("-m") and len(argument) > 2:
            models.append(argument[2:])
    return models


def has_explicit_model(arguments: Sequence[str]) -> bool:
    return bool(explicit_models(arguments))


def config_overrides(arguments: Sequence[str]) -> list[str]:
    overrides: list[str] = []
    for index, argument in enumerate(arguments):
        if argument in {"--config", "-c"}:
            value = _value_after(arguments, index)
            if value:
                overrides.append(value)
        elif argument.startswith("--config="):
            overrides.append(argument.split("=", 1)[1])
        elif argument.startswith("-c") and len(argument) > 2:
            overrides.append(argument[2:])
    return overrides


def config_key(override: str) -> str:
    return override.split("=", 1)[0].strip().replace("-", "_").lower()


def route_arguments_error(route: Route, arguments: Sequence[str]) -> str:
    profiles = explicit_profiles(arguments)
    if any(profile != route.profile for profile in profiles):
        return (
            f"{route.key} must use the {route.profile!r} gateway profile; "
            "a different Codex profile could bypass its TUI route."
        )

    if any(model not in ROUTER_MODELS for model in explicit_models(arguments)):
        return (
            f"{route.key} only supports Norman's Qwen Local, Luna, Terra, or "
            "Sol coding models; choose one from the TUI model selector."
        )

    routed_keys = {
        "auth",
        "base_url",
        "model",
        "model_catalog_json",
        "model_provider",
        "provider",
        "wire_api",
    }
    protected_keys = {"developer_instructions"} | PROTECTED_HOOK_CONFIG_KEYS
    for override in config_overrides(arguments):
        key = config_key(override)
        if key in routed_keys or key.startswith("model_providers."):
            return (
                f"{route.key} does not allow --config to override {key!r}; "
                "that would bypass its TUI route."
            )
        if key in protected_keys:
            return (
                f"{route.key} does not allow --config to override {key!r}; "
                "that would weaken its required Norman TUI secret guard."
            )
    return ""


def secret_guard_arguments_error(arguments: Sequence[str]) -> str:
    """Reject session overrides that could suppress the mandatory hook."""
    for override in config_overrides(arguments):
        key = config_key(override)
        if (
            key in PROTECTED_HOOK_CONFIG_KEYS
            or key.startswith("features.hooks.")
            or key.startswith("features.codex_hooks.")
            or key.startswith("hooks.")
            or key.startswith("rules.")
        ):
            return (
                f"Codex does not allow --config to override {key!r}; "
                "that would weaken its required Norman TUI secret guard."
            )
    return ""


def codex_cwd(arguments: Sequence[str]) -> Path:
    for index, argument in enumerate(arguments):
        if argument in {"-C", "--cd"}:
            value = _value_after(arguments, index)
            if value:
                return Path(value)
        if argument.startswith("--cd="):
            return Path(argument.split("=", 1)[1])
    return Path.cwd()


def command_name(arguments: Sequence[str]) -> str:
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
            continue
        if argument in OPTIONS_WITH_VALUE:
            skip_next = True
            continue
        if argument.startswith("-"):
            continue
        return argument
    return ""


def starts_session(arguments: Sequence[str]) -> bool:
    if any(argument in NON_SESSION_FLAGS for argument in arguments):
        return False
    command = command_name(arguments)
    return not command or command not in MANAGEMENT_COMMANDS


def uses_route_scoped_management_command(
    route: Route, arguments: Sequence[str]
) -> bool:
    """Keep the work Ops MCP visible to `codex mcp` without routing login/help."""
    return route.launcher == "work" and command_name(arguments) == "mcp"


def route_home(route: Route) -> Path:
    return Path(route.codex_home).expanduser()


def profile_path(route: Route) -> Path:
    return route_home(route) / f"{route.profile}.config.toml"


def route_config_path(route: Route) -> Path:
    return route_home(route) / "config.toml"


def route_skill_scope(route: Route) -> str | None:
    """Return the managed skill scope available to a routed Codex home."""
    return ROUTE_SKILL_SCOPE_BY_GROUP.get(route.group)


def scoped_skill_source_root(scope: str | None) -> Path | None:
    if scope == "work":
        return WORK_SKILLS_SOURCE_ROOT
    if scope == "personal":
        return PERSONAL_SKILLS_SOURCE_ROOT
    return None


def managed_skill_source_roots() -> tuple[Path, ...]:
    return (WORK_SKILLS_SOURCE_ROOT, PERSONAL_SKILLS_SOURCE_ROOT)


def _resolved_path(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return None


def _is_within(path: Path, root: Path) -> bool:
    resolved_path = _resolved_path(path)
    resolved_root = _resolved_path(root)
    if resolved_path is None or resolved_root is None:
        return False
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return False
    return True


def _managed_skill_link(path: Path) -> bool:
    return path.is_symlink() and any(
        _is_within(path, source_root) for source_root in managed_skill_source_roots()
    )


def _skill_source_entries(source_root: Path) -> dict[str, Path]:
    try:
        entries = list(source_root.iterdir())
    except FileNotFoundError:
        return {}
    except OSError as exc:
        print(
            f"codex-route: unable to inspect managed skills at {source_root}: {exc}; "
            "continuing without a skill sync.",
            file=sys.stderr,
        )
        return {}

    return {
        entry.name: entry
        for entry in sorted(entries, key=lambda candidate: candidate.name)
        if entry.is_dir() and (entry / "SKILL.md").is_file()
    }


def _same_skill_target(link: Path, source: Path) -> bool:
    resolved_link = _resolved_path(link)
    resolved_source = _resolved_path(source)
    return resolved_link is not None and resolved_link == resolved_source


def sync_scoped_skills(route: Route) -> None:
    """Expose only the route's managed skills through its isolated CODEX_HOME.

    Individual skill-directory symlinks keep work and personal sources canonical
    while preserving Codex's built-in `.system` directory and any unmanaged
    user-owned skill entries in an individual route home.
    """

    source_root = scoped_skill_source_root(route_skill_scope(route))
    skill_home = route_home(route) / "skills"
    try:
        skill_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"codex-route: unable to prepare skills for {route.key}: {exc}; "
            "continuing without a skill sync.",
            file=sys.stderr,
        )
        return

    source_entries = _skill_source_entries(source_root) if source_root else {}

    try:
        destination_entries = list(skill_home.iterdir())
    except OSError as exc:
        print(
            f"codex-route: unable to inspect skills for {route.key}: {exc}; "
            "continuing without a skill sync.",
            file=sys.stderr,
        )
        return

    for destination in destination_entries:
        if not _managed_skill_link(destination):
            continue
        source = source_entries.get(destination.name)
        if source is not None and _same_skill_target(destination, source):
            continue
        try:
            destination.unlink()
        except OSError as exc:
            print(
                f"codex-route: unable to remove stale managed skill "
                f"{destination} for {route.key}: {exc}; continuing.",
                file=sys.stderr,
            )

    for name, source in source_entries.items():
        destination = skill_home / name
        if destination.is_symlink() and _same_skill_target(destination, source):
            continue
        if destination.exists() or destination.is_symlink():
            print(
                f"codex-route: skill conflict for {route.key}: leaving "
                f"{destination} untouched instead of linking managed skill {name}.",
                file=sys.stderr,
            )
            continue
        try:
            destination.symlink_to(source, target_is_directory=True)
        except OSError as exc:
            print(
                f"codex-route: unable to link managed skill {name} for "
                f"{route.key}: {exc}; continuing.",
                file=sys.stderr,
            )


def models_cache_path(route: Route) -> Path:
    return route_home(route) / "models_cache.json"


def routed_model_catalog_path(route: Route) -> Path:
    return route_home(route) / "router-model-catalog.json"


def _routed_model_catalog_entry(
    *,
    slug: str,
    display_name: str,
    description: str,
    priority: int,
    include_skills: bool = True,
    include_plugins: bool = True,
) -> dict[str, object]:
    return {
        "slug": slug,
        "display_name": display_name,
        "description": description,
        "default_reasoning_level": "high",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Low reasoning effort."},
            {"effort": "medium", "description": "Standard reasoning effort."},
            {"effort": "high", "description": "High reasoning effort."},
        ],
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        # Codex 0.146 requires this field even when no base instructions apply.
        "base_instructions": "",
        "priority": priority,
        "additional_speed_tiers": [],
        "service_tiers": [],
        "availability_nux": None,
        "upgrade": None,
        "model_messages": {
            "instructions_template": "",
            "instructions_variables": None,
            "approvals": None,
            "collaboration_modes": None,
            "auto_review": None,
            "permissions": None,
        },
        "include_skills_usage_instructions": include_skills,
        "include_plugin_usage_instructions": include_plugins,
        "include_apps_usage_instructions": True,
        "default_reasoning_summary": "auto",
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text",
        "truncation_policy": {"mode": "bytes", "limit": 128000},
        "supports_parallel_tool_calls": True,
        "supports_image_detail_original": False,
        "context_window": 128000,
        "effective_context_window_percent": 95,
        "experimental_supported_tools": [],
        # The Responses facade currently normalizes text content only. Do not
        # advertise image input until it can safely forward image data.
        "input_modalities": ["text"],
        "supports_search_tool": False,
        "use_responses_lite": False,
    }


def routed_model_catalog() -> dict[str, object]:
    """Return the explicit local and cloud coding tiers shown by Codex."""
    return {
        "models": [
            _routed_model_catalog_entry(
                slug=QWEN_LOCAL_ROUTER_MODEL,
                display_name="Norman Code — Qwen Local",
                description=("Local Qwen coding lane with no cloud model invocation."),
                priority=1,
                include_skills=False,
                include_plugins=False,
            ),
            _routed_model_catalog_entry(
                slug=LUNA_ROUTER_MODEL,
                display_name="Norman Code — Luna",
                description=(
                    "Economical cloud coding lane with Qwen preflight and checking."
                ),
                priority=2,
                include_skills=False,
                include_plugins=False,
            ),
            _routed_model_catalog_entry(
                slug=TERRA_ROUTER_MODEL,
                display_name="Norman Code — Terra",
                description=(
                    "Balanced intelligence lane with Qwen preflight and checking."
                ),
                priority=3,
            ),
            _routed_model_catalog_entry(
                slug=SOL_ROUTER_MODEL,
                display_name="Norman Code — Sol",
                description=(
                    "Explicit flagship lane with Qwen preflight and checking; "
                    "never selected as an automatic fallback."
                ),
                priority=4,
            ),
        ]
    }


def write_routed_model_catalog(route: Route) -> Path:
    path = routed_model_catalog_path(route)
    contents = json.dumps(routed_model_catalog(), indent=2, sort_keys=True) + "\n"
    _write_private_text(path, contents)
    return path


def model_catalog_contract_stamp_path(route: Route) -> Path:
    return route_home(route) / ".router-model-catalog-contract"


def _model_catalog_contract_stamp(route: Route) -> str:
    return json.dumps(
        {
            "endpoint": route.endpoint,
            "model": DEFAULT_ROUTER_MODEL,
            "version": MODEL_CATALOG_CONTRACT_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_private_text(path: Path, contents: str) -> None:
    """Atomically replace a route-local file without exposing its contents."""
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(contents)
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def refresh_model_catalog_cache(route: Route) -> bool:
    """Discard stale Codex model metadata after the contract changes.

    Codex caches gateway model capabilities under each route home. A stale
    cache can cause it to omit local tools even after the gateway has been
    fixed, so invalidate it once per managed contract version. Existing chats
    retain their in-memory configuration and are not restarted.
    """

    stamp_path = model_catalog_contract_stamp_path(route)
    expected_stamp = _model_catalog_contract_stamp(route)
    try:
        current_stamp = stamp_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        current_stamp = ""
    except OSError as exc:
        raise RuntimeError(
            f"Unable to read the Codex model-catalog stamp at {stamp_path}."
        ) from exc
    if current_stamp == expected_stamp:
        return False

    cache_path = models_cache_path(route)
    if cache_path.exists():
        timestamp = int(time.time())
        backup_path = cache_path.with_name(f"{cache_path.name}.stale-{timestamp}")
        suffix = 1
        while backup_path.exists():
            backup_path = cache_path.with_name(
                f"{cache_path.name}.stale-{timestamp}-{suffix}"
            )
            suffix += 1
        try:
            cache_path.replace(backup_path)
        except OSError as exc:
            raise RuntimeError(
                f"Unable to refresh stale Codex model metadata at {cache_path}."
            ) from exc
    _write_private_text(stamp_path, f"{expected_stamp}\n")
    return True


def write_work_fallback_model_contract(home: Path | None = None) -> Path:
    """Refresh the generic codex-work selector without replacing its profile."""

    work_home = (
        home
        or Path(os.getenv("CODEX_WORK_HOME", str(HOME / ".codex-work"))).expanduser()
    )
    work_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    catalog_path = work_home / "router-model-catalog.json"
    _write_private_text(
        catalog_path,
        json.dumps(routed_model_catalog(), indent=2, sort_keys=True) + "\n",
    )
    profile_path = work_home / "work.config.toml"
    if not profile_path.is_file():
        return catalog_path
    contents = profile_path.read_text(encoding="utf-8")
    if not re.search(r'(?m)^model_provider\s*=\s*"norman"\s*$', contents):
        return catalog_path
    contents, model_count = re.subn(
        r'(?m)^model\s*=\s*"[^"]*"\s*$',
        f'model = "{DEFAULT_ROUTER_MODEL}"',
        contents,
        count=1,
    )
    if model_count != 1:
        raise RuntimeError("Managed codex-work profile is missing its model field.")
    catalog_line = f"model_catalog_json = {json.dumps(str(catalog_path))}"
    contents, catalog_count = re.subn(
        r"(?m)^model_catalog_json\s*=.*$", catalog_line, contents, count=1
    )
    if catalog_count == 0:
        contents = contents.replace(
            f'model = "{DEFAULT_ROUTER_MODEL}"',
            f'model = "{DEFAULT_ROUTER_MODEL}"\n{catalog_line}',
            1,
        )
    _write_private_text(profile_path, contents)
    return catalog_path


def write_routed_tui_secret_policy(home: Path) -> Path:
    """Install managed secret rules without discarding route-local instructions."""
    path = home / "AGENTS.md"
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError as exc:
        raise RuntimeError(
            f"Unable to read route-local instructions at {path}."
        ) from exc

    managed = (
        f"{ROUTED_TUI_POLICY_BEGIN}\n{ROUTED_TUI_SECRET_POLICY}"
        f"{ROUTED_TUI_POLICY_END}\n"
    )
    start = existing.find(ROUTED_TUI_POLICY_BEGIN)
    end = existing.find(ROUTED_TUI_POLICY_END, start + len(ROUTED_TUI_POLICY_BEGIN))
    if start >= 0 and end >= 0:
        end += len(ROUTED_TUI_POLICY_END)
        contents = f"{existing[:start]}{managed}{existing[end:]}"
    elif existing.strip():
        contents = f"{existing.rstrip()}\n\n{managed}"
    else:
        contents = managed
    _write_private_text(path, contents)
    return path


def is_ops_openbrand_work_route(route: Route) -> bool:
    # `codex-work` is itself the work-identity boundary. Repository aliases are
    # optional, so an unregistered checkout (for example d.ace) must retain the
    # same subject-bound read-only Ops connector as named work routes.
    return route.launcher == "work"


def ops_openbrand_mcp_config_block() -> str:
    return "\n".join(
        (
            OPS_OPENBRAND_MCP_CONFIG_BEGIN,
            "[mcp_servers.ops_openbrand]",
            f"url = {json.dumps(OPS_OPENBRAND_MCP_URL)}",
            f"bearer_token_env_var = {json.dumps(OPS_OPENBRAND_MCP_TOKEN_ENV)}",
            f"startup_timeout_sec = {OPS_OPENBRAND_MCP_STARTUP_TIMEOUT_SECONDS}",
            f"tool_timeout_sec = {OPS_OPENBRAND_MCP_TOOL_TIMEOUT_SECONDS}",
            'default_tools_approval_mode = "approve"',
            OPS_OPENBRAND_MCP_CONFIG_END,
            "",
        )
    )


def _table_end(contents: str, start: int) -> int:
    next_table = re.search(
        r"(?m)^[ \t]*\[(?!\[)[^\]\n]+\][^\n]*(?:\n|$)", contents[start:]
    )
    return start + next_table.start() if next_table else len(contents)


def _existing_ops_openbrand_mcp_span(contents: str) -> tuple[int, int] | None:
    managed_start = contents.find(OPS_OPENBRAND_MCP_CONFIG_BEGIN)
    if managed_start >= 0:
        managed_end = contents.find(
            OPS_OPENBRAND_MCP_CONFIG_END,
            managed_start + len(OPS_OPENBRAND_MCP_CONFIG_BEGIN),
        )
        if managed_end < 0:
            raise RuntimeError(
                "The managed Ops MCP configuration block is incomplete in "
                "the route Codex config."
            )
        managed_end += len(OPS_OPENBRAND_MCP_CONFIG_END)
        while managed_end < len(contents) and contents[managed_end] in "\r\n":
            managed_end += 1
        return managed_start, managed_end

    header = re.search(
        r"(?m)^[ \t]*\[\s*mcp_servers\.(?:ops_openbrand|"
        r'"ops_openbrand"|\'ops_openbrand\')\s*\][^\n]*(?:\n|$)',
        contents,
    )
    if header is None:
        return None
    return header.start(), _table_end(contents, header.end())


def write_ops_openbrand_mcp_config(route: Route) -> Path | None:
    """Ensure work routes register the bound read-only Ops MCP server."""
    if not is_ops_openbrand_work_route(route):
        return None

    path = route_config_path(route)
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError as exc:
        raise RuntimeError(f"Unable to read route Codex config at {path}.") from exc

    block = ops_openbrand_mcp_config_block()
    existing_span = _existing_ops_openbrand_mcp_span(existing)
    if existing_span is not None:
        start, end = existing_span
        contents = f"{existing[:start]}{block}{existing[end:]}"
    elif existing.strip():
        contents = f"{existing.rstrip()}\n\n{block}"
    else:
        contents = block

    try:
        tomllib.loads(contents)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(
            f"Unable to safely install the Ops MCP configuration in {path}: "
            f"invalid TOML ({exc})."
        ) from exc
    _write_private_text(path, contents)
    return path


def write_gateway_profile(route: Route) -> Path:
    """Create/refresh a profile without ever storing a bearer token."""
    if not GATEWAY_TOKEN_HELPER.is_file() or not os.access(
        GATEWAY_TOKEN_HELPER, os.X_OK
    ):
        raise RuntimeError(
            f"Gateway token helper is unavailable at {GATEWAY_TOKEN_HELPER}."
        )
    home = route_home(route)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_routed_tui_secret_policy(home)
    sync_scoped_skills(route)
    write_ops_openbrand_mcp_config(route)
    catalog_path = write_routed_model_catalog(route)
    path = profile_path(route)
    contents = "\n".join(
        (
            f'model_provider = "{route.provider}"',
            f'model = "{DEFAULT_ROUTER_MODEL}"',
            f"model_catalog_json = {json.dumps(str(catalog_path))}",
            "",
            f"[model_providers.{route.provider}]",
            f"name = {json.dumps(route.key + ' TUI model gateway')}",
            f"base_url = {json.dumps(route.endpoint)}",
            'wire_api = "responses"',
            "stream_idle_timeout_ms = 1200000",
            "",
            f"[model_providers.{route.provider}.auth]",
            f"command = {json.dumps(str(GATEWAY_TOKEN_HELPER))}",
            f'args = ["--secret", {json.dumps(route.resolved_token_secret)}]',
            "timeout_ms = 5000",
            "refresh_interval_ms = 300000",
            "",
        )
    )
    _write_private_text(path, contents)
    refresh_model_catalog_cache(route)
    return path


def resolve_real_codex() -> Path:
    configured = os.getenv("CODEX_REAL_BIN", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        raise RuntimeError(f"CODEX_REAL_BIN is not executable: {candidate}")

    wrappers = {
        LOCAL_CODEX_WRAPPER.resolve(),
        LOCAL_CODEX_WORK_WRAPPER.resolve(),
    }
    for directory in os.getenv("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / "codex"
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if (
            resolved in wrappers
            or not resolved.is_file()
            or not os.access(resolved, os.X_OK)
        ):
            continue
        return resolved

    fallback = shutil.which("codex")
    if fallback:
        candidate = Path(fallback).resolve()
        if candidate not in wrappers and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("Unable to find the real Codex binary.")


def route_payload(route: Route | None, launcher: str, cwd: Path) -> dict[str, object]:
    root, origin = checkout_identity(cwd)
    if route is None:
        return {
            "route": None,
            "launcher": launcher,
            "checkout_root": str(root),
            "origin": origin,
            "fallback": "regular-default" if launcher == "regular" else "work-bedrock",
        }
    payload = asdict(route)
    payload.update(
        {
            "checkout_root": str(root),
            "origin": origin,
            "profile": route.profile,
            "profile_path": str(profile_path(route)),
            "token_secret": route.resolved_token_secret,
        }
    )
    return payload


def brokered_gateway_token(route: Route) -> tuple[str, str]:
    """Resolve one short-lived gateway token without exposing it to callers."""

    if not GATEWAY_TOKEN_HELPER.is_file() or not os.access(
        GATEWAY_TOKEN_HELPER, os.X_OK
    ):
        return "", f"gateway token helper is unavailable: {GATEWAY_TOKEN_HELPER}"
    try:
        token_result = subprocess.run(
            (str(GATEWAY_TOKEN_HELPER), "--secret", route.resolved_token_secret),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"broker lookup failed: {exc}"
    token = token_result.stdout.strip() if token_result.returncode == 0 else ""
    if not token:
        return "", "broker lookup returned no token"
    return token, ""


def gateway_get_json(
    endpoint: str,
    path: str,
    *,
    token: str,
) -> tuple[int, dict[str, Any], str]:
    """Read a gateway JSON endpoint while preserving no response body details."""

    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/{path.lstrip('/')}",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=GATEWAY_REQUEST_TIMEOUT_SECONDS
        ) as response:
            status = int(response.status)
            body = response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), {}, f"gateway returned HTTP {exc.code}"
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return 0, {}, f"gateway request failed: {exc}"
    if status != 200:
        return status, {}, f"gateway returned HTTP {status}"
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (TypeError, UnicodeDecodeError, ValueError):
        return status, {}, "gateway returned malformed JSON"
    if not isinstance(payload, dict):
        return status, {}, "gateway returned an unexpected JSON response"
    return status, payload, ""


def verify_norman_capacity(route: Route, *, token: str) -> tuple[bool, str]:
    """Report Norman coding capacity and whether approved cloud fallback exists."""

    query = urllib.parse.urlencode({"model": QWEN_LOCAL_ROUTER_MODEL})
    status, payload, detail = gateway_get_json(
        route.endpoint,
        f"norman/capacity?{query}",
        token=token,
    )
    if status != 200:
        return False, detail
    cloud_fallback = payload.get("cloud_fallback")
    if not isinstance(cloud_fallback, bool):
        return False, "capacity report has an invalid cloud fallback policy"
    local_lane = payload.get("local_lane")
    local_lane = local_lane if isinstance(local_lane, dict) else {}
    condition = str(payload.get("condition") or "").strip()
    ready_workers = _coerce_int(local_lane.get("model_ready_worker_count"))
    eligible_workers = _coerce_int(local_lane.get("eligible_worker_count"))
    redundancy = str(local_lane.get("redundancy") or "").strip()
    lane_detail = ""
    if eligible_workers:
        lane_detail = f"; {ready_workers}/{eligible_workers} model-ready worker(s)" + (
            f", {redundancy.replace('_', ' ')}" if redundancy else ""
        )
    if payload.get("available") is True:
        return True, f"local coding capacity verified{lane_detail}"
    reason = str(payload.get("reason") or "unknown").strip() or "unknown"
    retryable = bool(payload.get("retryable"))
    retry_hint = "retry later" if retryable else "operator action is required"
    condition_detail = {
        "recent_local_failure": "the local lane was paused after a recent failed request",
        "model_placement": "the coding model is not placed on a reachable worker",
        "worker_reachability": "no eligible coding worker is reachable",
        "worker_configuration": "no eligible coding worker is configured",
        "frontdoor_reachability": "the local model front door is unreachable",
        "mesh_probe": "the local model-health probe is unavailable",
    }.get(condition, "the local coding lane is unavailable")
    if cloud_fallback:
        return (
            False,
            f"{condition_detail} ({reason}){lane_detail}; "
            "approved Bedrock fallback is ready and will run before any "
            f"local output; {retry_hint}",
        )
    return False, f"{condition_detail} ({reason}){lane_detail}; {retry_hint}"


def model_catalog_contract_error(payload: dict[str, Any]) -> str:
    """Return an actionable error when a route cannot provision coding tools."""

    models = payload.get("models")
    if not isinstance(models, list):
        return (
            "gateway model catalog is missing the Codex models list; "
            "deploy the catalog fix before starting a new chat"
        )
    selected = next(
        (
            model
            for model in models
            if isinstance(model, dict) and model.get("slug") == DEFAULT_ROUTER_MODEL
        ),
        None,
    )
    if selected is None:
        return (
            f"gateway model catalog does not advertise {DEFAULT_ROUTER_MODEL!r}; "
            "deploy the catalog fix before starting a new chat"
        )
    for key, expected in REQUIRED_CODEX_MODEL_CAPABILITIES.items():
        actual = selected.get(key)
        if (expected is True and actual is not True) or actual != expected:
            return (
                "gateway model catalog is incompatible with local coding tools: "
                f"{DEFAULT_ROUTER_MODEL!r} advertises {key}={actual!r}, "
                f"expected {expected!r}; deploy the catalog fix and start a new chat"
            )
    return ""


def verify_route_model_contract(_route: Route) -> tuple[bool, str]:
    """Check the locally enforced catalog that provisions Codex tools."""

    contract_error = model_catalog_contract_error(routed_model_catalog())
    if contract_error:
        return False, contract_error
    return True, "managed tool-capable Codex model catalog verified"


def preflight_route_capacity(route: Route) -> tuple[bool, str]:
    """Report local coding capacity before starting a mapped interactive session."""

    token, detail = brokered_gateway_token(route)
    if not token:
        return False, detail
    return verify_norman_capacity(route, token=token)


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > USAGE_STATE_READ_LIMIT_BYTES:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load bounded JSONL state without making startup depend on it."""

    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > USAGE_STATE_READ_LIMIT_BYTES:
                handle.seek(-USAGE_STATE_READ_LIMIT_BYTES, os.SEEK_END)
                handle.readline()
            data = handle.read(USAGE_STATE_READ_LIMIT_BYTES)
    except OSError:
        return []

    entries: list[dict[str, Any]] = []
    for line in data.decode("utf-8", errors="ignore").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def usage_state_paths(route: Route | None = None) -> tuple[Path, Path, Path]:
    """Return the routed profile's web-bridge state, honoring explicit overrides."""

    state_dir = STATE_DIR
    if state_dir is None:
        state_dir = (
            route_home(route) / "web-bridge"
            if route is not None
            else HOME / ".codex" / "web-bridge"
        )
    return (
        USAGE_LEDGER_PATH or state_dir / "usage-ledger.jsonl",
        USAGE_HISTORY_PATH or state_dir / "usage.jsonl",
        CODEX_ACCOUNT_CAPACITY_PATH or state_dir / "codex_account_capacity.json",
    )


def _usage_entries(route: Route | None = None) -> list[dict[str, Any]]:
    """Prefer the durable ledger; history remains a compatibility fallback."""

    ledger_path, history_path, _capacity_path = usage_state_paths(route)
    entries = _read_jsonl(ledger_path)
    return entries if entries else _read_jsonl(history_path)


def _monthly_cycle_bounds(observed_at: int) -> tuple[int, int, str]:
    current = datetime.fromtimestamp(observed_at).astimezone()
    starts = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if starts.month == 12:
        ends = starts.replace(year=starts.year + 1, month=1)
    else:
        ends = starts.replace(month=starts.month + 1)
    return (
        int(starts.timestamp()),
        int(ends.timestamp()),
        f"{starts:%b %d} to {ends:%b %d}",
    )


def _entry_estimate(entry: dict[str, Any], key: str) -> float | None:
    candidates: list[Any] = [entry.get(key)]
    for parent_key in ("cost", "billing", "estimate"):
        parent = entry.get(parent_key)
        if isinstance(parent, dict):
            candidates.append(parent.get(key))
    for candidate in candidates:
        value = _coerce_float(candidate)
        if value is not None and value >= 0:
            return value
    return None


def _entry_tokens(entry: dict[str, Any]) -> int:
    total = _coerce_int(entry.get("total_tokens"))
    if total > 0:
        return total
    return max(
        0,
        _coerce_int(entry.get("input_tokens"))
        + max(
            _coerce_int(entry.get("output_tokens")),
            _coerce_int(entry.get("reasoning_output_tokens")),
        ),
    )


def _format_compact_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.0f}"


def _format_usd(value: float) -> str:
    if value < 0.01:
        return f"${value:.4f}".rstrip("0").rstrip(".")
    if value < 10:
        return f"${value:.2f}"
    return f"${value:,.0f}"


def _capacity_usage_notice(capacity: dict[str, Any], *, observed_at: int) -> str:
    observed = _coerce_int(capacity.get("observed_at"))
    source = str(capacity.get("source") or "").strip().lower()
    state = str(capacity.get("state") or "").strip().lower()
    if (
        source != "interactive_usage"
        or state not in {"available", "blocked"}
        or observed <= 0
        or observed_at - observed > ACCOUNT_CAPACITY_FRESH_SECONDS
    ):
        return ""

    windows = capacity.get("windows")
    window_parts: list[str] = []
    if isinstance(windows, list):
        for raw_window in windows[:3]:
            if not isinstance(raw_window, dict):
                continue
            label = (
                re.sub(
                    r"[^A-Za-z0-9 ._-]+", "", str(raw_window.get("label") or "")
                ).strip()[:48]
                or "Current"
            )
            percent_left = min(100, max(0, _coerce_int(raw_window.get("percent_left"))))
            reset_hint = re.sub(
                r"[^A-Za-z0-9 .:_-]+", "", str(raw_window.get("reset_hint") or "")
            ).strip()[:96]
            detail = f"{label} {percent_left}% left"
            if reset_hint:
                detail += f" (resets {reset_hint})"
            window_parts.append(detail)
    if not window_parts:
        percent_left = capacity.get("minimum_window_percent_left")
        if percent_left is None:
            return ""
        window_parts.append(
            f"Current {min(100, max(0, _coerce_int(percent_left)))}% left"
        )
    return "subscription: " + "; ".join(window_parts)


def startup_usage_notices(
    route: Route | None = None, *, observed_at: int | None = None
) -> list[str]:
    """Summarize local subscription and metered state before a TUI starts."""

    now = _coerce_int(observed_at) or int(time.time())
    cycle_start, cycle_end, cycle_label = _monthly_cycle_bounds(now)
    entries = [
        entry
        for entry in _usage_entries(route)
        if cycle_start <= _coerce_int(entry.get("finished_at")) < cycle_end
    ]
    _ledger_path, _history_path, capacity_path = usage_state_paths(route)
    capacity_notice = _capacity_usage_notice(_read_json(capacity_path), observed_at=now)

    plan_entries = [
        entry
        for entry in entries
        if str(entry.get("charge_ledger_kind") or "").strip() == PLAN_LEDGER_KIND
    ]
    metered_entries = [
        entry
        for entry in entries
        if str(entry.get("charge_ledger_kind") or "").strip() in METERED_LEDGER_KINDS
    ]
    notices: list[str] = []
    if capacity_notice:
        notices.append(capacity_notice)

    if plan_entries and not capacity_notice:
        estimates = [
            estimate
            for entry in plan_entries
            if (estimate := _entry_estimate(entry, "estimated_credits")) is not None
        ]
        if estimates:
            notices.append(
                f"subscription ({cycle_label}): ~{_format_compact_number(sum(estimates))} "
                "locally estimated credits used"
            )
        else:
            notices.append(
                f"subscription ({cycle_label}): {len(plan_entries)} tracked plan turn(s)"
            )

    if metered_entries:
        estimates = [
            estimate
            for entry in metered_entries
            if (estimate := _entry_estimate(entry, "estimated_usd")) is not None
        ]
        if estimates:
            notices.append(
                f"metered ({cycle_label}): ~{_format_usd(sum(estimates))} "
                f"local estimate across {len(metered_entries)} turn(s)"
            )
        else:
            tokens = sum(_entry_tokens(entry) for entry in metered_entries)
            detail = f"{len(metered_entries)} tracked metered turn(s)"
            if tokens:
                detail += f", {_format_compact_number(float(tokens))} tokens"
            notices.append(
                f"metered ({cycle_label}): {detail}; pricing estimate unavailable"
            )

    if not notices:
        notices.append(
            "no locally captured subscription or metered usage for this profile yet"
        )
    return notices


def print_startup_usage_notices(route: Route) -> None:
    for notice in startup_usage_notices(route):
        print(
            f"codex-route: usage - {notice}. "
            "Local usage data; not a provider billing record.",
            file=sys.stderr,
        )


def verify_route(route: Route) -> tuple[bool, str]:
    """Prove the endpoint accepts a brokered token and has local capacity."""

    token, detail = brokered_gateway_token(route)
    if not token:
        return False, detail
    status, payload, detail = gateway_get_json(route.endpoint, "models", token=token)
    if status != 200:
        return False, detail
    contract_error = model_catalog_contract_error(payload)
    if contract_error:
        return False, contract_error
    available, detail = verify_norman_capacity(route, token=token)
    if not available:
        return False, detail
    return True, "authenticated Responses gateway and local coding capacity verified"


def route_environment(route: Route) -> dict[str, str]:
    """Build a mapped TUI environment without model-visible secret plumbing."""

    environment = os.environ.copy()
    for name in MODEL_HIDDEN_SECRET_ENVIRONMENT_KEYS:
        environment.pop(name, None)
    return environment


def work_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY", None)
    environment["CODEX_WORK_OPS_BINDING_LOADED"] = "1"
    environment["NORMAN_TUI_NO_DIRECT_VAULT"] = "1"
    return environment


def verify_managed_tui_secret_policy() -> None:
    """Fail closed unless the root-managed secret guard is active."""
    if not SECRET_GUARD.is_file() or not os.access(SECRET_GUARD, os.R_OK):
        raise RuntimeError(
            f"Norman TUI secret guard verifier is unavailable at {SECRET_GUARD}."
        )
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(SECRET_GUARD),
                "--verify-managed-policy",
                "--requirements-path",
                str(MANAGED_CODEX_REQUIREMENTS),
                "--managed-guard-path",
                str(MANAGED_SECRET_GUARD),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Unable to verify the enforced Norman TUI credential policy."
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "managed policy verification failed"
        raise RuntimeError(
            "Norman TUI credential policy is not enforced "
            f"({detail}). Install it with "
            "sudo -n ~/code/norman/scripts/deploy_codex_tui_secret_guard.sh."
        )


def exec_work_route(route: Route, arguments: list[str]) -> None:
    if not os.getenv("CODEX_WORK_OPS_BINDING_LOADED"):
        if not OPS_OPENBRAND_MCP_LAUNCHER.is_file():
            raise RuntimeError(
                "Work route requires the Ops MCP launcher at "
                f"{OPS_OPENBRAND_MCP_LAUNCHER}."
            )
        command = (
            str(OPS_OPENBRAND_MCP_LAUNCHER),
            "env",
            "CODEX_WORK_OPS_BINDING_LOADED=1",
            str(Path(__file__).resolve()),
            "--launcher",
            "work",
            "--",
            *arguments,
        )
        os.execve(str(OPS_OPENBRAND_MCP_LAUNCHER), command, work_environment())

    verify_managed_tui_secret_policy()
    write_gateway_profile(route)
    environment = route_environment(route)
    environment["CODEX_HOME"] = str(route_home(route))
    environment["CODEX_REAL_BIN"] = str(resolve_real_codex())
    environment["NORMAN_TUI_NO_DIRECT_VAULT"] = "1"
    command = [environment["CODEX_REAL_BIN"]]
    if not has_explicit_profile(arguments) and starts_session(arguments):
        command.extend(("--profile", route.profile))
    if not has_explicit_model(arguments) and starts_session(arguments):
        command.extend(("-m", DEFAULT_ROUTER_MODEL))
    command.extend(arguments)
    os.execve(command[0], command, environment)


def exec_regular_route(route: Route, arguments: list[str]) -> None:
    verify_managed_tui_secret_policy()
    write_gateway_profile(route)
    environment = route_environment(route)
    environment["CODEX_HOME"] = str(route_home(route))
    environment["CODEX_REAL_BIN"] = str(resolve_real_codex())
    environment["NORMAN_TUI_NO_DIRECT_VAULT"] = "1"
    command = [environment["CODEX_REAL_BIN"]]
    if not has_explicit_profile(arguments) and starts_session(arguments):
        command.extend(("--profile", route.profile))
    if not has_explicit_model(arguments) and starts_session(arguments):
        command.extend(("-m", DEFAULT_ROUTER_MODEL))
    command.extend(arguments)
    os.execve(command[0], command, environment)


def generic_codex_home() -> Path:
    configured = os.getenv("CODEX_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return HOME / ".codex"


def exec_regular_fallback(arguments: list[str]) -> None:
    real_codex = str(resolve_real_codex())
    environment = os.environ.copy()
    command = [real_codex]
    if starts_session(arguments):
        verify_managed_tui_secret_policy()
        environment["CODEX_HOME"] = str(generic_codex_home())
        environment["NORMAN_TUI_NO_DIRECT_VAULT"] = "1"
    command.extend(arguments)
    os.execve(real_codex, command, environment)


def exec_work_fallback(reenter: str, arguments: list[str]) -> None:
    if not reenter:
        raise RuntimeError("Work fallback requires the original codex-work launcher.")
    reentry_path = Path(reenter).expanduser().resolve()
    if not reentry_path.is_file() or not os.access(reentry_path, os.X_OK):
        raise RuntimeError(f"Work fallback launcher is not executable: {reentry_path}")
    write_work_fallback_model_contract()
    environment = os.environ.copy()
    environment["CODEX_ROUTER_RESOLVED"] = "1"
    environment["CODEX_REAL_BIN"] = str(resolve_real_codex())
    os.execve(str(reentry_path), [str(reentry_path), *arguments], environment)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route Codex through the checkout's TUI Responses gateway."
    )
    parser.add_argument("--launcher", choices=("regular", "work"), required=True)
    parser.add_argument("--reenter", default="")
    parser.add_argument("--print-route", action="store_true")
    parser.add_argument("--routes", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("codex_args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    if parsed.codex_args[:1] == ["--"]:
        parsed.codex_args = parsed.codex_args[1:]
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parsed = parse_args(argv or sys.argv[1:])
    if parsed.routes:
        print(
            json.dumps(
                [
                    {
                        "route": route.key,
                        "group": route.group,
                        "launcher": route.launcher,
                        "endpoint": route.endpoint,
                        "codex_home": route.codex_home,
                        "profile": route.profile,
                        "token_secret": route.resolved_token_secret,
                    }
                    for route in ROUTES
                ],
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    cwd = codex_cwd(parsed.codex_args)
    route = resolve_route(cwd)
    if parsed.print_route:
        print(
            json.dumps(
                route_payload(route, parsed.launcher, cwd), indent=2, sort_keys=True
            )
        )
        return 0
    if parsed.verify:
        if route is None:
            print(
                "codex-route: no mapped TUI route for this checkout.", file=sys.stderr
            )
            return 2
        success, detail = verify_route(route)
        print(f"{route.key}: {detail}", file=sys.stderr)
        return 0 if success else 1

    if starts_session(parsed.codex_args):
        arguments_error = secret_guard_arguments_error(parsed.codex_args)
        if arguments_error:
            print(f"codex-route: {arguments_error}", file=sys.stderr)
            return 2

    if route is not None and (
        starts_session(parsed.codex_args)
        or uses_route_scoped_management_command(route, parsed.codex_args)
    ):
        if route.launcher != parsed.launcher:
            required_command = "codex-work" if route.launcher == "work" else "codex"
            print(
                f"codex-route: {route.key} is a {route.group} route; "
                f"start this checkout with {required_command}.",
                file=sys.stderr,
            )
            return 2
        if starts_session(parsed.codex_args):
            arguments_error = route_arguments_error(route, parsed.codex_args)
            if arguments_error:
                print(f"codex-route: {arguments_error}", file=sys.stderr)
                return 2
            if parsed.launcher == "work" and not os.getenv(
                "CODEX_WORK_OPS_BINDING_LOADED"
            ):
                # The work launcher re-enters through the Ops binding loader.
                # Defer preflight output until the bound process so it is emitted once.
                exec_work_route(route, parsed.codex_args)
                return 0
            contract_available, contract_detail = verify_route_model_contract(route)
            if not contract_available:
                print(
                    f"codex-route: {route.key} startup blocked: {contract_detail}.",
                    file=sys.stderr,
                )
                return 1
            capacity_available, capacity_detail = preflight_route_capacity(route)
            if not capacity_available:
                print(
                    f"codex-route: {route.key} local capacity warning: "
                    f"{capacity_detail}. Starting Codex normally.",
                    file=sys.stderr,
                )
            print_startup_usage_notices(route)
        if parsed.launcher == "work":
            exec_work_route(route, parsed.codex_args)
        else:
            exec_regular_route(route, parsed.codex_args)
        return 0

    if parsed.launcher == "work":
        exec_work_fallback(parsed.reenter, parsed.codex_args)
    exec_regular_fallback(parsed.codex_args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"codex-route: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
