#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sync_agent_console_template import (
    HOSTS,
    discover_all_instances,
    host_frontdoor_hosts,
)


SCRIPT_DIR = Path(__file__).resolve().parent
INTERNAL_TLS_IMPORT = "import norman_internal_tls"

BOT_PATH_ALIASES: dict[str, tuple[str, ...]] = {
    "autocamera": ("auto",),
    "cloudagent": ("cloud",),
    "compere": ("keystone",),
    "control-plane": ("cp", "control", "controlplane"),
    "dj": ("yt", "youtube"),
    "gold-book": ("goldbook",),
    "housebot": ("house",),
    "leadership-kpis": ("leadership", "kpis"),
    "market-sizing": ("market",),
    "parkergale": ("pefb", "pef"),
    "phone-ops": ("phone", "phoneops"),
    "platinum-standard": ("platinum", "platinumstandard"),
    "publisher": ("editor", "cms", "publisher"),
    "scout": ("scoutbot",),
    "studio": ("camera-studio", "control-room"),
    "tmi-dashboards": ("tmi", "dashboards"),
}

BOT_HOST_LABELS: dict[str, tuple[str, ...]] = {
    "autocamera": ("autocamera", "auto"),
    "castle": ("castle",),
    "cloudagent": ("cloudagent", "cloud"),
    "compere": ("keystone", "compere"),
    "control-plane": ("cp", "control", "controlplane"),
    "dj": ("dj", "yt"),
    "earlybird": ("earlybird",),
    "gold-book": ("goldbook",),
    "housebot": ("housebot", "house"),
    "infra": ("infra",),
    "leadership-kpis": ("leadership", "kpis"),
    "market-sizing": ("market",),
    "networking": ("networking", "netbot"),
    "panelbot": ("panelbot",),
    "parkergale": ("pefb", "pef", "parkergale"),
    "phone-ops": ("phone", "phoneops"),
    "platinum-standard": ("platinum", "platinumstandard"),
    "publisher": ("publisher", "editor", "cms"),
    "scout": ("scout", "scoutbot"),
    "studio": ("studio", "camera-studio"),
    "theseus": ("theseus",),
    "tmi-dashboards": ("tmi",),
    "tv": ("tv",),
    "uplink": ("uplink",),
    "uscache": ("uscache",),
}

BOT_INTERNAL_FQDN_OVERRIDES: dict[str, tuple[str, ...]] = {
    # Keep the Glimpser app on glimpser.home.arpa; Eyebat is the Glimpser code operator bot.
    "glimpser": ("eyebat.home.arpa",),
    # Keep both the service-style short host and a bot-specific alias available.
    "mls": ("mlsbot.home.arpa", "mls.home.arpa"),
}

BOT_PUBLIC_FQDN_OVERRIDES: dict[str, tuple[str, ...]] = {
    "compere": ("keystone.kris.openbrand.com",),
    "control-plane": ("cp.kris.openbrand.com", "control.kris.openbrand.com"),
    "earlybird": ("earlybird.kris.openbrand.com",),
    "gold-book": ("goldbook.kris.openbrand.com",),
    "infra": ("infra.kris.openbrand.com",),
    "leadership-kpis": ("kpis.kris.openbrand.com", "leadership.kris.openbrand.com"),
    "market-sizing": ("market.kris.openbrand.com",),
    "mls": ("mls.kris.openbrand.com",),
    "panelbot": ("panelbot.kris.openbrand.com",),
    "platinum-standard": ("platinum.kris.openbrand.com",),
    "publisher": ("publisher.kris.openbrand.com", "editor.kris.openbrand.com"),
    "scout": ("scout.kris.openbrand.com",),
    "tmi-dashboards": ("dashboards.kris.openbrand.com", "tmi.kris.openbrand.com"),
}

WORK_BOT_KRIS_LOLLIE_SUFFIX = ".kris.lollie.org"
HOME_BOT_KNOX_LOLLIE_SUFFIX = ".knox.lollie.org"

