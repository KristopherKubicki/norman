#!/usr/bin/env python3
"""Keep pfSense LAN DNS aligned with the active Norman Caddy front door."""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
import urllib.error
import urllib.request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from norman_frontdoor_tls_guard import (
    discover_https_hosts,
    load_caddy_config,
    write_json,
)


DEFAULT_CADDY_ADMIN_URL = "http://127.0.0.1:2019/config/"
DEFAULT_RESOLVER = "192.168.2.1"
DEFAULT_FRONTDOOR_ADDRESS = "192.168.2.241"
DEFAULT_FIREWALL_HOST = "192.168.2.1"
DEFAULT_FIREWALL_USER = "admin"
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_OUTPUT = Path("/home/kristopher/.local/state/norman/frontdoor-dns-health.json")
FIREWALL_SECRET_NAME = "networking/firewall"
HEALTH_SCHEMA = "norman.frontdoor-dns-health.v1"
HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class DNSVerificationError(RuntimeError):
    """Raised when Unbound did not serve the requested front-door mapping."""


class NormanKeysConfigurationError(RuntimeError):
    """Raised when no approved Norman Keys path is configured."""


class NormanKeysLookupError(RuntimeError):
    """Raised when Norman Keys cannot supply the firewall credential."""


class NormanKeysSecretMissingError(NormanKeysLookupError):
    """Raised when the approved firewall credential has not been provisioned."""


class FirewallAuthenticationError(RuntimeError):
    """Raised when pfSense rejects the brokered automation credential."""


class FirewallConnectionError(RuntimeError):
    """Raised when pfSense cannot be reached over its management channel."""


class FirewallUpdateError(RuntimeError):
    """Raised when pfSense rejects the Unbound update command."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _valid_hostname(value: str) -> bool:
    candidate = value.strip().lower().rstrip(".")
    if len(candidate) > 253 or "." not in candidate:
        return False
    return all(HOST_LABEL_RE.fullmatch(label) for label in candidate.split("."))


def reconciled_hosts(hosts: list[str]) -> list[str]:
    """Return exact active HTTPS names that must resolve to the LAN front door."""
    return sorted(
        {
            host.strip().lower().rstrip(".")
            for host in hosts
            if _valid_hostname(host) and not host.strip().lower().endswith(".ts.net")
        }
    )


def load_active_hosts(caddy_admin_url: str, *, timeout: float) -> list[str]:
    hosts = reconciled_hosts(
        discover_https_hosts(load_caddy_config(caddy_admin_url, timeout=timeout))
    )
    if not hosts:
        raise RuntimeError("Caddy has no reconciliable HTTPS host routes")
    return hosts


def query_a_records(host: str, *, resolver: str, timeout: float) -> tuple[str, ...]:
    """Return direct A records from the authoritative LAN resolver."""
    result = subprocess.run(
        [
            "dig",
            f"@{resolver}",
            "+short",
            "+time=2",
            "+tries=1",
            host,
            "A",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=max(timeout, 3.0),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LAN DNS query failed for {host}")

    records: set[str] = set()
    for line in result.stdout.splitlines():
        candidate = line.strip()
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv4Address):
            records.add(str(address))
    return tuple(sorted(records))


def dns_drift(
    hosts: list[str],
    *,
    resolver: str,
    frontdoor_address: str,
    timeout: float,
    query: Callable[..., tuple[str, ...]] = query_a_records,
) -> dict[str, str]:
    """Return host->front-door records that are absent or point somewhere else."""
    target = str(ipaddress.IPv4Address(frontdoor_address))
    drift: dict[str, str] = {}
    for host in hosts:
        answers = query(host, resolver=resolver, timeout=timeout)
        if answers != (target,):
            drift[host] = target
    return drift


def _keys_secret_get_url() -> str:
    base = (
        os.environ.get("NORMAN_KEYS_URL", "").strip()
        or os.environ.get("NORMAN_KEYS_API_BASE", "").strip()
    ).rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1/secrets/get"):
        return base
    if base.endswith("/v1"):
        return f"{base}/secrets/get"
    return f"{base}/v1/secrets/get"


def _secret_command(secret_name: str) -> list[str]:
    command_text = (
        os.environ.get("NORMAN_SECRET_CMD", "").strip()
        or os.environ.get("NORMAN_CONFIG_SECRET_CMD", "").strip()
    )
    if not command_text:
        return []
    command = shlex.split(command_text)
    if not command:
        return []
    if "{name}" in command_text:
        return [part.replace("{name}", secret_name) for part in command]
    return [*command, "get", secret_name]


def _fetch_command_secret(command: list[str], *, timeout: float) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        diagnostic = str(exc.stderr or "").lower()
        missing_markers = (
            "not found",
            "no such",
            "does not exist",
            "unknown secret",
            "unknown entry",
        )
        if any(marker in diagnostic for marker in missing_markers):
            raise NormanKeysSecretMissingError(
                "Norman Keys has no approved firewall credential"
            ) from exc
        raise NormanKeysLookupError("Norman Keys command lookup failed") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise NormanKeysLookupError("Norman Keys command lookup failed") from exc
    password = str(result.stdout or "").rstrip("\r\n")
    if not password:
        raise NormanKeysLookupError(
            "Norman Keys command returned an empty firewall credential"
        )
    return password


def fetch_firewall_password(*, timeout: float) -> str:
    """Read the pfSense password through Norman Keys or its approved command."""
    url = _keys_secret_get_url()
    token = os.environ.get("NORMAN_KEYS_TOKEN", "").strip()
    if not url:
        command = _secret_command(FIREWALL_SECRET_NAME)
        if command:
            return _fetch_command_secret(command, timeout=timeout)
        raise NormanKeysConfigurationError(
            "Norman Keys broker credentials are not configured"
        )
    if not token:
        raise NormanKeysConfigurationError(
            "Norman Keys service token is not configured"
        )

    payload = {
        "name": FIREWALL_SECRET_NAME,
        "reason": "Reconcile Norman front-door LAN DNS for Caddy ACME",
        "requester_id": "norman-frontdoor-dns-reconcile",
        "session_id": "timer",
        "lane": "infrastructure",
        "target_host": socket.gethostname(),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        response_payload = json.loads(body) if body else {}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise NormanKeysLookupError(
            "Norman Keys lookup for the firewall credential failed"
        ) from exc
    if not isinstance(response_payload, dict):
        raise NormanKeysLookupError(
            "Norman Keys returned an invalid firewall credential"
        )
    password = str(
        response_payload.get("value") or response_payload.get("secret") or ""
    ).rstrip("\r\n")
    if not password:
        raise NormanKeysLookupError("Norman Keys returned an empty firewall credential")
    return password


def _runtime_temp_dir() -> Path:
    for candidate in (os.environ.get("XDG_RUNTIME_DIR", "").strip(), "/dev/shm"):
        if candidate:
            path = Path(candidate)
            if path.is_dir() and os.access(path, os.W_OK):
                return path
    return Path(tempfile.gettempdir())


@contextmanager
def _ssh_askpass(password: str) -> Iterator[tuple[Path, dict[str, str]]]:
    """Expose a password only to a one-shot SSH_ASKPASS process."""
    with tempfile.TemporaryDirectory(
        prefix="norman_frontdoor_dns_", dir=_runtime_temp_dir()
    ) as temporary_dir:
        root = Path(temporary_dir)
        password_path = root / "password"
        askpass_path = root / "askpass.sh"
        password_path.write_text(password + "\n", encoding="utf-8")
        password_path.chmod(0o600)
        askpass_path.write_text('#!/bin/sh\ncat "$ASKPASS_FILE"\n', encoding="utf-8")
        askpass_path.chmod(0o700)
        environment = os.environ.copy()
        environment.update(
            {
                "ASKPASS_FILE": str(password_path),
                "DISPLAY": ":0",
                "SSH_ASKPASS": str(askpass_path),
                "SSH_ASKPASS_REQUIRE": "force",
            }
        )
        yield askpass_path, environment


def _php_apply_code(records: dict[str, str]) -> str:
    encoded_records = base64.b64encode(
        json.dumps(records, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    return f"""
