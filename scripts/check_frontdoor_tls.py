#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import math
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_norman_bot_proxy_caddy import bot_host_groups


DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MIN_LIFETIME_DAYS = 2.0
DEFAULT_LAN_DNS_SERVER = "192.168.2.1"
DEFAULT_DOHIO_DNS_SERVER = "100.99.220.14"
DEFAULT_LAN_FRONTDOOR_ADDRESS = "192.168.2.241"
DEFAULT_ROAD_FRONTDOOR_ADDRESS = "100.103.34.17"
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
ROAD_FRONTDOOR_HOSTS = (
    ("norman.home.arpa", "Norman Front Door", ""),
    ("switchboard.home.arpa", "Switchboard", ""),
)
ROAD_BOT_ENTRY_HOSTS = (
    ("compere", "keystone.home.arpa"),
    ("compere", "keystone.kris.openbrand.com"),
    ("housebot", "housebot.home.arpa"),
    ("leadership-kpis", "kpis.home.arpa"),
    ("leadership-kpis", "kpis.kris.openbrand.com"),
    ("networking", "networking.home.arpa"),
    ("uplink", "uplink.home.arpa"),
    ("glimpser", "eyebat.home.arpa"),
)
ROAD_APP_HOSTS = (
    ("glimpser.home.arpa", "Glimpser App"),
    ("glimpser.knox.lollie.org", "Glimpser App"),
)
LABEL_OVERRIDES = {
    "compere": "Keystone",
    "glimpser": "Glimpser",
    "leadership-kpis": "Leadership KPIs",
}


@dataclass(frozen=True)
class HostExpectation:
    host: str
    label: str
    path: str = "/"
    redirect_to_host: str = ""
    surface: str = "service"
    expected_lan_addresses: tuple[str, ...] = ()
    expected_road_addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class DnsProbePath:
    name: str
    resolver: str
    transport: str
    expected_address_group: str


@dataclass(frozen=True)
class DnsSnapshot:
    name: str
    resolver: str
    transport: str
    addresses: tuple[str, ...]
    expected_addresses: tuple[str, ...]
    ok: bool
    error: str


@dataclass(frozen=True)
class TlsSnapshot:
    issuer: str
    not_before: str
    not_after: str
    san_dns: tuple[str, ...]
    san_ip_addresses: tuple[str, ...]
    hostname_matches: bool
    days_remaining: float
    tls_version: str
    cipher: str


@dataclass(frozen=True)
class HttpSnapshot:
    status: int
    reason: str
    location: str
    server: str


@dataclass(frozen=True)
class ProbeResult:
    host: str
    label: str
    surface: str
    addresses: tuple[str, ...]
    dns_paths: tuple[DnsSnapshot, ...]
    tls: TlsSnapshot | None
    http: HttpSnapshot | None
    trust_ok: bool
    trust_error: str
    issues: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _label_for_name(name: str) -> str:
    return LABEL_OVERRIDES.get(name, name.replace("-", " ").title())


def _dedupe_specs(specs: list[HostExpectation]) -> list[HostExpectation]:
    seen: set[tuple[str, str, str]] = set()
    ordered: list[HostExpectation] = []
    for spec in specs:
        key = (spec.host, spec.path, spec.redirect_to_host)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(spec)
    return ordered


def build_profile_specs(
    profile: str,
    *,
    lan_frontdoor_address: str = DEFAULT_LAN_FRONTDOOR_ADDRESS,
    road_frontdoor_address: str = DEFAULT_ROAD_FRONTDOOR_ADDRESS,
) -> list[HostExpectation]:
    if profile != "road":
        raise ValueError(f"unsupported profile: {profile}")

    specs: list[HostExpectation] = []
    for host, label, redirect_to_host in ROAD_FRONTDOOR_HOSTS:
        specs.append(
            HostExpectation(
                host=host,
                label=label,
                redirect_to_host=redirect_to_host,
                surface="frontdoor",
                expected_lan_addresses=(lan_frontdoor_address,),
                expected_road_addresses=(road_frontdoor_address,),
            )
        )
    for name, host in ROAD_BOT_ENTRY_HOSTS:
        groups = bot_host_groups(name)
        if not groups:
            continue
        canonical_host = groups[0][0]
        redirect_to_host = canonical_host if host != canonical_host else ""
        specs.append(
            HostExpectation(
                host=host,
                label=_label_for_name(name),
                redirect_to_host=redirect_to_host,
                surface="bot-tui",
                expected_lan_addresses=(lan_frontdoor_address,),
                expected_road_addresses=(road_frontdoor_address,),
            )
        )
    for host, label in ROAD_APP_HOSTS:
        specs.append(HostExpectation(host=host, label=label, surface="app"))
    return _dedupe_specs(specs)


