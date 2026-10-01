#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sync_agent_console_template as sync


DEFAULT_MIN_TIMEOUT_SECONDS = 3600
DEFAULT_NO_CONSOLE_SCAN_HOSTS: set[str] = set()
DEFAULT_ROUTE_PROOF_MAX_AGE_SECONDS = 45 * 60
DEFAULT_COLD_RECOVERY_PROOF_MAX_AGE_SECONDS = 9 * 60 * 60
DEFERRED_WEB_RESTART_GRACE_SECONDS = 60
BAD_WRAPPER_NEEDLES = (
    "earlybird_codex",
    "housebot_codex",
    "/opt/agent-console",
    "/usr/local/lib/norman-codex",
)
OWNER_WRAPPER_ALLOWLIST = {
    "earlybird": ("earlybird_codex",),
    "housebot": ("housebot_codex",),
}
RECOVERY_HINTS = {
    "work-special": (
        "recovery available: scripts/tui_host_recovery.py --target work-special "
        "(plan only); after operator approval use --execute --approved"
    ),
}
PRESSURE_THRESHOLDS = {
    "cpu_some": (70.0, 90.0),
    "io_some": (50.0, 80.0),
    "mem_some": (35.0, 60.0),
}
PRESSURE_ALIASES = {
    "cpu_some": ("cpu_some", "pressurecpusome"),
    "io_some": ("io_some", "pressureiosome"),
    "mem_some": ("mem_some", "memory_some", "pressurememorysome"),
}
PREFLIGHT_BLOCKED_MARKER = "tui release preflight blocked this route"
WORKFLOW_HEALTH_SCHEMA = "openbrand.system-health.workflow.v1"
APPROVED_PUBLIC_STATUS_COMPONENTS = (
    "Platform Access",
    "Dashboards",
    "Data API",
    "Pricing & Availability Data",
    "Product Content Data",
    "Scheduled Reports",
    "File Deliveries",
)


@dataclass(frozen=True)
class DoctorIssue:
    severity: str
    host: str
    instance: str
    check: str
    detail: str


@dataclass(frozen=True)
class HostReport:
    host: str
    active_count: int
    expected_count: int
    issues: list[DoctorIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "fail" for issue in self.issues)


def _first_line(value: str) -> str:
    return next((line.strip() for line in value.splitlines() if line.strip()), "")


def _tcp_probe(host: str, port: int, *, timeout: float = 2.0) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            if port in {
                80,
                8781,
                8782,
                8783,
                8784,
                8785,
                8786,
                8787,
                8789,
                8790,
                8791,
                8792,
                8793,
            }:
                sock.sendall(f"GET / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
            try:
                data = sock.recv(64)
            except socket.timeout:
                label = "HTTP bytes" if port != 22 else "SSH banner"
                return f"{host}:{port} connected; no {label} within {timeout:g}s"
            return f"{host}:{port} responded" if data else f"{host}:{port} closed"
    except socket.timeout:
        return f"{host}:{port} TCP timeout"
    except OSError as exc:
        return f"{host}:{port} {type(exc).__name__}: {_first_line(str(exc))}"


def _host_reachability_summary(host: sync.DiscoveryHost) -> str:
    candidates = []
    for value in (host.lan_host, host.public_host, *host.alias_hosts):
        if value and value not in candidates:
            candidates.append(value)
    probes: list[str] = []
    for name in candidates[:3]:
        probes.append(_tcp_probe(name, 22))
    if host.public_host:
        probes.append(_tcp_probe(host.public_host, 80))
    return "; ".join(probes)


def summarize_scan_failure(host: sync.DiscoveryHost, exc: Exception) -> str:
    stderr = str(getattr(exc, "stderr", "") or "")
    stdout = str(getattr(exc, "stdout", "") or "")
    raw = "\n".join(part for part in (stderr, stdout, str(exc)) if part.strip())
    lowered = raw.lower()
    if "timed out during banner exchange" in lowered:
        reason = "SSH banner timeout"
    elif "connection timed out" in lowered and "port 22" in lowered:
        reason = "SSH connect timeout"
    elif "permission denied" in lowered:
        reason = "SSH permission denied"
    elif isinstance(exc, subprocess.CalledProcessError):
        reason = f"remote scan exited {exc.returncode}"
    else:
        reason = _first_line(str(exc)) or type(exc).__name__

    detail = f"{type(exc).__name__}: {reason}"
    reachability = _host_reachability_summary(host)
    if reachability:
        detail = f"{detail}; reachability: {reachability}"
    recovery_hint = RECOVERY_HINTS.get(host.name)
    if recovery_hint:
        detail = f"{detail}; {recovery_hint}"
    return detail[:900]


def expected_ui_version() -> str:
    source = sync.SOURCE_FILES["web"].read_text(encoding="utf-8")
    match = re.search(r'DEFAULT_UI_VERSION\s*=\s*"([^"]+)"', source)
    if not match:
        raise RuntimeError("DEFAULT_UI_VERSION not found in agent console template")
    return match.group(1)


def _coerce_timeout(value: Any) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return 15 * 60


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(str(value or "0").strip()))
    except (TypeError, ValueError):
        return 0


def _coerce_nonnegative_float(value: Any) -> float:
    try:
        return max(0.0, float(str(value or "0").strip()))
    except (TypeError, ValueError):
        return 0.0


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _state_text(status: dict[str, Any]) -> str:
    return str(status.get("state") or status.get("status") or "").strip().lower()