require_once("config.inc");

$records = json_decode(base64_decode("{encoded_records}"), true);
if (!is_array($records) || count($records) === 0) {{
  exit(2);
}}

$target_map = [];
foreach ($records as $fqdn => $ip) {{
  $target_map[strtolower(trim((string)$fqdn))] = trim((string)$ip);
}}

$kept_hosts = [];
foreach (($config["unbound"]["hosts"] ?? []) as $entry) {{
  $host = strtolower(trim((string)($entry["host"] ?? "")));
  $domain = strtolower(trim((string)($entry["domain"] ?? "")));
  $fqdn = trim($host . "." . $domain, ".");
  if (isset($target_map[$fqdn])) {{
    continue;
  }}
  $kept_hosts[] = $entry;
}}
$config["unbound"]["hosts"] = $kept_hosts;

$custom_options = base64_decode((string)($config["unbound"]["custom_options"] ?? ""));
$lines = preg_split("/\\r?\\n/", $custom_options);
if ($lines === false) {{
  $lines = [];
}}
$filtered = [];
foreach ($lines as $line) {{
  $trimmed = trim($line);
  $drop = false;
  foreach ($target_map as $fqdn => $_ip) {{
    $pattern = '/^local-data:\\s+"'
      . preg_quote($fqdn . ".", '/')
      . '\\s+IN\\s+A\\s+/i';
    if (preg_match($pattern, $trimmed) === 1) {{
      $drop = true;
      break;
    }}
  }}
  if (!$drop) {{
    $filtered[] = $line;
  }}
}}
while (!empty($filtered) && trim((string)end($filtered)) === "") {{
  array_pop($filtered);
}}
foreach ($target_map as $fqdn => $ip) {{
  $filtered[] = 'local-data: "' . $fqdn . '. IN A ' . $ip . '"';
}}
$config["unbound"]["custom_options"] =
  base64_encode(implode("\\n", $filtered) . "\\n");

$backup = "/cf/conf/config.xml.bak-" . gmdate("Ymd\\THis\\Z")
  . "-before-norman-frontdoor-dns-reconcile";
