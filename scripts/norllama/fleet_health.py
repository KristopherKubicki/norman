#!/usr/bin/env python3
"""Collect a readiness, policy, and resource-health report for Norllama workers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class FleetTarget:
    name: str
    ssh_target: str
    identity_file: str
    root: str
    platform: str
    gateway_unit: str
    asr_unit: str = ""


DEFAULT_TARGETS = (
    FleetTarget(
        "spark-150",
        "kristopher@192.168.2.150",
        "/home/kristopher/.ssh/id_ed25519_netops_codex",
        "/home/kristopher/norllama",
        "linux",
        "norllama-gateway.service",
        "spark-audio-transcribe.service",
    ),
    FleetTarget(
        "spark-151",
        "kristopher@192.168.2.151",
        "/home/kristopher/.ssh/id_ed25519_netops_codex",
        "/home/kristopher/norllama",
        "linux",
        "norllama-gateway.service",
        "spark-audio-transcribe-core.service",
    ),
    FleetTarget(
        "mac-mini",
        "k@192.168.2.133",
        "/home/kristopher/.ssh/id_ed25519_macmini_codex",
        "/Users/k/norllama",
        "macos",
        "org.lollie.norllama",
    ),
)
ENDPOINTS = ("/healthz", "/readyz", "/asr-readyz", "/v1/models")
WARNING_EXPIRY_SECONDS = 72 * 60 * 60
WARNING_LINUX_MEM_AVAILABLE_KIB = 6 * 1024 * 1024
FAIL_LINUX_MEM_AVAILABLE_KIB = 2 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# Norllama Fleet Health",
        "",
        f"Checked: `{report.get('checked_at', '')}`",
        f"Status: `{report.get('status', '')}`",
        "",
        "| Worker | Platform | Status | Policy expiry |",
        "| --- | --- | --- | --- |",
    ]
    for target in report.get("targets", []):
        if not isinstance(target, dict):
            continue
        ready = target.get("endpoints", {}).get("/readyz", {})
        policy = ready.get("json", {}).get("policy", {}) if isinstance(ready, dict) else {}
        status = "healthy" if target.get("healthy") else "failed"
        lines.append(
            f"| {target.get('name', '')} | {target.get('platform', '')} | "
            f"{status} | {policy.get('expires_at', 'unknown')} |"
        )
    lines.extend(
        [
            "",
            f"Summary: `{summary.get('active', 0)}/{summary.get('expected', 0)}` healthy, "
            f"`{summary.get('warn', 0)}` warnings, `{summary.get('fail', 0)}` failures.",
        ]
    )
    issues = report.get("issues", [])
    if issues:
        lines.extend(["", "## Issues", ""])
        for issue in issues:
            lines.append(
                f"- `{issue.get('severity')}` {issue.get('host')} "
                f"`{issue.get('check')}`: {issue.get('detail')}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _remote_script(target: FleetTarget) -> str:
    target_json = json.dumps(
        {
            "name": target.name,
            "platform": target.platform,
            "gateway_unit": target.gateway_unit,
            "asr_unit": target.asr_unit,
        }
    )
    return f"""\
import json
import re
import subprocess
import urllib.error
import urllib.request

target = json.loads({target_json!r})