def _has_liveness_fields(status: dict[str, Any]) -> bool:
    return "web_worker_alive" in status or "model_process_alive" in status


def _has_live_process(status: dict[str, Any]) -> bool:
    return _is_truthy(status.get("web_worker_alive")) or _is_truthy(
        status.get("model_process_alive")
    )


def _active_child_pid(status: dict[str, Any]) -> int:
    return _coerce_nonnegative_int(status.get("active_child_pid"))


def _status_has_stale_child_ref(status: dict[str, Any]) -> bool:
    if _is_truthy(status.get("pending")):
        return False
    if _active_child_pid(status) <= 0:
        return False
    if not _has_liveness_fields(status) or _has_live_process(status):
        return False
    return _state_text(status) in {"", "ok", "ready", "idle", "complete", "completed"}


def _status_is_busy(status: dict[str, Any]) -> bool:
    if _is_truthy(status.get("pending")):
        return True
    state = _state_text(status)
    if state in {"active", "busy", "running"}:
        return True
    if _active_child_pid(status) <= 0:
        return False
    return not _status_has_stale_child_ref(status)


def _status_has_active_prompt(status: dict[str, Any]) -> bool:
    if _is_truthy(status.get("pending")):
        return True
    if _active_child_pid(status) <= 0:
        return False
    return not _status_has_stale_child_ref(status)


def _stale_preflight_failure_recovered(
    row: dict[str, Any], status: dict[str, Any]
) -> bool:
    if str(row.get("preflight_probe") or "").strip().lower() != "ready":
        return False
    if _is_truthy(status.get("pending")) or _status_has_active_prompt(status):
        return False
    auth = status.get("auth")
    if isinstance(auth, dict) and _is_truthy(auth.get("required")):
        return False
    last_error = str(status.get("last_error") or "").strip().lower()
    return not last_error or PREFLIGHT_BLOCKED_MARKER in last_error


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    if seconds >= 3600:
        hours = seconds / 3600
        return f"{hours:.1f}h" if seconds % 3600 else f"{seconds // 3600}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _running_started_at(status: dict[str, Any]) -> int:
    return _coerce_nonnegative_int(
        status.get("active_child_started_at") or status.get("last_started_at")
    )


def _running_budget_seconds(status: dict[str, Any]) -> int:
    return _coerce_nonnegative_int(status.get("running_timeout_seconds"))


def _busy_runtime_detail(status: dict[str, Any], *, now: int | None = None) -> str:
    parts = ["busy/running"]
    started_at = _running_started_at(status)
    observed_at = int(time.time()) if now is None else int(now)
    elapsed = max(0, observed_at - started_at) if started_at else 0
    budget = _running_budget_seconds(status)
    job_budget = str(status.get("running_job_budget") or "").strip()
    if elapsed:
        parts.append(f"{_format_duration(elapsed)} elapsed")
    if budget:
        parts.append(f"{_format_duration(budget)} budget")
    if job_budget:
        parts.append(f"budget={job_budget}")
    return " · ".join(parts)


def _running_exceeded_budget(status: dict[str, Any], *, now: int | None = None) -> bool:
    started_at = _running_started_at(status)
    budget = _running_budget_seconds(status)
    if not started_at or not budget:
        return False
    observed_at = int(time.time()) if now is None else int(now)
    return observed_at - started_at > budget + 300


def _pending_prompt_liveness_grace(
    status: dict[str, Any], *, now: int | None = None
) -> bool:
    """Allow a bounded tmux-owned prompt to report liveness on its next poll."""
    if not _is_truthy(status.get("pending")) or _has_liveness_fields(status):
        return False
    if _active_child_pid(status) > 0:
        return False
    if str(status.get("last_error") or "").strip():
        return False
    started_at = _running_started_at(status)
    budget = _running_budget_seconds(status)
    if not started_at or not budget:
        return False
    return not _running_exceeded_budget(status, now=now)


def _bad_refs_for_instance(name: str, stale_refs: list[str]) -> list[str]:
    allowed = OWNER_WRAPPER_ALLOWLIST.get(name, ())
    bad: list[str] = []
    for ref in stale_refs:
        if any(needle in ref for needle in allowed):
            continue
        bad.append(ref)
    return bad