# These work-bot names live under the kris.openbrand.com namespace but are
# intentionally Knox-local only. `io` resolves them to Norman via split DNS and
# Caddy terminates them with internal TLS, but they should not be treated as a
# Route53/public DNS target unless explicitly promoted later.
BOT_PUBLIC_INTERNAL_TLS_NAMES = {
    "compere",
    "earlybird",
    "infra",
    "leadership-kpis",
    "market-sizing",
    "mls",
    "panelbot",
    "scout",
    "tmi-dashboards",
    "publisher",
}

BOT_PUBLIC_KNOX_LOCAL_ONLY_NAMES = BOT_PUBLIC_INTERNAL_TLS_NAMES

BOT_HOME_KNOX_FQDN_OVERRIDES: dict[str, tuple[str, ...]] = {
    "autocamera": ("autocamera.knox.lollie.org",),
    "housebot": ("housebot.knox.lollie.org",),
    "theseus": ("theseus.knox.lollie.org",),
}

KNOX_LOCAL_ONLY_CLIENTS = (
    "127.0.0.1/32",
    "::1/128",
    "192.168.2.1/32",  # io / router
    "192.168.2.136/32",  # pixel10
    "100.78.41.73/32",  # pixel10 tailnet
    "192.168.2.137/32",  # hal
    "100.112.62.71/32",  # hal tailnet
    "192.168.2.140/32",  # plasma-mobile
    "100.109.202.7/32",  # plasma-mobile tailnet
    "192.168.2.141/32",  # yoga laptop
)

RESERVED_HOSTS = {
    host.public_host.strip().lower()
    for host in HOSTS.values()
    if host.public_host.strip()
}
ALLOWED_RESERVED_BOT_HOSTS = {
    # Intentionally reclaim this short name for the bot; the host surface moves to networking-host.home.arpa.
    "networking.home.arpa",
}

SPECIAL_PATH_ROUTES: dict[str, str] = {
    "ops": f"{HOSTS['norman'].lan_host}:8797",
    "subprime": f"{HOSTS['norman'].lan_host}:8796",
}

SPECIAL_FRONTDOOR_UPSTREAMS: dict[str, str] = {
    "switchboard": "127.0.0.1:8000",
}

SPECIAL_HOST_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "ops": (
        (
            "ops.home.arpa",
            "ops.norman.home.arpa",
            "normanops.home.arpa",
        ),
    ),
    "subprime": (
        (
            "subprime.home.arpa",
            "subprime.norman.home.arpa",
            "botprime.home.arpa",
            "bot.norman.home.arpa",
        ),
    ),
    "switchboard": (
        (
            "switchboard.home.arpa",
            "switchboard.norman.home.arpa",
        ),
    ),
}

SPECIAL_HOST_UPSTREAMS: dict[str, str] = {
    "ops": SPECIAL_PATH_ROUTES["ops"],
    "subprime": SPECIAL_PATH_ROUTES["subprime"],
    "switchboard": SPECIAL_FRONTDOOR_UPSTREAMS["switchboard"],
}

LOCAL_LLM_UPSTREAMS = (
    "192.168.2.133:18151",
    "192.168.2.150:18151",
    "192.168.2.151:18151",
)
LOCAL_LLM_CANONICAL_HOSTS = ("llm.knox.lollie.org",)
LOCAL_LLM_ALIAS_HOSTS = ("llm.home.arpa",)
DEFAULT_LB_TRY_DURATION = "5s"
DEFAULT_HEALTH_INTERVAL = "10s"
LOCAL_LLM_LB_TRY_DURATION = "15s"
LOCAL_LLM_HEALTH_INTERVAL = "3s"


