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
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


HOME = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
GATEWAY_TOKEN_HELPER = SCRIPT_DIR / "norman_codex_gateway_token.py"
OPS_OPENBRAND_MCP_LAUNCHER = (
    HOME / "code" / "control_plane" / "scripts" / "with_ops_openbrand_mcp.sh"
)
LOCAL_BIN = HOME / ".local" / "bin"
LOCAL_CODEX_WRAPPER = LOCAL_BIN / "codex"
LOCAL_CODEX_WORK_WRAPPER = LOCAL_BIN / "codex-work"
ROUTER_PROFILE_PREFIX = "router-"
DEFAULT_ROUTER_MODEL = "norman-code"


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


def has_explicit_model(arguments: Sequence[str]) -> bool:
    for index, argument in enumerate(arguments):
        if argument in {"--model", "-m"}:
            return bool(_value_after(arguments, index))
        if argument.startswith("--model="):
            return bool(argument.split("=", 1)[1])
        if argument.startswith("-m") and len(argument) > 2:
            return True
    return False


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

    routed_keys = {
        "auth",
        "base_url",
        "model_provider",
        "provider",
        "wire_api",
    }
    for override in config_overrides(arguments):
        key = config_key(override)
        if key in routed_keys or key.startswith("model_providers."):
            return (
                f"{route.key} does not allow --config to override {key!r}; "
                "that would bypass its TUI route."
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
    command = command_name(arguments)
    return not command or command not in MANAGEMENT_COMMANDS


def route_home(route: Route) -> Path:
    return Path(route.codex_home).expanduser()


def profile_path(route: Route) -> Path:
    return route_home(route) / f"{route.profile}.config.toml"


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
    path = profile_path(route)
    contents = "\n".join(
        (
            f'model_provider = "{route.provider}"',
            f'model = "{DEFAULT_ROUTER_MODEL}"',
            "",
            f"[model_providers.{route.provider}]",
            f"name = {json.dumps(route.key + ' TUI model gateway')}",
            f"base_url = {json.dumps(route.endpoint)}",
            'wire_api = "responses"',
            "stream_idle_timeout_ms = 300000",
            "",
            f"[model_providers.{route.provider}.auth]",
            f"command = {json.dumps(str(GATEWAY_TOKEN_HELPER))}",
            f'args = ["--secret", {json.dumps(route.resolved_token_secret)}]',
            "timeout_ms = 5000",
            "refresh_interval_ms = 300000",
            "",
        )
    )
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{route.profile}.", dir=home, text=True
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


def verify_route(route: Route) -> tuple[bool, str]:
    """Prove the endpoint accepts a brokered token without logging that token."""
    if not GATEWAY_TOKEN_HELPER.is_file() or not os.access(
        GATEWAY_TOKEN_HELPER, os.X_OK
    ):
        return False, f"gateway token helper is unavailable: {GATEWAY_TOKEN_HELPER}"
    try:
        token_result = subprocess.run(
            (str(GATEWAY_TOKEN_HELPER), "--secret", route.resolved_token_secret),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"broker lookup failed: {exc}"
    token = token_result.stdout.strip() if token_result.returncode == 0 else ""
    if not token:
        return False, "broker lookup returned no token"

    request = urllib.request.Request(
        f"{route.endpoint.rstrip('/')}/models",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        return False, f"gateway returned HTTP {exc.code}"
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return False, f"gateway request failed: {exc}"
    return status == 200, (
        "authenticated Responses gateway verified"
        if status == 200
        else f"gateway returned HTTP {status}"
    )


def work_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("OPS_OPENBRAND_MCP_CONTROL_PLANE_KEY", None)
    environment["CODEX_WORK_OPS_BINDING_LOADED"] = "1"
    return environment


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

    write_gateway_profile(route)
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(route_home(route))
    environment["CODEX_REAL_BIN"] = str(resolve_real_codex())
    command = [environment["CODEX_REAL_BIN"]]
    if not has_explicit_profile(arguments) and starts_session(arguments):
        command.extend(("--profile", route.profile))
    if not has_explicit_model(arguments) and starts_session(arguments):
        command.extend(("-m", DEFAULT_ROUTER_MODEL))
    command.extend(arguments)
    os.execve(command[0], command, environment)


def exec_regular_route(route: Route, arguments: list[str]) -> None:
    write_gateway_profile(route)
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(route_home(route))
    environment["CODEX_REAL_BIN"] = str(resolve_real_codex())
    command = [environment["CODEX_REAL_BIN"]]
    if not has_explicit_profile(arguments) and starts_session(arguments):
        command.extend(("--profile", route.profile))
    if not has_explicit_model(arguments) and starts_session(arguments):
        command.extend(("-m", DEFAULT_ROUTER_MODEL))
    command.extend(arguments)
    os.execve(command[0], command, environment)


def exec_regular_fallback(arguments: list[str]) -> None:
    real_codex = str(resolve_real_codex())
    os.execve(real_codex, [real_codex, *arguments], os.environ.copy())


def exec_work_fallback(reenter: str, arguments: list[str]) -> None:
    if not reenter:
        raise RuntimeError("Work fallback requires the original codex-work launcher.")
    reentry_path = Path(reenter).expanduser().resolve()
    if not reentry_path.is_file() or not os.access(reentry_path, os.X_OK):
        raise RuntimeError(f"Work fallback launcher is not executable: {reentry_path}")
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

    if route is not None and starts_session(parsed.codex_args):
        if route.launcher != parsed.launcher:
            required_command = "codex-work" if route.launcher == "work" else "codex"
            print(
                f"codex-route: {route.key} is a {route.group} route; "
                f"start this checkout with {required_command}.",
                file=sys.stderr,
            )
            return 2
        arguments_error = route_arguments_error(route, parsed.codex_args)
        if arguments_error:
            print(f"codex-route: {arguments_error}", file=sys.stderr)
            return 2
        if parsed.launcher == "work":
            exec_work_route(route, parsed.codex_args)
        exec_regular_route(route, parsed.codex_args)

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