def _host_pressure_from_rows(active_rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in active_rows:
        pressure = row.get("host_pressure")
        if isinstance(pressure, dict):
            return pressure
    return {}


def _pressure_value(pressure: dict[str, Any], key: str) -> float:
    for alias in PRESSURE_ALIASES[key]:
        if alias in pressure:
            return _coerce_nonnegative_float(pressure.get(alias))
    return 0.0


def _host_pressure_issue(
    host_name: str, pressure: dict[str, Any]
) -> DoctorIssue | None:
    if not pressure:
        return None
    warn_parts: list[str] = []
    fail_parts: list[str] = []
    observed_parts: list[str] = []
    for key, (warn_threshold, fail_threshold) in PRESSURE_THRESHOLDS.items():
        value = _pressure_value(pressure, key)
        if value <= 0:
            continue
        observed_parts.append(f"{key}={value:.2f}")
        if value >= fail_threshold:
            fail_parts.append(f"{key}={value:.2f} >= critical {fail_threshold:.0f}")
        elif value >= warn_threshold:
            warn_parts.append(f"{key}={value:.2f} >= warn {warn_threshold:.0f}")
    if not fail_parts and not warn_parts:
        return None
    severity = "fail" if fail_parts else "warn"
    state = "critical host pressure" if fail_parts else "elevated host pressure"
    detail_parts = [state, *(fail_parts or warn_parts)]
    if observed_parts:
        detail_parts.append("observed " + " ".join(observed_parts))
    recovery_hint = RECOVERY_HINTS.get(host_name)
    if recovery_hint:
        detail_parts.append(recovery_hint)
    return DoctorIssue(
        severity,
        host_name,
        "<host>",
        "host-pressure",
        "; ".join(detail_parts),
    )


def _web_restart_issue(
    host_name: str,
    instance_name: str,
    status: dict[str, Any],
    *,
    now: int,
) -> DoctorIssue | None:
    if not _is_truthy(status.get("web_restart_required")):
        return None

    reason = str(
        status.get("web_restart_reason")
        or "console web script changed after this process started"
    ).strip()
    deferred_at = _coerce_nonnegative_int(status.get("web_restart_deferred_at"))
    deadline_at = _coerce_nonnegative_int(
        status.get("web_restart_deferred_deadline_at")
    )
    expired_at = _coerce_nonnegative_int(status.get("web_restart_deferred_expired_at"))
    max_wait_seconds = _coerce_nonnegative_int(
        status.get("web_restart_deferred_max_wait_seconds")
    )
    if deferred_at > 0 and deadline_at <= deferred_at:
        deadline_at = deferred_at + max_wait_seconds
    age_seconds = max(0, now - deferred_at) if deferred_at > 0 else 0
    if expired_at > 0:
        elapsed = max(0, now - expired_at)
        return DoctorIssue(
            "fail",
            host_name,
            instance_name,
            "web-restart-expired",
            (
                f"deferred web restart expired {elapsed}s ago; staged UI remains "
                f"unapplied ({reason})"
            ),
        )
    if _is_truthy(status.get("web_restart_deferred")) and deferred_at > 0:
        wait_seconds = max(30, deadline_at - deferred_at)
        busy_reasons = status.get("busy_reasons")
        if isinstance(busy_reasons, list):
            busy_detail = ",".join(
                str(item).strip() for item in busy_reasons if str(item).strip()
            )
        else:
            busy_detail = ""
        if age_seconds > wait_seconds + DEFERRED_WEB_RESTART_GRACE_SECONDS:
            return DoctorIssue(
                "fail",
                host_name,
                instance_name,
                "web-restart-deferred",
                (
                    f"deferred web restart exceeded its {wait_seconds}s safety "
                    f"window by {age_seconds - wait_seconds}s ({reason})"
                ),
            )
        suffix = f"; busy={busy_detail}" if busy_detail else ""
        return DoctorIssue(
            "warn",
            host_name,
            instance_name,
            "web-restart-deferred",
            (
                f"deferred web restart waiting {age_seconds}s/{wait_seconds}s"
                f"{suffix} ({reason})"
            ),
        )
    return DoctorIssue("warn", host_name, instance_name, "web-restart", reason)


def analyze_host(
    *,
    host_name: str,
    expected_names: set[str],
    active_rows: list[dict[str, Any]],
    archived_names: set[str],
    min_timeout_seconds: int,
    ui_version: str,
    now: int | None = None,
) -> HostReport:
    observed_at = int(time.time()) if now is None else int(now)
    issues: list[DoctorIssue] = []
    active_names = {str(row.get("name") or "") for row in active_rows}
    pressure_issue = _host_pressure_issue(
        host_name, _host_pressure_from_rows(active_rows)
    )
    if pressure_issue is not None:
        issues.append(pressure_issue)

    for row in sorted(active_rows, key=lambda item: str(item.get("name") or "")):
        name = str(row.get("name") or "").strip()
        if not name:
            issues.append(
                DoctorIssue("fail", host_name, "<unknown>", "identity", "missing name")
            )
            continue

        if name in archived_names:
            issues.append(
                DoctorIssue(
                    "fail",
                    host_name,
                    name,
                    "inventory",
                    "archived instance is active",
                )
            )
        elif name not in expected_names:
            issues.append(
                DoctorIssue(
                    "fail",
                    host_name,
                    name,
                    "inventory",
                    "active instance missing from sync inventory",
                )
            )

        bad_refs = _bad_refs_for_instance(
            name, [str(ref) for ref in row.get("stale_refs") or []]
        )
        for ref in bad_refs:
            issues.append(DoctorIssue("fail", host_name, name, "wrapper-path", ref))

        timeout = _coerce_timeout(row.get("timeout"))
        if timeout < min_timeout_seconds:
            issues.append(
                DoctorIssue(
                    "fail",
                    host_name,
                    name,
                    "timeout",
                    f"{timeout}s below floor {min_timeout_seconds}s",
                )
            )

        status_error = str(row.get("status_error") or "").strip()
        status = row.get("status") if isinstance(row.get("status"), dict) else {}
        if status_error:
            issues.append(DoctorIssue("fail", host_name, name, "status", status_error))
            continue

        restart_issue = _web_restart_issue(host_name, name, status, now=observed_at)
        version = str(row.get("ui_version") or "").strip()
        if version != ui_version:
            severity = restart_issue.severity if restart_issue is not None else "fail"
            issues.append(
                DoctorIssue(
                    severity,
                    host_name,
                    name,
                    "ui-version",
                    f"{version or 'missing'} != {ui_version}",
                )
            )

        auth = status.get("auth") if isinstance(status, dict) else {}
        auth_required = isinstance(auth, dict) and _is_truthy(auth.get("required"))
        if auth_required:
            summary = str(auth.get("summary") or "auth required").strip()
            issues.append(DoctorIssue("fail", host_name, name, "auth", summary))

        if restart_issue is not None:
            issues.append(restart_issue)

        queue_depth = _coerce_nonnegative_int(status.get("queue_depth"))
        pending = _is_truthy(status.get("pending"))
        active_child_pid = _active_child_pid(status)
        active_prompt = _status_has_active_prompt(status)
        if queue_depth and not active_prompt:
            if _is_truthy(status.get("stale_queue")):
                issues.append(
                    DoctorIssue(
                        "warn",
                        host_name,
                        name,
                        "queue",
                        f"recovered queue requires review: {queue_depth} queued",
                    )
                )
            else:
                issues.append(
                    DoctorIssue(
                        "fail",
                        host_name,
                        name,
                        "queue",
                        f"queue has {queue_depth} item(s) but no prompt is running",
                    )
                )

        if (
            pending
            and (active_child_pid <= 0 or _has_liveness_fields(status))
            and not _has_live_process(status)
            and not _pending_prompt_liveness_grace(status)
        ):
            issues.append(
                DoctorIssue(
                    "fail",
                    host_name,
                    name,
                    "runtime",
                    "pending prompt has no live web worker or model process",
                )
            )

        if _status_has_stale_child_ref(status):
            issues.append(
                DoctorIssue(
                    "warn",
                    host_name,
                    name,
                    "runtime",
                    f"stale active_child_pid={active_child_pid} with no live worker/model process",
                )
            )

        state = _state_text(status)
        last_error = str(status.get("last_error") or "").strip()
        if state in {"error", "failed"}:
            if _stale_preflight_failure_recovered(row, status):
                continue
            if auth_required or _status_has_active_prompt(status):
                issues.append(
                    DoctorIssue("fail", host_name, name, "runtime", f"state={state}")
                )
            else:
                detail = last_error or f"state={state}"
                issues.append(
                    DoctorIssue(
                        "warn",
                        host_name,
                        name,
                        "runtime",
                        f"last prompt failed: {detail}",
                    )
                )
        elif last_error:
            issues.append(
                DoctorIssue(
                    "warn",
                    host_name,
                    name,
                    "runtime",
                    "last_error present while state is not failed",
                )
            )
        elif _status_is_busy(status):
            busy_detail = _busy_runtime_detail(status)
            busy_severity = "fail" if _running_exceeded_budget(status) else "warn"
            issues.append(
                DoctorIssue(busy_severity, host_name, name, "runtime", busy_detail)
            )

    for missing in sorted(expected_names - active_names):
        issues.append(
            DoctorIssue(
                "fail",
                host_name,
                missing,
                "service",
                "expected instance is not active",
            )
        )

    return HostReport(
        host=host_name,
        active_count=len(active_rows),
        expected_count=len(expected_names),
        issues=issues,
    )


def remote_scan_script(patterns: tuple[str, ...]) -> str:
    payload = json.dumps(list(patterns), separators=(",", ":"))
    default_launchers = json.dumps(sync.DEFAULT_LAUNCHERS, separators=(",", ":"))
    needles = json.dumps(BAD_WRAPPER_NEEDLES, separators=(",", ":"))
    return f"""
python3 - <<'PY'
import glob
import json
import os
import pwd
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

patterns = json.loads({payload!r})
default_launchers = json.loads({default_launchers!r})
needles = json.loads({needles!r})


def parse_env(path):
    env = {{}}
    try:
        text = Path(path).read_text(errors="replace")
    except Exception:
        return None, ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'\\\"")
    return env, text


def env_get(env, config_key, default=""):
    canonical_key = config_key
    legacy_key = config_key
    if config_key.startswith("HOUSEBOT_CODEX_"):
        canonical_key = "NORMAN_CODEX_" + config_key[len("HOUSEBOT_CODEX_"):]
    elif config_key.startswith("NORMAN_CODEX_"):
        legacy_key = "HOUSEBOT_CODEX_" + config_key[len("NORMAN_CODEX_"):]
    value = env.get(canonical_key)
    if value not in (None, ""):
        return value
    value = env.get(legacy_key)
    if value not in (None, ""):
        return value
    return default


def infer_name(path):
    base = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path))
    if base == "codex-web.env" and parent and parent != "net-agents":
        return parent
    return os.path.splitext(base)[0]


def is_active(unit):
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", unit],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return "unknown"
    return (proc.stdout or "").strip()


def fetch_status(port, token):
    if not port:
        return {{}}, "missing web port"
    query = "?" + urllib.parse.urlencode({{"token": token}}) if token else ""
    readiness_url = f"http://127.0.0.1:{{port}}/api/restart-readiness{{query}}"
    status_url = f"http://127.0.0.1:{{port}}/api/status{{query}}"
    try:
        with urllib.request.urlopen(status_url, timeout=4) as response:
            return json.loads(response.read().decode("utf-8") or "{{}}"), ""
    except Exception as status_exc:
        try:
            with urllib.request.urlopen(
                readiness_url, timeout=4
            ) as response:
                return json.loads(response.read().decode("utf-8") or "{{}}"), ""
        except Exception as readiness_exc:
            detail = (
                "status "
                + type(status_exc).__name__
                + ": "
                + str(status_exc)
                + "; readiness "
                + type(readiness_exc).__name__
                + ": "
                + str(readiness_exc)
            )
            return {{}}, detail


def _service_user(unit):
    try:
        proc = subprocess.run(
            ["systemctl", "show", unit, "--property=User", "--value"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception:
        return "root"
    return (proc.stdout or "").strip() or "root"


def release_preflight_probe(env, web_unit):
    script = env_get(env, "NORMAN_CODEX_PREFLIGHT_SCRIPT").strip()
    codex_home = env_get(env, "NORMAN_CODEX_HOME").strip()
    if not script or not codex_home or not Path(script).is_file():
        return "unavailable"
    try:
        timeout_seconds = max(
            0.2, float(env_get(env, "NORMAN_CODEX_PREFLIGHT_TIMEOUT_SECONDS", "10"))
        )
    except (TypeError, ValueError):
        timeout_seconds = 10.0
    service_user = _service_user(web_unit)
    launch_env = dict(os.environ)
    launch_env.update({{str(key): str(value) for key, value in env.items()}})
    launch_env["CODEX_HOME"] = codex_home
    run_kwargs = {{
        "text": True,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "timeout": max(5.0, timeout_seconds + 3.0),
        "check": False,
        "env": launch_env,
    }}
    if service_user != "root":
        try:
            account = pwd.getpwnam(service_user)
        except KeyError:
            return "unavailable"
        launch_env["HOME"] = account.pw_dir
        run_kwargs["user"] = account.pw_uid
        run_kwargs["group"] = account.pw_gid
    command = [
        sys.executable,
        script,
        "--codex-home",
        codex_home,
        "--service-tier",
        env_get(env, "NORMAN_CODEX_SERVICE_TIER", "default"),
        "--timeout-seconds",
        str(timeout_seconds),
        "--quiet",
        "--fail-on-blocker",
    ]
    try:
        completed = subprocess.run(command, **run_kwargs)
    except Exception:
        return "unavailable"
    return "ready" if completed.returncode == 0 else "blocked"


def fetch_ui_version(port, token, status):
    version = str(status.get("ui_version") or "").strip()
    if version:
        return version
    if not port:
        return ""
    query = "?" + urllib.parse.urlencode({{"token": token}}) if token else ""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{{port}}/api/version{{query}}", timeout=4
        ) as response:
            payload = json.loads(response.read().decode("utf-8") or "{{}}")
        version = str(payload.get("ui_version") or "").strip()
        if version:
            return version
    except Exception:
        pass
    try:
        opener = urllib.request.build_opener()
        with opener.open(f"http://127.0.0.1:{{port}}/{{query}}", timeout=4) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    match = re.search(r'class="version-chip"[^>]*>UI v([^<]+)<', html)
    if not match:
        match = re.search(r"UI v([0-9.]+)", html)
    return match.group(1).strip() if match else ""


def stale_refs(paths):
    refs = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            for needle in needles:
                if needle in line:
                    refs.append(f"{{path}}:{{needle}}:{{line.strip()}}")
    return refs


def pressure_some(path):
    try:
        text = Path(path).read_text(errors="replace")
    except Exception:
        return 0.0
    for line in text.splitlines():
        if not line.startswith("some "):
            continue
        match = re.search(r"avg10=([0-9.]+)", line)
        if match:
            return float(match.group(1))
    return 0.0


host_pressure = {{
    "cpu_some": pressure_some("/proc/pressure/cpu"),
    "io_some": pressure_some("/proc/pressure/io"),
    "mem_some": pressure_some("/proc/pressure/memory"),
}}


rows = []
seen = set()
for pattern in patterns:
    for env_path in sorted(glob.glob(pattern)):
        if env_path in seen:
            continue
        seen.add(env_path)
        env, _ = parse_env(env_path)
        if env is None or not any(
            key.startswith(("NORMAN_CODEX", "HOUSEBOT_CODEX")) for key in env
        ):
            continue
        name = infer_name(env_path)
        codex_unit = (
            env_get(env, "NORMAN_CODEX_SERVICE_NAME", f"{{name}}-codex.service")
        ).strip()
        web_unit = (
            env_get(
                env, "NORMAN_CODEX_WEB_SERVICE_NAME", f"{{name}}-codex-web.service"
            )
        ).strip()
        codex_active = is_active(codex_unit)
        web_active = is_active(web_unit)
        if codex_active != "active" and web_active != "active":
            continue
        port = (env_get(env, "NORMAN_CODEX_WEB_PORT") or "").strip()
        token = (env_get(env, "NORMAN_CODEX_WEB_TOKEN") or "").strip()
        status, status_error = fetch_status(port, token)
        preflight_probe = ""
        if (
            not status_error
            and isinstance(status, dict)
            and str(status.get("state") or status.get("status") or "").strip().lower()
            in {{"error", "failed"}}
            and str(status.get("pending") or "").strip().lower()
            not in {{"1", "true", "yes", "on"}}
        ):
            preflight_probe = release_preflight_probe(env, web_unit)
        launch_path = (
            env_get(env, "NORMAN_CODEX_LAUNCHER", default_launchers.get(name, ""))
        ).strip()
        rows.append(
            {{
                "name": name,
                "env_file": env_path,
                "launcher": launch_path,
                "timeout": (
                    env_get(env, "NORMAN_CODEX_WEB_PROMPT_TIMEOUT_SECONDS") or ""
                ).strip(),
                "codex_unit": codex_unit,
                "web_unit": web_unit,
                "codex_active": codex_active,
                "web_active": web_active,
                "status": status,
                "status_error": status_error,
                "preflight_probe": preflight_probe,
                "host_pressure": host_pressure,
                "ui_version": fetch_ui_version(port, token, status),
                "stale_refs": stale_refs([
                    env_path,
                    os.path.join("/etc/systemd/system", codex_unit),
                    os.path.join("/etc/systemd/system", web_unit),
                ]),
            }}
        )

print(json.dumps(rows, sort_keys=True))
PY
"""


def scan_host(host: sync.DiscoveryHost) -> list[dict[str, Any]]:
    raw = sync.capture(sync.ssh_command(host, remote_scan_script(host.env_globs)))
    data = json.loads(raw or "[]")
    if not isinstance(data, list):
        raise RuntimeError(f"{host.name}: doctor scan did not return a list")
    return [row for row in data if isinstance(row, dict)]


def route_proof_report(
    path: Path, *, max_age_seconds: int, now: int | None = None
) -> HostReport:
    observed_at = int(time.time()) if now is None else int(now)
    issues: list[DoctorIssue] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {}
        issues.append(
            DoctorIssue(
                "fail",
                "norman",
                "<fleet-canary>",
                "route-proof",
                "scheduled live route proof is missing",
            )
        )
    except (OSError, json.JSONDecodeError):
        payload = {}
        issues.append(
            DoctorIssue(
                "fail",
                "norman",
                "<fleet-canary>",
                "route-proof",
                "scheduled live route proof is unreadable",
            )
        )
    if payload:
        generated_at = _coerce_nonnegative_int(payload.get("generated_at"))
        if not payload.get("live"):
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "route-proof",
                    "latest route proof was not live",
                )
            )
        if not generated_at or observed_at - generated_at > max(0, max_age_seconds):
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "route-proof",
                    "scheduled live route proof is stale",
                )
            )
        summary = (
            payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        )
        passed = _coerce_nonnegative_int(summary.get("passed"))
        targets = _coerce_nonnegative_int(summary.get("targets"))
        failed = _coerce_nonnegative_int(summary.get("failed"))
        if not targets or failed or passed != targets:
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "route-proof",
                    (
                        "live route proof failed: "
                        f"passed={passed} targets={targets} failed={failed}"
                    ),
                )
            )
        if summary.get("named_codexspark_access_check_contract_ok") is not True:
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "route-proof",
                    "codexspark no longer has access-check-only semantics",
                )
            )
        scorecard = (
            summary.get("route_scorecard")
            if isinstance(summary.get("route_scorecard"), dict)
            else {}
        )
        observed_turns = _coerce_nonnegative_int(scorecard.get("observed_turns"))
        if not scorecard or observed_turns < passed:
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "route-proof",
                    (
                        "route scorecard is missing completed-turn evidence: "
                        f"observed={observed_turns} passed={passed}"
                    ),
                )
            )
    return HostReport(
        host="norman",
        active_count=0,
        expected_count=0,
        issues=issues,
    )