def command(*args):
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    return {{"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}}

def endpoint(path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:18151" + path, timeout=5) as response:
            body = response.read().decode("utf-8", "replace")
            if path in {"/healthz", "/v1/models"}:
                return {{"status": response.status}}
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {{}}
            return {{"status": response.status, "json": payload}}
    except urllib.error.HTTPError as exc:
        return {{"status": exc.code, "error": str(exc)}}
    except Exception as exc:
        return {{"status": 0, "error": f"{{type(exc).__name__}}: {{exc}}"}}

result = {{"endpoints": {{path: endpoint(path) for path in {ENDPOINTS!r}}}}}
if target["platform"] == "linux":
    def unit(unit_name):
        shown = command("systemctl", "show", unit_name, "--property=ActiveState,NRestarts,MemoryCurrent")
        values = {{}}
        for line in shown["stdout"].splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        return {{"active": values.get("ActiveState") == "active",
                 "restarts": int(values.get("NRestarts") or 0),
                 "memory_current": int(values.get("MemoryCurrent") or 0),
                 "error": shown["stderr"] if shown["returncode"] else ""}}
    mem_available_kib = 0
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                mem_available_kib = int(line.split()[1])
                break
    result["services"] = {{"gateway": unit(target["gateway_unit"]), "asr": unit(target["asr_unit"])}}
    result["resources"] = {{"mem_available_kib": mem_available_kib}}
else:
    uid = subprocess.run(["id", "-u"], check=True, capture_output=True, text=True).stdout.strip()
    printed = command("launchctl", "print", f"gui/{{uid}}/{{target['gateway_unit']}}")
    text = printed["stdout"]
    runs = re.search(r"runs = (\\d+)", text)
    state = re.search(r"state = ([^\\n]+)", text)
    free = command("memory_pressure", "-Q")
    percentage = re.search(r"System-wide memory free percentage: (\\d+)%", free["stdout"])
    result["services"] = {{"gateway": {{"active": bool(state and state.group(1).strip() == "running"),
                                          "restarts": max(0, int(runs.group(1)) - 1) if runs else 0,
                                          "error": printed["stderr"] if printed["returncode"] else ""}}}}
    result["resources"] = {{"memory_free_percent": int(percentage.group(1)) if percentage else -1}}
print(json.dumps(result, sort_keys=True))
"""


def probe_target(target: FleetTarget) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "IdentitiesOnly=yes",
            "-i",
            target.identity_file,
            target.ssh_target,
            "python3 -",
        ],
        input=_remote_script(target),
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    if result.returncode:
        return {
            "name": target.name,
            "platform": target.platform,
            "error": (result.stderr or result.stdout or "SSH probe failed").strip(),
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "name": target.name,
            "platform": target.platform,
            "error": f"invalid remote JSON: {exc}",
        }
    if not isinstance(payload, dict):
        payload = {"error": "invalid remote probe payload"}
    payload.update({"name": target.name, "platform": target.platform})
    return payload


def _issue(
    issues: list[dict[str, str]], severity: str, target: FleetTarget, check: str, detail: str
) -> None:
    issues.append(
        {
            "severity": severity,
            "host": target.name,
            "instance": target.gateway_unit,
            "check": check,
            "detail": detail,
        }
    )


def evaluate_target(target: FleetTarget, payload: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if payload.get("error"):
        _issue(issues, "fail", target, "ssh", str(payload["error"]))
        return issues
    endpoints = payload.get("endpoints") if isinstance(payload.get("endpoints"), dict) else {}
    for endpoint_name in ENDPOINTS:
        state = endpoints.get(endpoint_name)
        status = state.get("status") if isinstance(state, dict) else 0
        if status != 200:
            detail = state.get("error", f"HTTP {status}") if isinstance(state, dict) else "missing probe"
            _issue(issues, "fail", target, f"endpoint:{endpoint_name}", str(detail))
    ready = endpoints.get("/readyz") if isinstance(endpoints.get("/readyz"), dict) else {}
    ready_json = ready.get("json") if isinstance(ready.get("json"), dict) else {}
    policy = ready_json.get("policy") if isinstance(ready_json.get("policy"), dict) else {}
    for key in ("integrity_valid", "default_route_allowed", "production_route_eligible"):
        if policy.get(key) is not True:
            _issue(issues, "fail", target, f"policy:{key}", "policy is not eligible")
    remaining = policy.get("validation", {}).get("seconds_to_expiry") if isinstance(policy.get("validation"), dict) else None
    if not isinstance(remaining, int):
        remaining = policy.get("seconds_to_expiry")
    if not isinstance(remaining, int):
        _issue(issues, "fail", target, "policy:expiry", "expiry was not reported")
    elif remaining <= 0:
        _issue(issues, "fail", target, "policy:expiry", "policy has expired")
    elif remaining <= WARNING_EXPIRY_SECONDS:
        _issue(issues, "warn", target, "policy:expiry", f"expires in {remaining} seconds")
    services = payload.get("services") if isinstance(payload.get("services"), dict) else {}
    for name, service in services.items():
        if not isinstance(service, dict) or not service.get("active"):
            _issue(issues, "fail", target, f"service:{name}", str(service.get("error") if isinstance(service, dict) else "inactive"))
            continue
        restarts = service.get("restarts")
        if isinstance(restarts, int) and restarts >= 10:
            _issue(issues, "fail", target, f"restarts:{name}", f"{restarts} restarts")
        elif isinstance(restarts, int) and restarts >= 3:
            _issue(issues, "warn", target, f"restarts:{name}", f"{restarts} restarts")
    resources = payload.get("resources") if isinstance(payload.get("resources"), dict) else {}
    if target.platform == "linux":
        available = resources.get("mem_available_kib")
        if not isinstance(available, int):
            _issue(issues, "fail", target, "memory", "MemAvailable was not reported")
        elif available < FAIL_LINUX_MEM_AVAILABLE_KIB:
            _issue(issues, "fail", target, "memory", f"only {available} KiB available")
        elif available < WARNING_LINUX_MEM_AVAILABLE_KIB:
            _issue(issues, "warn", target, "memory", f"only {available} KiB available")
    else:
        free = resources.get("memory_free_percent")
        if not isinstance(free, int) or free < 0:
            _issue(issues, "fail", target, "memory", "memory pressure was not reported")
        elif free < 5:
            _issue(issues, "fail", target, "memory", f"only {free}% free")
        elif free < 15:
            _issue(issues, "warn", target, "memory", f"only {free}% free")
    return issues


def collect(targets: Sequence[FleetTarget]) -> dict[str, Any]:
    probes = [probe_target(target) for target in targets]
    issues: list[dict[str, str]] = []
    for target, probe in zip(targets, probes):
        issues.extend(evaluate_target(target, probe))
        probe["healthy"] = not any(
            issue["severity"] == "fail" and issue["host"] == target.name for issue in issues
        )
    failures = sum(issue["severity"] == "fail" for issue in issues)
    warnings = sum(issue["severity"] == "warn" for issue in issues)
    active = sum(bool(probe.get("healthy")) for probe in probes)
    return {
        "schema": "norman.norllama.fleet-health.v1",
        "checked_at": utc_now(),
        "status": "failed" if failures else "degraded" if warnings else "ok",
        "summary": {
            "active": active,
            "expected": len(targets),
            "fail": failures,
            "warn": warnings,
        },
        "targets": probes,
        "issues": issues,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--target", action="append", choices=[item.name for item in DEFAULT_TARGETS])
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    requested = set(args.target or ())
    targets = tuple(item for item in DEFAULT_TARGETS if not requested or item.name in requested)
    report = collect(targets)
    if args.output:
        write_json(args.output, report)
    if args.markdown_output:
        write_markdown(args.markdown_output, report)
    if args.json or not args.output:
        print(json.dumps(report, sort_keys=True))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