def _route_block(slug: str, upstream: str) -> str:
    slug = slug.strip()
    return f"""
redir /bot/{slug} /bot/{slug}/ 308
handle_path /bot/{slug}/* {{
    reverse_proxy {upstream} {{
        header_up X-Forwarded-Prefix /bot/{slug}
    }}
}}
""".strip()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        candidate = value.strip().lower()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _internal_bot_hosts(name: str) -> tuple[str, ...]:
    if name in BOT_INTERNAL_FQDN_OVERRIDES:
        return BOT_INTERNAL_FQDN_OVERRIDES[name]
    labels = BOT_HOST_LABELS.get(name, (name,))
    hosts = _dedupe_preserve_order([f"{label}.home.arpa" for label in labels if label])
    filtered: list[str] = []
    for host in hosts:
        if host in RESERVED_HOSTS and host not in ALLOWED_RESERVED_BOT_HOSTS:
            continue
        filtered.append(host)
    return tuple(filtered)


def _public_bot_hosts(name: str) -> tuple[str, ...]:
    return BOT_PUBLIC_FQDN_OVERRIDES.get(name, ())


def _canonical_bot_hosts(name: str) -> tuple[str, ...]:
    public_hosts = _public_bot_hosts(name)
    if public_hosts:
        return (public_hosts[0],)
    return _internal_bot_hosts(name)


def _work_bot_lollie_hosts(name: str) -> tuple[str, ...]:
    if name not in BOT_PUBLIC_FQDN_OVERRIDES:
        return ()
    labels: list[str] = []
    for host in _public_bot_hosts(name):
        if host.endswith(".kris.openbrand.com"):
            labels.append(host.removesuffix(".kris.openbrand.com"))
    labels.extend(BOT_HOST_LABELS.get(name, (name,)))
    return tuple(
        _dedupe_preserve_order(
            [f"{label}{WORK_BOT_KRIS_LOLLIE_SUFFIX}" for label in labels if label]
        )
    )


def _home_bot_knox_hosts(name: str) -> tuple[str, ...]:
    return BOT_HOME_KNOX_FQDN_OVERRIDES.get(name, ())


def _alias_bot_host_groups(name: str) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    public_hosts = _public_bot_hosts(name)
    if public_hosts:
        if len(public_hosts) > 1:
            groups.append(tuple(host for host in public_hosts[1:] if host))
        internal_hosts = _internal_bot_hosts(name)
        if internal_hosts:
            groups.append(internal_hosts)
        lollie_hosts = _work_bot_lollie_hosts(name)
        if lollie_hosts:
            groups.append(lollie_hosts)
    home_knox_hosts = _home_bot_knox_hosts(name)
    if home_knox_hosts:
        groups.append(home_knox_hosts)
    return tuple(group for group in groups if group)


def bot_host_groups(name: str) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    canonical_hosts = _canonical_bot_hosts(name)
    if canonical_hosts:
        groups.append(canonical_hosts)
    groups.extend(_alias_bot_host_groups(name))
    return tuple(groups)


def bot_hosts(name: str) -> tuple[str, ...]:
    flattened: list[str] = []
    for group in bot_host_groups(name):
        flattened.extend(group)
    return tuple(flattened)


def _uses_public_tls(hostnames: tuple[str, ...]) -> bool:
    return any(host.endswith(".kris.openbrand.com") for host in hostnames)


def _reverse_proxy_lines(
    upstreams: str | tuple[str, ...],
    *,
    prefix: str = "    ",
    lb_try_duration: str = DEFAULT_LB_TRY_DURATION,
    health_interval: str = DEFAULT_HEALTH_INTERVAL,
) -> list[str]:
    if isinstance(upstreams, str):
        return [f"{prefix}reverse_proxy {upstreams}"]
    clean = tuple(item.strip() for item in upstreams if item.strip())
    if len(clean) <= 1:
        return [f"{prefix}reverse_proxy {clean[0]}"] if clean else []
    joined = " ".join(clean)
    return [
        f"{prefix}reverse_proxy {joined} {{",
        f"{prefix}    lb_policy first",
        f"{prefix}    lb_try_duration {lb_try_duration}",
        f"{prefix}    lb_try_interval 250ms",
        f"{prefix}    fail_duration 20s",
        f"{prefix}    max_fails 1",
        f"{prefix}    health_uri /healthz",
        f"{prefix}    health_interval {health_interval}",
        f"{prefix}    health_timeout 2s",
        f"{prefix}}}",
    ]