def cold_recovery_proof_report(
    path: Path, *, max_age_seconds: int, now: int | None = None
) -> HostReport:
    observed_at = int(time.time()) if now is None else int(now)
    issues: list[DoctorIssue] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {}
        issues.append(
            DoctorIssue(
                "fail",
                "norman",
                "<fleet-canary>",
                "cold-recovery-proof",
                "scheduled no-inference cold-recovery drill is missing",
            )
        )
    except (OSError, json.JSONDecodeError):
        payload = {}
        issues.append(
            DoctorIssue(
                "fail",
                "norman",
                "<fleet-canary>",
                "cold-recovery-proof",
                "scheduled no-inference cold-recovery drill is unreadable",
            )
        )
    if payload:
        generated_at = _coerce_nonnegative_int(payload.get("generated_at"))
        if (
            payload.get("live")
            or str(payload.get("mode") or "") != "cold-recovery-drill"
        ):
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "cold-recovery-proof",
                    "latest cold-recovery evidence was not an isolated no-inference drill",
                )
            )
        if not generated_at or observed_at - generated_at > max(0, max_age_seconds):
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "cold-recovery-proof",
                    "scheduled no-inference cold-recovery drill is stale",
                )
            )
        summary = (
            payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        )
        passed = _coerce_nonnegative_int(summary.get("passed"))
        targets = _coerce_nonnegative_int(summary.get("targets"))
        failed = _coerce_nonnegative_int(summary.get("failed"))
        if not targets or failed or passed != targets:
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "cold-recovery-proof",
                    (
                        "no-inference cold-recovery drill failed: "
                        f"passed={passed} targets={targets} failed={failed}"
                    ),
                )
            )
        if summary.get("isolated_no_inference") is not True:
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "cold-recovery-proof",
                    "cold-recovery drill did not retain its no-inference invariant",
                )
            )
        if summary.get("stale_timeout_recovery_verified") is not True:
            issues.append(
                DoctorIssue(
                    "fail",
                    "norman",
                    "<fleet-canary>",
                    "cold-recovery-proof",
                    "stale planner timeout recovery was not verified",
                )
            )
    return HostReport(
        host="norman",
        active_count=0,
        expected_count=0,
        issues=issues,
    )


