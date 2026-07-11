#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TARGET_NAMES = (
    "norman",
    "housebot",
    "uplink",
    "networking",
    "scout",
    "cloudagent",
)
CONSOLE_RUNTIME_TOKEN_SECRET_DEFAULTS = (
    "norman/console-runtime-token",
    "norman/console-runtime-service-token",
    "runtime/console-runtime-token",
    "runtime/console-runtime-service-token",
)


def norman_ssh_target() -> str:
    override = os.environ.get("NORMAN_TUI_ACCEPTANCE_NORMAN_SSH_TARGET")
    if override is not None:
        return override.strip()
    hostname = (socket.gethostname() or "").strip().lower().split(".", 1)[0]
    return "" if hostname == "norman" else "norman.home.arpa"


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _norman_keys_secret_get_url() -> str:
    base = _first_env("NORMAN_KEYS_URL", "NORMAN_KEYS_API_BASE").rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1/secrets/get"):
        return base
    if base.endswith("/v1"):
        return f"{base}/secrets/get"
    return f"{base}/v1/secrets/get"


def _norman_keys_timeout_seconds() -> float:
    value = _first_env(
        "NORMAN_KEYS_TIMEOUT_SECONDS",
        "NORMAN_CONSOLE_RUNTIME_TIMEOUT_SECONDS",
    )
    try:
        return max(0.1, float(value or "2.0"))
    except ValueError:
        return 2.0


def _runtime_token_secret_names() -> list[str]:
    explicit = _first_env(
        "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET",
        "NORMAN_CONSOLE_RUNTIME_SECRET_NAME",
        "NORMAN_KEYS_SECRET_NAME",
    )
    names = [explicit] if explicit else []
    if not explicit and (
        _norman_keys_secret_get_url() or os.environ.get("NORMAN_SECRET_CMD", "").strip()
    ):
        names.extend(CONSOLE_RUNTIME_TOKEN_SECRET_DEFAULTS)
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        clean = str(name or "").strip()
        if clean and clean not in seen:
            out.append(clean)
            seen.add(clean)
    return out


def _resolve_runtime_token_from_norman_keys(secret_name: str) -> str:
    url = _norman_keys_secret_get_url()
    if not url:
        return ""
    payload = {
        "name": secret_name,
        "reason": "TUI kernel acceptance route-proof receipt checks",
        "requester_id": _first_env(
            "NORMAN_KEYS_REQUESTER_ID",
            "NORMAN_CONSOLE_RUNTIME_REQUESTER_ID",
        )
        or "runtime-tui-bridge",
        "session_id": _first_env("NORMAN_CODEX_SESSION", "HOUSEBOT_CODEX_SESSION")
        or "tui-kernel-acceptance",
        "lane": _first_env("NORMAN_KEYS_LANE", "NORMAN_CONSOLE_RUNTIME_LANE"),
        "target_host": socket.gethostname(),
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    keys_token = _first_env("NORMAN_KEYS_TOKEN", "NORMAN_KEYS_API_TOKEN")
    if keys_token:
        headers["Authorization"] = f"Bearer {keys_token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(
        request, timeout=_norman_keys_timeout_seconds()
    ) as response:
        body = response.read().decode("utf-8", "replace")
    parsed = json.loads(body) if body.strip() else {}
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("value") or parsed.get("secret") or "").strip()


def _norman_secret_command(secret_name: str) -> list[str]:
    configured = os.environ.get("NORMAN_SECRET_CMD", "").strip()
    if not configured:
        return []
    command = shlex.split(configured)
    if not command:
        return []
    if "{name}" in configured:
        return [part.replace("{name}", secret_name) for part in command]
    return [*command, "get", secret_name]


def _resolve_runtime_token_from_secret_command(secret_name: str) -> str:
    command = _norman_secret_command(secret_name)
    if not command:
        return ""
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=_norman_keys_timeout_seconds(),
    )
    return result.stdout.strip()


def resolve_console_runtime_token() -> str:
    token, _meta = resolve_console_runtime_token_with_source()
    return token


def resolve_console_runtime_token_with_source() -> tuple[str, dict[str, str]]:
    direct = _first_env("NORMAN_CONSOLE_RUNTIME_TOKEN", "NORMAN_API_TOKEN")
    if direct:
        return direct, {
            "runtime_token_source": "env",
            "runtime_token_secret_name": "",
        }
    for secret_name in _runtime_token_secret_names():
        for source, resolver in (
            ("norman_keys", _resolve_runtime_token_from_norman_keys),
            ("secret_command", _resolve_runtime_token_from_secret_command),
        ):
            try:
                token = resolver(secret_name)
            except (
                json.JSONDecodeError,
                subprocess.SubprocessError,
                TimeoutError,
                OSError,
                urllib.error.URLError,
            ):
                continue
            if token:
                return token, {
                    "runtime_token_source": source,
                    "runtime_token_secret_name": secret_name,
                }
    return "", {
        "runtime_token_source": "none",
        "runtime_token_secret_name": "",
    }


REMOTE_TUI_SCRIPT = r"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def fetch_json(url, *, data=None, timeout=10.0):
    headers = {}
    method = "GET"
    body = None
    if data is not None:
        method = "POST"
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        status = int(exc.code)
    payload = {}
    if text.strip():
        payload = json.loads(text)
    return status, payload


config = json.loads(CONFIG_JSON)
base_url = str(config["base_url"]).rstrip("/")
form = dict(config["form"])
expected = str(config.get("expected_response") or "")
nonce = str(config.get("nonce") or "")
poll_attempts = max(1, int(config.get("poll_attempts") or 1))
poll_interval = max(0.1, float(config.get("poll_interval") or 1.0))
ask_timeout = max(1.0, float(config.get("ask_timeout") or 20.0))
status_timeout = max(1.0, float(config.get("status_timeout") or 10.0))

result = {
    "ok": False,
    "ask_http_status": 0,
    "status_http_status": 0,
    "ask": {},
    "status": {},
    "error": "",
    "before_job_id": "",
    "ask_job_id": "",
}
try:
    _before_status_code, before_status = fetch_json(
        base_url + "/api/status",
        timeout=status_timeout,
    )
    result["before_job_id"] = str(
        before_status.get("last_console_runtime_job_id")
        or before_status.get("running_console_runtime_job_id")
        or ""
    )
except Exception:
    pass
try:
    ask_status, ask_payload = fetch_json(
        base_url + "/api/ask",
        data=form,
        timeout=ask_timeout,
    )
    result["ask_http_status"] = ask_status
    result["ask"] = ask_payload
    ask_snapshot = ask_payload.get("snapshot") if isinstance(ask_payload, dict) else {}
    if not isinstance(ask_snapshot, dict):
        ask_snapshot = {}
    result["ask_job_id"] = str(
        ask_payload.get("console_runtime_job_id")
        or ask_snapshot.get("console_runtime_job_id")
        or ask_snapshot.get("turn_shadow_job_id")
        or ask_snapshot.get("running_console_runtime_job_id")
        or ""
    )
except Exception as exc:
    result["error"] = "ask failed: %s" % exc

