#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import ssl
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.request import urlopen


DEFAULT_CADDY_ADMIN_URL = "http://127.0.0.1:2019/config/"
DEFAULT_CONNECT_HOST = "127.0.0.1"
DEFAULT_PORT = 443
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_WARN_DAYS = 30.0
DEFAULT_MIN_DAYS = 14.0
DEFAULT_OUTPUT = Path("/home/kristopher/.local/state/norman/frontdoor-tls-health.json")
DEFAULT_ALERT_STATE = Path(
    "/home/kristopher/.local/state/norman/frontdoor-tls-alerts-state.json"
)
DEFAULT_ALERT_SCRIPT = Path("/home/kristopher/code/norman/scripts/tui_fleet_alerts.py")
DEFAULT_ALERT_THREAD_ID = "th_frontdoor_tls_health"
ALERT_TITLE = "Norman front-door TLS"
HEALTH_SCHEMA = "norman.frontdoor-tls-health.v1"


def _listener_is_https(listener: Any) -> bool:
    value = str(listener or "").strip()
    if not value:
        return False
    _host, separator, port = value.rpartition(":")
    return bool(separator) and port == "443"


def _valid_host(value: Any) -> str:
    host = str(value or "").strip().rstrip(".").lower()
    if not host or "*" in host or " " in host or ":" in host:
        return ""
    return host


def _collect_route_hosts(value: Any, hosts: set[str]) -> None:
    if isinstance(value, dict):
        matches = value.get("match")
        if isinstance(matches, list):
            for matcher in matches:
                if not isinstance(matcher, dict):
                    continue
                candidate_hosts = matcher.get("host")
                if not isinstance(candidate_hosts, list):
                    continue
                for candidate in candidate_hosts:
                    host = _valid_host(candidate)
                    if host:
                        hosts.add(host)
        for nested in value.values():
            _collect_route_hosts(nested, hosts)
        return
    if isinstance(value, list):
        for nested in value:
            _collect_route_hosts(nested, hosts)


def discover_https_hosts(caddy_config: dict[str, Any]) -> list[str]:
    apps = caddy_config.get("apps")
    if not isinstance(apps, dict):
        return []
    http = apps.get("http")
    if not isinstance(http, dict):
        return []
    servers = http.get("servers")
    if not isinstance(servers, dict):
        return []

    hosts: set[str] = set()
    for server in servers.values():
        if not isinstance(server, dict):
            continue
        listeners = server.get("listen")
        if not isinstance(listeners, list) or not any(
            _listener_is_https(listener) for listener in listeners
        ):
            continue
        _collect_route_hosts(server.get("routes"), hosts)
    return sorted(hosts)