def _host_block(
    hostnames: tuple[str, ...],
    upstream: str | tuple[str, ...],
    *,
    internal_tls: bool = False,
    allowed_clients: tuple[str, ...] = (),
    lb_try_duration: str = DEFAULT_LB_TRY_DURATION,
    health_interval: str = DEFAULT_HEALTH_INTERVAL,
) -> str:
    https_hosts = ", ".join(hostnames)
    http_hosts = ", ".join(f"http://{host}" for host in hostnames)
    lines = [
        f"{http_hosts} {{",
        "    redir https://{host}{uri} 308",
        "}",
        "",
        f"{https_hosts} {{",
    ]
    if internal_tls or not _uses_public_tls(hostnames):
        lines.append(f"    {INTERNAL_TLS_IMPORT}")
    if allowed_clients:
        client_ranges = " ".join(allowed_clients)
        lines.extend(
            [
                f"    @knox_allowed remote_ip {client_ranges}",
                "    handle @knox_allowed {",
            ]
        )
        lines.extend(
            _reverse_proxy_lines(
                upstream,
                prefix="        ",
                lb_try_duration=lb_try_duration,
                health_interval=health_interval,
            )
        )
        lines.extend(["    }", '    respond "forbidden" 403', "}"])
    else:
        lines.extend(
            _reverse_proxy_lines(
                upstream,
                prefix="    ",
                lb_try_duration=lb_try_duration,
                health_interval=health_interval,
            )
        )
        lines.append("}")
    return "\n".join(lines)


def _redirect_host_block(
    hostnames: tuple[str, ...],
    canonical_host: str,
    *,
    internal_tls: bool = False,
    allowed_clients: tuple[str, ...] = (),
) -> str:
    https_hosts = ", ".join(hostnames)
    http_hosts = ", ".join(f"http://{host}" for host in hostnames)
    lines = [
        f"{http_hosts} {{",
        "    redir https://{host}{uri} 308",
        "}",
        "",
        f"{https_hosts} {{",
    ]
    if internal_tls or not _uses_public_tls(hostnames):
        lines.append(f"    {INTERNAL_TLS_IMPORT}")
    if allowed_clients:
        client_ranges = " ".join(allowed_clients)
        lines.extend(
            [
                f"    @knox_allowed remote_ip {client_ranges}",
                "    handle @knox_allowed {",
                f"        redir https://{canonical_host}" + "{uri} 308",
                "    }",
                '    respond "forbidden" 403',
                "}",
            ]
        )
    else:
        lines.extend(
            [
                f"    redir https://{canonical_host}" + "{uri} 308",
                "}",
            ]
        )
    return "\n".join(lines)


def render_paths() -> str:
    _, by_name = discover_all_instances()
    blocks: list[str] = []
    for name in sorted(by_name):
        instance = by_name[name]
        host = HOSTS[instance.host_name]
        if not instance.web_port:
            continue
        upstream = f"{host.lan_host}:{instance.web_port}"
        slugs = [name, *BOT_PATH_ALIASES.get(name, ())]
        rendered = []
        for slug in slugs:
            rendered.append(_route_block(slug, upstream))
        blocks.append(f"# {name}\n" + "\n\n".join(rendered))
    for slug, upstream in SPECIAL_PATH_ROUTES.items():
        blocks.append(f"# {slug}\n" + _route_block(slug, upstream))
    return "\n\n".join(blocks)