latest_status = {}
latest_status_code = 0
poll_deadline = time.time() + max(poll_interval, poll_attempts * poll_interval)
while time.time() <= poll_deadline:
    try:
        latest_status_code, latest_status = fetch_json(
            base_url + "/api/status",
            timeout=status_timeout,
        )
        result["status_http_status"] = latest_status_code
        result["status"] = latest_status
    except Exception as exc:
        result["error"] = (result.get("error") or "") + "; status failed: %s" % exc
        if result.get("ask_job_id"):
            break
        time.sleep(poll_interval)
        continue
    prompt = str(latest_status.get("last_prompt") or "")
    response = str(latest_status.get("last_response") or "")
    error = str(latest_status.get("last_error") or "")
    pending = bool(latest_status.get("pending"))
    job_id = str(
        latest_status.get("last_console_runtime_job_id")
        or latest_status.get("running_console_runtime_job_id")
        or latest_status.get("last_response_console_runtime_job_id")
        or ""
    )
    prompt_matches = bool(nonce and nonce in prompt)
    response_ready = bool(expected and expected in response)
    desired_job = str(result.get("ask_job_id") or "")
    fresh_job = bool(desired_job) or not result["before_job_id"] or job_id != result["before_job_id"]
    if desired_job:
        break
    if (
        prompt_matches
        and fresh_job
        and not pending
        and (response_ready or error.strip())
    ):
        break
    time.sleep(poll_interval)

