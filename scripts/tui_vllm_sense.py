#!/usr/bin/env python3
"""Read-only vLLM/OpenAI-compatible endpoint sensing for local model routing."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


SCHEMA = "norman.tui.vllm-sense.v1"
DEFAULT_VLLM_PORT = 8000
DEFAULT_ENDPOINTS = (
    "https://llm.home.arpa",
    "http://llm.home.arpa",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)
DEFAULT_LAN_SUFFIXES = ("home.arpa", "local")
urlopen = request.urlopen


def _clean_endpoint(value: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    if not endpoint:
        return ""
    if "://" not in endpoint:
        endpoint = f"http://{endpoint}"
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/v1"):
        endpoint = endpoint[:-3]
    if endpoint.endswith("/v1/models"):
        endpoint = endpoint[: -len("/v1/models")]
    return endpoint.rstrip("/")


def _endpoint_scope(endpoint: str) -> str:
    host = endpoint.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "local"
    return "lan"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = _clean_endpoint(item)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _truthy_env(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _candidate_limit() -> int:
    try:
        return max(0, int(os.environ.get("NORMAN_TUI_VLLM_LAN_CANDIDATE_LIMIT", "48")))
    except ValueError:
        return 48


def configured_ports(extra_ports: list[int] | None = None) -> list[int]:
    raw = os.environ.get("NORMAN_TUI_VLLM_PORTS", "")
    ports: list[int] = [DEFAULT_VLLM_PORT, *(extra_ports or [])]
    for item in raw.split(","):
        try:
            port = int(item.strip())
        except ValueError:
            continue
        if port > 0:
            ports.append(port)
    return list(dict.fromkeys(ports))


def _endpoint_for_host(host: str, port: int = DEFAULT_VLLM_PORT) -> str:
    clean = str(host or "").strip().strip("[]")
    if not clean:
        return ""
    if "://" in clean:
        return _clean_endpoint(clean)
    if ":" in clean and not clean.count(".") == 3:
        clean = f"[{clean}]"
    return _clean_endpoint(f"http://{clean}:{port}")


def _private_lan_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return bool(
        address.version == 4
        and address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
    )


def _lan_host_candidate_ok(value: str) -> bool:
    clean = str(value or "").strip().strip("[]")
    if not clean:
        return False
    try:
        ipaddress.ip_address(clean)
    except ValueError:
        return True
    return _private_lan_ipv4(clean)


def _hostname_candidates() -> list[str]:
    names: list[str] = []
    for name in (socket.gethostname(), socket.getfqdn()):
        clean = str(name or "").strip().lower()
        if clean and clean not in {"localhost", "localhost.localdomain"}:
            names.append(clean)
            if "." not in clean:
                names.extend(f"{clean}.{suffix}" for suffix in DEFAULT_LAN_SUFFIXES)
    return list(dict.fromkeys(names))


def _local_ipv4_candidates() -> list[str]:
    hosts = _hostname_candidates() or [socket.gethostname()]
    addresses: list[str] = []
    for host in hosts:
        try:
            infos = socket.getaddrinfo(host, None, family=socket.AF_INET)
        except OSError:
            continue
        for info in infos:
            sockaddr = info[4]
            if not sockaddr:
                continue
            address = str(sockaddr[0] or "").strip()
            if _private_lan_ipv4(address):
                addresses.append(address)
    return list(dict.fromkeys(addresses))


def _arp_ipv4_candidates(path: Path = Path("/proc/net/arp")) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    addresses: list[str] = []
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        address = parts[0]
        if _private_lan_ipv4(address):
            addresses.append(address)
    return list(dict.fromkeys(addresses))


def configured_lan_hosts(extra_hosts: list[str] | None = None) -> list[str]:
    raw_env = os.environ.get("NORMAN_TUI_VLLM_LAN_HOSTS", "")
    env_hosts = [item.strip() for item in raw_env.split(",") if item.strip()]
    hosts = [
        *(extra_hosts or []),
        *env_hosts,
        *_hostname_candidates(),
        *_local_ipv4_candidates(),
        *_arp_ipv4_candidates(),
    ]
    limit = _candidate_limit()
    deduped = [host for host in dict.fromkeys(hosts) if _lan_host_candidate_ok(host)]
    return deduped[:limit] if limit else []


def autosensed_lan_endpoints(
    extra_hosts: list[str] | None = None, extra_ports: list[int] | None = None
) -> list[str]:
    ports = configured_ports(extra_ports)
    return _dedupe(
        [
            _endpoint_for_host(host, port)
            for host in configured_lan_hosts(extra_hosts)
            for port in ports
        ]
    )


def configured_endpoints(
    extra: list[str] | None = None,
    *,
    autosense_lan: bool | None = None,
    extra_lan_hosts: list[str] | None = None,
    extra_ports: list[int] | None = None,
) -> list[str]:
    raw_env = os.environ.get("NORMAN_TUI_VLLM_ENDPOINTS", "")
    env_items = [item.strip() for item in raw_env.split(",") if item.strip()]
    raw_default = os.environ.get("NORMAN_TUI_VLLM_DEFAULT_ENDPOINTS", "")
    default_items = (
        [item.strip() for item in raw_default.split(",") if item.strip()]
        if raw_default.strip()
        else list(DEFAULT_ENDPOINTS)
    )
    should_autosense = (
        _truthy_env("NORMAN_TUI_VLLM_AUTOSENSE_LAN", True)
        if autosense_lan is None
        else autosense_lan
    )
    lan_items = (
        autosensed_lan_endpoints(extra_lan_hosts, extra_ports)
        if should_autosense
        else []
    )
    return _dedupe([*(extra or []), *env_items, *default_items, *lan_items])


def _model_names(payload: dict[str, Any]) -> list[str]:
    candidates = payload.get("data")
    if not isinstance(candidates, list):
        candidates = payload.get("models")
    if not isinstance(candidates, list):
        return []
    names: list[str] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(
            item.get("id") or item.get("name") or item.get("model") or ""
        ).strip()
        if name:
            names.append(name)
    return sorted(set(names))


def _ssl_context() -> ssl.SSLContext | None:
    if _truthy_env("NORMAN_TUI_VLLM_TLS_VERIFY", False):
        return None
    return ssl._create_unverified_context()


def _request_headers(accept: str = "application/json") -> dict[str, str]:
    headers = {"Accept": accept}
    api_key = os.environ.get("NORMAN_TUI_VLLM_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


@dataclass(frozen=True)
class ProbeResult:
    endpoint: str
    scope: str
    ok: bool
    status: str
    latency_ms: int
    models: list[str]
    preferred_model: str
    health_ok: bool = False
    health_status: str = ""
    error: str = ""

    @property
    def usable(self) -> bool:
        return self.ok and (
            not self.preferred_model or self.preferred_model in set(self.models)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "provider": "vllm-openai-compatible",
            "scope": self.scope,
            "ok": self.ok,
            "usable": self.usable,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "health_ok": self.health_ok,
            "health_status": self.health_status,
            "models": self.models,
            "preferred_model": self.preferred_model,
            "error": self.error,
        }


def _probe_health(endpoint: str, *, timeout: float) -> tuple[bool, str]:
    try:
        req = request.Request(f"{endpoint}/health", headers=_request_headers("*/*"))
        with urlopen(req, timeout=timeout, context=_ssl_context()) as response:
            response.read()
        return True, "health-ok"
    except error.HTTPError as exc:
        return False, f"health-http-{exc.code}"
    except (OSError, TimeoutError, error.URLError) as exc:
        return False, str(exc)[:120]


def probe_endpoint(
    endpoint: str, *, timeout: float, preferred_model: str = ""
) -> ProbeResult:
    clean = _clean_endpoint(endpoint)
    started = time.monotonic()
    preferred = str(preferred_model or "").strip()
    try:
        req = request.Request(f"{clean}/v1/models", headers=_request_headers())
        with urlopen(req, timeout=timeout, context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = _model_names(payload)
        latency_ms = int((time.monotonic() - started) * 1000)
        if not models:
            status = "no-models"
        elif preferred and preferred not in set(models):
            status = "model-missing"
        else:
            status = "online"
        return ProbeResult(
            endpoint=clean,
            scope=_endpoint_scope(clean),
            ok=bool(models),
            status=status,
            latency_ms=latency_ms,
            models=models,
            preferred_model=preferred,
            health_ok=True,
            health_status="models-ok",
        )
    except error.HTTPError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        status = f"http-{exc.code}"
        health_ok = False
        health_status = ""
        if exc.code in {401, 403}:
            status = "auth-required"
        elif exc.code == 404:
            status = "not-openai-compatible"
        elif exc.code in {502, 503, 504}:
            health_ok, health_status = _probe_health(clean, timeout=timeout)
            if health_ok:
                status = "health-online-models-unavailable"
        error_text = f"models probe failed: HTTP {exc.code}"
        if health_status:
            error_text = f"{error_text}; health: {health_status}"
        return ProbeResult(
            endpoint=clean,
            scope=_endpoint_scope(clean),
            ok=False,
            status=status,
            latency_ms=latency_ms,
            models=[],
            preferred_model=preferred,
            health_ok=health_ok,
            health_status=health_status,
            error=error_text[:240],
        )
    except (OSError, TimeoutError, error.URLError, json.JSONDecodeError) as exc:
        health_ok, health_status = _probe_health(clean, timeout=timeout)
        latency_ms = int((time.monotonic() - started) * 1000)
        status = "health-online-models-unavailable" if health_ok else "offline"
        error_text = str(exc)[:160]
        if health_status:
            error_text = f"models probe failed: {error_text}; health: {health_status}"
        return ProbeResult(
            endpoint=clean,
            scope=_endpoint_scope(clean),
            ok=False,
            status=status,
            latency_ms=latency_ms,
            models=[],
            preferred_model=preferred,
            health_ok=health_ok,
            health_status=health_status,
            error=error_text[:240],
        )


def build_report(
    endpoints: list[str],
    *,
    timeout: float,
    preferred_model: str = "",
    stop_after_usable: bool = False,
) -> dict[str, Any]:
    candidate_endpoints = _dedupe(endpoints)
    results: list[ProbeResult] = []
    for endpoint in candidate_endpoints:
        result = probe_endpoint(
            endpoint,
            timeout=timeout,
            preferred_model=preferred_model,
        )
        results.append(result)
        if stop_after_usable and result.usable:
            break
    usable = [result for result in results if result.usable]
    online = [result for result in results if result.ok]
    reachable = [result for result in results if result.ok or result.health_ok]
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "summary": {
            "candidate_endpoint_count": len(candidate_endpoints),
            "total_endpoints": len(results),
            "reachable_endpoints": len(reachable),
            "online_endpoints": len(online),
            "usable_endpoints": len(usable),
            "local_endpoints": sum(1 for result in results if result.scope == "local"),
            "lan_endpoints": sum(1 for result in results if result.scope == "lan"),
            "reachable_lan_endpoints": sum(
                1 for result in reachable if result.scope == "lan"
            ),
            "online_lan_endpoints": sum(
                1 for result in online if result.scope == "lan"
            ),
            "preferred_model": preferred_model,
            "best_endpoint": usable[0].endpoint if usable else "",
            "degradation_ready": bool(usable),
        },
        "endpoints": [result.as_dict() for result in results],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# TUI vLLM Sense",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Degradation ready: {summary['degradation_ready']}",
        f"- Reachable endpoints: {summary['reachable_endpoints']}/{summary['total_endpoints']}",
        f"- Online endpoints: {summary['online_endpoints']}/{summary['total_endpoints']}",
        f"- Usable endpoints: {summary['usable_endpoints']}",
        f"- LAN endpoints: {summary['online_lan_endpoints']}/{summary['lan_endpoints']} model-online; {summary['reachable_lan_endpoints']} reachable",
        f"- Best endpoint: {summary['best_endpoint'] or 'none'}",
        "",
        "| Endpoint | Scope | Status | Health | Latency ms | Models |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in report["endpoints"]:
        models = ", ".join(item["models"][:6])
        if len(item["models"]) > 6:
            models += f", +{len(item['models']) - 6} more"
        if item["error"] and not models:
            models = item["error"]
        lines.append(
            "| {endpoint} | {scope} | {status} | {health} | {latency_ms} | {models} |".format(
                endpoint=item["endpoint"],
                scope=item["scope"],
                status=item["status"],
                health=item.get("health_status") or "-",
                latency_ms=item["latency_ms"],
                models=models or "-",
            )
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="vLLM/OpenAI-compatible endpoint base URL, such as http://host:8000.",
    )
    parser.add_argument(
        "--lan-host",
        action="append",
        default=[],
        help="LAN host or IP to autosense on configured vLLM ports.",
    )
    parser.add_argument(
        "--port",
        action="append",
        type=int,
        default=[],
        help="Additional port to probe for --lan-host/autosensed LAN hosts.",
    )
    parser.add_argument(
        "--no-autosense-lan",
        action="store_true",
        help="Only probe default, env, and explicit --endpoint values.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("NORMAN_TUI_VLLM_TIMEOUT_SECONDS", "1.5")),
        help="Per-endpoint timeout in seconds.",
    )
    parser.add_argument(
        "--preferred-model",
        default=os.environ.get("NORMAN_TUI_VLLM_MODEL", ""),
        help="Optional model that must be present for an endpoint to be usable.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON report to this path.")
    parser.add_argument(
        "--markdown", type=Path, help="Write Markdown report to this path."
    )
    parser.add_argument(
        "--fail-when-none",
        action="store_true",
        help="Exit non-zero when no usable endpoint is found.",
    )
    parser.add_argument(
        "--probe-all",
        action="store_true",
        help="Probe every candidate even after a usable endpoint is found.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        configured_endpoints(
            args.endpoint,
            autosense_lan=not args.no_autosense_lan,
            extra_lan_hosts=args.lan_host,
            extra_ports=args.port,
        ),
        timeout=max(0.1, args.timeout),
        preferred_model=args.preferred_model.strip(),
        stop_after_usable=not args.probe_all,
    )
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    if args.markdown:
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if args.fail_when_none and not report["summary"]["degradation_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