def build_reports(
    *,
    targets: list[str] | None,
    min_timeout_seconds: int,
    ui_version: str,
    route_proof_json: Path | None = None,
    route_proof_max_age_seconds: int = DEFAULT_ROUTE_PROOF_MAX_AGE_SECONDS,
    cold_recovery_proof_json: Path | None = None,
    cold_recovery_proof_max_age_seconds: int = (
        DEFAULT_COLD_RECOVERY_PROOF_MAX_AGE_SECONDS
    ),
) -> list[HostReport]:
    requested_targets = targets or list(sync.HOSTS)
    discovery_targets = requested_targets
    if targets is None and DEFAULT_NO_CONSOLE_SCAN_HOSTS:
        discovery_targets = [
            target
            for target in requested_targets
            if target not in DEFAULT_NO_CONSOLE_SCAN_HOSTS
        ]
    discovered_by_host, _ = sync.discover_all_instances(discovery_targets)
    selected_hosts = (
        list(sync.HOSTS)
        if targets is None
        else [host_name for host_name in discovered_by_host if host_name in sync.HOSTS]
    )

    reports: list[HostReport] = []
    for host_name in selected_hosts:
        if (
            targets is None
            and host_name in DEFAULT_NO_CONSOLE_SCAN_HOSTS
            and host_name not in discovered_by_host
        ):
            reports.append(
                HostReport(
                    host=host_name,
                    active_count=0,
                    expected_count=0,
                    issues=[],
                )
            )
            continue
        host = sync.HOSTS[host_name]
        expected_names = {
            instance.name for instance in discovered_by_host.get(host_name, [])
        }
        try:
            active_rows = scan_host(host)
        except Exception as exc:
            reports.append(
                HostReport(
                    host=host_name,
                    active_count=0,
                    expected_count=len(expected_names),
                    issues=[
                        DoctorIssue(
                            "fail",
                            host_name,
                            "<host>",
                            "scan",
                            summarize_scan_failure(host, exc),
                        )
                    ],
                )
            )
            continue
        reports.append(
            analyze_host(
                host_name=host_name,
                expected_names=expected_names,
                active_rows=active_rows,
                archived_names=set(sync.ARCHIVED_INSTANCE_NAMES),
                min_timeout_seconds=min_timeout_seconds,
                ui_version=ui_version,
            )
        )
    if route_proof_json is not None:
        reports.append(
            route_proof_report(
                route_proof_json,
                max_age_seconds=max(0, int(route_proof_max_age_seconds)),
            )
        )
    if cold_recovery_proof_json is not None:
        reports.append(
            cold_recovery_proof_report(
                cold_recovery_proof_json,
                max_age_seconds=max(0, int(cold_recovery_proof_max_age_seconds)),
            )
        )
    return reports


