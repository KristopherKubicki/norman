#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sync_agent_console_template import HOSTS, ConsoleInstance, discover_all_instances


SCRIPT_DIR = Path(__file__).resolve().parent

BOT_PATH_ALIASES: dict[str, tuple[str, ...]] = {
    "artmonster": ("artbot",),
    "autocamera": ("auto",),
    "cloudagent": ("cloud",),
    "compere": ("keystone",),
    "control-plane": ("cp", "control", "controlplane"),
    "dj": ("yt", "youtube"),
    "gold-book": ("goldbook",),
    "housebot": ("house",),
    "leadership-kpis": ("leadership", "kpis"),
    "market-sizing": ("mc", "market", "monte-carlo", "montecarlo"),
    "mc": ("market", "market-sizing", "monte-carlo", "montecarlo"),
    "parkergale": ("pefb", "pef"),
    "phone-ops": ("phone", "phoneops"),
    "platinum-standard": ("platinum", "platinumstandard"),
    "scout": ("ranger", "scoutbot"),
    "studio": ("camera-studio", "control-room"),
    "tmi-dashboards": ("tmi", "dashboards"),
}

BOT_HOST_LABELS: dict[str, tuple[str, ...]] = {
    "artmonster": ("artmonster", "artbot"),
    "autocamera": ("autocamera", "auto"),
    "castle": ("castle",),
    "cloudagent": ("cloudagent", "cloud"),
    "compere": ("keystone", "compere"),
    "control-plane": ("cp", "control", "controlplane"),
    "diamond-roc": ("diamond-roc", "diamondroc"),
    "dj": ("dj", "yt"),
    "earlybird": ("earlybird",),
    "gold-book": ("goldbook",),
    "housebot": ("housebot", "house"),
    "infra": ("infra",),
    "leadership-kpis": ("leadership", "kpis"),
    "market-sizing": ("mc", "market", "montecarlo"),
    "mc": ("mc", "market", "montecarlo"),
    "networking": ("networking", "netbot"),
    "panelbot": ("panelbot",),
    "parkergale": ("pefb", "pef", "parkergale"),
    "phone-ops": ("phone", "phoneops"),
    "platinum-standard": ("platinum", "platinumstandard"),
    "scout": ("ranger", "scoutbot"),
    "studio": ("studio", "camera-studio"),
    "theseus": ("theseus",),
    "tmi-dashboards": ("tmi",),
    "tv": ("tv",),
    "uplink": ("uplink",),
    "usbhome": ("usbhome",),
    "uscache": ("uscache",),
}

BOT_INTERNAL_FQDN_OVERRIDES: dict[str, tuple[str, ...]] = {
    "artmonster": ("artmonster.home.arpa", "artbot.home.arpa"),
    # Keep Glimpser service/app names separate from its operator bot session.
    "glimpser": ("eyebat.home.arpa", "eyeball.home.arpa"),
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
    "market-sizing": ("mc.kris.openbrand.com", "market.kris.openbrand.com"),
    "mc": ("mc.kris.openbrand.com", "market.kris.openbrand.com"),
    "mls": ("mls.kris.openbrand.com",),
    "panelbot": ("panelbot.kris.openbrand.com",),
    "platinum-standard": ("platinum.kris.openbrand.com",),
    # The console/TUI is Ranger; the underlying service identity remains scout.
    "scout": ("ranger.kris.openbrand.com",),
    "tmi-dashboards": ("dashboards.kris.openbrand.com", "tmi.kris.openbrand.com"),
}

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
    "mc",
    "mls",
    "panelbot",
    "scout",
    "tmi-dashboards",
}

BOT_PUBLIC_KNOX_LOCAL_ONLY_NAMES = BOT_PUBLIC_INTERNAL_TLS_NAMES

STATIC_PUBLIC_WORK_PORTS: dict[str, str] = {
    "earlybird": "8781",
    "infra": "8782",
    "control-plane": "8783",
    "market-sizing": "8784",
    "mc": "8784",
    "tmi-dashboards": "8785",
    "gold-book": "8786",
    "platinum-standard": "8787",
    "compere": "8789",
    "leadership-kpis": "8790",
    "panelbot": "8791",
    "mls": "8792",
    "scout": "8793",
}

