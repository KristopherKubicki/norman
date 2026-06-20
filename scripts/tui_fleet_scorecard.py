#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from app.services.console_status import (
    classify_console_credit_assessment,
    fetch_console_status,
)
from render_norman_bot_proxy_caddy import (
    SPECIAL_HOST_GROUPS,
    bot_hosts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "norman.db"
DEFAULT_REGISTRY = REPO_ROOT / "db" / "estate" / "registry.yaml"
DEFAULT_PERSISTED_HOSTS = Path("/etc/caddy/includes/norman-bot-hosts.caddy")
DEFAULT_OPERATOR_CONSOLE_LINK_PATHS = (
    Path("/home/operator/.codex-work/web-bridge/console_links.json"),
    Path("/home/operator/.codex-bot-prime/web-bridge/console_links.json"),
)
DEFAULT_HEADSCALE_RESOLVER = "100.64.0.5"
DEFAULT_TAILSCALE_RESOLVER = "100.100.100.100"
DEFAULT_RESOLVER_PROFILE = "tailscale"
RESOLVER_PROFILES = {
    "headscale": DEFAULT_HEADSCALE_RESOLVER,
    "tailscale": DEFAULT_TAILSCALE_RESOLVER,
}
DEFAULT_FRONTDOOR_IP = "127.0.0.1"
DEFAULT_HEADSCALE_FRONTDOOR = "192.168.2.241"
DEFAULT_TAILSCALE_FRONTDOOR = "100.103.34.17"
FRONTDOOR_PROFILES = {
    "headscale": DEFAULT_HEADSCALE_FRONTDOOR,
    "tailscale": DEFAULT_TAILSCALE_FRONTDOOR,
}

TUI_SERVICE_KINDS = {
    "game-tui",
    "ops-console",
}

NON_TUI_SLUGS = {
    "norman-ops",
    "publisher",
    "subprime",
    "switchboard",
}

SLUG_ALIASES = {
    "control_plane": "control-plane",
    "tmi_dashboards": "tmi-dashboards",
    "norman-agent": "norman",
    "norman-service": "norman",
    "norman-bot-prime": "subprime",
}

HOST_LIKE_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


@dataclass
class FleetItem:
    slug: str
    label: str
    source: str
    connector_name: str = ""
    collector_url: str = ""
    web_url: str = ""
    token: str = ""
    route_hosts: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    ok: bool
    score: int
    max_score: int
    detail: str = ""
    status: str = ""


@dataclass
class ScoreRow:
    slug: str
    label: str
    source: str
    score: int
    grade: str
    collector: CheckResult
    authenticated: CheckResult
    runtime: CheckResult
    drift: CheckResult
    usage: CheckResult
    storage: CheckResult
    frontdoor: CheckResult
    dns: CheckResult
    persistence: CheckResult
    notes: list[str] = field(default_factory=list)


def _norm_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    return text


def _status_url(base_url: str, *, token: str = "") -> str:
    normalized = _norm_url(base_url)
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    if token:
        query_items["token"] = token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/api/status",
            urlencode(query_items),
            "",
        )
    )


def _url_with_token(base_url: str, token: str) -> str:
    normalized = _norm_url(base_url)
    if not normalized or not token:
        return normalized
    parts = urlsplit(normalized)
    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    query_items.setdefault("token", token)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", urlencode(query_items), "")
    )