def deployment_closure_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    mismatch_count = sum(1 for issue in issues if issue.get("check") == "ui-version")
    staged_count = sum(
        1
        for issue in issues
        if issue.get("check")
        in {"web-restart", "web-restart-deferred", "web-restart-expired"}
    )
    deferred_count = sum(
        1 for issue in issues if issue.get("check") == "web-restart-deferred"
    )
    expired_count = sum(
        1 for issue in issues if issue.get("check") == "web-restart-expired"
    )
    return {
        "ready": mismatch_count == 0 and staged_count == 0,
        "version_mismatch": mismatch_count,
        "restart_staged": staged_count,
        "restart_deferred": deferred_count,
        "restart_expired": expired_count,
    }


def workflow_health_payload() -> dict[str, Any]:
    controls = [
        {
            "id": "openbrand_webgoat_staging_boundary_control",
            "label": "WebGOAT source-to-GAPI boundary",
            "lifecycle": "staged",
            "deployment_state": "not_deployed",
            "visibility": "private",
            "live_status_source": False,
            "public_status_eligible": False,
            "write_boundary": "no_gapi_product_placement_or_price_writes",
            "operator_handling": "private_source_evidence_review",
        },
        {
            "id": "openbrand_product_placement_recovery_control",
            "label": "Product placement recovery",
            "lifecycle": "staged",
            "deployment_state": "not_deployed",
            "visibility": "private",
            "live_status_source": False,
            "public_status_eligible": False,
            "write_boundary": "guarded_gapi_npm_and_product_only_npc_writes",
            "operator_handling": "private_system_health_event_required",
        },
        {
            "id": "openbrand_category_launch_coverage_flash",
            "label": "Category launch coverage flash",
            "lifecycle": "staged",
            "deployment_state": "not_deployed",
            "visibility": "private",
            "live_status_source": False,
            "public_status_eligible": False,
            "write_boundary": "no_gapi_or_webgoat_writes",
            "operator_handling": "private_system_health_event_required",
        },
    ]
    return {
        "schema": WORKFLOW_HEALTH_SCHEMA,
        "visibility": "private",
        "summary": {
            "controls": len(controls),
            "staged": len(controls),
            "not_deployed": len(controls),
            "live_status_sources": 0,
        },
        "public_status": {
            "incident_eligible": False,
            "requires_verified_customer_impact": True,
            "approved_components": list(APPROVED_PUBLIC_STATUS_COMPONENTS),
        },
        "controls": controls,
    }