def render_hosts() -> str:
    _, by_name = discover_all_instances()
    blocks: list[str] = []
    for name in sorted(by_name):
        instance = by_name[name]
        host = HOSTS[instance.host_name]
        if not instance.web_port:
            continue
        canonical_hosts = _canonical_bot_hosts(name)
        if not canonical_hosts:
            continue
        upstream = f"{host.lan_host}:{instance.web_port}"
        public_hosts = _public_bot_hosts(name)
        canonical_host = canonical_hosts[0]
        use_internal_tls = bool(public_hosts) and name in BOT_PUBLIC_INTERNAL_TLS_NAMES
        allowed_clients = (
            KNOX_LOCAL_ONLY_CLIENTS
            if public_hosts and name in BOT_PUBLIC_KNOX_LOCAL_ONLY_NAMES
            else ()
        )
        rendered = [
            _host_block(
                canonical_hosts,
                upstream,
                internal_tls=use_internal_tls,
                allowed_clients=allowed_clients,
            )
        ]
        for hostnames in _alias_bot_host_groups(name):
            rendered.append(
                _redirect_host_block(
                    hostnames,
                    canonical_host,
                    internal_tls=(
                        hostnames
                        and all(
                            host.endswith(".kris.openbrand.com") for host in hostnames
                        )
                        and name in BOT_PUBLIC_INTERNAL_TLS_NAMES
                    ),
                    allowed_clients=allowed_clients,
                )
            )
        blocks.append(f"# {name}\n" + "\n\n".join(rendered))
    for name, host_groups in SPECIAL_HOST_GROUPS.items():
        upstream = SPECIAL_HOST_UPSTREAMS[name]
        rendered = [
            _host_block(hostnames, upstream, internal_tls=True)
            for hostnames in host_groups
        ]
        blocks.append(f"# {name}\n" + "\n\n".join(rendered))
    blocks.append(
        "# llm\n"
        + _host_block(
            (*LOCAL_LLM_ALIAS_HOSTS, *LOCAL_LLM_CANONICAL_HOSTS),
            LOCAL_LLM_UPSTREAMS,
            internal_tls=True,
            lb_try_duration=LOCAL_LLM_LB_TRY_DURATION,
            health_interval=LOCAL_LLM_HEALTH_INTERVAL,
        )
    )
    return "\n\n".join(blocks)


def render_dns_map(frontdoor_address: str | None = None) -> dict[str, str]:
    _, by_name = discover_all_instances()
    dns_map: dict[str, str] = {}
    norman_ip = frontdoor_address or HOSTS["norman"].lan_host
    for host in host_frontdoor_hosts(HOSTS["norman"]):
        if host.endswith(".ts.net"):
            continue
        dns_map[host] = norman_ip
    for name in sorted(by_name):
        if not by_name[name].web_port:
            continue
        for group in bot_host_groups(name):
            for host in group:
                dns_map[host] = norman_ip
    for host_groups in SPECIAL_HOST_GROUPS.values():
        for group in host_groups:
            for host in group:
                dns_map[host] = norman_ip
    for host in (*LOCAL_LLM_CANONICAL_HOSTS, *LOCAL_LLM_ALIAS_HOSTS):
        dns_map[host] = norman_ip
    return dns_map


def render_dns_json(frontdoor_address: str | None = None) -> str:
    return json.dumps(
        render_dns_map(frontdoor_address=frontdoor_address),
        indent=2,
        sort_keys=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Render Norman bot proxy Caddy config.")
    ap.add_argument(
        "--mode",
        choices=("paths", "hosts", "dns-json", "all"),
        default="all",
        help="Which output to render.",
    )
    ap.add_argument(
        "--frontdoor-address",
        help=(
            "Override the DNS frontdoor address. Use Norman's LAN IP for LAN DNS "
            "and Norman's Tailscale IP for tailnet/mobile DNS."
        ),
    )
    args = ap.parse_args()

    if args.mode == "paths":
        print(render_paths())
        return
    if args.mode == "hosts":
        print(render_hosts())
        return
    if args.mode == "dns-json":
        print(render_dns_json(frontdoor_address=args.frontdoor_address))
        return
    print(
        "# path-routes\n"
        + render_paths()
        + "\n\n# bot-hosts\n"
        + render_hosts()
        + "\n\n# dns-json\n"
        + render_dns_json(frontdoor_address=args.frontdoor_address)
    )


if __name__ == "__main__":
    main()