if (!copy("/cf/conf/config.xml", $backup)) {{
  exit(3);
}}
write_config("Reconcile Norman front-door LAN DNS");
services_unbound_configure();
echo "records=" . count($target_map) . "\\n";
"""


def apply_pfsense_records(
    records: dict[str, str],
    *,
    firewall_host: str,
    firewall_user: str,
    firewall_password: str,
    timeout: float,
) -> None:
    """Upsert selected Unbound A records and reload Unbound on pfSense."""
    if not records:
        return
    php_code = _php_apply_code(records)
    encoded_code = base64.b64encode(php_code.encode("utf-8")).decode("ascii")
    command = f"php -r 'eval(base64_decode(\"{encoded_code}\"));'"
    with _ssh_askpass(firewall_password) as (_askpass_path, environment):
        result = subprocess.run(
            [
                "setsid",
                "-w",
                "ssh",
                "-o",
                "BatchMode=no",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "KbdInteractiveAuthentication=no",
                "-o",
                "NumberOfPasswordPrompts=1",
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "PubkeyAuthentication=no",
                "-o",
                "StrictHostKeyChecking=accept-new",
                f"{firewall_user}@{firewall_host}",
                command,
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=max(timeout * 4, 30.0),
            check=False,
        )
    if result.returncode != 0:
        output = result.stdout.lower()
        if "permission denied" in output or "authentication failed" in output:
            raise FirewallAuthenticationError(
                "pfSense rejected the brokered automation credential"
            )
        connection_markers = (
            "connection refused",
            "connection timed out",
            "could not resolve hostname",
            "no route to host",
        )
        if any(marker in output for marker in connection_markers):
            raise FirewallConnectionError("pfSense management SSH is unavailable")
        raise FirewallUpdateError("pfSense rejected the Unbound update command")


def verify_records(
    records: dict[str, str],
    *,
    resolver: str,
    timeout: float,
    query: Callable[..., tuple[str, ...]] = query_a_records,
) -> list[str]:
    """Return any selected names that do not resolve exclusively to their target."""
    failed: list[str] = []
    for host, target in sorted(records.items()):
        if query(host, resolver=resolver, timeout=timeout) != (target,):
            failed.append(host)
    return failed


def build_health_report(
    *,
    active_hosts: list[str],
    drift: dict[str, str],
    status: str,
    checked_at: str | None = None,
    dry_run: bool = False,
    error: str = "",
) -> dict[str, Any]:
    return {
        "schema": HEALTH_SCHEMA,
        "checked_at": checked_at or _utc_now(),
        "status": status,
        "dry_run": dry_run,
        "summary": {
            "active_https_hosts": len(active_hosts),
            "dns_drift": len(drift),
            "reconciled": len(drift) if status == "ok" and not dry_run else 0,
            "ok": status == "ok",
        },
        "hosts_reconciled": sorted(drift),
        "error": error,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile active Norman Caddy hosts into pfSense LAN DNS."
    )
    parser.add_argument("--caddy-admin-url", default=DEFAULT_CADDY_ADMIN_URL)
    parser.add_argument("--resolver", default=DEFAULT_RESOLVER)
    parser.add_argument("--frontdoor-address", default=DEFAULT_FRONTDOOR_ADDRESS)
    parser.add_argument("--firewall-host", default=DEFAULT_FIREWALL_HOST)
    parser.add_argument("--firewall-user", default=DEFAULT_FIREWALL_USER)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    active_hosts: list[str] = []
    drift: dict[str, str] = {}
    try:
        active_hosts = load_active_hosts(args.caddy_admin_url, timeout=args.timeout)
        drift = dns_drift(
            active_hosts,
            resolver=args.resolver,
            frontdoor_address=args.frontdoor_address,
            timeout=args.timeout,
        )
        if drift and not args.dry_run:
            password = fetch_firewall_password(timeout=args.timeout)
            apply_pfsense_records(
                drift,
                firewall_host=args.firewall_host,
                firewall_user=args.firewall_user,
                firewall_password=password,
                timeout=args.timeout,
            )
            failed = verify_records(
                drift,
                resolver=args.resolver,
                timeout=args.timeout,
            )
            if failed:
                raise DNSVerificationError(
                    "pfSense did not serve all reconciled records"
                )
    except Exception as exc:
        report = build_health_report(
            active_hosts=active_hosts,
            drift=drift,
            status="fail",
            dry_run=args.dry_run,
            error=type(exc).__name__,
        )
        write_json(args.output, report)
        print(
            "frontdoor DNS status=fail hosts={hosts} drift={drift} error={error}".format(
                hosts=len(active_hosts),
                drift=len(drift),
                error=type(exc).__name__,
            ),
            file=sys.stderr,
        )
        return 1

    report = build_health_report(
        active_hosts=active_hosts,
        drift=drift,
        status="ok",
        dry_run=args.dry_run,
    )
    write_json(args.output, report)
    print(
        "frontdoor DNS status=ok hosts={hosts} drift={drift} dry_run={dry_run}".format(
            hosts=len(active_hosts),
            drift=len(drift),
            dry_run=str(args.dry_run).lower(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