def build_payload(
    reports: list[HostReport], ui_version: str, *, checked_at: str | None = None
) -> dict[str, Any]:
    checked_at = checked_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    issues = [asdict(issue) for report in reports for issue in report.issues]
    fail_count = sum(1 for issue in issues if issue["severity"] == "fail")
    warn_count = sum(1 for issue in issues if issue["severity"] == "warn")
    active_count = sum(report.active_count for report in reports)
    expected_count = sum(report.expected_count for report in reports)
    status = "fail" if fail_count else "warn" if warn_count else "ok"

    return {
        "available": True,
        "status": status,
        "checked_at": checked_at,
        "expected_ui_version": ui_version,
        "summary": {
            "active": active_count,
            "expected": expected_count,
            "fail": fail_count,
            "warn": warn_count,
            "hosts": len(reports),
            "ok": fail_count == 0,
        },
        "deployment_closure": deployment_closure_summary(issues),
        "workflow_health": workflow_health_payload(),
        "hosts": [
            {
                "host": report.host,
                "active_count": report.active_count,
                "expected_count": report.expected_count,
                "ok": report.ok,
                "fail_count": sum(
                    1 for issue in report.issues if issue.severity == "fail"
                ),
                "warn_count": sum(
                    1 for issue in report.issues if issue.severity == "warn"
                ),
                "issues": [asdict(issue) for issue in report.issues],
            }
            for report in reports
        ],
        "issues": issues,
    }