result["ok"] = bool(result.get("status"))
print(json.dumps(result, sort_keys=True))
"""


@dataclass(frozen=True)
class TuiTarget:
    name: str
    label: str
    base_url: str
    ssh_target: str = ""


@dataclass(frozen=True)
class AcceptanceScenario:
    name: str
    message_template: str
    expected_template: str
    description: str = ""
    runtime: str = "localllm"
    model: str = "qwen3.6:27b"
    route_lock: bool = True
    speed: str = "fast"
    detail: int = 1
    service_tier: str = "default"
    job_budget: str = "2m"
    min_local_tokens: int = 1
    require_kernel_owned: bool = True
    require_local_first_on_target: bool = True
    require_norllama_tokens: bool = True
    require_worker_attribution: bool = True
    expected_task_kind: str = "literal_response"
    min_spark_evidence_count: int = 1


@dataclass(frozen=True)
class ScenarioRun:
    name: str
    nonce: str
    message: str
    expected_response: str
    scenario: AcceptanceScenario


def default_targets() -> dict[str, TuiTarget]:
    return {
        "norman": TuiTarget(
            name="norman",
            label="Norman",
            base_url="http://127.0.0.1:8788",
            ssh_target=norman_ssh_target(),
        ),
        "housebot": TuiTarget(
            name="housebot",
            label="Housebot",
            base_url="http://127.0.0.1:8787",
            ssh_target="toy-box",
        ),
        "uplink": TuiTarget(
            name="uplink",
            label="Uplink",
            base_url="http://127.0.0.1:8792",
            ssh_target="debian@192.168.2.242",
        ),
        "networking": TuiTarget(
            name="networking",
            label="Networking",
            base_url="http://127.0.0.1:8791",
            ssh_target="debian@192.168.2.242",
        ),
        "scout": TuiTarget(
            name="scout",
            label="Scout",
            base_url="http://127.0.0.1:8793",
            ssh_target="work-special",
        ),
        "cloudagent": TuiTarget(
            name="cloudagent",
            label="CloudAgent",
            base_url="http://127.0.0.1:8793",
            ssh_target="debian@192.168.2.242",
        ),
    }


def default_scenarios() -> dict[str, AcceptanceScenario]:
    return {
        "canary": AcceptanceScenario(
            name="canary",
            message_template="Canary only. Reply exactly: {expected_response}",
            expected_template="DONE local visible {nonce}",
            description="Fast literal-response proof for local visible output.",
        ),
        "route_receipt": AcceptanceScenario(
            name="route_receipt",
            message_template=(
                "Route receipt canary. Use the local Norllama runtime only, do not "
                "use tools, and reply exactly: {expected_response}"
            ),
            expected_template="DONE receipt visible {nonce}",
            description="Proves the DB route receipt and worker attribution path.",
        ),
        "auto_route_local": AcceptanceScenario(
            name="auto_route_local",
            message_template=(
                "Unlocked local routing check. Do not use tools. Given these service "
                "statuses: api=healthy, billing=unhealthy timeout, cache=healthy. "
                "Return one compact JSON object with keys unhealthy_service, evidence, "
                "and nonce. Use nonce value {nonce}."
            ),
            expected_template="{nonce}",
            description=(
                "Proves Norman can autonomously select local Norllama routing without "
                "an operator route lock."
            ),
            runtime="auto",
            model="",
            route_lock=False,
            expected_task_kind="chat",
            detail=2,
            job_budget="3m",
        ),
        "workspace_preflight": AcceptanceScenario(
            name="workspace_preflight",
            message_template=(
                "Workspace preflight canary. Use local runtime preflight behavior if "
                "available, do not mutate files, and reply exactly: {expected_response}"
            ),
            expected_template="DONE preflight visible {nonce}",
            description="Exercises the local preflight posture without file mutation.",
            detail=2,
            job_budget="3m",
        ),
        "specialist_visibility": AcceptanceScenario(
            name="specialist_visibility",
            message_template=(
                "Specialist visibility canary. Prefer local risk/evidence gates if "
                "available, do not use cloud models, and reply exactly: "
                "{expected_response}"
            ),
            expected_template="DONE specialist visible {nonce}",
            description="Smoke test for specialist cascade visibility on local turns.",
            detail=2,
            job_budget="3m",
        ),
    }


def split_names(raw: str, *, default: tuple[str, ...]) -> list[str]:
    value = str(raw or "").strip()
    if not value or value == "default":
        return list(default)
    if value == "all":
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def select_targets(raw: str) -> list[TuiTarget]:
    targets = default_targets()
    names = split_names(raw, default=DEFAULT_TARGET_NAMES)
    unknown = [name for name in names if name not in targets]
    if unknown:
        raise ValueError("Unknown TUI target(s): %s" % ", ".join(sorted(unknown)))
    return [targets[name] for name in names]


def select_scenarios(raw: str) -> list[AcceptanceScenario]:
    scenarios = default_scenarios()
    if str(raw or "").strip() == "all":
        names = list(scenarios)
    else:
        names = split_names(raw, default=("canary",))
    unknown = [name for name in names if name not in scenarios]
    if unknown:
        raise ValueError("Unknown scenario(s): %s" % ", ".join(sorted(unknown)))
    return [scenarios[name] for name in names]


def materialize_scenario(
    scenario: AcceptanceScenario,
    target: TuiTarget,
    *,
    run_id: str,
) -> ScenarioRun:
    nonce = "%s-%s-%s" % (run_id, target.name, scenario.name)
    expected = scenario.expected_template.format(
        nonce=nonce,
        target=target.name,
        target_label=target.label,
    )
    message = scenario.message_template.format(
        nonce=nonce,
        target=target.name,
        target_label=target.label,
        expected_response=expected,
    )
    return ScenarioRun(
        name=scenario.name,
        nonce=nonce,
        message=message,
        expected_response=expected,
        scenario=scenario,
    )


def form_payload(run: ScenarioRun) -> dict[str, str]:
    scenario = run.scenario
    return {
        "message": run.message,
        "runtime": scenario.runtime,
        "model": scenario.model,
        "route_lock": "1" if scenario.route_lock else "0",
        "speed": scenario.speed,
        "detail": str(scenario.detail),
        "service_tier": scenario.service_tier,
        "job_budget": scenario.job_budget,
    }


def _fetch_json(
    url: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    request_headers = dict(headers or {})
    body = None
    method = "GET"
    if data is not None:
        method = "POST"
        body = urllib.parse.urlencode(data).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        status = int(exc.code)
    payload: dict[str, Any] = {}
    if text.strip():
        payload = json.loads(text)
    return status, payload


def run_tui_probe_local(
    target: TuiTarget,
    run: ScenarioRun,
    *,
    poll_attempts: int,
    poll_interval: float,
    ask_timeout: float,
    status_timeout: float,
) -> dict[str, Any]:
    base_url = target.base_url.rstrip("/")
    result: dict[str, Any] = {
        "ok": False,
        "ask_http_status": 0,
        "status_http_status": 0,
        "ask": {},
        "status": {},
        "error": "",
        "before_job_id": "",
        "ask_job_id": "",
    }
    try:
        _before_status, before_payload = _fetch_json(
            base_url + "/api/status",
            timeout=status_timeout,
        )
        result["before_job_id"] = str(
            before_payload.get("last_console_runtime_job_id")
            or before_payload.get("running_console_runtime_job_id")
            or ""
        )
    except Exception:
        pass
    try:
        status, payload = _fetch_json(
            base_url + "/api/ask",
            data=form_payload(run),
            timeout=ask_timeout,
        )
        result["ask_http_status"] = status
        result["ask"] = payload
        ask_snapshot = payload.get("snapshot") if isinstance(payload, dict) else {}
        if not isinstance(ask_snapshot, dict):
            ask_snapshot = {}
        result["ask_job_id"] = str(
            payload.get("console_runtime_job_id")
            or ask_snapshot.get("console_runtime_job_id")
            or ask_snapshot.get("turn_shadow_job_id")
            or ask_snapshot.get("running_console_runtime_job_id")
            or ""
        )
    except Exception as exc:
        result["error"] = "ask failed: %s" % exc

    poll_deadline = time.time() + max(poll_interval, poll_attempts * poll_interval)
    while time.time() <= poll_deadline:
        try:
            status, payload = _fetch_json(
                base_url + "/api/status",
                timeout=status_timeout,
            )
            result["status_http_status"] = status
            result["status"] = payload
        except Exception as exc:
            result["error"] = "%s; status failed: %s" % (result.get("error") or "", exc)
            if result.get("ask_job_id"):
                break
            time.sleep(poll_interval)
            continue
        prompt = str(payload.get("last_prompt") or "")
        response = str(payload.get("last_response") or "")
        error = str(payload.get("last_error") or "")
        pending = bool(payload.get("pending"))
        job_id = str(
            payload.get("last_console_runtime_job_id")
            or payload.get("running_console_runtime_job_id")
            or payload.get("last_response_console_runtime_job_id")
            or ""
        )
        desired_job = str(result.get("ask_job_id") or "")
        fresh_job = (
            bool(desired_job)
            or not result["before_job_id"]
            or job_id != result["before_job_id"]
        )
        if desired_job:
            break
        if (
            run.nonce in prompt
            and fresh_job
            and not pending
            and (run.expected_response in response or error.strip())
        ):
            break
        time.sleep(poll_interval)
    result["ok"] = bool(result.get("status"))
    return result


def run_tui_probe(
    target: TuiTarget,
    run: ScenarioRun,
    *,
    poll_attempts: int,
    poll_interval: float,
    ask_timeout: float,
    status_timeout: float,
    ssh_timeout: float,
) -> dict[str, Any]:
    if not target.ssh_target:
        return run_tui_probe_local(
            target,
            run,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            ask_timeout=ask_timeout,
            status_timeout=status_timeout,
        )
    config = {
        "base_url": target.base_url,
        "form": form_payload(run),
        "expected_response": run.expected_response,
        "nonce": run.nonce,
        "poll_attempts": poll_attempts,
        "poll_interval": poll_interval,
        "ask_timeout": ask_timeout,
        "status_timeout": status_timeout,
    }
    remote_program = "CONFIG_JSON = %r\n%s" % (json.dumps(config), REMOTE_TUI_SCRIPT)
    try:
        completed = subprocess.run(
            ["ssh", target.ssh_target, "python3", "-"],
            input=remote_program,
            text=True,
            capture_output=True,
            timeout=ssh_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "ask": {},
            "status": {},
            "error": "ssh probe timed out after %.1fs for %s"
            % (ssh_timeout, target.name),
            "ssh_returncode": None,
            "raw_stdout": (exc.stdout or "")[:2000],
            "raw_stderr": (exc.stderr or "")[:2000],
        }
    if completed.returncode != 0:
        return {
            "ok": False,
            "ask": {},
            "status": {},
            "error": (completed.stderr or completed.stdout or "").strip(),
            "ssh_returncode": completed.returncode,
        }
    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "ask": {},
            "status": {},
            "error": "invalid ssh probe JSON: %s" % exc,
            "raw_stdout": completed.stdout,
            "raw_stderr": completed.stderr,
        }
    return payload


def _dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, dict) else {}


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _status_snapshot(probe: dict[str, Any]) -> dict[str, Any]:
    status = probe.get("status")
    return dict(status or {}) if isinstance(status, dict) else {}


def _event_route(payload: dict[str, Any]) -> dict[str, Any]:
    route = _dict(payload.get("route"))
    if route:
        return route
    metadata = _dict(payload.get("metadata"))
    return _dict(metadata.get("norllama_route"))


def _event_route_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = _dict(payload.get("route_receipt"))
    if receipt:
        return receipt
    nested = _dict(payload.get("receipt"))
    receipt = _dict(nested.get("route_receipt"))
    if receipt:
        return receipt
    metadata = _dict(payload.get("metadata"))
    norllama_receipt = _dict(metadata.get("norllama_receipt"))
    receipt_metadata = _dict(norllama_receipt.get("metadata"))
    receipt = _dict(receipt_metadata.get("route_receipt"))
    if receipt:
        return receipt
    return _dict(metadata.get("route_receipt"))


def _first_clean(*values: Any) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _event_worker_id(payload: dict[str, Any]) -> str:
    route = _event_route(payload)
    receipt = _event_route_receipt(payload)
    attribution = _dict(payload.get("attribution")) or _dict(route.get("attribution"))
    return _first_clean(
        receipt.get("selected_worker"),
        payload.get("selected_worker_id"),
        payload.get("worker_id"),
        route.get("selected_worker_id"),
        route.get("worker_id"),
        route.get("worker"),
        attribution.get("worker_id"),
    )


def _event_observed_worker_id(payload: dict[str, Any]) -> str:
    route = _event_route(payload)
    receipt = _event_route_receipt(payload)
    attribution = _dict(payload.get("attribution")) or _dict(route.get("attribution"))
    return _first_clean(
        receipt.get("observed_worker"),
        payload.get("observed_worker"),
        payload.get("observed_worker_id"),
        route.get("observed_worker"),
        attribution.get("observed_worker"),
    )


def _event_observed_worker_source(payload: dict[str, Any]) -> str:
    route = _event_route(payload)
    receipt = _event_route_receipt(payload)
    attribution = _dict(payload.get("attribution")) or _dict(route.get("attribution"))
    return _first_clean(
        receipt.get("observed_worker_source"),
        payload.get("observed_worker_source"),
        route.get("observed_worker_source"),
        attribution.get("observed_worker_source"),
    )


def _event_execution_mode(payload: dict[str, Any]) -> str:
    receipt = _event_route_receipt(payload)
    return _first_clean(payload.get("execution_mode"), receipt.get("execution_mode"))


def _event_output_shape(payload: dict[str, Any]) -> str:
    receipt = _event_route_receipt(payload)
    return _first_clean(payload.get("output_shape"), receipt.get("output_shape"))


def _event_receipt_task_kind(payload: dict[str, Any]) -> str:
    receipt = _event_route_receipt(payload)
    return _first_clean(receipt.get("task_kind"), payload.get("task_kind"))


def _event_receipt_phase(payload: dict[str, Any]) -> str:
    receipt = _event_route_receipt(payload)
    return _first_clean(receipt.get("phase"), payload.get("phase"))


def _event_cloud_proxy(payload: dict[str, Any]) -> bool:
    route = _event_route(payload)
    receipt = _event_route_receipt(payload)
    return bool(
        receipt.get("cloud_proxy")
        or payload.get("cloud_proxy")
        or route.get("cloud_proxy")
    )


def _event_receipt_audit(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = _event_route_receipt(payload)
    return _dict(payload.get("receipt_audit")) or _dict(receipt.get("receipt_audit"))


def _event_completion_gate(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = _event_route_receipt(payload)
    return _dict(payload.get("completion_gate")) or _dict(
        receipt.get("completion_gate")
    )


def _event_request_ids(payload: dict[str, Any]) -> dict[str, str]:
    receipt = _event_route_receipt(payload)
    metadata = _dict(payload.get("metadata"))
    return {
        "request_id": _first_clean(
            receipt.get("request_id"),
            payload.get("request_id"),
            metadata.get("request_id"),
        ),
        "client_request_id": _first_clean(
            receipt.get("client_request_id"),
            payload.get("client_request_id"),
            metadata.get("client_request_id"),
        ),
        "gateway_request_id": _first_clean(
            receipt.get("gateway_request_id"),
            payload.get("gateway_request_id"),
            metadata.get("gateway_request_id"),
        ),
        "invocation_id": _first_clean(
            receipt.get("invocation_id"),
            payload.get("invocation_id"),
            metadata.get("invocation_id"),
        ),
    }


def _audit_passed(value: dict[str, Any]) -> bool:
    return str(value.get("status") or "").strip().lower() == "pass" or bool(
        value.get("pass")
    )


def _completion_gate_passed(value: dict[str, Any]) -> bool:
    return str(value.get("status") or "").strip().lower() == "pass" or bool(
        value.get("gate_passed") or value.get("pass")
    )


def _event_model(payload: dict[str, Any]) -> str:
    route = _event_route(payload)
    receipt = _event_route_receipt(payload)
    return _first_clean(
        receipt.get("selected_model"),
        payload.get("selected_model"),
        payload.get("model"),
        route.get("model"),
    )


def _event_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = _event_route_receipt(payload)
    route = _event_route(payload)
    metadata = _dict(payload.get("metadata"))
    request_ids = _event_request_ids(payload)
    phase = _event_receipt_phase(payload)
    route_selected_model = _first_clean(
        receipt.get("route_selected_model"),
        payload.get("route_selected_model"),
        metadata.get("route_selected_model"),
        receipt.get("selected_model"),
        route.get("model"),
    )
    requested_model = _first_clean(
        receipt.get("requested_model"),
        payload.get("requested_model"),
        metadata.get("requested_model"),
        route_selected_model,
    )
    effective_model = _first_clean(
        receipt.get("effective_runtime_model"),
        payload.get("effective_runtime_model"),
        payload.get("runtime_model"),
        payload.get("model"),
        requested_model,
    )
    invocation_id = request_ids.get("invocation_id") or _first_clean(
        payload.get("event_id"),
        payload.get("id"),
    )
    if not phase:
        return {}
    return {
        "phase": phase,
        "task_kind": _event_receipt_task_kind(payload),
        "route_selected_model": route_selected_model,
        "requested_model": requested_model,
        "effective_runtime_model": effective_model,
        "selected_worker": _event_worker_id(payload),
        "observed_worker": _event_observed_worker_id(payload),
        "observed_worker_source": _event_observed_worker_source(payload),
        "execution_mode": _event_execution_mode(payload) or "unknown",
        "output_shape": _event_output_shape(payload),
        "request_id": request_ids.get("request_id", ""),
        "client_request_id": request_ids.get("client_request_id", ""),
        "gateway_request_id": request_ids.get("gateway_request_id", ""),
        "invocation_id": invocation_id,
    }


def _append_invocation(
    invocations: list[dict[str, Any]],
    seen: set[tuple[str, str, str, str]],
    payload: dict[str, Any],
) -> None:
    invocation = _event_invocation(payload)
    if not invocation:
        return
    key = (
        str(invocation.get("phase") or ""),
        str(invocation.get("invocation_id") or ""),
        str(invocation.get("request_id") or ""),
        str(invocation.get("gateway_request_id") or ""),
    )
    fallback_key = (
        str(invocation.get("phase") or ""),
        str(invocation.get("route_selected_model") or ""),
        str(invocation.get("effective_runtime_model") or ""),
        str(invocation.get("observed_worker") or ""),
    )
    dedupe_key = key if any(key[1:]) else fallback_key
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    invocations.append(invocation)


def _models_by_phase(invocations: list[dict[str, Any]]) -> dict[str, str]:
    models: dict[str, str] = {}
    for invocation in invocations:
        phase = str(invocation.get("phase") or "").strip()
        model = str(
            invocation.get("effective_runtime_model")
            or invocation.get("requested_model")
            or invocation.get("route_selected_model")
            or ""
        ).strip()
        if phase and model:
            models[phase] = model
    return models


def _ask_snapshot(probe: dict[str, Any]) -> dict[str, Any]:
    ask = probe.get("ask")
    if not isinstance(ask, dict):
        return {}
    snapshot = ask.get("snapshot")
    return dict(snapshot or {}) if isinstance(snapshot, dict) else {}


def job_id_from_probe(probe: dict[str, Any]) -> str:
    status = _status_snapshot(probe)
    ask = _dict(probe.get("ask"))
    ask_snapshot = _ask_snapshot(probe)
    candidates = [
        probe.get("ask_job_id"),
        ask.get("console_runtime_job_id"),
        ask_snapshot.get("console_runtime_job_id"),
        _dict(ask_snapshot.get("snapshot")).get("console_runtime_job_id"),
        _dict(ask_snapshot.get("snapshot")).get("turn_shadow_job_id"),
        _dict(ask_snapshot.get("snapshot")).get("running_console_runtime_job_id"),
        status.get("last_console_runtime_job_id"),
        status.get("running_console_runtime_job_id"),
        status.get("last_response_console_runtime_job_id"),
        ask_snapshot.get("last_console_runtime_job_id"),
        ask_snapshot.get("running_console_runtime_job_id"),
    ]
    for value in candidates:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _runtime_api_url(api_base: str, path: str) -> str:
    base = str(api_base or "").strip().rstrip("/")
    clean_path = "/" + str(path or "").strip().lstrip("/")
    if not base:
        return clean_path
    if base.endswith("/api/v1"):
        return f"{base}{clean_path}"
    if base.endswith("/api"):
        return f"{base}/v1{clean_path}"
    return f"{base}/api/v1{clean_path}"


def _receipt_from_activity_snapshot(
    job_id: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    job = _dict(snapshot.get("job"))
    contract = _dict(job.get("contract"))
    metadata = _dict(job.get("metadata"))
    authority = _dict(contract.get("authority_flags"))
    route_policy = _dict(contract.get("route_policy"))
    contract_metadata = _dict(contract.get("metadata"))
    summary = _dict(snapshot.get("route_summary"))
    usage_ledger = _dict(summary.get("usage_ledger"))
    local_first = _dict(summary.get("local_first_kpi"))
    model_summary = _dict(summary.get("model"))
    planner_summary = _dict(summary.get("planner"))
    route_summary = _dict(summary.get("route"))
    workers = _dict(_dict(summary.get("workers")).get("by_id"))
    by_provider = _dict(usage_ledger.get("by_provider"))
    model_latest = _dict(model_summary.get("latest"))
    planner_latest = _dict(planner_summary.get("latest"))
    route_latest = _dict(route_summary.get("latest"))
    worker = ""
    observed_worker = ""
    observed_worker_source = ""
    event_model = ""
    receipt_task_kind = ""
    receipt_phase = ""
    task_kinds: list[str] = []
    execution_mode = ""
    output_shape = ""
    cloud_proxy = False
    receipt_audit: dict[str, Any] = {}
    completion_gate: dict[str, Any] = {}
    invocations: list[dict[str, Any]] = []
    invocation_keys: set[tuple[str, str, str, str]] = set()
    request_ids = {
        "request_id": "",
        "client_request_id": "",
        "gateway_request_id": "",
        "invocation_id": "",
    }
    for event in snapshot.get("events") or []:
        if not isinstance(event, dict):
            continue
        if event.get("category") not in {
            "route",
            "planner",
            "model",
        } and event.get("event_type") not in {
            "route.decided",
            "planner.receipt",
            "model.completed",
        }:
            continue
        payload = _dict(event.get("payload") or event.get("payload_json"))
        if (
            event.get("category") == "model"
            or event.get("event_type") == "model.completed"
        ):
            _append_invocation(invocations, invocation_keys, payload)
        worker = _event_worker_id(payload) or worker
        observed_worker = _event_observed_worker_id(payload) or observed_worker
        observed_worker_source = (
            _event_observed_worker_source(payload) or observed_worker_source
        )
        event_model = _event_model(payload) or event_model
        event_task_kind = _event_receipt_task_kind(payload)
        if event_task_kind and event_task_kind not in task_kinds:
            task_kinds.append(event_task_kind)
        receipt_task_kind = event_task_kind or receipt_task_kind
        receipt_phase = _event_receipt_phase(payload) or receipt_phase
        execution_mode = _event_execution_mode(payload) or execution_mode
        output_shape = _event_output_shape(payload) or output_shape
        cloud_proxy = _event_cloud_proxy(payload) or cloud_proxy
        receipt_audit = _event_receipt_audit(payload) or receipt_audit
        completion_gate = _event_completion_gate(payload) or completion_gate
        event_request_ids = _event_request_ids(payload)
        request_ids = {
            key: event_request_ids.get(key) or request_ids.get(key, "")
            for key in request_ids
        }
    if not worker and workers:
        worker = sorted(str(key) for key in workers.keys() if str(key).strip())[0]
    if not observed_worker:
        observed_worker = worker
    model = _first_clean(
        event_model,
        model_latest.get("model"),
        planner_latest.get("model"),
    )
    local_tokens = _int(local_first.get("offline_tokens")) or _int(
        usage_ledger.get("offline_tokens")
    )
    spark_evidence_count = _int(summary.get("spark_evidence_count"))
    if not spark_evidence_count and (
        str(observed_worker).startswith("spark-") or str(worker).startswith("spark-")
    ):
        spark_evidence_count = 1
    envelope_task_kind = str(
        metadata.get("task_kind")
        or route_policy.get("task_kind")
        or contract_metadata.get("task_kind")
        or ""
    ).strip()
    task_kind = _first_clean(receipt_task_kind, envelope_task_kind)
    models_by_phase = _models_by_phase(invocations)
    final_invocation = invocations[-1] if invocations else {}
    return {
        "available": True,
        "job_id": str(job.get("job_id") or job_id),
        "job_status": str(job.get("status") or ""),
        "last_error": job.get("last_error"),
        "kernel_owned_turn": bool(
            metadata.get("kernel_owned_turn")
            or route_policy.get("kernel_owned_turn")
            or authority.get("kernel_owned_turn")
            or contract_metadata.get("kernel_owned_turn")
        ),
        "task_kind": task_kind,
        "task_kinds": task_kinds,
        "receipt_task_kind": receipt_task_kind,
        "receipt_phase": receipt_phase,
        "envelope_task_kind": envelope_task_kind,
        "host_name": str(metadata.get("host_name") or authority.get("host_name") or ""),
        "session_name": str(
            metadata.get("session_name") or authority.get("session_name") or ""
        ),
        "selected_model": model,
        "selected_worker": worker,
        "observed_worker": observed_worker,
        "observed_worker_source": observed_worker_source,
        "invocations": invocations,
        "models_by_phase": models_by_phase,
        "final_invocation_phase": str(final_invocation.get("phase") or ""),
        "final_effective_model": str(
            final_invocation.get("effective_runtime_model") or ""
        ),
        **request_ids,
        "execution_mode": execution_mode or "unknown",
        "output_shape": output_shape,
        "local_tokens": local_tokens,
        "cloud_proxy": cloud_proxy,
        "receipt_audit": receipt_audit,
        "completion_gate": completion_gate,
        "route_summary": summary,
        "ledger_offline_tokens": _int(usage_ledger.get("offline_tokens")),
        "ledger_cloud_tokens": _int(usage_ledger.get("cloud_llm_tokens"))
        + _int(usage_ledger.get("cloud_proxy_tokens"))
        + _int(usage_ledger.get("other_cloud_tokens")),
        "ledger_by_provider": by_provider,
        "goal_local_tokens": _int(local_first.get("offline_tokens")),
        "goal_cloud_tokens": _int(local_first.get("cloud_llm_tokens")),
        "local_first_status": str(local_first.get("status") or ""),
        "local_first_readiness_percent": _int(local_first.get("readiness_percent")),
        "model_completed_count": _int(model_summary.get("completed")),
        "spark_evidence_count": spark_evidence_count,
    }


def receipt_from_norman_api(
    job_id: str,
    *,
    api_base: str,
    token: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    clean_job_id = str(job_id or "").strip()
    if not clean_job_id:
        return {"available": False, "error": "missing job id"}
    clean_base = str(api_base or "").strip()
    clean_token = str(token or "").strip()
    if not clean_base or not clean_token:
        return {"available": False, "error": "runtime API not configured"}
    url = _runtime_api_url(
        clean_base,
        "/console-runtime/jobs/%s" % urllib.parse.quote(clean_job_id, safe=""),
    )
    try:
        status, payload = _fetch_json(
            url,
            headers={"Authorization": f"Bearer {clean_token}"},
            timeout=timeout,
        )
    except Exception as exc:
        return {"available": False, "error": "runtime API failed: %s" % exc}
    if status < 200 or status >= 300:
        return {
            "available": False,
            "error": "runtime API status %s: %s" % (status, payload.get("detail")),
        }
    return _receipt_from_activity_snapshot(clean_job_id, payload)


def _receipt_is_terminal_or_provable(receipt: dict[str, Any]) -> bool:
    if not receipt.get("available"):
        return False
    if receipt.get("job_status") in {"done", "failed", "canceled", "blocked"}:
        return True
    return (
        receipt.get("output_shape") == "complete"
        and receipt.get("execution_mode") == "live"
        and _audit_passed(_dict(receipt.get("receipt_audit")))
        and _completion_gate_passed(_dict(receipt.get("completion_gate")))
    )


def receipt_from_norman_api_poll(
    job_id: str,
    *,
    api_base: str,
    token: str,
    timeout: float = 10.0,
    poll_attempts: int = 1,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    attempts = max(1, int(poll_attempts or 1))
    interval = max(0.1, float(poll_interval or 1.0))
    latest: dict[str, Any] = {"available": False, "error": "not polled"}
    for attempt in range(attempts):
        latest = receipt_from_norman_api(
            job_id,
            api_base=api_base,
            token=token,
            timeout=timeout,
        )
        if _receipt_is_terminal_or_provable(latest):
            return latest
        if attempt < attempts - 1:
            time.sleep(interval)
    return latest


def receipt_from_norman_db(job_id: str, *, repo_root: Path) -> dict[str, Any]:
    clean_job_id = str(job_id or "").strip()
    if not clean_job_id:
        return {"available": False, "error": "missing job id"}
    root = str(repo_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from app.db.session import SessionLocal
        from app.models.console_runtime import (
            ConsoleRuntimeEventRecord,
            ConsoleRuntimeJobRecord,
        )
        from app.services.console_runtime.store import db_console_runtime_store
    except Exception as exc:
        return {"available": False, "error": "import failed: %s" % exc}

    db = SessionLocal()
    try:
        record = (
            db.query(ConsoleRuntimeJobRecord)
            .filter(ConsoleRuntimeJobRecord.job_id == clean_job_id)
            .first()
        )
        if record is None:
            return {"available": False, "error": "job not found: %s" % clean_job_id}
        job = db_console_runtime_store.get_job(
            db,
            user_id=record.user_id,
            job_id=clean_job_id,
        )
        summary = db_console_runtime_store.route_activity_summary(
            db,
            user_id=record.user_id,
            job_id=clean_job_id,
        )
        events = (
            db.query(ConsoleRuntimeEventRecord)
            .filter(ConsoleRuntimeEventRecord.job_id == clean_job_id)
            .order_by(ConsoleRuntimeEventRecord.sequence.asc())
            .all()
        )
    except Exception as exc:
        return {"available": False, "error": "receipt query failed: %s" % exc}
    finally:
        db.close()

    contract = job.contract.as_dict()
    metadata = _dict(job.metadata)
    authority = _dict(contract.get("authority_flags"))
    route_policy = _dict(contract.get("route_policy"))
    contract_metadata = _dict(contract.get("metadata"))
    usage_ledger = _dict(summary.get("usage_ledger"))
    local_first = _dict(summary.get("local_first_kpi"))
    model_summary = _dict(summary.get("model"))
    planner_summary = _dict(summary.get("planner"))
    route_summary = _dict(summary.get("route"))
    workers = _dict(_dict(summary.get("workers")).get("by_id"))
    by_provider = _dict(usage_ledger.get("by_provider"))
    model_latest = _dict(model_summary.get("latest"))
    planner_latest = _dict(planner_summary.get("latest"))
    route_latest = _dict(route_summary.get("latest"))
    worker = ""
    observed_worker = ""
    observed_worker_source = ""
    event_model = ""
    receipt_task_kind = ""
    receipt_phase = ""
    task_kinds: list[str] = []
    execution_mode = ""
    output_shape = ""
    cloud_proxy = False
    receipt_audit: dict[str, Any] = {}
    completion_gate: dict[str, Any] = {}
    invocations: list[dict[str, Any]] = []
    invocation_keys: set[tuple[str, str, str, str]] = set()
    request_ids = {
        "request_id": "",
        "client_request_id": "",
        "gateway_request_id": "",
        "invocation_id": "",
    }
    for event in events:
        if event.category not in {
            "route",
            "planner",
            "model",
        } and event.event_type not in {
            "route.decided",
            "planner.receipt",
            "model.completed",
        }:
            continue
        payload = _dict(event.payload_json)
        if event.category == "model" or event.event_type == "model.completed":
            _append_invocation(invocations, invocation_keys, payload)
        worker = _event_worker_id(payload) or worker
        observed_worker = _event_observed_worker_id(payload) or observed_worker
        observed_worker_source = (
            _event_observed_worker_source(payload) or observed_worker_source
        )
        event_model = _event_model(payload) or event_model
        event_task_kind = _event_receipt_task_kind(payload)
        if event_task_kind and event_task_kind not in task_kinds:
            task_kinds.append(event_task_kind)
        receipt_task_kind = event_task_kind or receipt_task_kind
        receipt_phase = _event_receipt_phase(payload) or receipt_phase
        execution_mode = _event_execution_mode(payload) or execution_mode
        output_shape = _event_output_shape(payload) or output_shape
        cloud_proxy = _event_cloud_proxy(payload) or cloud_proxy
        receipt_audit = _event_receipt_audit(payload) or receipt_audit
        completion_gate = _event_completion_gate(payload) or completion_gate
        event_request_ids = _event_request_ids(payload)
        request_ids = {
            key: event_request_ids.get(key) or request_ids.get(key, "")
            for key in request_ids
        }
    if not worker and workers:
        worker = sorted(str(key) for key in workers.keys() if str(key).strip())[0]
    if not observed_worker:
        observed_worker = worker
    model = _first_clean(
        event_model,
        model_latest.get("model"),
        planner_latest.get("model"),
    )
    local_tokens = _int(local_first.get("offline_tokens")) or _int(
        usage_ledger.get("offline_tokens")
    )
    spark_evidence_count = _int(summary.get("spark_evidence_count"))
    if not spark_evidence_count and (
        str(observed_worker).startswith("spark-") or str(worker).startswith("spark-")
    ):
        spark_evidence_count = 1
    envelope_task_kind = str(
        metadata.get("task_kind")
        or route_policy.get("task_kind")
        or contract_metadata.get("task_kind")
        or ""
    ).strip()
    task_kind = _first_clean(receipt_task_kind, envelope_task_kind)
    models_by_phase = _models_by_phase(invocations)
    final_invocation = invocations[-1] if invocations else {}
    return {
        "available": True,
        "job_id": job.job_id,
        "job_status": job.status.value,
        "last_error": job.last_error,
        "kernel_owned_turn": bool(
            metadata.get("kernel_owned_turn")
            or route_policy.get("kernel_owned_turn")
            or authority.get("kernel_owned_turn")
            or contract_metadata.get("kernel_owned_turn")
        ),
        "task_kind": task_kind,
        "task_kinds": task_kinds,
        "receipt_task_kind": receipt_task_kind,
        "receipt_phase": receipt_phase,
        "envelope_task_kind": envelope_task_kind,
        "host_name": str(metadata.get("host_name") or authority.get("host_name") or ""),
        "session_name": str(
            metadata.get("session_name") or authority.get("session_name") or ""
        ),
        "selected_model": model,
        "selected_worker": worker,
        "observed_worker": observed_worker,
        "observed_worker_source": observed_worker_source,
        "invocations": invocations,
        "models_by_phase": models_by_phase,
        "final_invocation_phase": str(final_invocation.get("phase") or ""),
        "final_effective_model": str(
            final_invocation.get("effective_runtime_model") or ""
        ),
        **request_ids,
        "execution_mode": execution_mode or "unknown",
        "output_shape": output_shape,
        "local_tokens": local_tokens,
        "cloud_proxy": cloud_proxy,
        "receipt_audit": receipt_audit,
        "completion_gate": completion_gate,
        "route_summary": summary,
        "ledger_offline_tokens": _int(usage_ledger.get("offline_tokens")),
        "ledger_cloud_tokens": _int(usage_ledger.get("cloud_llm_tokens"))
        + _int(usage_ledger.get("cloud_proxy_tokens"))
        + _int(usage_ledger.get("other_cloud_tokens")),
        "ledger_by_provider": by_provider,
        "goal_local_tokens": _int(local_first.get("offline_tokens")),
        "goal_cloud_tokens": _int(local_first.get("cloud_llm_tokens")),
        "local_first_status": str(local_first.get("status") or ""),
        "local_first_readiness_percent": _int(local_first.get("readiness_percent")),
        "model_completed_count": _int(model_summary.get("completed")),
        "spark_evidence_count": spark_evidence_count,
    }


def validate_acceptance(
    target: TuiTarget,
    run: ScenarioRun,
    probe: dict[str, Any],
    receipt: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    observation_failures: list[str] = []
    status = _status_snapshot(probe)
    response = str(status.get("last_response") or "")
    prompt = str(status.get("last_prompt") or "")
    last_error = str(status.get("last_error") or "").strip()
    job_id = job_id_from_probe(probe)
    if not probe.get("ok"):
        observation_failures.append(
            "TUI probe did not return a status snapshot: %s"
            % str(probe.get("error") or "no probe error")[:240]
        )
    if run.nonce not in prompt:
        observation_failures.append("latest prompt does not contain the run nonce")
    if bool(status.get("pending")):
        observation_failures.append("TUI is still pending")
    if last_error:
        observation_failures.append("TUI reported last_error: %s" % last_error[:240])
    if run.expected_response not in response:
        observation_failures.append(
            "visible response did not contain the expected literal"
        )
    if not job_id:
        failures.append("TUI did not expose a console-runtime job id")
    before_job_id = str(probe.get("before_job_id") or "").strip()
    if before_job_id and job_id == before_job_id:
        failures.append("TUI did not expose a fresh console-runtime job id")
    if not receipt.get("available"):
        failures.append("receipt unavailable: %s" % receipt.get("error", "unknown"))
    else:
        scenario = run.scenario
        if receipt.get("job_id") != job_id:
            failures.append("receipt job id did not match TUI job id")
        if receipt.get("job_status") != "done":
            failures.append("receipt job status is %s" % receipt.get("job_status"))
        if receipt.get("last_error"):
            failures.append(
                "receipt has last_error: %s" % str(receipt.get("last_error"))[:240]
            )
        if scenario.require_kernel_owned and not receipt.get("kernel_owned_turn"):
            failures.append("receipt is not kernel-owned")
        if (
            scenario.expected_task_kind
            and receipt.get("task_kind") != scenario.expected_task_kind
            and receipt.get("receipt_phase") != scenario.expected_task_kind
            and receipt.get("envelope_task_kind") != scenario.expected_task_kind
            and scenario.expected_task_kind not in (receipt.get("task_kinds") or [])
        ):
            failures.append(
                "task kind is %s phase %s, expected %s in %s"
                % (
                    receipt.get("task_kind"),
                    receipt.get("receipt_phase"),
                    scenario.expected_task_kind,
                    receipt.get("task_kinds") or [],
                )
            )
        if _int(receipt.get("goal_local_tokens")) < scenario.min_local_tokens:
            failures.append("receipt did not record enough local tokens")
        if _int(receipt.get("goal_cloud_tokens")):
            failures.append("receipt recorded cloud LLM tokens")
        if _int(receipt.get("ledger_cloud_tokens")):
            failures.append("usage ledger recorded cloud/proxy tokens")
        provider_tokens = _dict(receipt.get("ledger_by_provider"))
        if (
            scenario.require_norllama_tokens
            and _int(provider_tokens.get("norllama")) < 1
        ):
            failures.append("usage ledger did not record Norllama tokens")
        if scenario.require_worker_attribution and not receipt.get("selected_worker"):
            failures.append("receipt did not record worker attribution")
        if scenario.require_worker_attribution and not receipt.get("observed_worker"):
            failures.append("receipt did not record observed worker attribution")
        if (
            scenario.require_worker_attribution
            and receipt.get("observed_worker_source") != "gateway_response"
        ):
            failures.append(
                "receipt observed worker source is %s"
                % (receipt.get("observed_worker_source") or "missing")
            )
        if receipt.get("execution_mode") != "live":
            failures.append(
                "receipt execution mode is %s"
                % (receipt.get("execution_mode") or "missing")
            )
        if receipt.get("output_shape") != "complete":
            failures.append(
                "receipt output shape is %s"
                % (receipt.get("output_shape") or "missing")
            )
        if _int(receipt.get("local_tokens")) < scenario.min_local_tokens:
            failures.append("receipt did not record positive local tokens")
        if bool(receipt.get("cloud_proxy")):
            failures.append("receipt used cloud proxy")
        if not _audit_passed(_dict(receipt.get("receipt_audit"))):
            failures.append("receipt audit did not pass")
        if not _completion_gate_passed(_dict(receipt.get("completion_gate"))):
            failures.append("completion gate did not pass")
        if _int(receipt.get("model_completed_count")) < 1:
            failures.append("receipt did not record a model.completed event")
        if (
            _int(receipt.get("spark_evidence_count"))
            < scenario.min_spark_evidence_count
        ):
            failures.append(
                "receipt spark evidence count is %s, expected at least %s"
                % (
                    receipt.get("spark_evidence_count"),
                    scenario.min_spark_evidence_count,
                )
            )
        if (
            scenario.require_local_first_on_target
            and receipt.get("local_first_status") != "on_target"
        ):
            failures.append("local-first KPI is %s" % receipt.get("local_first_status"))
    receipt_route_proof_passed = (
        bool(receipt.get("available"))
        and bool(job_id)
        and receipt.get("job_id") == job_id
        and receipt.get("job_status") == "done"
        and not receipt.get("last_error")
        and receipt.get("output_shape") == "complete"
        and receipt.get("execution_mode") == "live"
        and _int(receipt.get("local_tokens")) >= run.scenario.min_local_tokens
        and not _int(receipt.get("goal_cloud_tokens"))
        and not _int(receipt.get("ledger_cloud_tokens"))
        and not bool(receipt.get("cloud_proxy"))
        and _audit_passed(_dict(receipt.get("receipt_audit")))
        and _completion_gate_passed(_dict(receipt.get("completion_gate")))
    )
    observation_warnings: list[str] = []
    if observation_failures:
        if receipt_route_proof_passed:
            observation_warnings.extend(observation_failures)
        else:
            failures.extend(observation_failures)
    proof = {
        "target": target.name,
        "label": target.label,
        "scenario": run.name,
        "nonce": run.nonce,
        "runtime": run.scenario.runtime,
        "model": run.scenario.model,
        "route_lock": run.scenario.route_lock,
        "job_id": job_id,
        "passed": not failures,
        "failures": failures,
        "observation_warnings": observation_warnings,
        "route_proof_passed": receipt_route_proof_passed,
        "response_preview": response[:240],
        "probe_error": str(probe.get("error") or "")[:500],
        "before_job_id": str(probe.get("before_job_id") or ""),
        "ask_job_id": str(probe.get("ask_job_id") or ""),
        "status_job_id": str(
            _status_snapshot(probe).get("last_console_runtime_job_id")
            or _status_snapshot(probe).get("running_console_runtime_job_id")
            or _status_snapshot(probe).get("last_response_console_runtime_job_id")
            or ""
        ),
        "ask_http_status": probe.get("ask_http_status"),
        "status_http_status": probe.get("status_http_status"),
        "receipt": {
            key: receipt.get(key)
            for key in (
                "available",
                "job_status",
                "kernel_owned_turn",
                "task_kind",
                "task_kinds",
                "receipt_task_kind",
                "receipt_phase",
                "envelope_task_kind",
                "selected_model",
                "selected_worker",
                "observed_worker",
                "observed_worker_source",
                "invocations",
                "models_by_phase",
                "final_invocation_phase",
                "final_effective_model",
                "request_id",
                "client_request_id",
                "gateway_request_id",
                "invocation_id",
                "execution_mode",
                "output_shape",
                "local_tokens",
                "cloud_proxy",
                "receipt_audit",
                "completion_gate",
                "goal_local_tokens",
                "goal_cloud_tokens",
                "ledger_cloud_tokens",
                "local_first_status",
                "local_first_readiness_percent",
                "model_completed_count",
                "spark_evidence_count",
            )
        },
    }
    return not failures, failures, proof


def print_report(results: list[dict[str, Any]]) -> None:
    passed = sum(1 for item in results if item.get("passed"))
    total = len(results)
    print("TUI kernel acceptance: %s/%s passed" % (passed, total))
    for item in results:
        marker = "PASS" if item.get("passed") else "FAIL"
        receipt = _dict(item.get("receipt"))
        print(
            "%s %-11s %-7s job=%s model=%s worker=%s local=%s cloud=%s kpi=%s"
            % (
                marker,
                item.get("target"),
                item.get("scenario"),
                item.get("job_id") or "-",
                receipt.get("selected_model") or "-",
                receipt.get("selected_worker") or "-",
                receipt.get("goal_local_tokens") or 0,
                receipt.get("goal_cloud_tokens") or 0,
                receipt.get("local_first_status") or "-",
            )
        )
        for failure in item.get("failures") or []:
            print("  - %s" % failure)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Norman TUI kernel local-first acceptance canaries."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually send prompts. Without this flag, only print the planned matrix.",
    )
    parser.add_argument(
        "--targets",
        default="default",
        help="Comma-separated target names, 'default', or 'all'.",
    )
    parser.add_argument(
        "--scenarios",
        default="canary",
        help="Comma-separated scenario names.",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Stable run id for nonce generation. Defaults to a random short id.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Norman repo root used for DB receipt imports.",
    )
    parser.add_argument(
        "--runtime-api-base",
        default=os.environ.get("NORMAN_CONSOLE_RUNTIME_API_BASE", ""),
        help=(
            "Console-runtime API base for receipt checks. Defaults to "
            "NORMAN_CONSOLE_RUNTIME_API_BASE."
        ),
    )
    parser.add_argument(
        "--runtime-token",
        default="",
        help=(
            "Console-runtime bearer token for receipt checks. Defaults to "
            "NORMAN_CONSOLE_RUNTIME_TOKEN/NORMAN_API_TOKEN, then brokered "
            "Norman Keys or NORMAN_SECRET_CMD lookup."
        ),
    )
    parser.add_argument("--poll-attempts", type=int, default=90)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--ask-timeout", type=float, default=30.0)
    parser.add_argument("--status-timeout", type=float, default=15.0)
    parser.add_argument("--ssh-timeout", type=float, default=420.0)
    parser.add_argument("--output-json", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = select_targets(args.targets)
        scenarios = select_scenarios(args.scenarios)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    run_id = str(args.run_id or uuid.uuid4().hex[:10]).strip()
    matrix: list[tuple[TuiTarget, ScenarioRun]] = []
    for target in targets:
        for scenario in scenarios:
            matrix.append(
                (target, materialize_scenario(scenario, target, run_id=run_id))
            )

    if not args.live:
        print("Dry run. Add --live to send prompts.")
        for target, run in matrix:
            transport = "ssh:%s" % target.ssh_target if target.ssh_target else "local"
            print(
                "%-11s %-7s %s %s"
                % (target.name, run.name, transport, run.expected_response)
            )
        return 0

    results: list[dict[str, Any]] = []
    repo_root = Path(args.repo_root)
    runtime_api_base = str(args.runtime_api_base or "").strip()
    runtime_token = str(args.runtime_token or "").strip()
    if runtime_token:
        runtime_token_meta = {
            "runtime_token_source": "cli",
            "runtime_token_secret_name": "",
        }
    else:
        runtime_token, runtime_token_meta = resolve_console_runtime_token_with_source()
    for index, (target, run) in enumerate(matrix, start=1):
        print(
            "Running %s/%s %s:%s" % (index, len(matrix), target.name, run.name),
            flush=True,
        )
        probe = run_tui_probe(
            target,
            run,
            poll_attempts=args.poll_attempts,
            poll_interval=args.poll_interval,
            ask_timeout=args.ask_timeout,
            status_timeout=args.status_timeout,
            ssh_timeout=args.ssh_timeout,
        )
        job_id = job_id_from_probe(probe)
        if not job_id:
            receipt = {"available": False, "error": "missing job id"}
        elif runtime_api_base and runtime_token:
            receipt = receipt_from_norman_api_poll(
                job_id,
                api_base=runtime_api_base,
                token=runtime_token,
                timeout=args.status_timeout,
                poll_attempts=args.poll_attempts,
                poll_interval=args.poll_interval,
            )
            if not receipt.get("available"):
                db_receipt = receipt_from_norman_db(job_id, repo_root=repo_root)
                if db_receipt.get("available"):
                    receipt = db_receipt
        else:
            receipt = receipt_from_norman_db(job_id, repo_root=repo_root)
        _ok, _failures, proof = validate_acceptance(target, run, probe, receipt)
        results.append(proof)
        print(
            "%s %s:%s job=%s"
            % (
                "PASS" if proof.get("passed") else "FAIL",
                target.name,
                run.name,
                proof.get("job_id") or "-",
            ),
            flush=True,
        )

    report = {
        "schema": "norman.tui-kernel-acceptance.v1",
        "run_id": run_id,
        "generated_at": int(time.time()),
        "passed": all(item.get("passed") for item in results),
        "pass_count": sum(1 for item in results if item.get("passed")),
        "total_count": len(results),
        "runtime_api": {
            "base": runtime_api_base,
            "token_available": bool(runtime_token),
            **runtime_token_meta,
        },
        "results": results,
    }
    print_report(results)
    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