STATIC_TUI_PORTS: dict[str, tuple[str, str]] = {
    "housebot": ("toy-box", "8787"),
    "glimpser": ("toy-box", "8788"),
    "castle": ("toy-box", "8789"),
    "phone-ops": ("toy-box", "8790"),
    "uscache": ("toy-box", "8791"),
    "usbhome": ("toy-box", "8792"),
    "diamond-roc": ("toy-box", "8796"),
    "autocamera": ("hal", "8794"),
    "theseus": ("hal", "8795"),
    "parkergale": ("private-host", "8796"),
    "networking": ("networking-host", "8791"),
    "uplink": ("networking-host", "8792"),
    "cloudagent": ("networking-host", "8793"),
    **{name: ("work-special", port) for name, port in STATIC_PUBLIC_WORK_PORTS.items()},
}

KNOX_LOCAL_ONLY_CLIENTS = (
    "127.0.0.1/32",
    "::1/128",
    "192.168.2.1/32",  # io / router
    "192.168.2.241/32",  # norman LAN front door
    "100.103.34.17/32",  # norman tailnet front door
    "fd7a:115c:a1e0::3438:2211/128",  # norman tailnet front door ipv6
    "192.168.2.136/32",  # pixel10
    "100.78.41.73/32",  # pixel10 tailnet
    "fd7a:115c:a1e0::4d33:2949/128",  # pixel10 tailnet ipv6
    "192.168.2.137/32",  # hal
    "100.112.62.71/32",  # hal tailnet
    "192.168.2.140/32",  # plasma-mobile
    "100.109.202.7/32",  # plasma-mobile tailnet
    "192.168.2.141/32",  # sal LAN
    "100.77.147.57/32",  # sal tailscale
)

BOT_EXTRA_KNOX_LOCAL_ONLY_CLIENTS: dict[str, tuple[str, ...]] = {
    "panelbot": (
        "192.168.2.141/32",  # sal LAN
        "100.77.147.57/32",  # sal tailscale
    ),
}

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
    "switchboard": f"{HOSTS['norman'].lan_host}:8765",
    "subprime": f"{HOSTS['norman'].lan_host}:8765",
}

SPECIAL_HOST_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "switchboard": (
        (
            "switchboard.home.arpa",
            "switchboard.norman.home.arpa",
        ),
        (
            "subprime.home.arpa",
            "subprime.norman.home.arpa",
            "botprime.home.arpa",
            "bot.norman.home.arpa",
        ),
    ),
}

SPECIAL_HOST_ONLY_ROUTES: dict[str, tuple[str, tuple[tuple[str, ...], ...]]] = {
    "bbs": (
        f"{HOSTS['norman'].lan_host}:8765",
        (("bbs.home.arpa",),),
    ),
}

NORMAN_TAILNET_FRONTDOOR = os.environ.get("NORMAN_TAILNET_FRONTDOOR", "100.103.34.17")


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


def knox_local_clients_for_bot(name: str) -> tuple[str, ...]:
    return tuple(
        _dedupe_preserve_order(
            [
                *KNOX_LOCAL_ONLY_CLIENTS,
                *BOT_EXTRA_KNOX_LOCAL_ONLY_CLIENTS.get(name, ()),
            ]
        )
    )


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


def bot_host_groups(name: str) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    public_hosts = _public_bot_hosts(name)
    if public_hosts:
        groups.append(public_hosts)
    internal_hosts = _internal_bot_hosts(name)
    if internal_hosts:
        groups.append(internal_hosts)
    return tuple(groups)


def bot_hosts(name: str) -> tuple[str, ...]:
    flattened: list[str] = []
    for group in bot_host_groups(name):
        flattened.extend(group)
    return tuple(flattened)


def _uses_public_tls(hostnames: tuple[str, ...]) -> bool:
    return any(host.endswith(".kris.openbrand.com") for host in hostnames)


