#!/usr/bin/env python3
from __future__ import annotations

import argparse


LOLLIE_CERT_PATH = "/etc/caddy/certs/networking-lollie.crt"
LOLLIE_KEY_PATH = "/etc/caddy/certs/networking-lollie.key"
NETWORKING_HOME_HOSTS = (
    "networking.home.arpa",
    "networking.home.lollie.org",
    "networking.knox.lollie.org",
    "networking-host.home.arpa",
)
NETOPS_HOST = "netops.home.arpa"
NETWORKING_GATEWAY_UPSTREAM = "https://192.168.2.241"
NETWORKING_GATEWAY_SERVER_NAME = "netbot.home.arpa"
NETWORKING_CONSOLE_UPSTREAM = "127.0.0.1:8791"
DEFAULT_HOST_HOME_ROOT = "/var/www/host-home"
PRIVATE_CLIENTS = (
    "127.0.0.1/8",
    "::1",
    "192.168.2.0/24",
    "100.78.41.73/32",
    "fd7a:115c:a1e0::4d33:2949/128",
    "100.103.34.17/32",
    "fd7a:115c:a1e0::3438:2211/128",
    "100.113.136.38/32",
    "fd7a:115c:a1e0::38:8826/128",
)


def _comma_join(hosts: tuple[str, ...]) -> str:
    return ", ".join(hosts)


def _http_hosts(hosts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"http://{host}" for host in hosts)


def _render_tls_snippet() -> str:
    return "\n".join(
        (
            "(networking_lollie_tls) {",
            f"\ttls {LOLLIE_CERT_PATH} {LOLLIE_KEY_PATH}",
            "}",
        )
    )


def _render_private_clients_snippet() -> str:
    return "\n".join(
        (
            "(private_clients) {",
            f"\t@private_clients remote_ip {' '.join(PRIVATE_CLIENTS)}",
            "}",
        )
    )


def _render_http_redirect_site(hosts: tuple[str, ...]) -> str:
    return "\n".join(
        (
            f"{_comma_join(_http_hosts(hosts))} {{",
            "\timport private_clients",
            "\thandle @private_clients {",
            "\t\tredir https://{host}{uri} 308",
            "\t}",
            '\trespond "Forbidden" 403',
            "}",
        )
    )


def _render_networking_site(
    *,
    host_home_root: str,
    gateway_upstream: str,
) -> str:
    return "\n".join(
        (
            f"{_comma_join(NETWORKING_HOME_HOSTS)} {{",
            "\timport networking_lollie_tls",
            "\timport private_clients",
            "\thandle @private_clients {",
            "\t\thandle /v1/* {",
            f"\t\t\treverse_proxy {gateway_upstream} {{",
            f"\t\t\t\theader_up Host {NETWORKING_GATEWAY_SERVER_NAME}",
            "\t\t\t\ttransport http {",
            f"\t\t\t\t\ttls_server_name {NETWORKING_GATEWAY_SERVER_NAME}",
            "\t\t\t\t}",
            "\t\t\t}",
            "\t\t}",
            "\t\thandle {",
            f"\t\t\troot * {host_home_root}",
            "\t\t\tfile_server",
            "\t\t}",
            "\t}",
            '\trespond "Forbidden" 403',
            "}",
        )
    )


def _render_netops_site(*, networking_upstream: str) -> str:
    return "\n".join(
        (
            f"{NETOPS_HOST} {{",
            "\timport networking_lollie_tls",
            "\timport private_clients",
            "\thandle @private_clients {",
            f"\t\treverse_proxy {networking_upstream}",
            "\t}",
            '\trespond "Forbidden" 403',
            "}",
        )
    )


def _render_default_http_site(root: str) -> str:
    return "\n".join(
        (
            ":80 {",
            "\timport private_clients",
            "\thandle @private_clients {",
            f"\t\troot * {root}",
            "\t\tfile_server",
            "\t}",
            '\trespond "Forbidden" 403',
            "}",
        )
    )


def render_caddy(
    *,
    networking_upstream: str = NETWORKING_CONSOLE_UPSTREAM,
    host_home_root: str = DEFAULT_HOST_HOME_ROOT,
    gateway_upstream: str = NETWORKING_GATEWAY_UPSTREAM,
) -> str:
    return "\n\n".join(
        (
            _render_tls_snippet(),
            _render_private_clients_snippet(),
            _render_http_redirect_site(NETWORKING_HOME_HOSTS),
            _render_http_redirect_site((NETOPS_HOST,)),
            _render_networking_site(
                host_home_root=host_home_root,
                gateway_upstream=gateway_upstream,
            ),
            _render_netops_site(networking_upstream=networking_upstream),
            _render_default_http_site(host_home_root),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the networking-host Caddy config."
    )
    parser.add_argument(
        "--networking-upstream",
        default=NETWORKING_CONSOLE_UPSTREAM,
        help="Local upstream for the NetOps console surface.",
    )
    parser.add_argument(
        "--host-home-root",
        default=DEFAULT_HOST_HOME_ROOT,
        help="Document root for the networking host surface.",
    )
    parser.add_argument(
        "--gateway-upstream",
        default=NETWORKING_GATEWAY_UPSTREAM,
        help="Norman front-door upstream for the networking /v1 gateway.",
    )
    args = parser.parse_args()
    print(
        render_caddy(
            networking_upstream=args.networking_upstream,
            host_home_root=args.host_home_root,
            gateway_upstream=args.gateway_upstream,
        )
    )


if __name__ == "__main__":
    main()