def render_markdown(
    reports: list[HostReport], ui_version: str, *, checked_at: str | None = None
) -> str:
    fail_count = sum(
        1 for report in reports for issue in report.issues if issue.severity == "fail"
    )
    warn_count = sum(
        1 for report in reports for issue in report.issues if issue.severity == "warn"
    )
    active_count = sum(report.active_count for report in reports)
    checked_at = checked_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    issues = [issue for report in reports for issue in report.issues]
    deployment = deployment_closure_summary([asdict(issue) for issue in issues])
    workflow_health = workflow_health_payload()
    lines = [
        "# TUI Fleet Doctor",
        "",
        f"Checked at: `{checked_at}`",
        f"Expected UI version: `{ui_version}`",
        "",
        f"Summary: active={active_count}, fail={fail_count}, warn={warn_count}",
        (
            "Deployment closure: "
            f"ready={str(bool(deployment['ready'])).lower()}, "
            f"version-mismatch={deployment['version_mismatch']}, "
            f"staged={deployment['restart_staged']}, "
            f"deferred={deployment['restart_deferred']}, "
            f"expired={deployment['restart_expired']}"
        ),
        "",
        "Workflow controls: private operator health only. Staged controls do not "
        "affect fleet status or public availability.",
        "",
        "| Workflow control | State | Visibility | Live status source | Write boundary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for control in workflow_health["controls"]:
        lines.append(
            "| {label} | {state} | {visibility} | {live} | {boundary} |".format(
                label=control["label"],
                state=control["deployment_state"],
                visibility=control["visibility"],
                live=str(bool(control["live_status_source"])).lower(),
                boundary=control["write_boundary"],
            )
        )
    lines.extend(
        [
            "",
            "| Severity | Host | TUI | Check | Detail |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if not issues:
        lines.append("| ok | all | all | all | clear |")
    for issue in sorted(
        issues, key=lambda item: (item.severity, item.host, item.instance, item.check)
    ):
        lines.append(
            "| {severity} | {host} | {instance} | {check} | {detail} |".format(
                severity=issue.severity,
                host=issue.host,
                instance=issue.instance.replace("|", "\\|"),
                check=issue.check,
                detail=issue.detail.replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect drift in deployed Norman TUI env/unit/template state."
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=None,
        help="Hosts to check. Defaults to every sync host.",
    )
    parser.add_argument(
        "--min-timeout-seconds",
        type=int,
        default=DEFAULT_MIN_TIMEOUT_SECONDS,
    )
    parser.add_argument("--expected-ui-version", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Also write structured JSON health state to this path.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="Also write the markdown health report to this path.",
    )
    parser.add_argument(
        "--route-proof-json",
        type=Path,
        help="Require a fresh successful scheduled live route proof at this path.",
    )
    parser.add_argument(
        "--route-proof-max-age-seconds",
        type=int,
        default=DEFAULT_ROUTE_PROOF_MAX_AGE_SECONDS,
    )
    parser.add_argument(
        "--cold-recovery-proof-json",
        type=Path,
        help="Require a fresh successful scheduled no-inference cold-recovery drill.",
    )
    parser.add_argument(
        "--cold-recovery-proof-max-age-seconds",
        type=int,
        default=DEFAULT_COLD_RECOVERY_PROOF_MAX_AGE_SECONDS,
    )
    args = parser.parse_args(argv)

    ui_version = args.expected_ui_version or expected_ui_version()
    reports = build_reports(
        targets=args.targets,
        min_timeout_seconds=max(0, args.min_timeout_seconds),
        ui_version=ui_version,
        route_proof_json=args.route_proof_json,
        route_proof_max_age_seconds=max(0, args.route_proof_max_age_seconds),
        cold_recovery_proof_json=args.cold_recovery_proof_json,
        cold_recovery_proof_max_age_seconds=max(
            0, args.cold_recovery_proof_max_age_seconds
        ),
    )
    structured = build_payload(reports, ui_version)
    markdown = render_markdown(reports, ui_version, checked_at=structured["checked_at"])
    payload = (
        json.dumps(structured, indent=2, sort_keys=True) if args.json else markdown
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(structured, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown, encoding="utf-8")
    print(payload, end="" if payload.endswith("\n") else "\n")
    failed = any(not report.ok for report in reports)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