def build_dns_probe_paths(
    profile: str,
    *,
    lan_dns_server: str = DEFAULT_LAN_DNS_SERVER,
    dohio_dns_server: str = DEFAULT_DOHIO_DNS_SERVER,
) -> tuple[DnsProbePath, ...]:
    if profile == "none":
        return ()
    if profile != "networking":
        raise ValueError(f"unsupported DNS profile: {profile}")
    return (
        DnsProbePath(
            name="lan",
            resolver=lan_dns_server,
            transport="udp",
            expected_address_group="lan",
        ),
        DnsProbePath(
            name="dohio-udp",
            resolver=dohio_dns_server,
            transport="udp",
            expected_address_group="road",
        ),
        DnsProbePath(
            name="dohio-tcp",
            resolver=dohio_dns_server,
            transport="tcp",
            expected_address_group="road",
        ),
    )


def select_specs(
    profile: str,
    hosts: list[str],
    *,
    lan_frontdoor_address: str = DEFAULT_LAN_FRONTDOOR_ADDRESS,
    road_frontdoor_address: str = DEFAULT_ROAD_FRONTDOOR_ADDRESS,
) -> list[HostExpectation]:
    profile_specs = build_profile_specs(
        profile,
        lan_frontdoor_address=lan_frontdoor_address,
        road_frontdoor_address=road_frontdoor_address,
    )
    if not hosts:
        return profile_specs
    by_host = {spec.host: spec for spec in profile_specs}
    selected: list[HostExpectation] = []
    for host in hosts:
        clean = host.strip()
        if not clean:
            continue
        selected.append(by_host.get(clean) or HostExpectation(host=clean, label=clean))
    return _dedupe_specs(selected)


def _flatten_name(entries: Any) -> str:
    parts: list[str] = []
    for rdn in entries or ():
        for key, value in rdn:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _decode_pem_certificate(pem_data: str) -> dict[str, Any]:
    decoder = getattr(getattr(ssl, "_ssl", None), "_test_decode_cert", None)
    if decoder is None:
        raise RuntimeError("ssl certificate decoder unavailable")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="ascii",
        suffix=".pem",
        delete=False,
    ) as handle:
        handle.write(pem_data)
        temp_path = Path(handle.name)
    try:
        return decoder(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)


def _hostname_matches_certificate(
    host: str,
    *,
    san_dns: tuple[str, ...],
    san_ip_addresses: tuple[str, ...],
) -> bool:
    candidate = host.strip().lower()
    if not candidate:
        return False
    if candidate in {value.strip().lower() for value in san_ip_addresses}:
        return True
    for pattern in san_dns:
        clean = pattern.strip().lower()
        if not clean:
            continue
        if clean == candidate:
            return True
        if clean.startswith("*.") and candidate.count(".") == clean.count("."):
            if fnmatchcase(candidate, clean.replace("*.", "*.")):
                return True
    return False


def resolve_host_addresses(host: str, port: int = 443) -> tuple[str, ...]:
    infos = socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    ordered: list[str] = []
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        address = str(sockaddr[0]).strip()
        if address and address not in ordered:
            ordered.append(address)
    return tuple(ordered)