def _slug_from_connector(connector_name: str) -> str:
    name = str(connector_name or "").strip()
    if name.startswith("tmux:"):
        name = name.split(":", 1)[1]
    return SLUG_ALIASES.get(name, name.replace("_", "-"))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def console_link_token_paths() -> list[Path]:
    env_value = os.environ.get("NORMAN_CONSOLE_LINK_PATHS", "").strip()
    if env_value:
        return [
            Path(value).expanduser()
            for value in env_value.split(os.pathsep)
            if value.strip()
        ]
    home = Path.home()
    candidates = [
        home / ".codex-work" / "web-bridge" / "console_links.json",
        home / ".codex-bot-prime" / "web-bridge" / "console_links.json",
        *DEFAULT_OPERATOR_CONSOLE_LINK_PATHS,
    ]
    seen: set[str] = set()
    paths: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def _coerce_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_number(value: object) -> str:
    number = max(0, _coerce_int(value))
    if number >= 1_000_000:
        text = f"{number / 1_000_000:.1f}M"
    elif number >= 1_000:
        text = f"{number / 1_000:.1f}K"
    else:
        return str(number)
    return text.replace(".0", "")


def sparkline_glyphs(values: list[object], *, floor: int = 0) -> str:
    clean_values = [max(0, _coerce_int(value)) for value in values if value is not None]
    if not clean_values:
        return ""
    bars = "▁▂▃▄▅▆▇█"
    max_value = max(max(clean_values), floor, 1)
    return "".join(
        bars[min(len(bars) - 1, round((value / max_value) * (len(bars) - 1)))]
        for value in clean_values
    )


def _tone_status(value: object) -> str:
    clean = str(value or "").strip().lower()
    if clean in {"alert", "error", "danger"}:
        return "alert"
    if clean in {"warn", "watch", "warning"}:
        return "warn"
    if clean in {"active", "busy"}:
        return "active"
    if clean in {"ok", "good", "ready"}:
        return "ok"
    return clean or "unknown"


def _host_from_url(value: str) -> str:
    normalized = _norm_url(value)
    if not normalized:
        return ""
    return str(urlsplit(normalized).hostname or "").strip().lower()


def _netloc_key(value: str) -> str:
    normalized = _norm_url(value)
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    return str(parts.netloc or "").strip().lower()


def _route_hosts_for(slug: str, web_url: str = "") -> list[str]:
    hosts: list[str] = []
    parts = urlsplit(_norm_url(web_url)) if web_url else None
    host = str(parts.hostname or "").strip().lower() if parts else ""
    explicit_port = parts.port if parts else None
    direct_service_port = explicit_port not in {None, 80, 443}
    if host and not HOST_LIKE_RE.match(host) and not direct_service_port:
        hosts.append(host)
    for group in SPECIAL_HOST_GROUPS.get(slug, ()):
        hosts.extend(group)
    try:
        hosts.extend(bot_hosts(slug))
    except Exception:
        pass
    if slug == "norman":
        hosts.append("norman.home.arpa")
    return _dedupe(hosts)


def _preferred_web_url(slug: str, existing: str) -> str:
    if existing:
        return existing
    hosts = _route_hosts_for(slug)
    if hosts:
        return f"https://{hosts[0]}/"
    return ""


def _load_tokens_from_console_links(paths: list[Path]) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        links = data.get("links")
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            for key in ("url", "lan_url", "tailnet_url"):
                url = str(link.get(key) or "").replace("{profile}", "")
                parts = urlsplit(_norm_url(url))
                query = {
                    item_key: item_value
                    for item_key, item_value in parse_qsl(
                        parts.query, keep_blank_values=True
                    )
                }
                token = str(query.get("token") or "").strip()
                if not token or not parts.netloc:
                    continue
                tokens[str(parts.netloc).lower()] = token
    return tokens