def _host_block(
    hostnames: tuple[str, ...],
    upstream: str,
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
        lines.append("    tls internal")
    if allowed_clients:
        client_ranges = " ".join(allowed_clients)
        lines.extend(
            [
                f"    @knox_allowed remote_ip {client_ranges}",
                "    handle @knox_allowed {",
                f"        reverse_proxy {upstream}",
                "    }",
                '    respond "forbidden" 403',
                "}",
            ]
        )
    else:
        lines.extend(
            [
                f"    reverse_proxy {upstream}",
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


def _instances_with_static_public_fallbacks() -> dict[str, ConsoleInstance]:
    _, by_name = discover_all_instances()
    by_name = dict(by_name)
    for name, (host_name, port) in STATIC_TUI_PORTS.items():
        if name in by_name:
            continue
        fallback_host = HOSTS.get(host_name)
        if fallback_host is None:
            continue
        by_name[name] = ConsoleInstance(
            name=name,
            host_name=host_name,
            ssh_target=getattr(fallback_host, "ssh_target", ""),
            use_sudo=bool(getattr(fallback_host, "use_sudo", False)),
            env_file="",
            web_path="",
            launch_path="",
            supervisor_path="",
            restart_units=(),
            agent_label=name.replace("-", " ").title(),
            web_port=port,
            web_token="",
            prompt_file="",
            codex_home="",
        )
    return by_name


def render_hosts() -> str:
    by_name = _instances_with_static_public_fallbacks()
    blocks: list[str] = []
    seen_host_groups: set[tuple[str, ...]] = set()
    for name in sorted(by_name):
        instance = by_name[name]
        host = HOSTS[instance.host_name]
        if not instance.web_port:
            continue
        host_groups = bot_host_groups(name)
        if not host_groups:
            continue
        upstream = f"{host.lan_host}:{instance.web_port}"
        public_hosts = _public_bot_hosts(name)
        unique_host_groups = []
        for hostnames in host_groups:
            key = tuple(hostnames)
            if key in seen_host_groups:
                continue
            seen_host_groups.add(key)
            unique_host_groups.append(hostnames)
        if not unique_host_groups:
            continue
        rendered = [
            _host_block(
                hostnames,
                upstream,
                internal_tls=(
                    hostnames == public_hosts and name in BOT_PUBLIC_INTERNAL_TLS_NAMES
                ),
                allowed_clients=(
                    knox_local_clients_for_bot(name)
                    if hostnames == public_hosts
                    and name in BOT_PUBLIC_KNOX_LOCAL_ONLY_NAMES
                    else ()
                ),
            )
            for hostnames in unique_host_groups
        ]
        blocks.append(f"# {name}\n" + "\n\n".join(rendered))
    for name, host_groups in SPECIAL_HOST_GROUPS.items():
        upstream = SPECIAL_PATH_ROUTES[name]
        rendered = [
            _host_block(hostnames, upstream, internal_tls=True)
            for hostnames in host_groups
        ]
        blocks.append(f"# {name}\n" + "\n\n".join(rendered))
    for name, (upstream, host_groups) in SPECIAL_HOST_ONLY_ROUTES.items():
        rendered = [
            _host_block(hostnames, upstream, internal_tls=True)
            for hostnames in host_groups
        ]
        blocks.append(f"# {name}\n" + "\n\n".join(rendered))
    return "\n\n".join(blocks)


def render_dns_json(target: str = "lan") -> str:
    by_name = _instances_with_static_public_fallbacks()
    dns_map: dict[str, str] = {}
    norman_ip = (
        NORMAN_TAILNET_FRONTDOOR if target == "tailnet" else HOSTS["norman"].lan_host
    )
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
    for _, host_groups in SPECIAL_HOST_ONLY_ROUTES.values():
        for group in host_groups:
            for host in group:
                dns_map[host] = norman_ip
    return json.dumps(dns_map, indent=2, sort_keys=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render Norman bot proxy Caddy config.")
    ap.add_argument(
        "--mode",
        choices=("paths", "hosts", "dns-json", "all"),
        default="all",
        help="Which output to render.",
    )
    ap.add_argument(
        "--dns-target",
        choices=("lan", "tailnet"),
        default="lan",
        help="Frontdoor address to use when rendering --mode dns-json.",
    )
    args = ap.parse_args()

    if args.mode == "paths":
        print(render_paths())
        return
    if args.mode == "hosts":
        print(render_hosts())
        return
    if args.mode == "dns-json":
        print(render_dns_json(args.dns_target))
        return
    print("# path-routes\n" + render_paths() + "\n\n# bot-hosts\n" + render_hosts())


if __name__ == "__main__":
    main()