def _looks_like_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def resolve_host_addresses_via_dns(
    host: str,
    *,
    resolver: str,
    transport: str = "udp",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[tuple[str, ...], str]:
    dig_timeout = max(1, int(math.ceil(timeout)))
    command = [
        "dig",
        f"+time={dig_timeout}",
        "+tries=1",
        "+short",
        f"@{resolver}",
        host,
        "A",
    ]
    if transport == "tcp":
        command.insert(1, "+tcp")
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 1.0,
        )
    except FileNotFoundError:
        return (), "dig command not found"
    except subprocess.TimeoutExpired:
        return (), f"dig timed out after {timeout:.1f}s"
    addresses = tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if _looks_like_ip_address(line.strip())
    )
    if completed.returncode == 0:
        return addresses, ""
    detail = (completed.stderr or completed.stdout or "").strip().splitlines()
    suffix = f": {detail[-1]}" if detail else ""
    return addresses, f"dig exited {completed.returncode}{suffix}"


def probe_dns_paths(
    spec: HostExpectation,
    paths: tuple[DnsProbePath, ...],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[DnsSnapshot, ...]:
    snapshots: list[DnsSnapshot] = []
    for path in paths:
        if path.expected_address_group == "lan":
            expected_addresses = spec.expected_lan_addresses
        elif path.expected_address_group == "road":
            expected_addresses = spec.expected_road_addresses
        else:
            expected_addresses = ()
        if not expected_addresses:
            continue
        addresses, error = resolve_host_addresses_via_dns(
            spec.host,
            resolver=path.resolver,
            transport=path.transport,
            timeout=timeout,
        )
        expected_set = {address.strip() for address in expected_addresses if address}
        address_set = {address.strip() for address in addresses if address}
        ok = not error and bool(expected_set.intersection(address_set))
        snapshots.append(
            DnsSnapshot(
                name=path.name,
                resolver=path.resolver,
                transport=path.transport,
                addresses=addresses,
                expected_addresses=expected_addresses,
                ok=ok,
                error=error,
            )
        )
    return tuple(snapshots)


def fetch_tls_snapshot(
    host: str,
    port: int = 443,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> TlsSnapshot:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw_socket:
        with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
            der_certificate = tls_socket.getpeercert(binary_form=True)
            tls_version = str(tls_socket.version() or "")
            cipher = str((tls_socket.cipher() or ("", "", ""))[0] or "")
    pem_certificate = ssl.DER_cert_to_PEM_cert(der_certificate)
    decoded = _decode_pem_certificate(pem_certificate)
    san_dns: list[str] = []
    san_ip_addresses: list[str] = []
    for entry_type, value in decoded.get("subjectAltName", ()):
        if entry_type == "DNS":
            san_dns.append(str(value))
        elif entry_type == "IP Address":
            san_ip_addresses.append(str(value))
    hostname_matches = _hostname_matches_certificate(
        host,
        san_dns=tuple(san_dns),
        san_ip_addresses=tuple(san_ip_addresses),
    )
    not_after = str(decoded.get("notAfter") or "")
    days_remaining = 0.0
    if not_after:
        days_remaining = (ssl.cert_time_to_seconds(not_after) - time.time()) / 86400.0
    return TlsSnapshot(
        issuer=_flatten_name(decoded.get("issuer")),
        not_before=str(decoded.get("notBefore") or ""),
        not_after=not_after,
        san_dns=tuple(san_dns),
        san_ip_addresses=tuple(san_ip_addresses),
        hostname_matches=hostname_matches,
        days_remaining=days_remaining,
        tls_version=tls_version,
        cipher=cipher,
    )


def check_system_trust(
    host: str,
    port: int = 443,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw_socket:
            with ssl.create_default_context().wrap_socket(
                raw_socket,
                server_hostname=host,
            ):
                return ""
    except Exception as exc:  # pragma: no cover - exercised via probe_host
        return f"{exc.__class__.__name__}: {exc}"


def fetch_http_snapshot(
    host: str,
    port: int = 443,
    *,
    path: str = "/",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> HttpSnapshot:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(
        host, port=port, timeout=timeout, context=context
    )
    try:
        conn.request(
            "GET",
            path,
            headers={
                "User-Agent": "norman-frontdoor-probe/1.0",
                "Accept": "text/html, text/plain;q=0.9, */*;q=0.1",
            },
        )
        response = conn.getresponse()
        response.read(256)
        return HttpSnapshot(
            status=int(response.status),
            reason=str(response.reason or ""),
            location=str(response.getheader("Location") or ""),
            server=str(response.getheader("Server") or ""),
        )
    finally:
        conn.close()


def probe_host(
    spec: HostExpectation,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    min_lifetime_days: float = DEFAULT_MIN_LIFETIME_DAYS,
    check_trust: bool = True,
    dns_paths: tuple[DnsProbePath, ...] = (),
) -> ProbeResult:
    issues: list[str] = []
    warnings: list[str] = []
    dns_snapshots = probe_dns_paths(spec, dns_paths, timeout=timeout)
    for snapshot in dns_snapshots:
        if snapshot.ok:
            continue
        expected = ",".join(snapshot.expected_addresses) or "-"
        actual = ",".join(snapshot.addresses) or "-"
        if snapshot.error:
            issues.append(f"{snapshot.name} DNS failed: {snapshot.error}")
        else:
            issues.append(f"{snapshot.name} DNS expected {expected}, got {actual}")
    try:
        addresses = resolve_host_addresses(spec.host)
    except Exception as exc:
        return ProbeResult(
            host=spec.host,
            label=spec.label,
            surface=spec.surface,
            addresses=(),
            dns_paths=dns_snapshots,
            tls=None,
            http=None,
            trust_ok=False,
            trust_error="",
            issues=(f"dns resolution failed: {exc.__class__.__name__}: {exc}",),
            warnings=(),
        )

    tls: TlsSnapshot | None = None
    try:
        tls = fetch_tls_snapshot(spec.host, timeout=timeout)
    except Exception as exc:
        issues.append(f"tls handshake failed: {exc.__class__.__name__}: {exc}")

    trust_error = ""
    trust_ok = False
    if check_trust:
        trust_error = check_system_trust(spec.host, timeout=timeout)
        trust_ok = not trust_error
        if trust_error:
            issues.append(f"system trust check failed: {trust_error}")

    http: HttpSnapshot | None = None
    try:
        http = fetch_http_snapshot(spec.host, path=spec.path, timeout=timeout)
    except Exception as exc:
        issues.append(f"http request failed: {exc.__class__.__name__}: {exc}")

    if tls is not None:
        if not tls.hostname_matches:
            issues.append("certificate SAN does not match hostname")
        if tls.days_remaining < min_lifetime_days:
            issues.append(
                f"certificate expires too soon ({tls.days_remaining:.2f}d < {min_lifetime_days:.2f}d)"
            )

    if http is not None:
        if spec.redirect_to_host:
            if http.status not in REDIRECT_STATUSES:
                issues.append(
                    f"expected redirect to {spec.redirect_to_host}, got HTTP {http.status}"
                )
            elif not http.location:
                issues.append(
                    f"expected redirect to {spec.redirect_to_host}, got no Location header"
                )
            else:
                redirect_host = (urlparse(http.location).hostname or "").strip().lower()
                if redirect_host != spec.redirect_to_host:
                    issues.append(
                        f"expected redirect to {spec.redirect_to_host}, got {http.location}"
                    )
        elif http.status >= 500:
            warnings.append(f"backend returned HTTP {http.status}")

    return ProbeResult(
        host=spec.host,
        label=spec.label,
        surface=spec.surface,
        addresses=addresses,
        dns_paths=dns_snapshots,
        tls=tls,
        http=http,
        trust_ok=trust_ok,
        trust_error=trust_error,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def _status_label(result: ProbeResult) -> str:
    if not result.ok:
        return "FAIL"
    if result.warnings:
        return "WARN"
    return "OK"


def render_text_report(results: list[ProbeResult]) -> str:
    lines: list[str] = []
    for result in results:
        addresses = ",".join(result.addresses) or "-"
        tls_days = "-"
        if result.tls is not None:
            tls_days = f"{result.tls.days_remaining:.1f}d"
        http_status = "-"
        location = "-"
        if result.http is not None:
            http_status = str(result.http.status)
            location = result.http.location or "-"
        trust = (
            "yes"
            if result.trust_ok
            else ("skipped" if not result.trust_error else "no")
        )
        detail = (
            f"{_status_label(result)} {result.host} [{result.label}] "
            f"type={result.surface} "
            f"dns={addresses} tls={tls_days} trust={trust} http={http_status}"
        )
        if location != "-":
            detail += f" location={location}"
        lines.append(detail)
        for snapshot in result.dns_paths:
            dns_status = "OK" if snapshot.ok else "FAIL"
            actual = ",".join(snapshot.addresses) or "-"
            expected = ",".join(snapshot.expected_addresses) or "-"
            detail = (
                f"  dns-path: {dns_status} {snapshot.name} "
                f"@{snapshot.resolver}/{snapshot.transport}={actual} "
                f"expected={expected}"
            )
            if snapshot.error:
                detail += f" error={snapshot.error}"
            lines.append(detail)
        for issue in result.issues:
            lines.append(f"  issue: {issue}")
        for warning in result.warnings:
            lines.append(f"  warn: {warning}")
    ok_count = sum(1 for result in results if result.ok and not result.warnings)
    warn_count = sum(1 for result in results if result.ok and result.warnings)
    fail_count = sum(1 for result in results if not result.ok)
    lines.append(
        f"Summary: ok={ok_count} warn={warn_count} fail={fail_count} total={len(results)}"
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Norman front-door DNS, TLS, trust, and redirect health."
    )
    parser.add_argument(
        "--profile",
        choices=("road",),
        default="road",
        help="Named host set to probe.",
    )
    parser.add_argument(
        "--dns-profile",
        choices=("none", "networking"),
        default="none",
        help=(
            "Optional resolver-path checks. `networking` verifies LAN DNS plus "
            "DOHIO UDP/TCP road DNS and is intended to run from networking.home.arpa."
        ),
    )
    parser.add_argument(
        "--host",
        action="append",
        default=[],
        help="Specific hostname to probe. Can be repeated; bypasses the named profile.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-step timeout in seconds.",
    )
    parser.add_argument(
        "--min-days",
        type=float,
        default=DEFAULT_MIN_LIFETIME_DAYS,
        help="Fail if the certificate expires sooner than this many days.",
    )
    parser.add_argument(
        "--no-trust-check",
        action="store_true",
        help="Skip the system trust verification step.",
    )
    parser.add_argument(
        "--lan-dns-server",
        default=DEFAULT_LAN_DNS_SERVER,
        help="LAN resolver to query when --dns-profile networking is enabled.",
    )
    parser.add_argument(
        "--dohio-dns-server",
        default=DEFAULT_DOHIO_DNS_SERVER,
        help="DOHIO/tailnet resolver to query when --dns-profile networking is enabled.",
    )
    parser.add_argument(
        "--lan-frontdoor-address",
        default=DEFAULT_LAN_FRONTDOOR_ADDRESS,
        help="Expected LAN frontdoor address for bot/TUI shortcut hosts.",
    )
    parser.add_argument(
        "--road-frontdoor-address",
        default=DEFAULT_ROAD_FRONTDOOR_ADDRESS,
        help="Expected DOHIO/tailnet frontdoor address for bot/TUI shortcut hosts.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a text report.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write the report. Parent directories are created.",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 after writing the report; useful for scheduled snapshot jobs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    specs = select_specs(
        args.profile,
        args.host,
        lan_frontdoor_address=args.lan_frontdoor_address,
        road_frontdoor_address=args.road_frontdoor_address,
    )
    dns_paths = build_dns_probe_paths(
        args.dns_profile,
        lan_dns_server=args.lan_dns_server,
        dohio_dns_server=args.dohio_dns_server,
    )
    results = [
        probe_host(
            spec,
            timeout=args.timeout,
            min_lifetime_days=args.min_days,
            check_trust=not args.no_trust_check,
            dns_paths=dns_paths,
        )
        for spec in specs
    ]
    if args.json:
        report = json.dumps(
            [asdict(result) for result in results], indent=2, sort_keys=True
        )
    else:
        report = render_text_report(results)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
    if args.exit_zero:
        return 0
    return 1 if any(not result.ok for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
