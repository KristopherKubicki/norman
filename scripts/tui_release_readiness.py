#!/usr/bin/env python3
"""Run no-inference readiness checks for a managed Norman TUI launch."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 is still used by a few managed TUIs.
    tomllib = None


SCHEMA = "norman.tui.release-readiness.v1"
DEFAULT_TIMEOUT_SECONDS = 4.0
DEFAULT_NORLLAMA_ENDPOINTS = (
    "https://llm.home.arpa",
    "https://llm.knox.lollie.org",
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any, default: bool = False) -> bool:
    clean = _clean(value).lower()
    if not clean:
        return default
    return clean in {"1", "true", "yes", "on"}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        if clean and clean not in result:
            result.append(clean)
    return result


def _safe_url(value: Any) -> str:
    parsed = urllib.parse.urlsplit(_clean(value))
    if not parsed.scheme or not parsed.hostname:
        return ""
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, host, parsed.path.rstrip("/"), "", "")
    )


def _health_url(value: Any) -> str:
    base = _safe_url(value)
    if not base:
        return ""
    if urllib.parse.urlsplit(base).path.rstrip("/").endswith("/health"):
        return base
    return f"{base.rstrip('/')}/health"


def _models_url(value: Any) -> str:
    base = _safe_url(value)
    if not base:
        return ""
    path = urllib.parse.urlsplit(base).path.rstrip("/")
    if path.endswith("/v1/models"):
        return base
    if path.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def _network_error_detail(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return type(reason).__name__ if reason else "network unavailable"
    if isinstance(exc, TimeoutError):
        return "timed out"
    return type(exc).__name__


def _http_json(url: str, *, timeout_seconds: float) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status = int(getattr(response, "status", 200) or 200)
        body = response.read().decode("utf-8", errors="replace")
    return status, json.loads(body or "{}")


def _run_command(
    command: list[str], *, env: dict[str, str] | None, timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=timeout_seconds,
        check=False,
    )


def _check(
    check_id: str,
    status: str,
    detail: str,
    *,
    blocking: bool = False,
    recovery: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "blocking": bool(blocking and status == "fail"),
        "detail": detail,
        "recovery": recovery,
        "metadata": metadata or {},
    }


def _read_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:
        return _read_toml_fallback(path)
    try:
        with path.open("rb") as handle:
            parsed = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_toml_fallback(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    parsed: dict[str, Any] = {}
    section: dict[str, Any] = parsed
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            section = parsed.setdefault(name, {})
            if not isinstance(section, dict):
                return {}
            continue
        if "=" not in line:
            continue
        key, value = (item.strip() for item in line.split("=", 1))
        section[key] = value.strip("\"'")
    return parsed


def _config_values(payload: Any, key: str) -> list[str]:
    if not isinstance(payload, dict):
        return []
    values: list[str] = []
    for current_key, value in payload.items():
        if current_key == key and not isinstance(value, (dict, list, tuple)):
            clean = _clean(value)
            if clean:
                values.append(clean)
        if isinstance(value, dict):
            values.extend(_config_values(value, key))
    return values


def _config_aws_value(payload: dict[str, Any], key: str) -> str:
    aws = payload.get("aws")
    if isinstance(aws, dict):
        return _clean(aws.get(key))
    return ""


def _provider_from_config(payload: dict[str, Any]) -> str:
    providers = [
        item.lower()
        for item in _config_values(payload, "model_provider")
        + _config_values(payload, "provider")
    ]
    if any("bedrock" in item for item in providers):
        return "aws-bedrock"
    if providers:
        return "openai-direct"
    return ""


def _configured_profile_path(codex_home: Path, profile_v2: str) -> Path | None:
    profile = _clean(profile_v2)
    if profile:
        candidate = codex_home / f"{Path(profile).name}.config.toml"
        if candidate.exists():
            return candidate
    candidate = codex_home / "config.toml"
    return candidate if candidate.exists() else None


def launch_context(
    *,
    service_tier: str,
    codex_home: str,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if env is None else env
    tier = _clean(service_tier or source.get("NORMAN_CODEX_SERVICE_TIER")).lower()
    if tier in {"", "standard"}:
        tier = "default"
    profile_v2 = (
        _clean(source.get("NORMAN_CODEX_STANDARD_PROFILE_V2"))
        or _clean(source.get("NORMAN_CODEX_DEFAULT_PROFILE_V2"))
        or _clean(source.get("NORMAN_CODEX_BEDROCK_PROFILE_V2"))
    )
    home = Path(codex_home).expanduser()
    config_path = _configured_profile_path(home, profile_v2)
    config = _read_toml(config_path) if config_path else {}
    configured_provider = _provider_from_config(config)

    provider_surface = "openai-direct"
    if tier in {"auto", "default"} and (
        profile_v2 or configured_provider == "aws-bedrock"
    ):
        provider_surface = "aws-bedrock"

    aws_profile = (
        _clean(source.get("NORMAN_CODEX_STANDARD_AWS_PROFILE"))
        or _config_aws_value(config, "profile")
        or _clean(source.get("AWS_PROFILE"))
    )
    aws_region = (
        _clean(source.get("NORMAN_CODEX_STANDARD_AWS_REGION"))
        or _config_aws_value(config, "region")
        or _clean(source.get("AWS_REGION"))
        or _clean(source.get("AWS_DEFAULT_REGION"))
    )
    model = (
        _clean(source.get("NORMAN_CODEX_STANDARD_MODEL"))
        if provider_surface == "aws-bedrock"
        else _clean(source.get("NORMAN_CODEX_DIRECT_MODEL"))
    ) or _clean(source.get("NORMAN_CODEX_MODEL"))

    return {
        "service_tier": tier,
        "provider_surface": provider_surface,
        "profile_v2": profile_v2,
        "model": model,
        "aws_profile": aws_profile,
        "aws_region": aws_region,
        "configured_provider": configured_provider,
        "config_present": "true" if config_path else "false",
    }


def _check_norman_health(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    if not url:
        return _check(
            "norman_health",
            "skip",
            "No Norman health endpoint was configured for this TUI.",
            recovery="Set NORMAN_CODEX_PREFLIGHT_NORMAN_HEALTH_URL when this lane needs a control-plane health gate.",
        )
    try:
        status, _payload = _http_json(url, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return _check(
            "norman_health",
            "warn",
            f"Norman health endpoint {_safe_url(url)} is unavailable ({_network_error_detail(exc)}).",
            recovery="Restore the Norman API health endpoint or remove the stale endpoint setting.",
            metadata={"url": _safe_url(url)},
        )
    if 200 <= status < 300:
        return _check(
            "norman_health",
            "pass",
            f"Norman health endpoint {_safe_url(url)} responded.",
            metadata={"url": _safe_url(url)},
        )
    return _check(
        "norman_health",
        "warn",
        f"Norman health endpoint {_safe_url(url)} returned HTTP {status}.",
        recovery="Restore the health endpoint before relying on control-plane routing.",
        metadata={"url": _safe_url(url), "http_status": status},
    )


def _model_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("data", "models"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _check_norllama(endpoints: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    urls = _dedupe([_models_url(endpoint) for endpoint in endpoints])
    if not urls:
        return _check(
            "norllama_models",
            "skip",
            "No Norllama endpoint was configured for this TUI.",
            recovery="Configure NORMAN_LOCAL_LLM_ENDPOINTS before expecting local-first execution.",
        )
    reachable = 0
    model_count = 0
    for url in urls:
        try:
            status, payload = _http_json(url, timeout_seconds=timeout_seconds)
        except Exception:
            continue
        if 200 <= status < 300:
            reachable += 1
            model_count = max(model_count, _model_count(payload))
    if reachable:
        return _check(
            "norllama_models",
            "pass",
            f"Norllama model inventory responded at {reachable}/{len(urls)} endpoint(s).",
            metadata={
                "configured_endpoints": len(urls),
                "reachable_endpoints": reachable,
                "model_count": model_count,
            },
        )
    return _check(
        "norllama_models",
        "warn",
        f"Norllama model inventory did not respond at {len(urls)} configured endpoint(s).",
        recovery="Restore the configured Norllama gateway or correct NORMAN_LOCAL_LLM_ENDPOINTS; cloud routing remains separately gated.",
        metadata={"configured_endpoints": len(urls), "reachable_endpoints": 0},
    )


def _check_codex_binary(codex_bin: str) -> tuple[dict[str, Any], str]:
    clean = _clean(codex_bin) or "codex"
    resolved = clean if Path(clean).is_file() else shutil.which(clean)
    if not resolved:
        return (
            _check(
                "codex_binary",
                "fail",
                "Codex binary is unavailable.",
                blocking=True,
                recovery="Install Codex or set NORMAN_CODEX_BIN to the managed binary path.",
            ),
            "",
        )
    return (
        _check("codex_binary", "pass", "Codex binary is available."),
        resolved,
    )


def _check_direct_login(
    codex_bin: str, *, provider_surface: str, timeout_seconds: float
) -> dict[str, Any]:
    if provider_surface != "openai-direct":
        return _check(
            "codex_direct_login",
            "skip",
            "Direct Codex authentication is not required for the selected Bedrock route.",
        )
    try:
        completed = _run_command(
            [codex_bin, "login", "status"],
            env=None,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _check(
            "codex_direct_login",
            "fail",
            f"Direct Codex authentication could not be checked ({type(exc).__name__}).",
            blocking=True,
            recovery="Run `codex login` for this CODEX_HOME, then retry the TUI.",
        )
    if completed.returncode == 0:
        return _check(
            "codex_direct_login",
            "pass",
            "Direct Codex authentication is available.",
        )
    return _check(
        "codex_direct_login",
        "fail",
        "Direct Codex authentication is unavailable.",
        blocking=True,
        recovery="Run `codex login` for this CODEX_HOME, then retry the TUI.",
        metadata={"returncode": completed.returncode},
    )


def _check_bedrock_contract(context: dict[str, str]) -> dict[str, Any]:
    if context["provider_surface"] != "aws-bedrock":
        if context["configured_provider"] == "aws-bedrock":
            return _check(
                "launch_contract",
                "fail",
                "The selected direct tier conflicts with a Bedrock provider configured "
                "in CODEX_HOME.",
                blocking=True,
                recovery="Use the managed standard tier or select a CODEX_HOME configured for direct Codex before launching.",
            )
        return _check(
            "launch_contract",
            "pass",
            "Selected direct Codex launch contract is coherent.",
        )
    if not context["aws_profile"]:
        return _check(
            "bedrock_credentials_profile_missing",
            "fail",
            "Selected Bedrock route has no configured AWS credential profile.",
            blocking=True,
            recovery="Set NORMAN_CODEX_STANDARD_AWS_PROFILE or the selected profile's aws.profile, then restart the managed TUI.",
        )
    if not context["aws_region"]:
        return _check(
            "bedrock_credentials_region_missing",
            "fail",
            "Selected Bedrock route has no configured AWS region.",
            blocking=True,
            recovery="Set NORMAN_CODEX_STANDARD_AWS_REGION or the selected profile's aws.region, then restart the managed TUI.",
        )
    return _check(
        "launch_contract",
        "pass",
        "Selected Bedrock route has an explicit AWS profile and region.",
        metadata={
            "profile_v2": context["profile_v2"],
            "aws_profile": context["aws_profile"],
            "aws_region": context["aws_region"],
        },
    )


def _check_bedrock_identity(
    context: dict[str, str], *, timeout_seconds: float
) -> dict[str, Any]:
    if context["provider_surface"] != "aws-bedrock":
        return _check(
            "bedrock_aws_identity",
            "skip",
            "AWS identity is not required for the selected direct Codex route.",
        )
    if not context["aws_profile"] or not context["aws_region"]:
        return _check(
            "bedrock_aws_identity",
            "skip",
            "AWS identity was not checked because the Bedrock launch contract is incomplete.",
        )
    aws_bin = shutil.which("aws")
    if not aws_bin:
        return _check(
            "bedrock_aws_identity",
            "fail",
            "AWS CLI is unavailable for the selected Bedrock route.",
            blocking=True,
            recovery="Install the AWS CLI in the managed TUI PATH, then retry.",
        )
    env = dict(os.environ)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        env.pop(key, None)
    env["AWS_PROFILE"] = context["aws_profile"]
    env["AWS_REGION"] = context["aws_region"]
    env["AWS_DEFAULT_REGION"] = context["aws_region"]
    command = [
        aws_bin,
        "--profile",
        context["aws_profile"],
        "--region",
        context["aws_region"],
        "sts",
        "get-caller-identity",
        "--output",
        "json",
    ]
    try:
        completed = _run_command(command, env=env, timeout_seconds=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _check(
            "bedrock_aws_identity",
            "fail",
            f"AWS identity check could not run ({type(exc).__name__}).",
            blocking=True,
            recovery="Refresh the approved AWS profile credentials, then retry the managed TUI.",
        )
    if completed.returncode == 0:
        return _check(
            "bedrock_aws_identity",
            "pass",
            "Configured AWS profile passed the read-only STS identity check.",
            metadata={
                "aws_profile": context["aws_profile"],
                "aws_region": context["aws_region"],
            },
        )
    return _check(
        "bedrock_credentials_invalid",
        "fail",
        "Configured AWS profile did not pass the read-only STS identity check.",
        blocking=True,
        recovery="Refresh or reauthorize the configured AWS profile, then retry the managed TUI.",
        metadata={
            "aws_profile": context["aws_profile"],
            "aws_region": context["aws_region"],
            "returncode": completed.returncode,
        },
    )


def _check_cloud_budget(raw_budget: str) -> dict[str, Any]:
    raw = _clean(raw_budget)
    if not raw:
        return _check(
            "cloud_budget_policy",
            "skip",
            "No launch-level cloud token budget was supplied; runtime cloud routes still require an explicit budget.",
        )
    try:
        value = int(raw)
    except ValueError:
        return _check(
            "cloud_budget_policy",
            "fail",
            "Configured cloud token budget is not an integer.",
            blocking=True,
            recovery="Set a nonnegative cloud token budget or leave it unset for per-request policy.",
        )
    if value < 0:
        return _check(
            "cloud_budget_policy",
            "fail",
            "Configured cloud token budget is negative.",
            blocking=True,
            recovery="Set a nonnegative cloud token budget.",
        )
    return _check(
        "cloud_budget_policy",
        "pass",
        "Configured cloud token budget is nonnegative.",
        metadata={"cloud_token_budget": value},
    )


def build_report(
    *,
    codex_bin: str,
    codex_home: str,
    service_tier: str,
    norman_health_url: str,
    norllama_endpoints: list[str],
    cloud_token_budget: str,
    timeout_seconds: float,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    context = launch_context(
        service_tier=service_tier,
        codex_home=codex_home,
        env=env,
    )
    checks: list[dict[str, Any]] = [
        _check_norman_health(norman_health_url, timeout_seconds=timeout_seconds),
        _check_norllama(norllama_endpoints, timeout_seconds=timeout_seconds),
    ]
    binary_check, resolved_codex_bin = _check_codex_binary(codex_bin)
    checks.append(binary_check)
    checks.append(_check_bedrock_contract(context))
    if resolved_codex_bin:
        checks.append(
            _check_direct_login(
                resolved_codex_bin,
                provider_surface=context["provider_surface"],
                timeout_seconds=timeout_seconds,
            )
        )
    else:
        checks.append(
            _check(
                "codex_direct_login",
                "skip",
                "Direct Codex authentication was not checked because the binary is unavailable.",
            )
        )
    checks.append(_check_bedrock_identity(context, timeout_seconds=timeout_seconds))
    checks.append(_check_cloud_budget(cloud_token_budget))

    summary = {
        status: sum(1 for check in checks if check["status"] == status)
        for status in ("pass", "warn", "fail", "skip")
    }
    blockers = [check["id"] for check in checks if check["blocking"]]
    status = "blocked" if blockers else "warn" if summary["warn"] else "ready"
    return {
        "schema": SCHEMA,
        "checked_at": int(time.time()),
        "status": status,
        "blocking": bool(blockers),
        "blockers": blockers,
        "summary": {"checks": len(checks), **summary},
        "launch": context,
        "checks": checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    launch = report["launch"]
    lines = [
        "# Norman TUI Release Readiness",
        "",
        f"Status: **{str(report['status']).upper()}**",
        f"Checked at: {report['checked_at']}",
        (
            "Launch: "
            f"{launch['provider_surface']} / tier={launch['service_tier']} "
            f"/ model={launch['model'] or 'unspecified'}"
        ),
        (
            "Summary: "
            f"pass={report['summary']['pass']}, warn={report['summary']['warn']}, "
            f"fail={report['summary']['fail']}, skip={report['summary']['skip']}"
        ),
        "",
        "## Checks",
    ]
    for check in report["checks"]:
        marker = str(check["status"]).upper()
        blocking = " (blocking)" if check["blocking"] else ""
        lines.append(f"- [{marker}]{blocking} `{check['id']}`: {check['detail']}")
        if check["recovery"]:
            lines.append(f"  Recovery: {check['recovery']}")
    return "\n".join(lines) + "\n"


def summary_line(report: dict[str, Any]) -> str:
    launch = report["launch"]
    blockers = ",".join(report["blockers"]) or "none"
    return (
        f"TUI release readiness: {str(report['status']).upper()} "
        f"({launch['provider_surface']}; blockers={blockers}; "
        f"pass={report['summary']['pass']}; warn={report['summary']['warn']})"
    )


def _configured_norllama_endpoints(
    explicit: list[str], *, env: dict[str, str]
) -> list[str]:
    endpoints = list(explicit)
    endpoints.extend(
        item.strip()
        for item in _clean(env.get("NORMAN_LOCAL_LLM_ENDPOINTS")).split(",")
        if item.strip()
    )
    raw_mapping = _clean(env.get("NORMAN_LOCAL_LLM_MODEL_ENDPOINTS"))
    try:
        mapping = json.loads(raw_mapping) if raw_mapping else {}
    except json.JSONDecodeError:
        mapping = {}
    if isinstance(mapping, dict):
        for values in mapping.values():
            if isinstance(values, list):
                endpoints.extend(_clean(value) for value in values if _clean(value))
    if _truthy(env.get("NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED"), default=True):
        configured = _clean(env.get("NORMAN_LOCAL_LLM_AUTOSENSE_ENDPOINTS"))
        endpoints.extend(
            item.strip()
            for item in (configured or ",".join(DEFAULT_NORLLAMA_ENDPOINTS)).split(",")
            if item.strip()
        )
    return _dedupe(endpoints)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run no-inference release readiness checks for a Norman TUI."
    )
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("NORMAN_CODEX_BIN", "codex"),
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get(
            "CODEX_HOME",
            os.environ.get("NORMAN_CODEX_HOME", str(Path.home() / ".codex")),
        ),
    )
    parser.add_argument(
        "--service-tier",
        default=os.environ.get("NORMAN_CODEX_SERVICE_TIER", "default"),
    )
    parser.add_argument(
        "--norman-health-url",
        default=(
            os.environ.get("NORMAN_CODEX_PREFLIGHT_NORMAN_HEALTH_URL", "")
            or os.environ.get("NORMAN_CONSOLE_RUNTIME_API_BASE", "")
            or os.environ.get("NORMAN_API_BASE_URL", "")
        ),
    )
    parser.add_argument("--norllama-endpoint", action="append", default=[])
    parser.add_argument(
        "--cloud-token-budget",
        default=os.environ.get("NORMAN_CODEX_CLOUD_TOKEN_BUDGET", ""),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(
            os.environ.get(
                "NORMAN_CODEX_PREFLIGHT_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            )
        ),
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--fail-on-blocker",
        action="store_true",
        help="Exit nonzero when a route-blocking check fails.",
    )
    return parser.parse_args(argv)


def _default_output_paths(codex_home: str) -> tuple[Path, Path]:
    state_dir = _clean(os.environ.get("NORMAN_CODEX_WEB_STATE_DIR"))
    base = (
        Path(state_dir).expanduser()
        if state_dir
        else Path(codex_home).expanduser() / "web-bridge"
    )
    return base / "release_readiness.json", base / "release_readiness.md"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env = dict(os.environ)
    timeout_seconds = max(0.2, float(args.timeout_seconds))
    default_json, default_markdown = _default_output_paths(str(args.codex_home))
    report = build_report(
        codex_bin=_clean(args.codex_bin) or "codex",
        codex_home=_clean(args.codex_home),
        service_tier=_clean(args.service_tier),
        norman_health_url=_health_url(args.norman_health_url),
        norllama_endpoints=_configured_norllama_endpoints(
            list(args.norllama_endpoint), env=env
        ),
        cloud_token_budget=_clean(args.cloud_token_budget),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    markdown = render_markdown(report)
    _write(
        args.json_output or default_json,
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )
    _write(args.markdown_output or default_markdown, markdown)
    if not args.quiet:
        print(summary_line(report) if args.summary else markdown, end="")
    return 1 if args.fail_on_blocker and report["blocking"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