def load_caddy_config(url: str, *, timeout: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Caddy admin config is not an object")
    return payload


def _certificate_expiry_days(certificate: dict[str, Any]) -> float:
    not_after = str(certificate.get("notAfter") or "").strip()
    if not not_after:
        raise RuntimeError("peer certificate did not provide notAfter")
    expires_at = datetime.fromtimestamp(
        ssl.cert_time_to_seconds(not_after), tz=timezone.utc
    )
    return (expires_at - datetime.now(timezone.utc)).total_seconds() / 86400


def probe_host(
    host: str,
    *,
    connect_host: str,
    port: int,
    timeout: float,
    warn_days: float,
    min_days: float,
) -> dict[str, Any]:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((connect_host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls_socket:
                certificate = tls_socket.getpeercert()
                days_remaining = _certificate_expiry_days(certificate)
                issuer = " / ".join(
                    f"{key}={value}"
                    for rdn in certificate.get("issuer") or ()
                    for key, value in rdn
                )
                result = {
                    "host": host,
                    "status": "ok",
                    "days_remaining": round(days_remaining, 2),
                    "issuer": issuer,
                    "detail": f"certificate valid for {days_remaining:.1f} days",
                }
    except (OSError, ssl.SSLError, ValueError, RuntimeError) as exc:
        return {
            "host": host,
            "status": "fail",
            "days_remaining": None,
            "issuer": "",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    if days_remaining < min_days:
        return {
            **result,
            "status": "fail",
            "detail": (
                f"certificate expires in {days_remaining:.1f} days; "
                f"minimum is {min_days:.1f}"
            ),
        }
    if days_remaining < warn_days:
        return {
            **result,
            "status": "warn",
            "detail": (
                f"certificate expires in {days_remaining:.1f} days; "
                f"warning threshold is {warn_days:.1f}"
            ),
        }
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_health_report(
    results: Iterable[dict[str, Any]], *, checked_at: str | None = None
) -> dict[str, Any]:
    ordered_results = list(results)
    issues = []
    for result in ordered_results:
        status = str(result.get("status") or "fail").lower()
        if status == "ok":
            continue
        issues.append(
            {
                "severity": "fail" if status == "fail" else "warn",
                "host": str(result.get("host") or "unknown"),
                "instance": "<frontdoor>",
                "check": "tls_certificate",
                "detail": str(result.get("detail") or "certificate check failed"),
            }
        )
    fail_count = sum(1 for issue in issues if issue["severity"] == "fail")
    warn_count = sum(1 for issue in issues if issue["severity"] == "warn")
    status = "fail" if fail_count else "warn" if warn_count else "ok"
    return {
        "schema": HEALTH_SCHEMA,
        "checked_at": checked_at or _utc_now(),
        "status": status,
        "summary": {
            "active": 0,
            "expected": len(ordered_results),
            "fail": fail_count,
            "warn": warn_count,
            "hosts": len(ordered_results),
            "ok": status == "ok",
        },
        "hosts": ordered_results,
        "issues": issues,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def post_alerts(
    *,
    alert_script: Path,
    health_json: Path,
    state: Path,
    thread_id: str,
) -> None:
    subprocess.run(
        [
            sys.executable,
            str(alert_script),
            "--health-json",
            str(health_json),
            "--state",
            str(state),
            "--thread-id",
            thread_id,
            "--title",
            ALERT_TITLE,
            "--report-path",
            str(health_json),
        ],
        check=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify every active Norman front-door TLS certificate."
    )
    parser.add_argument("--caddy-admin-url", default=DEFAULT_CADDY_ADMIN_URL)
    parser.add_argument("--connect-host", default=DEFAULT_CONNECT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--warn-days", type=float, default=DEFAULT_WARN_DAYS)
    parser.add_argument("--min-days", type=float, default=DEFAULT_MIN_DAYS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--post-alerts", action="store_true")
    parser.add_argument("--alert-script", type=Path, default=DEFAULT_ALERT_SCRIPT)
    parser.add_argument("--alert-state", type=Path, default=DEFAULT_ALERT_STATE)
    parser.add_argument("--alert-thread-id", default=DEFAULT_ALERT_THREAD_ID)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        hosts = discover_https_hosts(
            load_caddy_config(args.caddy_admin_url, timeout=args.timeout)
        )
    except (OSError, ValueError, RuntimeError) as exc:
        report = build_health_report(
            [
                {
                    "host": "<caddy-admin>",
                    "status": "fail",
                    "days_remaining": None,
                    "issuer": "",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ]
        )
    else:
        if not hosts:
            report = build_health_report(
                [
                    {
                        "host": "<frontdoor>",
                        "status": "fail",
                        "days_remaining": None,
                        "issuer": "",
                        "detail": "Caddy has no HTTPS host routes",
                    }
                ]
            )
        else:
            report = build_health_report(
                [
                    probe_host(
                        host,
                        connect_host=args.connect_host,
                        port=args.port,
                        timeout=args.timeout,
                        warn_days=max(args.warn_days, args.min_days),
                        min_days=args.min_days,
                    )
                    for host in hosts
                ]
            )
    write_json(args.output, report)
    if args.post_alerts:
        post_alerts(
            alert_script=args.alert_script,
            health_json=args.output,
            state=args.alert_state,
            thread_id=args.alert_thread_id,
        )
    summary = report["summary"]
    print(
        "frontdoor TLS status={status} hosts={hosts} fail={fail} warn={warn}".format(
            status=report["status"],
            hosts=summary["hosts"],
            fail=summary["fail"],
            warn=summary["warn"],
        )
    )
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