def load_db_items(db_path: Path) -> list[FleetItem]:
    if not db_path.exists() or db_path.stat().st_size <= 0:
        return []
    con = sqlite3.connect(db_path)
    rows = con.execute(
        """
        select
            channels.name,
            connectors.name,
            connectors.config
        from channels
        join connectors on channels.connector_id = connectors.id
        where connectors.connector_type = 'tmux'
        order by channels.id
        """
    ).fetchall()
    items: list[FleetItem] = []
    for channel_name, connector_name, config_raw in rows:
        try:
            cfg = json.loads(config_raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            cfg = {}
        slug = _slug_from_connector(str(connector_name or ""))
        collector_url = str(cfg.get("collector_url") or "").strip()
        web_url = str(cfg.get("web_url") or "").strip()
        token = str(cfg.get("web_token") or "").strip()
        if not collector_url and not web_url:
            continue
        if slug in NON_TUI_SLUGS:
            continue
        items.append(
            FleetItem(
                slug=slug,
                label=str(channel_name or slug).replace("Console - ", ""),
                source="db",
                connector_name=str(connector_name or ""),
                collector_url=collector_url,
                web_url=_preferred_web_url(slug, web_url),
                token=token,
                route_hosts=_route_hosts_for(slug, web_url),
            )
        )
    return items


def load_registry_items(registry_path: Path) -> list[FleetItem]:
    if not registry_path.exists():
        return []
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    services = data.get("services") if isinstance(data, dict) else []
    if not isinstance(services, list):
        return []
    items: list[FleetItem] = []
    for service in services:
        if not isinstance(service, dict):
            continue
        if service.get("is_active") is False:
            continue
        kind = str(service.get("kind") or "").strip()
        if kind not in TUI_SERVICE_KINDS:
            continue
        collector_url = str(service.get("console_url") or "").strip()
        if not collector_url:
            continue
        slug = str(service.get("slug") or "").strip()
        if not slug:
            continue
        slug = SLUG_ALIASES.get(slug, slug)
        if slug in NON_TUI_SLUGS:
            continue
        web_url = str(service.get("web_url") or "").strip()
        items.append(
            FleetItem(
                slug=slug,
                label=str(service.get("display_name") or slug),
                source="registry",
                collector_url=collector_url,
                web_url=_preferred_web_url(slug, web_url),
                route_hosts=_route_hosts_for(slug, web_url),
            )
        )
    return items


def merge_items(items: list[FleetItem], token_map: dict[str, str]) -> list[FleetItem]:
    merged: dict[str, FleetItem] = {}
    collector_keys: dict[str, str] = {}

    for item in items:
        collector_key = _netloc_key(item.collector_url)
        key = item.slug
        if item.source == "registry" and collector_key in collector_keys:
            key = collector_keys[collector_key]

        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            if collector_key:
                collector_keys[collector_key] = key
            continue

        if not existing.collector_url and item.collector_url:
            existing.collector_url = item.collector_url
        if not existing.web_url and item.web_url:
            existing.web_url = item.web_url
        if not existing.token and item.token:
            existing.token = item.token
        if not existing.connector_name and item.connector_name:
            existing.connector_name = item.connector_name
        existing.route_hosts = _dedupe(existing.route_hosts + item.route_hosts)
        if existing.source != item.source:
            existing.source = f"{existing.source}+{item.source}"

    for item in merged.values():
        if not item.token:
            for url in (item.collector_url, item.web_url):
                token = token_map.get(_netloc_key(url))
                if token:
                    item.token = token
                    break
        item.web_url = _preferred_web_url(item.slug, item.web_url)
        item.route_hosts = _dedupe(
            item.route_hosts or _route_hosts_for(item.slug, item.web_url)
        )

    return sorted(merged.values(), key=lambda item: item.label.lower())


def _curl_status(
    url: str, *, resolve_host: str = "", timeout: float = 2.0
) -> tuple[int, str]:
    if not url:
        return 0, "missing-url"
    cmd = [
        "curl",
        "-ksS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        str(timeout),
    ]
    if resolve_host:
        parts = urlsplit(_norm_url(url))
        port = parts.port or (443 if parts.scheme == "https" else 80)
        cmd.extend(["--resolve", f"{resolve_host}:{port}:{DEFAULT_FRONTDOOR_IP}"])
    cmd.append(url)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout + 1,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 0, str(exc)
    code_text = str(proc.stdout or "").strip()
    try:
        return int(code_text or 0), str(proc.stderr or "").strip()
    except ValueError:
        return 0, str(proc.stderr or code_text).strip()


def check_collector(item: FleetItem) -> CheckResult:
    status_url = _status_url(item.collector_url)
    code, error = _curl_status(status_url, timeout=2)
    if code == 200:
        return CheckResult(True, 20, 20, "status endpoint ok", str(code))
    if code == 403:
        return CheckResult(True, 20, 20, "token gate alive", str(code))
    if code:
        return CheckResult(False, 5, 20, f"unexpected HTTP {code}", str(code))
    return CheckResult(False, 0, 20, error or "no response", "down")


def check_authenticated_status(item: FleetItem) -> tuple[CheckResult, dict]:
    if not item.token:
        status = fetch_console_status(item.collector_url, timeout=1.75)
        if status.get("reachable"):
            return (
                CheckResult(
                    True,
                    12,
                    20,
                    "status visible without known token",
                    "visible-no-token",
                ),
                status,
            )
        return CheckResult(False, 0, 20, "no status token known", "missing-token"), {}
    status = fetch_console_status(
        item.collector_url, access_token=item.token, timeout=1.75
    )
    if status.get("reachable"):
        return CheckResult(True, 20, 20, "authenticated status ok", "ok"), status
    return CheckResult(False, 0, 20, "authenticated status failed", "failed"), status


def check_runtime(status: dict) -> CheckResult:
    if not status:
        return CheckResult(False, 0, 20, "runtime unknown", "unknown")
    assessment = classify_console_credit_assessment(status)
    if assessment.issue_code:
        return CheckResult(False, 0, 20, assessment.issue_label, assessment.issue_code)
    state = str(status.get("state") or "").strip().lower()
    pending = bool(status.get("pending"))
    queue_depth = int(status.get("queue_depth") or 0)
    has_error = bool(str(status.get("last_error") or "").strip())
    if state in {"error", "failed"}:
        return CheckResult(False, 0, 20, "runtime state is error", state)
    if has_error:
        return CheckResult(False, 12, 20, "last_error present", state or "warn")
    if pending or queue_depth > 0 or state == "running":
        return CheckResult(True, 14, 20, f"busy queue={queue_depth}", state or "busy")
    if state in {"ok", "idle", "ready"}:
        return CheckResult(True, 20, 20, "ready", state)
    return CheckResult(True, 16, 20, state or "reachable", state or "unknown")


def check_drift(status: dict) -> CheckResult:
    if not status:
        return CheckResult(True, 0, 0, "drift unknown", "unknown")
    drift = status.get("drift_assessment")
    if not isinstance(drift, dict):
        return CheckResult(True, 0, 0, "no drift signal yet", "missing")
    if drift.get("enabled") is False:
        return CheckResult(True, 0, 0, "drift disabled", "disabled")
    tone = _tone_status(drift.get("tone"))
    mission = str(drift.get("mission_drift") or "in_lane").replace("_", " ")
    context = str(drift.get("context_drift") or "fresh").replace("_", " ")
    scope = str(drift.get("scope_drift") or "normal").replace("_", " ")
    power = (
        drift.get("power_drift") if isinstance(drift.get("power_drift"), list) else []
    )
    summary = str(drift.get("summary") or tone or "drift").strip()
    severity_values = [
        {"in_lane": 0, "adjacent": 1, "cross_lane": 2}.get(
            str(drift.get("mission_drift") or "in_lane"), 0
        ),
        {"fresh": 0, "possibly_stale": 1, "conflicting": 2}.get(
            str(drift.get("context_drift") or "fresh"), 0
        ),
        {"normal": 0, "expanding": 1, "over_budget": 2}.get(
            str(drift.get("scope_drift") or "normal"), 0
        ),
        min(2, len([item for item in power if str(item or "").strip()])),
    ]
    glyph = sparkline_glyphs(severity_values, floor=2)
    power_label = (
        "+".join(str(item) for item in power if str(item or "").strip()) or "none"
    )
    detail = (
        f"{summary} {glyph}; mission={mission}; context={context}; "
        f"scope={scope}; power={power_label}"
    )
    return CheckResult(
        ok=tone not in {"warn", "alert"},
        score=0,
        max_score=0,
        detail=detail,
        status=tone,
    )


def check_usage(status: dict) -> CheckResult:
    if not status:
        return CheckResult(True, 0, 0, "usage unknown", "unknown")
    usage = status.get("usage") if isinstance(status.get("usage"), dict) else {}
    recent = usage.get("last_24h") if isinstance(usage.get("last_24h"), dict) else {}
    thread = (
        usage.get("current_thread")
        if isinstance(usage.get("current_thread"), dict)
        else {}
    )
    billing = usage.get("billing") if isinstance(usage.get("billing"), dict) else {}
    tag_health = (
        billing.get("tag_health") if isinstance(billing.get("tag_health"), dict) else {}
    )
    estimate = (
        billing.get("last_24h_estimate")
        if isinstance(billing.get("last_24h_estimate"), dict)
        else {}
    )
    sparkline_values = (
        billing.get("sparkline") if isinstance(billing.get("sparkline"), list) else []
    )
    recent_tokens = _coerce_int(recent.get("total_tokens"))
    recent_turns = _coerce_int(recent.get("turns"))
    thread_tokens = _coerce_int(thread.get("total_tokens"))
    tag_state = _tone_status(tag_health.get("state") or "ok")
    sparkline = sparkline_glyphs(sparkline_values)
    if recent_tokens >= 220_000:
        tone = "alert"
    elif recent_tokens >= 90_000 or tag_state in {"warn", "missing"}:
        tone = "warn"
    else:
        tone = "ok"
    if estimate.get("configured"):
        value = f"${float(estimate.get('usd') or 0.0):.2f}"
    elif recent_tokens:
        value = f"{_compact_number(recent_tokens)} tok"
    else:
        value = "quiet"
    detail = (
        f"{value}; 24h={_compact_number(recent_tokens)} tok/{recent_turns} turns; "
        f"thread={_compact_number(thread_tokens)} tok; tags={tag_state}; "
        f"burn={sparkline or 'n/a'}"
    )
    return CheckResult(
        ok=tone == "ok",
        score=0,
        max_score=0,
        detail=detail,
        status=tone,
    )


def check_storage(status: dict) -> CheckResult:
    if not status:
        return CheckResult(True, 0, 0, "storage unknown", "unknown")
    state_db_enabled = status.get("state_db_enabled")
    history_format = str(status.get("history_format") or "").strip()
    state_db_path = str(status.get("state_db_path") or "").strip()
    if state_db_enabled is True:
        if history_format:
            detail = history_format
            if state_db_path:
                detail = f"{detail}; {state_db_path}"
            return CheckResult(True, 0, 0, detail, "db")
        return CheckResult(True, 0, 0, state_db_path or "state DB enabled", "db")
    if state_db_enabled is False:
        return CheckResult(False, 0, 0, history_format or "state DB disabled", "jsonl")
    return CheckResult(False, 0, 0, "storage field missing from status", "missing")


def check_frontdoor(item: FleetItem) -> CheckResult:
    if not item.web_url:
        return CheckResult(False, 0, 15, "missing route URL", "missing")
    url = _url_with_token(item.web_url, item.token)
    parts = urlsplit(_norm_url(url))
    resolve_host = ""
    if (
        parts.scheme == "https"
        and parts.hostname
        and not HOST_LIKE_RE.match(parts.hostname)
    ):
        resolve_host = parts.hostname
    code, error = _curl_status(url, resolve_host=resolve_host, timeout=2.5)
    if 200 <= code < 400:
        return CheckResult(True, 15, 15, f"HTTP {code}", str(code))
    if code in {401, 403}:
        return CheckResult(
            False, 8, 15, f"route alive but auth denied HTTP {code}", str(code)
        )
    if code:
        return CheckResult(False, 4, 15, f"HTTP {code}", str(code))
    return CheckResult(False, 0, 15, error or "no response", "down")


def _dig_a(host: str, resolver: str) -> list[str]:
    try:
        proc = subprocess.run(
            [
                "dig",
                f"@{resolver}",
                host,
                "A",
                "+short",
                "+time=2",
                "+tries=1",
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def check_dns(
    item: FleetItem, expected_dns: dict[str, str], resolver: str
) -> CheckResult:
    expected_hosts = [host for host in item.route_hosts if host in expected_dns]
    if not expected_hosts:
        return CheckResult(True, 15, 15, "no managed DOHIO host", "skip")
    failures: list[str] = []
    checked = 0
    for host in expected_hosts:
        expected = expected_dns[host]
        answers = _dig_a(host, resolver)
        checked += 1
        if expected not in answers:
            failures.append(
                f"{host}={','.join(answers) or 'NO_ANSWER'} expected {expected}"
            )
    if not failures:
        return CheckResult(True, 15, 15, f"{checked} host(s) ok", "ok")
    score = 0 if len(failures) == checked else 8
    return CheckResult(False, score, 15, "; ".join(failures[:3]), "mismatch")


def check_persistence(item: FleetItem, persisted_hosts_path: Path) -> CheckResult:
    expected_hosts = [host for host in item.route_hosts if host.endswith(".home.arpa")]
    if not expected_hosts:
        return CheckResult(True, 10, 10, "no home.arpa route", "skip")
    try:
        source = persisted_hosts_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(False, 0, 10, str(exc), "unreadable")
    missing = [host for host in expected_hosts if host not in source]
    if not missing:
        return CheckResult(True, 10, 10, "persisted include has route", "ok")
    score = 0 if len(missing) == len(expected_hosts) else 5
    return CheckResult(False, score, 10, f"missing {', '.join(missing[:3])}", "missing")


def grade(score: int, row: ScoreRow | None = None) -> str:
    if row and not row.collector.ok:
        return "down"
    if row and row.runtime.status in {
        "needs_billing",
        "needs_reauth",
        "error",
        "failed",
    }:
        return "critical"
    if row and row.notes and score >= 90:
        return "watch"
    if score >= 90:
        return "good"
    if score >= 75:
        return "watch"
    if score >= 55:
        return "degraded"
    return "critical"


def score_item(
    item: FleetItem,
    expected_dns: dict[str, str],
    resolver: str,
    persisted_hosts_path: Path,
) -> ScoreRow:
    collector = check_collector(item)
    authenticated, status = check_authenticated_status(item)
    runtime = check_runtime(status)
    drift = check_drift(status)
    usage = check_usage(status)
    storage = check_storage(status)
    frontdoor = check_frontdoor(item)
    dns = check_dns(item, expected_dns, resolver)
    persistence = check_persistence(item, persisted_hosts_path)
    score = sum(
        result.score
        for result in (
            collector,
            authenticated,
            runtime,
            frontdoor,
            dns,
            persistence,
        )
    )
    notes: list[str] = []
    for label, result in (
        ("collector", collector),
        ("auth", authenticated),
        ("runtime", runtime),
        ("drift", drift),
        ("usage", usage),
        ("storage", storage),
        ("frontdoor", frontdoor),
        ("dns", dns),
        ("persist", persistence),
    ):
        if not result.ok or result.score < result.max_score:
            notes.append(f"{label}: {result.detail}")
    row = ScoreRow(
        slug=item.slug,
        label=item.label,
        source=item.source,
        score=score,
        grade="",
        collector=collector,
        authenticated=authenticated,
        runtime=runtime,
        drift=drift,
        usage=usage,
        storage=storage,
        frontdoor=frontdoor,
        dns=dns,
        persistence=persistence,
        notes=notes,
    )
    row.grade = grade(score, row)
    return row


def expected_tailnet_dns(items: list[FleetItem], frontdoor_ip: str) -> dict[str, str]:
    expected: dict[str, str] = {}
    for item in items:
        for host in item.route_hosts:
            if host.endswith(".home.arpa"):
                expected[host] = frontdoor_ip
    return expected


def render_markdown(rows: list[ScoreRow]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.grade] = counts.get(row.grade, 0) + 1
    checked_at = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    lines = [
        "# TUI Fleet Scorecard",
        "",
        f"Checked at: `{checked_at}`",
        "",
        "Rubric: collector endpoint 20, authenticated status 20, runtime/auth/quota 20, frontdoor route 15, DOHIO DNS 15, Caddy persistence 10.",
        "",
        "Summary: "
        + ", ".join(
            f"{name}={counts.get(name, 0)}"
            for name in ("good", "watch", "degraded", "critical", "down")
        ),
        "",
        "| Score | Grade | TUI | Runtime | Drift | Tokens | DB | Frontdoor | DNS | Persist | Notes |",
        "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted(rows, key=lambda item: (item.score, item.label.lower())):
        notes = "; ".join(row.notes[:4]) or "clear"
        lines.append(
            "| {score} | {grade} | {label} | {runtime} | {drift} | {usage} | {storage} | {frontdoor} | {dns} | {persist} | {notes} |".format(
                score=row.score,
                grade=row.grade,
                label=row.label.replace("|", "\\|"),
                runtime=row.runtime.status or ("ok" if row.runtime.ok else "bad"),
                drift=(row.drift.status or "unknown").replace("|", "\\|"),
                usage=(row.usage.detail or row.usage.status or "unknown").replace(
                    "|", "\\|"
                ),
                storage=(row.storage.status or "unknown").replace("|", "\\|"),
                frontdoor=row.frontdoor.status or ("ok" if row.frontdoor.ok else "bad"),
                dns=row.dns.status or ("ok" if row.dns.ok else "bad"),
                persist=row.persistence.status
                or ("ok" if row.persistence.ok else "bad"),
                notes=notes.replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Norman TUI fleet health.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--resolver-profile",
        choices=sorted(RESOLVER_PROFILES),
        default=DEFAULT_RESOLVER_PROFILE,
        help="Named DNS resolver plane to score.",
    )
    parser.add_argument(
        "--resolver",
        default="",
        help="Override DNS resolver IP. Defaults to --resolver-profile.",
    )
    parser.add_argument(
        "--tailnet-frontdoor",
        default="",
        help="Override expected frontdoor IP. Defaults to --resolver-profile.",
    )
    parser.add_argument("--persisted-hosts", type=Path, default=DEFAULT_PERSISTED_HOSTS)
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of markdown."
    )
    parser.add_argument("--output", type=Path, help="Write report to this path.")
    args = parser.parse_args()
    resolver = args.resolver or RESOLVER_PROFILES[args.resolver_profile]
    tailnet_frontdoor = (
        args.tailnet_frontdoor or FRONTDOOR_PROFILES[args.resolver_profile]
    )

    token_map = _load_tokens_from_console_links(console_link_token_paths())
    items = merge_items(
        [*load_db_items(args.db), *load_registry_items(args.registry)],
        token_map,
    )
    expected_dns = expected_tailnet_dns(items, tailnet_frontdoor)
    with ThreadPoolExecutor(max_workers=max(1, int(args.jobs))) as executor:
        rows = list(
            executor.map(
                lambda item: score_item(
                    item,
                    expected_dns,
                    resolver,
                    args.persisted_hosts,
                ),
                items,
            )
        )

    if args.json:
        payload = json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True)
    else:
        payload = render_markdown(rows)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
